// Sockets: Emscripten's socket calls over the host's. Included only by adapter.c.
#ifndef ADAPTER_SOCKETS_H
#define ADAPTER_SOCKETS_H

#include "common.h"
#include "state.h"
#include "metadata.h"
#include "openfiles.h"

// ================================================================== sockets: Emscripten's socket calls over the host's
// WASI preview1 cannot create or connect a socket, so the host gives a few operations; a socket is a guest
// descriptor (see the table below). The main module's fd_read / fd_write / fd_close / fd_fdstat_get come here first
// (OpenSSL reads and writes its socket with read() and write()); other descriptors pass on to WASI.
#define NET(n) __attribute__((import_module("net"), import_name(n)))
// The host reads and writes the guest's structures (sockaddr, msghdr, option values, addrinfo) itself: these take pointers.
NET("socket") i32 net_socket(i32 domain, i32 type, i32 proto);  // -> handle, or -errno
NET("bind") i32 net_bind(i32 h, const u8 *sa, i32 len);
NET("listen") i32 net_listen(i32 h, i32 backlog);
NET("accept") i32 net_accept(i32 h, u8 *sa, u32 *lenp, i32 nb);  // -> the new handle; the peer's address into sa, *lenp
NET("connect") i32 net_connect(i32 h, const u8 *sa, i32 len, i32 nb);  // nb: EINPROGRESS, the connection goes on
// flags are musl's MSG_*; the adapter adds MSG_DONTWAIT for a non-blocking socket, and the host then never waits
NET("sendto") i32 net_sendto(i32 h, const u8 *p, i32 n, i32 flags, const u8 *sa, i32 salen);
NET("recvfrom") i32 net_recvfrom(i32 h, u8 *p, i32 n, i32 flags, u8 *sa, u32 *lenp);
NET("sendmsg") i32 net_sendmsg(i32 h, const u32 *msg, i32 flags);
NET("recvmsg") i32 net_recvmsg(i32 h, u32 *msg, i32 flags);
NET("poll") i32 net_poll(i32 h, i32 events, i32 timeout_ms);  // -> revents
NET("pollv") i32 net_pollv(i32 n, const i32 *hs, const i32 *events, i32 timeout_ms, i32 *revents);  // several sockets at once
NET("close") i32 net_close(i32 h);
NET("shutdown") i32 net_shutdown(i32 h, i32 how);
NET("name") i32 net_name(i32 h, i32 peer, u8 *sa, u32 *lenp);  // the local or peer address
NET("getopt") i32 net_getopt(i32 h, i32 level, i32 opt, u8 *val, u32 *lenp);
NET("setopt") i32 net_setopt(i32 h, i32 level, i32 opt, const u8 *val, u32 len);
NET("ioctl") i32 net_ioctl(i32 h, i32 op, i32 *argp);  // FIONREAD
NET("resolve") i32 net_resolve(const char *name, i32 n, u8 *addr4);  // -> 0, or -errno
NET("getaddrinfo") i32 net_getaddrinfo(const char *node, const char *service, const i32 *hint, u32 *out);
NET("getnameinfo") i32 net_getnameinfo(const u8 *sa, i32 salen, char *node, i32 nodelen, char *serv, i32 servlen, i32 flags);
NET("protobyname") u32 net_protobyname(const char *name);

// A socket takes a real WASI descriptor number (a directory opened as a placeholder), so that numbers stay small
// (select() takes less than 1024) and never clash with files; the table is indexed by that number.
typedef struct {
    i32 h[MAXFD];  // the host's handle + 1; 0: not a socket
    u8 nb[MAXFD];  // O_NONBLOCK: SOCK_NONBLOCK, ioctl(FIONBIO), fcntl(F_SETFL), set by the program
} Socks;
__asm__(".globaltype sock_state, i32\nsock_state:\n");
static Socks *socks(void) {
    Socks *r;
    __asm__ volatile("global.get sock_state\n\tlocal.set %0" : "=r"(r));
    if (!r) {
        r = (Socks *)calloc(1, sizeof(Socks));
        __asm__ volatile("local.get %0\n\tglobal.set sock_state" : : "r"(r));
    }
    return r;
}
static i32 is_sock(i32 fd) { return fd >= 0 && fd < MAXFD && socks()->h[fd]; }
static i32 hof(i32 fd) { return socks()->h[fd] - 1; }
static i32 sock_nb(i32 fd) { return socks()->nb[fd]; }
static void sock_set_nb(i32 fd, i32 on) { socks()->nb[fd] = (u8)(on != 0); }

#define EAGAIN_ 6
#define ENOTSOCK_ 57
#define EFAULT_ 21
#define EINVAL_ 28
#define MSG_DONTWAIT 0x40
// a descriptor that is not a socket: EBADF if it is not open at all, else ENOTSOCK
static i32 notsock(i32 fd) {
    u8 st[24] __attribute__((aligned(8)));
    return w_fd_fdstat_get(fd, st) ? -EBADF : -ENOTSOCK_;
}
static i32 nbflag(i32 fd) { return sock_nb(fd) ? MSG_DONTWAIT : 0; }
// does the socket have what is asked (events: 1 read, 4 write)? An error or a hang-up is an answer too. EAGAIN if not
static i32 would_block(i32 fd, i32 flags, i32 events) {
    if (!sock_nb(fd) && !(flags & MSG_DONTWAIT)) return 0;
    return !(net_poll(hof(fd), events, 0) & (events | 8 | 16));
}

// a placeholder descriptor for a new socket: a directory opened, so the number is a real WASI one. -errno
static i32 sock_fd(void) {
    u64 all = (1ull << 30) - 1, writes = (1ull << 6) | (1ull << 0) | (1ull << 8) | (1ull << 22);
    i32 fd = -1;
    char dot[2];  // "." built on the stack: a string literal would be a data section
    dot[0] = '.', dot[1] = 0;
    i32 e = w_path_open(PREOPEN, 1, dot, 1, 2 /* O_DIRECTORY */, all & ~writes, 0, 0, &fd);
    if (e) return -33;  // EMFILE
    if (fd < 0 || fd >= MAXFD) {
        w_fd_close(fd);
        return -33;
    }
    return fd;
}

EXPORT("__syscall_socket") i32 sc_socket(i32 domain, i32 type, i32 proto, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    i32 fd = sock_fd();
    if (fd < 0) return fd;
    i32 h = net_socket(domain, type & ~(04000 | 02000000), proto);  // without SOCK_NONBLOCK, SOCK_CLOEXEC
    if (h < 0) {
        w_fd_close(fd);
        return h;
    }
    socks()->h[fd] = h + 1;
    socks()->nb[fd] = (type & 04000) != 0;  // SOCK_NONBLOCK
    return fd;
}

EXPORT("__syscall_bind") i32 sc_bind(i32 fd, const u8 *sa, i32 len, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    if (!is_sock(fd)) return notsock(fd);
    return net_bind(hof(fd), sa, len);
}

EXPORT("__syscall_listen") i32 sc_listen(i32 fd, i32 backlog, i32 a, i32 b, i32 c, i32 d) {
    (void)a, (void)b, (void)c, (void)d;
    if (!is_sock(fd)) return notsock(fd);
    return net_listen(hof(fd), backlog);
}

EXPORT("__syscall_accept4") i32 sc_accept4(i32 fd, u8 *sa, u32 *lenp, i32 flags, i32 a, i32 b) {
    (void)a, (void)b;
    if (!is_sock(fd)) return notsock(fd);
    if (flags & ~(04000 | 02000000)) return -EINVAL_;  // SOCK_NONBLOCK, SOCK_CLOEXEC
    if (would_block(fd, 0, 1)) return -EAGAIN_;
    i32 nfd = sock_fd();  // before the accept: no descriptor, the connection stays queued
    if (nfd < 0) return nfd;
    i32 h = net_accept(hof(fd), sa, lenp, sock_nb(fd));
    if (h < 0) {
        w_fd_close(nfd);
        return h;
    }
    socks()->h[nfd] = h + 1;
    socks()->nb[nfd] = (flags & 04000) != 0;
    return nfd;
}

EXPORT("__syscall_connect") i32 sc_connect(i32 fd, const u8 *sa, i32 len, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    if (!is_sock(fd)) return notsock(fd);
    return net_connect(hof(fd), sa, len, sock_nb(fd));
}

EXPORT("__syscall_sendto") i32 sc_sendto(i32 fd, const u8 *p, i32 n, i32 flags, const u8 *addr, i32 alen) {
    if (!is_sock(fd)) return notsock(fd);
    if (would_block(fd, flags, 4)) return -EAGAIN_;
    return net_sendto(hof(fd), p, n, flags | nbflag(fd), addr, alen);
}

EXPORT("__syscall_recvfrom") i32 sc_recvfrom(i32 fd, u8 *p, i32 n, i32 flags, u8 *addr, u32 *alen) {
    if (!is_sock(fd)) return notsock(fd);
    if (would_block(fd, flags, 1)) return -EAGAIN_;
    return net_recvfrom(hof(fd), p, n, flags | nbflag(fd), addr, alen);
}

// sendmsg / recvmsg: the iovecs and msg_name are the host's to read and write; no control data (msg_controllen stays 0,
// and a message that carries some is EOPNOTSUPP)
EXPORT("__syscall_sendmsg") i32 sc_sendmsg(i32 fd, const u32 *msg, i32 flags, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    if (!is_sock(fd)) return notsock(fd);
    if (would_block(fd, flags, 4)) return -EAGAIN_;
    return net_sendmsg(hof(fd), msg, flags | nbflag(fd));
}

EXPORT("__syscall_recvmsg") i32 sc_recvmsg(i32 fd, u32 *msg, i32 flags, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    if (!is_sock(fd)) return notsock(fd);
    if (would_block(fd, flags, 1)) return -EAGAIN_;
    return net_recvmsg(hof(fd), msg, flags | nbflag(fd));
}

EXPORT("__syscall_shutdown") i32 sc_shutdown(i32 fd, i32 how, i32 a, i32 b, i32 c, i32 d) {
    (void)a, (void)b, (void)c, (void)d;
    if (!is_sock(fd)) return notsock(fd);
    return net_shutdown(hof(fd), how);
}

EXPORT("__syscall_getpeername") i32 sc_getpeername(i32 fd, u8 *sa, u32 *lenp, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    if (!is_sock(fd)) return notsock(fd);
    if (!sa || !lenp) return -EFAULT_;
    return net_name(hof(fd), 1, sa, lenp);
}
EXPORT("__syscall_getsockname") i32 sc_getsockname(i32 fd, u8 *sa, u32 *lenp, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    if (!is_sock(fd)) return notsock(fd);
    if (!sa || !lenp) return -EFAULT_;
    return net_name(hof(fd), 0, sa, lenp);
}

EXPORT("__syscall_getsockopt") i32 sc_getsockopt(i32 fd, i32 level, i32 opt, u8 *val, u32 *lenp, i32 a) {
    (void)a;
    if (!is_sock(fd)) return notsock(fd);
    if (!val || !lenp) return -EFAULT_;
    return net_getopt(hof(fd), level, opt, val, lenp);  // the host's real value; ENOPROTOOPT for an option it has not
}

// setsockopt is a stub INSIDE pyodide.asm.wasm (it returns 0); the build (tools/patch_main.mjs) turns it into this import
EXPORT("__syscall_setsockopt_host") i32 sc_setsockopt(i32 fd, i32 level, i32 opt, const u8 *val, u32 len, i32 a) {
    (void)a;
    if (!is_sock(fd)) return notsock(fd);
    return net_setopt(hof(fd), level, opt, val, len);
}

// struct pollfd {int fd; short events, revents;}. Sockets are polled by the host, all in one call, with the timeout;
// a file is always ready for what it is asked (POLLIN, POLLOUT); a descriptor that is not open is POLLNVAL; a negative
// one is ignored. A file that is ready, or an invalid descriptor, makes the sockets answer at once (nothing to wait for).
#define POLLNVAL 32
static i32 do_poll(u8 *fds, i32 n, i32 timeout) {
    if ((u32)n > MAXFD) return -EINVAL_;  // more entries than descriptors (RLIMIT_NOFILE)
    i32 ready = 0, nsock = 0, immediate = 0;
    i32 *buf = n > 0 ? (i32 *)malloc((u32)n * 3 * 4) : 0;  // handles, events, revents of the sockets
    i32 *hs = buf, *evs = buf + n, *revs = buf + 2 * n;
    for (i32 k = 0; k < n; k++) {
        i32 fd = *(i32 *)(fds + 8 * k);
        i16 ev = *(i16 *)(fds + 8 * k + 4), rev = 0;
        if (fd >= 0 && is_sock(fd)) {
            hs[nsock] = hof(fd), evs[nsock] = ev & 7, revs[nsock] = 0;  // POLLIN, POLLPRI, POLLOUT
            nsock++;
        } else if (fd >= 0) {
            u8 st[24] __attribute__((aligned(8)));
            if (w_fd_fdstat_get(fd, st)) rev = POLLNVAL;
            else rev = (i16)(ev & 5);
            if (rev) immediate = 1;
        }
        *(i16 *)(fds + 8 * k + 6) = rev;
    }
    if (nsock) net_pollv(nsock, hs, evs, immediate ? 0 : timeout, revs);
    else if (!immediate && timeout > 0) {  // nothing to wait for but time: the host's clock
        i32 none = 0;
        net_pollv(0, &none, &none, timeout, &none);
    }
    i32 j = 0;
    for (i32 k = 0; k < n; k++) {
        i32 fd = *(i32 *)(fds + 8 * k);
        if (fd >= 0 && is_sock(fd)) *(i16 *)(fds + 8 * k + 6) = (i16)revs[j++];
        if (*(i16 *)(fds + 8 * k + 6)) ready++;
    }
    if (buf) free(buf);
    return ready;
}
EXPORT("__syscall_poll") i32 sc_poll(u8 *fds, i32 n, i32 timeout) { return do_poll(fds, n, timeout); }
EXPORT("__syscall_poll_nonblocking") i32 sc_poll_nb(u8 *fds, i32 n) { return do_poll(fds, n, 0); }

// DNS, by the host. libc's gethostbyname has no way to fail through this call (Pyodide's JavaScript never fails: it
// makes up an address): a name the host cannot resolve gives INADDR_NONE (255.255.255.255), which no connection reaches.
EXPORT("_emscripten_lookup_name") u32 lookup_name(const char *name) {
    u8 a[4];
    if (net_resolve(name, slen(name), a)) return 0xffffffffu;
    return (u32)a[0] | ((u32)a[1] << 8) | ((u32)a[2] << 16) | ((u32)a[3] << 24);
}

// the whole list is one malloc'd block that freeaddrinfo (it frees the first node and its ai_addr) releases
EXPORT("getaddrinfo") i32 getaddrinfo_(const char *node, const char *service, const i32 *hint, u32 *out) {
    return net_getaddrinfo(node, service, hint, out);
}

EXPORT("getnameinfo") i32 getnameinfo_(const u8 *sa, i32 salen, char *node, i32 nodelen, char *serv, i32 servlen, i32 flags) {
    return net_getnameinfo(sa, salen, node, nodelen, serv, servlen, flags);
}

EXPORT("getprotobyname") u32 getprotobyname_(const char *name) { return net_protobyname(name); }

// ioctl as Pyodide's JavaScript answers: a descriptor that is not open is EBADF; FIONREAD and FIONBIO belong to
// sockets (a file has no ioctl: ENOTTY); the terminal requests are ENOTTY (no descriptor here is a terminal for
// them); anything else is EINVAL.
EXPORT("__syscall_ioctl") i32 sc_ioctl(i32 fd, i32 op, i32 va) {
    u8 st[24] __attribute__((aligned(8)));
    if (!is_sock(fd) && w_fd_fdstat_get(fd, st)) return -EBADF;
    i32 *argp = va ? *(i32 **)va : 0;  // va points at the variable arguments; the first is the argument's address
    if (op == 0x5421 || op == 0x541B) {  // FIONBIO, FIONREAD
        if (!is_sock(fd)) return -ENOTTY;
        if (!argp) return -21;  // EFAULT
        if (op == 0x541B) return net_ioctl(hof(fd), op, argp);
        sock_set_nb(fd, *argp != 0);
        return 0;
    }
    if ((op >= 0x5401 && op <= 0x5408) || op == 0x540B || op == 0x540F || op == 0x5410 || op == 0x5413 || op == 0x5414)
        return -ENOTTY;
    return -28;  // EINVAL
}

// the main module's WASI calls, for socket descriptors
EXPORT("fd_read") i32 x_fd_read(i32 fd, const u32 *iov, i32 n, i32 *nread) {
    if (!is_sock(fd)) return w_fd_read(fd, iov, n, nread);
    if (would_block(fd, 0, 1)) return EAGAIN_;
    i32 tot = 0;
    for (i32 k = 0; k < n; k++) {
        i32 r = net_recvfrom(hof(fd), (u8 *)iov[2 * k], (i32)iov[2 * k + 1], nbflag(fd), 0, 0);
        if (r < 0) {
            if (tot) break;
            return -r;
        }
        tot += r;
        if (r < (i32)iov[2 * k + 1]) break;
    }
    *nread = tot;
    return 0;
}

WASI("fd_write") i32 w_fd_write(i32 fd, const void *iovs, i32 n, i32 *nwritten);
EXPORT("fd_write") i32 x_fd_write(i32 fd, const u32 *iov, i32 n, i32 *nw) {
    if (!is_sock(fd)) return w_fd_write(fd, iov, n, nw);
    if (would_block(fd, 0, 4)) return EAGAIN_;
    i32 tot = 0;
    for (i32 k = 0; k < n; k++) {
        i32 r = net_sendto(hof(fd), (const u8 *)iov[2 * k], (i32)iov[2 * k + 1], nbflag(fd), 0, 0);
        if (r < 0) {
            if (tot) break;
            return -r;
        }
        tot += r;
        if (r < (i32)iov[2 * k + 1]) break;
    }
    *nw = tot;
    return 0;
}

EXPORT("fd_close") i32 x_fd_close(i32 fd) {
    if (!is_sock(fd)) {
        if (mt()->norphan) meta_closing(fd);
        fd_forget(fd);
        return w_fd_close(fd);
    }
    net_close(hof(fd));
    socks()->h[fd] = 0;
    socks()->nb[fd] = 0;
    return w_fd_close(fd);  // the placeholder
}

WASI("fd_fdstat_get") i32 w_fd_fdstat_get(i32 fd, void *buf);
EXPORT("fd_fdstat_get") i32 x_fd_fdstat_get(i32 fd, u8 *buf) {
    if (!is_sock(fd)) return w_fd_fdstat_get(fd, buf);
    for (i32 i = 0; i < 24; i++) buf[i] = 0;
    buf[0] = 6;  // SOCKET_STREAM
    *(u64 *)(buf + 8) = (1ull << 30) - 1, *(u64 *)(buf + 16) = (1ull << 30) - 1;
    return 0;
}

#endif
