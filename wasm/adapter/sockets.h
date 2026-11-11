// Sockets: Emscripten's socket calls over the host's. Included only by adapter.c.
#ifndef ADAPTER_SOCKETS_H
#define ADAPTER_SOCKETS_H

#include "common.h"
#include "state.h"
#include "metadata.h"
#include "openfiles.h"
#include "vfd.h"

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

// A socket takes a real WASI descriptor number (a directory opened as a placeholder, vfd.h), so that numbers stay small
// (select() takes less than 1024) and never clash with files; its object (handle, O_NONBLOCK) is shared by the dups.
static void sock_close(i32 h) { net_close(h); }
static i32 sock_new(i32 fd, i32 h, i32 nb) {  // 0, or -ENOMEM (the host's socket is closed, and the placeholder)
    Obj *o = (Obj *)calloc(1, sizeof(Obj));
    if (!o || !vt()) {
        free(o);
        net_close(h);
        w_fd_close(fd);
        return -ENOMEM;
    }
    o->kind = K_SOCK, o->ref = 1, o->w = h, o->nb = (u8)nb;
    vt()->o[fd] = o;
    return 0;
}

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

EXPORT("__syscall_socket") i32 sc_socket(i32 domain, i32 type, i32 proto, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    i32 fd = sock_fd();
    if (fd < 0) return fd;
    i32 h = net_socket(domain, type & ~(04000 | 02000000), proto);  // without SOCK_NONBLOCK, SOCK_CLOEXEC
    if (h < 0) {
        w_fd_close(fd);
        return h;
    }
    i32 e = sock_new(fd, h, (type & 04000) != 0);  // SOCK_NONBLOCK
    if (e) return e;
    cloexec_set(fd, type & 02000000);  // SOCK_CLOEXEC
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
    i32 e = sock_new(nfd, h, (flags & 04000) != 0);
    if (e) return e;
    cloexec_set(nfd, flags & 02000000);
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
        } else if (is_pipe(fd)) {  // PIPEFS's poll: ready from its buffer, now
            rev = (i16)(pipe_mask(vobj(fd)) & (ev | 8 | 16 | POLLNVAL));
            if (rev) immediate = 1;
        } else if (fd >= 0) {
            u8 st[24] __attribute__((aligned(8)));
            if (is_pre(fd) || w_fd_fdstat_get(fd, st)) rev = POLLNVAL;  // a preopen is no descriptor of the guest
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

// getprotobyname as Pyodide's glue answers it, from a fixed table that is not the host's: "tcp" and "6", "udp" and "17"
// (case matters, any other name is NULL), the same struct protoent each time. The two entries are one calloc'd block
// (name, aliases [alias, NULL], proto; the strings after them), built on first use; no data section holds them.
__asm__(".globaltype proto_state, i32\nproto_state:\n");
EXPORT("getprotobyname") u32 getprotobyname_(const char *name) {
    u32 key = 0;
    for (i32 i = 0; i < 4; i++) {  // up to 3 characters, packed as bytes; a longer name gets a key no case has
        u8 c = (u8)name[i];
        if (!c) break;
        key |= (u32)c << (8 * i);
        if (i == 3) key = 0xffffffffu;
    }
    i32 e = key == 0x706374u || key == 0x36u ? 0 : key == 0x706475u || key == 0x3731u ? 1 : -1;  // "tcp" "6", "udp" "17"
    if (e < 0) return 0;
    u32 *t;
    __asm__ volatile("global.get proto_state\n\tlocal.set %0" : "=r"(t));
    if (!t) {
        t = (u32 *)calloc(1, 64);
        if (!t) return 0;
        for (i32 j = 0; j < 2; j++) {
            u32 *pe = t + 8 * j;  // 32 bytes: protoent (12), alias list (8), name (4), alias (4)
            char *nm = (char *)(pe + 5);
            u32 up = j ? 0x504455u : 0x504354u;  // "UDP" "TCP"
            u32 lo = j ? 0x706475u : 0x706374u;  // "udp" "tcp"
            pe[0] = (u32)nm, pe[1] = (u32)(pe + 3), pe[2] = j ? 17 : 6, pe[3] = (u32)(nm + 4);
            *(u32 *)nm = lo, *(u32 *)(nm + 4) = up;
        }
        __asm__ volatile("local.get %0\n\tglobal.set proto_state" : : "r"(t));
    }
    return (u32)(t + 8 * e);
}

// ioctl as Pyodide's JavaScript answers: a descriptor that is not open is EBADF; FIONREAD and FIONBIO belong to
// sockets (a file has no ioctl: ENOTTY; a pipe: FIONREAD is the bytes buffered, FIONBIO is EINVAL); the terminal
// requests are ENOTTY (no descriptor here is a terminal for them); anything else is EINVAL. (FIOCLEX and FIONCLEX never
// come here: the main module's libc answers them with 0 itself, so os.set_inheritable(fd, True) is a no-op; F_SETFD works.)
EXPORT("__syscall_ioctl") i32 sc_ioctl(i32 fd, i32 op, i32 va) {
    u8 st[24] __attribute__((aligned(8)));
    if (is_pre(fd) || (!is_sock(fd) && w_fd_fdstat_get(fd, st))) return -EBADF;
    i32 *argp = va ? *(i32 **)va : 0;  // va points at the variable arguments; the first is the argument's address
    if (is_pipe(fd) && (op == 0x541B || op == 0x5421)) {  // PIPEFS: FIONREAD is the bytes buffered, its other ioctls EINVAL
        if (op == 0x5421) return -28;
        if (!argp) return -21;
        *argp = (i32)vobj(fd)->pipe->size;
        return 0;
    }
    if (op == 0x5421 && nb_keeps(fd)) return argp ? nb_set(fd, *argp != 0) : -21;  // a stream or directory: succeeds, as Pyodide
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

// readv, writev, preadv, pwritev on a regular file: wasmtime uses only the first buffer of an iovec array, so the buffers
// are done one by one (op 0 read, 1 write, 2 pread, 3 pwrite). A short count ends the call (the total so far is the result,
// an error only when nothing was done); the offset kinds go on until the buffer is full or the file ends: wasmtime's pread
// and pwrite do at most 64 KiB at a time. The total stops at 0x7ffff000 (Linux's MAX_RW_COUNT), so it never overflows.
// Not for a stream (stdin, a terminal, a pipe): a read of the next buffer would wait for more input after the first came
// back full (musl's stdio always reads with two buffers); those keep the one WASI call.
static i32 file_iov(i32 op, i32 fd, const u32 *iov, i32 n, u64 off, i32 *done) {
    i32 tot = 0, e = 0;
    u32 none[2] = {0, 0};  // no buffer: one call of length 0, so that a bad descriptor still says so
    if (n == 0) iov = none, n = 1;
    for (i32 k = 0; k < n && !e; k++) {
        i32 room = 0x7ffff000 - tot, len = iov[2 * k + 1] > (u32)room ? room : (i32)iov[2 * k + 1], got = 0;
        do {
            u32 one[2] = {iov[2 * k] + (u32)got, (u32)(len - got)};
            i32 r = 0;
            e = op == 0 ? w_fd_read(fd, one, 1, &r) : op == 1 ? w_fd_write(fd, one, 1, &r) : op == 2 ? w_fd_pread(fd, one, 1, off + (u64)(tot + got), &r) : w_fd_pwrite(fd, one, 1, off + (u64)(tot + got), &r);
            if (e || r <= 0) break;
            got += r;
            if (op < 2) break;
        } while (got < len);
        tot += got;
        if (got < len) break;
    }
    if (e && tot) e = 0;
    *done = tot;
    return e;
}

static i32 is_regular(i32 fd) { return fd_type(fd) == 4; }

// the main module's WASI calls, for socket descriptors
EXPORT("fd_read") i32 x_fd_read(i32 fd, const u32 *iov, i32 n, i32 *nread) {
    if (is_pre(fd)) return FE_BADF;
    i32 empty = 1;
    for (i32 k = 0; k < n; k++) empty &= !iov[2 * k + 1];
    if (empty && !is_virt(fd) && fd_std(rfd(fd))) return *nread = 0;  // a read of 0 bytes on stdin must not wait for input
    if (is_pipe(fd)) return pipe_read(vobj(fd), iov, n, nread);
    if (!is_sock(fd)) return n <= 1 || !is_regular(fd) ? w_fd_read(rfd(fd), iov, n, nread) : file_iov(0, rfd(fd), iov, n, 0, nread);
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
    if (is_pre(fd)) return FE_BADF;
    if (is_pipe(fd)) return pipe_write(vobj(fd), iov, n, nw);
    if (!is_sock(fd)) return n <= 1 || !is_regular(fd) ? w_fd_write(rfd(fd), iov, n, nw) : file_iov(1, rfd(fd), iov, n, 0, nw);
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

EXPORT("fd_close") i32 x_fd_close(i32 fd) { return is_pre(fd) ? FE_BADF : fd_release(fd); }

WASI("fd_fdstat_get") i32 w_fd_fdstat_get(i32 fd, void *buf);
EXPORT("fd_fdstat_get") i32 x_fd_fdstat_get(i32 fd, u8 *buf) {
    if (is_pre(fd)) return FE_BADF;
    if (!is_virt(fd)) return w_fd_fdstat_get(rfd(fd), buf);
    for (i32 i = 0; i < 24; i++) buf[i] = 0;
    if (is_pipe(fd)) {
        buf[0] = 4;  // as Pyodide's: a regular file, no flags, no rights
        return 0;
    }
    buf[0] = 6;  // SOCKET_STREAM
    *(u64 *)(buf + 8) = (1ull << 30) - 1, *(u64 *)(buf + 16) = (1ull << 30) - 1;
    return 0;
}

// pread, pwrite and fsync of the main module: a socket or a pipe has no offset (ESPIPE), a pipe can not be synced (EINVAL)
WASI("fd_sync") i32 w_fd_sync(i32 fd);
EXPORT("fd_pread") i32 x_fd_pread(i32 fd, const void *iov, i32 n, u64 off, i32 *nread) {
    if ((i64)off > (1ll << 53) || (i64)off < -(1ll << 53)) return FE_FBIG;  // the glue's bigintToI53Checked
    return is_pre(fd) ? FE_BADF : is_virt(fd) ? FE_SPIPE : file_iov(2, rfd(fd), (const u32 *)iov, n, off, nread);
}
EXPORT("fd_pwrite") i32 x_fd_pwrite(i32 fd, const void *iov, i32 n, u64 off, i32 *nw) {
    if ((i64)off > (1ll << 53) || (i64)off < -(1ll << 53)) return FE_FBIG;
    return is_pre(fd) ? FE_BADF : is_virt(fd) ? FE_SPIPE : file_iov(3, rfd(fd), (const u32 *)iov, n, off, nw);
}
EXPORT("fd_sync") i32 x_fd_sync(i32 fd) {
    if (is_pre(fd)) return FE_BADF;
    if (is_pipe(fd)) return FE_INVAL;
    if (is_sock(fd)) return 0;
    i32 ft = fd_type(fd);  // a standard stream and a directory have nothing to sync: success, as Pyodide
    return ft < 0 ? -ft : fd_std(rfd(fd)) || ft == 3 ? 0 : w_fd_sync(rfd(fd));
}

#endif
