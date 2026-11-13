// The virtual /dev and /proc: what Pyodide has there, served by the adapter with no help from the host (the same on every
// OS: Windows has no /dev). Included only by adapter.c (through openfiles.h).
//
// The two subtrees are VIRTUAL as a whole: a path that, after the cwd/dirfd and "." / ".." are applied, lies at or below
// /dev or /proc is answered here and never reaches WASI (a host folder mounted at /dev is not seen by the calls that go
// through vnode(); an entry that is not listed below is ENOENT even if the host has it). What is there (Pyodide's names,
// modes, device numbers and inodes; where Pyodide's answer is a defect of its own, Linux's):
//   /dev                 directory: null, tty, tty1, random, urandom, shm, stdin, stdout, stderr
//   /dev/null            reads 0, takes every write, can seek (to 0)
//   /dev/random, urandom reads random_get; mode 0555 (Pyodide's: an input-only device), so it is not opened for writing
//   /dev/tty, tty1       write to stdout / stderr; tty reads stdin (tty1: ENXIO); the terminal requests of tty_ioctl
//   /dev/stdin|out|err   character devices (Pyodide: not links) that reach the host's stream; the wrong direction is EIO
//   /dev/shm             an empty directory (Pyodide's holds an empty `tmp`)
//   /proc, /proc/self    directories; /proc/self/fd lists the numbers of the descriptor table (Vt), each a symlink whose
//                        target is what the descriptor stands for (fd_target); stat follows it, lstat and readlink do not
// A virtual node has no WASI descriptor: an open one is an Obj of kind K_DEV (w = -1, `dev` = the node, `path` its absolute
// path), so it is a descriptor number like any other (dup, dup2, close, fcntl, poll). Every call that takes such a number
// handles K_DEV explicitly or gets WASI's EBADF from rfd() == -1: never a guest number reaches a w_fd_* call.
// For the calls that look at WASI's filestat (stat, access, chmod) a node is described by a synthesized filestat (vfs):
// its st_dev is VDEV (no host file has it), its mode is in the padding at +20 (def_for reads it there), so a chmod/chown
// is kept in the session's metadata like a file's. The mutating path calls (mkdir, unlink, rmdir, rename,
// symlink, link) are refused here (vdeny), truncate and utimensat by path answer for a node, chdir/fchdir enter the directories.
#ifndef ADAPTER_DEV_H
#define ADAPTER_DEV_H

#include "common.h"
#include "state.h"
#include "cwd.h"
#include "metadata.h"
#include "vfd.h"

// the main module's libc entropy (musl's getentropy: up to 256 bytes a call; it asks WASI's random_get itself), resolved from its
// exports like malloc: the adapter imports no WASI function for it
i32 getentropy(void *buf, u32 len);
WASI("fd_write") i32 w_fd_write(i32 fd, const void *iovs, i32 n, i32 *nwritten);
static i32 has_dotdot(const char *s);
static const char *fixpath(i32 gfd, const char *path);

#define FE_IO 29
#define FE_ISDIR 31
#define FE_NXIO 60

// the nodes; the directories first (dev_isdir), the devices in the order of /dev's listing
#define VN_DEV 1
#define VN_PROC 2
#define VN_SELF 3
#define VN_FDDIR 4
#define VN_SHM 5
#define VN_NULL 6
#define VN_TTY 7
#define VN_TTY1 8
#define VN_RANDOM 9
#define VN_URANDOM 10
#define VN_STDIN 11  // stdout, stderr: the next two (the host's stream is 0 + VN_x - VN_STDIN)
#define VN_STDOUT 12
#define VN_STDERR 13
#define VN_FDLINK 14  // /proc/self/fd/N: never an Obj

// a name of up to 7 characters as one number (no string literal: the adapter has no data section)
#define NK(a, b, c, d, e, f, g) ((u64)(a) | (u64)(b) << 8 | (u64)(c) << 16 | (u64)(d) << 24 | (u64)(e) << 32 | (u64)(f) << 40 | (u64)(g) << 48)
#define N_DEV NK('d', 'e', 'v', 0, 0, 0, 0)
#define N_PROC NK('p', 'r', 'o', 'c', 0, 0, 0)
#define N_SELF NK('s', 'e', 'l', 'f', 0, 0, 0)
#define N_FD NK('f', 'd', 0, 0, 0, 0, 0)
#define N_SHM NK('s', 'h', 'm', 0, 0, 0, 0)
#define N_NULL NK('n', 'u', 'l', 'l', 0, 0, 0)
#define N_TTY NK('t', 't', 'y', 0, 0, 0, 0)
#define N_TTY1 NK('t', 't', 'y', '1', 0, 0, 0)
#define N_RANDOM NK('r', 'a', 'n', 'd', 'o', 'm', 0)
#define N_URANDOM NK('u', 'r', 'a', 'n', 'd', 'o', 'm')
#define N_STDIN NK('s', 't', 'd', 'i', 'n', 0, 0)
#define N_STDOUT NK('s', 't', 'd', 'o', 'u', 't', 0)
#define N_STDERR NK('s', 't', 'd', 'e', 'r', 'r', 0)

typedef struct {
    i32 id;   // VN_*
    i32 n;    // VN_FDLINK: the descriptor
    i32 err;  // vnode() == 2: why there is nothing (ENOENT, ENOTDIR)
    i32 slash;  // the path ended in '/' or '/.': it must name a directory
} Vn;

static i32 dev_isdir(const Obj *o) { return o->dev <= VN_SHM; }  // (of a K_DEV object)
// fd_fdstat_get's filetype of a K_DEV object. Pyodide's: a terminal is a character device (that is what isatty asks), the other
// devices are "regular files" (so isatty(/dev/null) is False)
static i32 dev_wasi_type(const Obj *o) { return dev_isdir(o) ? 3 : o->dev == VN_TTY || o->dev == VN_TTY1 ? 2 : 4; }
static u64 vn_name(i32 id) {  // the last name of a node's path
    switch (id) {
        case VN_DEV: return N_DEV;
        case VN_PROC: return N_PROC;
        case VN_SELF: return N_SELF;
        case VN_FDDIR: return N_FD;
        case VN_SHM: return N_SHM;
        case VN_NULL: return N_NULL;
        case VN_TTY: return N_TTY;
        case VN_TTY1: return N_TTY1;
        case VN_RANDOM: return N_RANDOM;
        case VN_URANDOM: return N_URANDOM;
        case VN_STDIN: return N_STDIN;
        case VN_STDOUT: return N_STDOUT;
        default: return N_STDERR;
    }
}
static i32 vn_depth(i32 id) { return id == VN_DEV || id == VN_PROC ? 1 : id == VN_FDDIR ? 3 : 2; }
static i32 dev_id(u64 k) {  // the node of a name inside /dev, or 0
    switch (k) {
        case N_SHM: return VN_SHM;
        case N_NULL: return VN_NULL;
        case N_TTY: return VN_TTY;
        case N_TTY1: return VN_TTY1;
        case N_RANDOM: return VN_RANDOM;
        case N_URANDOM: return VN_URANDOM;
        case N_STDIN: return VN_STDIN;
        case N_STDOUT: return VN_STDOUT;
        case N_STDERR: return VN_STDERR;
        default: return 0;
    }
}
// Pyodide's numbers (st_ino; st_dev of a device is its inode, of the rest 1; st_rdev)
static u64 vn_ino(i32 id, i32 n) {
    switch (id) {
        case VN_DEV: return 5;
        case VN_PROC: return 13;
        case VN_SELF: return 14;
        case VN_FDDIR: return 15;
        case VN_SHM: return 11;
        case VN_NULL: return 6;
        case VN_TTY: return 7;
        case VN_TTY1: return 8;
        case VN_RANDOM: return 9;
        case VN_URANDOM: return 10;
        case VN_STDIN: return 29;
        case VN_STDOUT: return 30;
        case VN_STDERR: return 31;
        default: return 32 + (u64)n;
    }
}
static u32 vn_rdev(i32 id) {
    switch (id) {
        case VN_NULL: return 0x103;
        case VN_TTY: return 0x500;
        case VN_TTY1: return 0x600;
        case VN_RANDOM: return 0x4000;
        case VN_URANDOM: return 0x4100;
        case VN_STDIN: return 0x4300;
        case VN_STDOUT: return 0x4301;
        case VN_STDERR: return 0x4302;
        default: return 0;
    }
}
static u32 vn_mode(i32 id) { return id <= VN_SHM || id == VN_FDLINK ? 0777 : id == VN_RANDOM || id == VN_URANDOM ? 0555 : 0666; }

// the absolute path of a node written to d (at most 14 bytes with the NUL) -> its length
static i32 vn_put(char *d, i32 id) {
    i32 k = 0;
    for (i32 c = 0; c < vn_depth(id); c++) {
        u64 key = c == 0 ? (id == VN_PROC || id == VN_SELF || id == VN_FDDIR ? N_PROC : N_DEV) : c == 1 && id == VN_FDDIR ? N_SELF : vn_name(id);
        d[k++] = '/';
        for (; key; key >>= 8) d[k++] = (char)key;
    }
    d[k] = 0;
    return k;
}
static i32 put_num(char *d, u32 v) {  // decimal digits at d -> how many
    char t[10];
    i32 n = 0;
    do {
        t[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v);
    for (i32 k = 0; k < n; k++) d[k] = t[n - 1 - k];
    return n;
}

// ---- finding the node a path names. vnode: 0 = the path is not under /dev or /proc (the caller goes on as before),
// 1 = it names the node in *v, 2 = it lies under one but there is nothing there (v->err: ENOENT, or ENOTDIR below a device).
static u64 ckey(const char *s, i32 l) {
    if (l > 7) return ~0ull;
    u64 k = 0;
    for (i32 i = 0; i < l; i++) k |= (u64)(u8)s[i] << (8 * i);
    return k;
}
static i32 fdnum(const char *s, i32 l) {  // a canonical decimal number below MAXFD, else -1
    if (l < 1 || l > 4 || (s[0] == '0' && l > 1)) return -1;
    i32 v = 0;
    for (i32 i = 0; i < l; i++) {
        if (s[i] < '0' || s[i] > '9') return -1;
        v = v * 10 + (s[i] - '0');
    }
    return v < MAXFD ? v : -1;
}
// the names of s are applied to the path of depth n kept in cp/cl (the first four names; ".." pops, "." and "" are nothing)
static i32 vwalk(const char *s, i32 n, const char **cp, i32 *cl) {
    for (i32 i = 0; s[i];) {
        while (s[i] == '/') i++;
        if (!s[i]) break;
        i32 st = i;
        while (s[i] && s[i] != '/') i++;
        i32 l = i - st;
        if (l == 2 && s[st] == '.' && s[st + 1] == '.') {
            if (n) n--;
        } else if (!(l == 1 && s[st] == '.')) {
            if (n < 4) cp[n] = s + st, cl[n] = l;
            n++;
        }
    }
    return n;
}
static i32 fd_isdir(i32 fd) {  // the descriptor's object is a directory
    u8 st[24] __attribute__((aligned(8)));
    Obj *o = vobj(fd);
    if (o && o->kind == K_DEV) return dev_isdir(o);
    return o && o->kind == K_FILE && !o->std && !w_fd_fdstat_get(o->w, st) && st[0] == 3;
}
static i32 vnode(i32 dirfd, const char *path, Vn *v) {
    const char *base = 0, *cp[4];
    i32 cl[4], n = 0;
    if (!path[0]) return 0;
    Obj *d = path[0] == '/' ? 0 : vobj(dirfd);
    if (path[0] != '/') {
        if (dirfd == AT_FDCWD) base = cwdst()->cwd;
        else if (d && d->path) base = d->path;  // (a K_FILE directory's path, or a virtual directory's)
        else return 0;
    }
    if (has_dotdot(path) && !(d && d->kind == K_DEV)) {  // physical ".." (a link before it), as resolve() does
        path = fixpath(dirfd, path);
        if (path[0] == '/') base = 0;
    }
    i32 pl = slen(path), slash = pl && (path[pl - 1] == '/' || (pl > 1 && path[pl - 1] == '.' && path[pl - 2] == '/'));  // (fixpath can give "")
    if (base) n = vwalk(base, n, cp, cl);
    n = vwalk(path, n, cp, cl);
    u64 k0 = n ? ckey(cp[0], cl[0]) : 0;
    if (k0 != N_DEV && k0 != N_PROC) return 0;
    i32 id = 0, err = FE_NOENT;
    if (k0 == N_DEV) {
        i32 c = n > 1 ? dev_id(ckey(cp[1], cl[1])) : 0;
        if (n == 1) id = VN_DEV;
        else if (n == 2) id = c;
        else if (c > VN_SHM) err = FE_NOTDIR;  // below a device
    } else if (n == 1) {
        id = VN_PROC;
    } else if (ckey(cp[1], cl[1]) == N_SELF) {
        if (n == 2) {
            id = VN_SELF;
        } else if (ckey(cp[2], cl[2]) == N_FD) {
            i32 fd = n > 3 ? fdnum(cp[3], cl[3]) : -1;
            if (n == 3) id = VN_FDDIR;
            else if (fd >= 0 && vobj(fd)) {
                if (n == 4) id = VN_FDLINK, v->n = fd;
                else err = FE_NOTDIR;
                if (id && slash && !fd_isdir(fd)) id = 0, err = FE_NOTDIR;  // "/proc/self/fd/1/": the target must be a directory
            }
        }
    }
    if (id > VN_SHM && id != VN_FDLINK && slash) id = 0, err = FE_NOTDIR;  // "/dev/null/", "/dev/null/."
    v->id = id, v->err = err, v->slash = slash;
    return id ? 1 : 2;
}

// ---- the WASI filestat of a node (see the top)
static void vfs(i32 id, i32 n, u64 *fs) {
    Vt *T = vt();
    for (i32 k = 0; k < 8; k++) fs[k] = 0;
    fs[0] = VDEV, fs[1] = vn_ino(id, n), fs[3] = 1;
    ((u8 *)fs)[16] = id == VN_FDLINK ? 7 : id <= VN_SHM ? 3 : 2;
    *(u32 *)((u8 *)fs + 20) = vn_mode(id);
    if (id <= VN_SHM) fs[4] = 4096;
    if (T) fs[5] = fs[6] = fs[7] = T->ts;
}
// put_stat made the 96 bytes from vfs; Emscripten's st_dev (the inode of a device, 1 for the rest) and st_rdev are not in it
static void vpatch(u8 *buf, i32 id) {
    *(u32 *)(buf + 0) = id >= VN_NULL && id <= VN_STDERR ? (u32)vn_ino(id, 0) : 1;
    *(u32 *)(buf + 20) = vn_rdev(id);
}
static i32 dev_fs(i32 fd, u64 *fs) {  // the number is a virtual node: its filestat in fs, 1
    Obj *o = vobj(fd);
    if (!o || o->kind != K_DEV) return 0;
    vfs(o->dev, 0, fs);
    return 1;
}

// ---- /proc/self/fd/N: the target of the link, written to buf cut to len (not ended) -> its length, or -errno
static i32 fd_target(i32 fd, char *buf, i32 len) {
    Obj *o = vobj(fd);
    char tmp[24];
    const char *s = o ? o->path : 0;
    i32 n = 0;
    if (!o) return -FE_NOENT;
    if (o->kind == K_FILE && o->std) {  // Pyodide: /dev/stdin, /dev/stdout, /dev/stderr
        s = tmp, n = vn_put(tmp, VN_STDIN + o->w);
    } else if (o->kind == K_PIPER || o->kind == K_PIPEW || o->kind == K_SOCK) {  // Linux: pipe:[inode], socket:[inode]
        s = tmp;
        if (o->kind == K_SOCK) n = 7, tmp[0] = 's', tmp[1] = 'o', tmp[2] = 'c', tmp[3] = 'k', tmp[4] = 'e', tmp[5] = 't', tmp[6] = ':';
        else n = 5, tmp[0] = 'p', tmp[1] = 'i', tmp[2] = 'p', tmp[3] = 'e', tmp[4] = ':';
        tmp[n++] = '[';
        n += put_num(tmp + n, o->kind == K_SOCK ? (u32)o->w : o->pipe->ino + (o->kind == K_PIPEW));
        tmp[n++] = ']';
    } else if (s) {
        n = slen(s);
    } else {
        return -FE_NOENT;  // opened by a path that could not be kept
    }
    u32 cap = (u32)len;  // a size of 2^31 or more is a size, not a negative one
    if ((u32)n > cap) n = (i32)cap;
    for (i32 k = 0; k < n; k++) buf[k] = s[k];
    return n;
}

// ---- open: the object for a virtual path, in the free number fd -> fd, or -errno
static i32 dev_open(i32 fd, i32 vk, const Vn *v, i32 flags) {
    if (vk == 2) return -((flags & 0100) && v->err == FE_NOENT ? FE_ACCES : v->err);  // nothing can be made here
    i32 dir = v->id <= VN_SHM, acc = flags & 3;
    if (v->id == VN_FDLINK) return -FE_ACCES;  // (Pyodide's answer; Linux would open what the link points to)
    if ((flags & 0100) && (flags & 0200)) return -FE_EXIST;
    if ((flags & 0200000) && !dir) return -FE_NOTDIR;
    if (dir && (acc || (flags & (01000 | 0100)))) return -FE_ISDIR;  // (a write open or O_CREAT of a directory)
    u64 fs[8];
    vfs(v->id, 0, fs);
    Meta *r = meta_find(fs[0], fs[1]);  // a chmod of the session counts
    u32 mode = r ? r->mode : vn_mode(v->id);
    i32 need = acc == 0 ? 4 : acc == 1 ? 2 : 6;
    if (((need & 4) && !(mode & 0444)) || ((need & 2) && !(mode & 0222))) return -FE_ACCES;
    Obj *o = (Obj *)calloc(1, sizeof(Obj));
    char *p = (char *)malloc(16);
    if (!o || !p) {
        free(o), free(p);
        return -ENOMEM;
    }
    vn_put(p, v->id);
    o->kind = K_DEV, o->ref = 1, o->w = -1, o->dev = (u8)v->id, o->oflags = flags, o->fl = flags & 02000, o->nb = (u8)((flags & 04000) != 0), o->path = p;
    Vt *T = vt();  // (not 0: fd_new made it)
    T->o[fd] = o;
    T->cloexec[fd] = (flags & 02000000) != 0;
    return fd;
}

// ---- read, write (the WASI forms of x_fd_read/x_fd_write, which call these for a K_DEV number)
static u32 iov_total(const u32 *iov, i32 n) {  // the bytes of the buffers, at most Linux's MAX_RW_COUNT
    u64 t = 0;
    for (i32 k = 0; k < n; k++) t += iov[2 * k + 1];
    return t > 0x7ffff000ull ? 0x7ffff000u : (u32)t;
}
static i32 dev_read(const Obj *o, const u32 *iov, i32 n, i32 *nread) {
    i32 id = o->dev;
    if ((o->oflags & 3) == 1) return FE_BADF;  // opened write-only
    if (dev_isdir(o)) return FE_ISDIR;
    if (id == VN_TTY1) return FE_NXIO;
    if (id == VN_STDOUT || id == VN_STDERR) return FE_IO;
    u32 room = iov_total(iov, n);
    if (id == VN_NULL || !room) return *nread = 0;  // (a read of no bytes must not wait for stdin)
    if (id == VN_TTY || id == VN_STDIN) return w_fd_read(0, iov, n, nread);
    for (i32 k = 0, left = (i32)room; k < n && left > 0; k++) {  // random, urandom
        i32 l = iov[2 * k + 1] < (u32)left ? (i32)iov[2 * k + 1] : left;
        for (i32 at = 0; at < l; at += 256)
            if (getentropy((u8 *)iov[2 * k] + at, (u32)(l - at < 256 ? l - at : 256))) return FE_IO;
        left -= l;
    }
    *nread = (i32)room;
    return 0;
}
static i32 dev_write(const Obj *o, const u32 *iov, i32 n, i32 *nw) {
    i32 id = o->dev;
    if ((o->oflags & 3) == 0) return FE_BADF;  // opened read-only
    if (dev_isdir(o)) return FE_ISDIR;
    if (id == VN_STDIN) return FE_IO;
    if (id == VN_TTY || id == VN_STDOUT) return w_fd_write(1, iov, n, nw);
    if (id == VN_TTY1 || id == VN_STDERR) return w_fd_write(2, iov, n, nw);
    *nw = (i32)iov_total(iov, n);  // null, random, urandom: all of it is taken
    return 0;
}

// ---- the mutating path calls (mkdir, unlink, rmdir, rename, symlink, link) never reach the host's folder for a path in the
// virtual tree. -> 0 (not virtual: the caller goes on), else the errno. mk: the call makes the name (an existing node is
// EEXIST, a name that can not exist here EACCES: nothing can be made under /dev or /proc), else it needs the name to exist
// (a node is EACCES: it can not be removed or renamed; a name that is not there says why). mk == 2: rename's new name, which
// would replace a node (EACCES: it can not be replaced, like a name that can not be made) where mkdir and symlink say EEXIST.
static i32 vdeny(i32 dirfd, const char *path, i32 mk) {
    Vn v;
    i32 vk = vnode(dirfd, path, &v);
    if (!vk) return 0;
    if (vk == 1) return mk == 1 ? FE_EXIST : FE_ACCES;
    return mk && v.err == FE_NOENT ? FE_ACCES : v.err;
}

// ---- the terminal requests of /dev/tty as Pyodide's answers them: TCGETS gives a terminal in cooked mode, TIOCGWINSZ 24 rows
// by 80 columns, TIOCGPGRP 0, and the setting requests succeed; /dev/tty1 succeeds without writing anything. (musl's isatty is
// TIOCGWINSZ: both are terminals.) argp: the request's argument, or 0.
static i32 tty_ioctl(i32 id, i32 op, u8 *argp) {
    if (!argp) return -FE_FAULT;
    if (id == VN_TTY1 || op == 0x5402 || op == 0x5403 || op == 0x5404 || op == 0x5414 || op == 0x5410) return 0;
    if (op == 0x5413) {
        for (i32 k = 0; k < 8; k++) argp[k] = 0;
        argp[0] = 24, argp[2] = 80;
    } else if (op == 0x540F) {
        *(i32 *)argp = 0;
    } else {  // TCGETS: struct termios (60 bytes): the four flag words, c_line, c_cc
        for (i32 k = 0; k < 60; k++) argp[k] = 0;
        *(u32 *)argp = 0x6500, *(u32 *)(argp + 4) = 5, *(u32 *)(argp + 8) = 0xbf, *(u32 *)(argp + 12) = 0x8a3b;
        u8 *c = argp + 17;  // VINTR VQUIT VERASE VKILL VEOF VTIME VMIN VSWTC VSTART VSTOP VSUSP VEOL VREPRINT VDISCARD VWERASE VLNEXT
        c[0] = 3, c[1] = 0x1c, c[2] = 0x7f, c[3] = 0x15, c[4] = 4, c[5] = 0, c[6] = 1, c[7] = 0;
        c[8] = 0x11, c[9] = 0x13, c[10] = 0x1a, c[11] = 0, c[12] = 0x12, c[13] = 0x0f, c[14] = 0x17, c[15] = 0x16;
    }
    return 0;
}

// ---- the listing of a directory, as the WASI dirent records that sc_getdents64 turns into linux_dirent64 ({d_next u64, d_ino
// u64, d_namlen u32, d_type u8, name}): "." and "..", then the children. /proc/self/fd lists the table as it is now.
static u32 dent(u8 *b, u32 at, u64 ino, u8 ft, const char *nm, i32 l) {
    u8 *r = b + at;
    *(u64 *)r = at + 1, *(u64 *)(r + 8) = ino, *(u32 *)(r + 16) = (u32)l, r[20] = ft, r[21] = r[22] = r[23] = 0;
    for (i32 i = 0; i < l; i++) r[24 + i] = (u8)nm[i];
    return at + 24 + (u32)l;
}
static i32 knm(char *d, u64 key) {
    i32 l = 0;
    for (; key; key >>= 8) d[l++] = (char)key;
    return l;
}
static i32 dev_snap(const Obj *o, Snap *s) {  // WASI errno: 0 or ENOMEM
    i32 id = o->dev, cnt = 2;
    Vt *T = vt();
    if (id == VN_DEV) cnt += 9;
    else if (id == VN_PROC || id == VN_SELF) cnt += 1;
    else if (id == VN_FDDIR)
        for (i32 k = 0; T && k < MAXFD; k++) cnt += T->o[k] != 0;
    u8 *b = (u8 *)malloc(32u * (u32)cnt);  // (a record is 24 bytes and a name of at most 7)
    if (!b) return ENOMEM;
    char nm[8];
    u32 at = dent(b, 0, vn_ino(id, 0), 3, nm, knm(nm, 0x2e));
    at = dent(b, at, 1, 3, nm, knm(nm, 0x2e2e));
    if (id == VN_DEV) {
        for (i32 c = VN_SHM; c <= VN_STDERR; c++) at = dent(b, at, vn_ino(c, 0), c <= VN_SHM ? 3 : 2, nm, knm(nm, vn_name(c)));
    } else if (id == VN_PROC || id == VN_SELF) {
        i32 c = id == VN_PROC ? VN_SELF : VN_FDDIR;
        at = dent(b, at, vn_ino(c, 0), 3, nm, knm(nm, vn_name(c)));
    } else if (id == VN_FDDIR) {
        for (i32 k = 0; T && k < MAXFD; k++)
            if (T->o[k]) at = dent(b, at, vn_ino(VN_FDLINK, k), 7, nm, put_num(nm, (u32)k));
    }
    s->buf = b, s->len = at, s->cpos = s->cidx = 0, s->loaded = 1;
    return 0;
}

#endif
