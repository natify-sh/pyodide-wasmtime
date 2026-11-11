// The open-files table, path resolution, stat, open, dup, fcntl, readdir, lseek. Included only by adapter.c.
#ifndef ADAPTER_OPENFILES_H
#define ADAPTER_OPENFILES_H

#include "common.h"
#include "state.h"
#include "cwd.h"
#include "metadata.h"
#include "vfd.h"

// ---- the open files: the absolute guest path and the open flags of each descriptor opened by openat (indexed by the
// WASI descriptor that holds the file, see vfd.h): the paths that ".." and fstatfs need, and mmap's reopen.
typedef struct {
    char *path[MAXFD];
    i32 flags[MAXFD];
} Fds;
__asm__(".globaltype fds_state, i32\nfds_state:\n");
static Fds *fds(void) {
    Fds *r;
    __asm__ volatile("global.get fds_state\n\tlocal.set %0" : "=r"(r));
    if (!r) {
        r = (Fds *)calloc(1, sizeof(Fds));
        __asm__ volatile("local.get %0\n\tglobal.set fds_state" : : "r"(r));
    }
    return r;
}
static const char *fd_base_path(i32 fd) {  // the path of a directory descriptor, including the preopens
    fd = rfd(fd);
    if (fd >= 0 && fd < MAXFD && fds()->path[fd]) return fds()->path[fd];
    Pre *P = preopens();
    for (i32 k = 0; k < P->n; k++)
        if (P->fd[k] == fd) return P->name[k];
    return 0;
}
static char *absdup(i32 dirfd, const char *path);
static void fd_forget(i32 fd) {
    if (fd >= 0 && fd < MAXFD && fds()->path[fd]) {
        free(fds()->path[fd]);
        fds()->path[fd] = 0;
    }
}
// the WASI descriptor `from` is renumbered to `to` (vfd.h): its records follow it
static void fd_move_meta(i32 from, i32 to) {
    if (from < 0 || from >= MAXFD || to < 0 || to >= MAXFD) return;
    fd_forget(to);
    fds()->path[to] = fds()->path[from], fds()->flags[to] = fds()->flags[from];
    fds()->path[from] = 0;
    if (!ckp(from > to ? from : to)) return;  // the table grows (and moves) here, not between the two pointers
    u64 *a = ckp(from), *b = ckp(to);
    if (a && b) *b = *a, *a = 0;
}
// is a descriptor (other than `skip`) that this adapter opened still open on the file (dev, ino)?
static i32 fd_open_inode(u64 dev, u64 ino, i32 skip) {
    Fds *F = fds();
    for (i32 k = 0; k < MAXFD; k++) {
        u64 fs[8];
        if (k != skip && F->path[k] && !w_fd_filestat_get(k, fs) && fs[0] == dev && fs[1] == ino) return 1;
    }
    return 0;
}
// the last name of a file is gone: its record goes too, unless a descriptor still holds the file (an unlinked file keeps
// its mode until the last close; its inode can not be reused before)
static void meta_release(u64 dev, u64 ino) {
    Meta *e = meta_find(dev, ino);
    if (!e) return;
    if (fd_open_inode(dev, ino, -1)) {
        if (!e->orphan) e->orphan = 1, mt()->norphan++;
    } else {
        meta_del(dev, ino);
    }
}
// a descriptor is about to be closed: if it held an unlinked file, drop the record when it was the last one
static void meta_closing(i32 fd) {
    u64 fs[8];
    if (w_fd_filestat_get(fd, fs)) return;
    Meta *e = meta_find(fs[0], fs[1]);
    if (e && e->orphan && !fd_open_inode(fs[0], fs[1], fd)) meta_del(fs[0], fs[1]);
}

static i32 ncomp(const char *s) {  // the depth of an absolute path below the root
    i32 n = 0;
    for (i32 i = 0; s[i];) {
        while (s[i] == '/') i++;
        if (!s[i]) break;
        i32 st = i;
        while (s[i] && s[i] != '/') i++;
        i32 l = i - st;
        if (l == 2 && s[st] == '.' && s[st + 1] == '.') {
            if (n) n--;
        } else if (!(l == 1 && s[st] == '.')) {
            n++;
        }
    }
    return n;
}
static i32 has_dotdot(const char *s) {
    for (i32 i = 0; s[i];) {
        while (s[i] == '/') i++;
        i32 st = i;
        while (s[i] && s[i] != '/') i++;
        if (i - st == 2 && s[st] == '.' && s[st + 1] == '.') return 1;
    }
    return 0;
}
// The path to resolve (the path itself when it needs nothing, else a buffer of ours):
//  * a path relative to the cwd is made absolute (the cwd is kept here, WASI has none);
//  * ".." is resolved by WASI physically, and that is right except where WASI refuses it: above the root (Linux: "/.." is "/")
//    and out of a directory descriptor (WASI's sandbox is the descriptor). A chain of ".." that opens the path, from the
//    cwd (a physical path) or the root, is a plain lexical pop and is clamped here; a ".." after a name may follow a symlink,
//    so such a path is walked physically (phys(): readlink of every name) and the result is clamped at the real root;
//  * a relative path with ".." to a directory descriptor is left to WASI, and walked physically from the path the
//    descriptor was opened with only if WASI refuses it, and only if that path still names the same directory (a
//    renamed directory is not guessed at: the refusal stands).
static i32 phys(const char *base, const char *path, i32 follow, char **res);
static i32 resolve(i32 dirfd, const char *path, const char **out, i32 *len, char *dot);
static i32 lead_dots_only(const char *s) {  // every ".." comes before the first name
    i32 seen = 0;
    for (i32 i = 0; s[i];) {
        while (s[i] == '/') i++;
        i32 st = i;
        while (s[i] && s[i] != '/') i++;
        i32 l = i - st;
        if (l == 2 && s[st] == '.' && s[st + 1] == '.') {
            if (seen) return 0;
        } else if (l && !(l == 1 && s[st] == '.')) {
            seen = 1;
        }
    }
    return 1;
}
static const char *fixpath(i32 dirfd, const char *path) {
    dirfd = rfd(dirfd);
    Cwd *C = cwdst();
    i32 rel = path[0] != '/';
    i32 dd = has_dotdot(path);
    const char *base = 0;
    i32 byfd = rel && dirfd != AT_FDCWD;
    if (byfd) {
        u64 fs[8], gs[8];
        if (!dd || w_path_filestat_get(dirfd, 0, path, slen(path), fs) != FE_PERM) return path;
        base = fd_base_path(dirfd);
        char dot[2];
        const char *bp;
        i32 bn, bfd;
        if (!base) return path;
        bfd = resolve(AT_FDCWD, base, &bp, &bn, dot);
        if (w_fd_filestat_get(dirfd, fs) || w_path_filestat_get(bfd, 1, bp, bn, gs) || fs[0] != gs[0] || fs[1] != gs[1]) return path;
    } else if (rel) {
        base = C->cwd;
    }
    i32 compose = rel && !byfd && !(C->cwd[0] == '/' && C->cwd[1] == 0);
    if (!compose && !dd) return path;
    if (dd && (byfd || !lead_dots_only(path))) {
        char *r;
        if (!phys(base, path, 0, &r)) {
            u32 n = (u32)slen(r);
            char *o = slot(C->flip, n + 1);
            if (o) {
                C->flip ^= 1;
                for (u32 i = 0; i <= n; i++) o[i] = r[i];
                free(r);
                return o;
            }
            free(r);
        }
        if (byfd) return path;
    }
    i32 depth = base ? ncomp(base) : 0;
    u32 bl = compose ? (u32)slen(base) : 0;
    char *o = slot(C->flip, bl + (u32)slen(path) + 2);
    if (!o) return path;
    C->flip ^= 1;
    i32 k = 0;
    if (compose) {
        for (u32 i = 0; i < bl; i++) o[k++] = base[i];
        if (k == 0 || o[k - 1] != '/') o[k++] = '/';
    }
    for (i32 i = 0; path[i];) {
        while (path[i] == '/') o[k++] = path[i++];
        if (!path[i]) break;
        i32 st = i;
        while (path[i] && path[i] != '/') i++;
        i32 l = i - st;
        if (l == 2 && path[st] == '.' && path[st + 1] == '.') {
            if (depth == 0) {  // above the root: it stays there
                if (path[i] == '/') i++;
                continue;
            }
            depth--;
        } else if (!(l == 1 && path[st] == '.')) {
            depth++;
        }
        for (i32 j = 0; j < l; j++) o[k++] = path[st + j];
    }
    o[k] = 0;
    return o;
}
// an absolute path (malloc'd, ".." resolved as above), or 0: the directory descriptor has no known path, or no memory
static char *absdup(i32 dirfd, const char *path) {
    if (path[0] == '/') {
        const char *f = fixpath(dirfd, path);
        return dupn(f, (u32)slen(f));
    }
    const char *base = dirfd == AT_FDCWD ? cwdst()->cwd : fd_base_path(dirfd);
    if (!base) return 0;
    u32 bl = (u32)slen(base), pl = (u32)slen(path);
    char *t = (char *)malloc(bl + pl + 2);
    if (!t) return 0;
    for (u32 i = 0; i < bl; i++) t[i] = base[i];
    u32 k = bl;
    if (k == 0 || t[k - 1] != '/') t[k++] = '/';
    for (u32 i = 0; i <= pl; i++) t[k + i] = path[i];
    const char *f = fixpath(AT_FDCWD, t);
    char *r = dupn(f, (u32)slen(f));
    free(t);
    return r;
}

// A guest path and dirfd -> (WASI fd, path pointer, length). An empty result is ".". The cwd is kept by chdir (the root at first).
static i32 resolve(i32 dirfd, const char *path, const char **out, i32 *len, char *dot) {
    i32 fd = dirfd = rfd(dirfd);
    if (path[0] != '/' && is_pre(dirfd)) {  // a preopen is no descriptor of the guest: WASI answers EBADF for -1
        dot[0] = '.', dot[1] = 0;
        *out = dot, *len = 1;
        return -1;
    }
    path = fixpath(dirfd, path);
    if (path[0] == '/' || dirfd == AT_FDCWD) {
        Pre *P = preopens();
        i32 best = -1, bl = -1;
        for (i32 k = 0; k < P->n; k++) {
            i32 l = P->len[k];
            const char *nm = P->name[k];
            i32 root = (l == 1 && nm[0] == '/');
            const char *q = path[0] == '/' ? path : 0;
            if (!q) {  // relative to the cwd "/": the root preopen
                if (root && l > bl) best = k, bl = l;
                continue;
            }
            i32 m = 1;
            if (!root) {
                for (i32 i = 0; i < l; i++)
                    if (q[i] != nm[i]) { m = 0; break; }
                if (m && q[l] != 0 && q[l] != '/') m = 0;
            }
            if (m && l > bl) best = k, bl = l;
        }
        fd = best >= 0 ? P->fd[best] : PREOPEN;
        if (path[0] == '/' && best >= 0 && !(bl == 1 && P->name[best][0] == '/')) path += bl;
    }
    while (*path == '/') path++;
    i32 n = slen(path);
    if (n == 0) {
        dot[0] = '.';
        path = dot;
        n = 1;
    }
    *out = path;
    *len = n;
    return fd;
}

// WASI filestat (64 bytes) -> Emscripten struct stat (96 bytes): the type from the WASI filetype, the permission bits
// and owners from the record (or the defaults). st_dev is 32 bits in this ABI: the two halves are folded.
static void put_stat(u8 *dst, const u8 *fs) {
    u64 dev = *(const u64 *)(fs + 0), ino = *(const u64 *)(fs + 8);
    u8 ft = fs[16];
    u64 nlink = *(const u64 *)(fs + 24), size = *(const u64 *)(fs + 32);
    u64 at = *(const u64 *)(fs + 40), mtm = *(const u64 *)(fs + 48), ct = *(const u64 *)(fs + 56);
    Meta *r = meta_find(dev, ino);
    u32 mode = type_bits(ft) | (r ? r->mode : def_for(fs));
    if (ft == 7 && r && r->target) size = (u64)slen(r->target);  // a symlink's size is the length of its target
    for (i32 i = 0; i < 96; i++) dst[i] = 0;
    *(u32 *)(dst + 0) = (u32)dev ^ (u32)(dev >> 32);
    *(u32 *)(dst + 4) = mode;
    *(u32 *)(dst + 8) = (u32)nlink;
    *(u32 *)(dst + 12) = r ? r->uid : 0;
    *(u32 *)(dst + 16) = r ? r->gid : 0;
    *(i64 *)(dst + 24) = (i64)size;
    *(u32 *)(dst + 32) = 4096;
    *(u32 *)(dst + 36) = (u32)((size + 511) / 512);
    *(i64 *)(dst + 40) = (i64)(at / 1000000000ull);
    *(u32 *)(dst + 48) = (u32)(at % 1000000000ull);
    *(i64 *)(dst + 56) = (i64)(mtm / 1000000000ull);
    *(u32 *)(dst + 64) = (u32)(mtm % 1000000000ull);
    *(i64 *)(dst + 72) = (i64)(ct / 1000000000ull);
    *(u32 *)(dst + 80) = (u32)(ct % 1000000000ull);
    *(u64 *)(dst + 88) = ino;
}

// the WASI filestat of dirfd + path: an empty path is ENOENT (only AT_EMPTY_PATH allows it); -> an errno or 0
static i32 fx_lookup(i32 dirfd, const char *path, i32 follow, u64 *fs) {
    if (!path[0]) return FE_NOENT;
    char dot[2];
    const char *p;
    i32 n, fd = resolve(dirfd, path, &p, &n, dot);
    return w_path_filestat_get(fd, follow ? 1 : 0, p, n, fs);
}

static i32 stat_path(i32 dirfd, const char *path, void *buf, i32 follow) {
    u64 fs[8];
    i32 e = fx_lookup(dirfd, path, follow, fs);
    if (e) return -e;
    put_stat((u8 *)buf, (const u8 *)fs);
    return 0;
}

EXPORT("__syscall_getcwd") i32 sc_getcwd(char *buf, i32 size) {
    Cwd *C = cwdst();
    i32 n = slen(C->cwd);
    if (n + 1 > size) return -ERANGE;
    for (i32 k = 0; k <= n; k++) buf[k] = C->cwd[k];
    return n + 1;
}

// The physical path of `path` (against `base` when relative): the names are walked one by one and every symlink is read
// and followed (the last name only if `follow`), ".." goes to the real parent, a loop of more than 40 links is ELOOP.
// -> 0 and the absolute path in *res (malloc'd), or an errno (positive).
static i32 phys(const char *base, const char *path, i32 follow, char **res) {
    char sl[2];
    sl[0] = '/', sl[1] = 0;
    char *cur = path[0] == '/' ? dupn(sl, 1) : dupn(base, (u32)slen(base));
    char *rest = dupn(path, (u32)slen(path));
    i32 links = 0, err = 0;
    if (!cur || !rest) {
        if (cur) free(cur);
        if (rest) free(rest);
        return ENOMEM;
    }
    for (i32 i = 0;;) {
        while (rest[i] == '/') i++;
        if (!rest[i]) break;
        i32 st = i;
        while (rest[i] && rest[i] != '/') i++;
        i32 l = i - st;
        if (l == 1 && rest[st] == '.') continue;
        if (l == 2 && rest[st] == '.' && rest[st + 1] == '.') {  // the parent; the root has none
            i32 j = slen(cur) - 1;
            while (j > 0 && cur[j] != '/') j--;
            if (j == 0) cur[1] = 0;
            else cur[j] = 0;
            continue;
        }
        i32 last = 1;
        for (i32 j = i; rest[j]; j++)
            if (rest[j] != '/') {
                last = 0;
                break;
            }
        i32 cl = slen(cur);
        char *cand = (char *)malloc((u32)(cl + l + 2));
        if (!cand) {
            err = ENOMEM;
            break;
        }
        for (i32 j = 0; j < cl; j++) cand[j] = cur[j];
        if (cl == 0 || cand[cl - 1] != '/') cand[cl++] = '/';
        for (i32 j = 0; j < l; j++) cand[cl + j] = rest[st + j];
        cand[cl + l] = 0;
        if (last && !follow) {
            free(cur);
            cur = cand;
            continue;
        }
        u32 cap = 256;
        char *tb;
        i32 used = 0, e;
        for (;;) {
            char dot[2];
            const char *p;
            i32 n, fd = resolve(AT_FDCWD, cand, &p, &n, dot);
            tb = (char *)malloc(cap);
            if (!tb) {
                e = ENOMEM;
                break;
            }
            e = w_path_readlink(fd, p, n, tb, (i32)cap, &used);
            if (e || used < (i32)cap) break;
            free(tb);
            cap *= 2;
        }
        if (e == ENOMEM) {
            free(cand);
            err = e;
            break;
        }
        if (e == FE_INVAL) {  // not a link
            free(tb);
            free(cur);
            cur = cand;
            continue;
        }
        free(cand);
        if (e || ++links > 40) {
            free(tb);
            err = e ? e : FE_LOOP;
            break;
        }
        tb[used] = 0;
        u32 rl = (u32)slen(rest + i);
        char *nr = (char *)malloc((u32)used + 1 + rl + 1);
        if (!nr) {
            free(tb);
            err = ENOMEM;
            break;
        }
        for (i32 j = 0; j < used; j++) nr[j] = tb[j];
        nr[used] = '/';
        for (u32 j = 0; j <= rl; j++) nr[used + 1 + (i32)j] = rest[i + (i32)j];
        if (tb[0] == '/') {
            free(cur);
            cur = dupn(sl, 1);
            if (!cur) {
                free(tb);
                free(nr);
                free(rest);
                return ENOMEM;
            }
        }
        free(tb);
        free(rest);
        rest = nr;
        i = 0;
    }
    free(rest);
    if (err) {
        free(cur);
        return err;
    }
    *res = cur;
    return 0;
}

// chdir is physical: getcwd after chdir through a link shows the real directory, and ".." is its real parent
EXPORT("__syscall_chdir") i32 sc_chdir(const char *path) {
    if (!path[0]) return -FE_NOENT;
    Cwd *C = cwdst();
    char *res;
    i32 e = phys(C->cwd, path, 1, &res);
    if (e) return -e;
    u64 fs[8];
    char dot[2];
    const char *p;
    i32 n, fd = resolve(AT_FDCWD, res, &p, &n, dot);
    e = w_path_filestat_get(fd, 1, p, n, fs);
    Meta *r = e ? 0 : meta_find(fs[0], fs[1]);
    if (e || *((u8 *)fs + 16) != 3 || (r && !(r->mode & 0111))) {  // the search permission, as Pyodide's nodePermissions
        free(res);
        return e ? -e : *((u8 *)fs + 16) != 3 ? -FE_NOTDIR : -FE_ACCES;
    }
    free(C->cwd);
    C->cwd = res;
    return 0;
}

EXPORT("__syscall_fchdir") i32 sc_fchdir(i32 fd) {
    if (is_pre(fd)) return -FE_BADF;
    const char *p = fd_base_path(fd);  // a directory opened by openat, or a preopen
    if (p) return sc_chdir(p);
    u8 st[24] __attribute__((aligned(8)));
    return (is_virt(fd) || !w_fd_fdstat_get(rfd(fd), st)) ? -FE_NOTDIR : -FE_BADF;  // a stream: not a directory
}

// nocheck: mmap opens the same file again (from its path record), which no permission can forbid
static i32 open_at(i32 dirfd, const char *path, i32 flags, u32 mode, i32 nocheck) {
    char dot[2];
    const char *p;
    i32 n, fd = resolve(dirfd, path, &p, &n, dot);
    i32 acc = flags & 3, oflags = 0, fdflags = 0, created = 0;
    if (flags & 0100) oflags |= 1;       // O_CREAT
    if (flags & 0200000) oflags |= 2;    // O_DIRECTORY
    if (flags & 0200) oflags |= 4;       // O_EXCL
    if (flags & 01000) oflags |= 8;      // O_TRUNC
    if (flags & 02000) fdflags |= 1;     // O_APPEND
    if (flags & 04000) fdflags |= 4;     // O_NONBLOCK
    if (!nocheck && ((flags & 0100) || mt()->nrestrict)) {  // is it made now? if it exists, may it be opened (its recorded mode)?
        u64 fs[8];
        if (w_path_filestat_get(fd, (flags & 0400000) ? 0 : 1, p, n, fs)) {
            created = (flags & 0100) != 0;
        } else if (!((flags & 0100) && (flags & 0200))) {
            Meta *r = meta_find(fs[0], fs[1]);
            i32 need = acc == 0 ? 4 : acc == 1 ? 2 : 6;
            if (flags & 01000) need |= 2;
            if (r && (((need & 4) && !(r->mode & 0444)) || ((need & 2) && !(r->mode & 0222)))) return -FE_ACCES;
        }
    }
    if (created) {
        i32 de = dir_denies(fd, p, n, 1);
        if (de) return -de;
    }
    u64 all = (1ull << 30) - 1, writes = (1ull << 6) | (1ull << 0) | (1ull << 8) | (1ull << 22);
    u64 reads = (1ull << 1) | (1ull << 14);
    u64 rights = acc == 0 ? all & ~writes : acc == 1 ? all & ~reads : all;
    i32 out = -1;
    i32 e = w_path_open(fd, (flags & 0400000) ? 0 : 1, p, n, oflags, rights, all, fdflags, &out);
    if (e) return -e;
    if (created) {
        u64 fs[8];
        if (!w_fd_filestat_get(out, fs)) meta_created((const u8 *)fs, mode, 07777);
    }
    if (out >= 0 && out < MAXFD) {
        u64 *ck = ckp(out);
        if (ck) *ck = 0;  // a new descriptor lists its directory from the start
        fd_forget(out);
        char *copy = absdup(dirfd, path);  // the path mmap opens again, of any length
        if (copy) {
            fds()->path[out] = copy;
            fds()->flags[out] = flags;
        }
    }
    return out;
}

// the mode of O_CREAT is the variable argument (va points at it)
EXPORT("__syscall_openat") i32 sc_openat(i32 dirfd, const char *path, i32 flags, i32 va) {
    i32 fd = open_at(dirfd, path, flags, va ? *(const u32 *)va : 0, 0);
    if (fd >= 0) cloexec_set(fd, flags & 02000000);  // O_CLOEXEC: kept per number, as POSIX does (there is no exec)
    return fd;
}

EXPORT("__syscall_stat64") i32 sc_stat64(const char *path, void *buf) { return stat_path(AT_FDCWD, path, buf, 1); }
EXPORT("__syscall_lstat64") i32 sc_lstat64(const char *path, void *buf) { return stat_path(AT_FDCWD, path, buf, 0); }

EXPORT("__syscall_fstat64") i32 sc_fstat64(i32 fd, void *buf) {
    u64 fs[8];
    if (is_pre(fd)) return -FE_BADF;
    if (is_sock(fd)) {  // a socket: S_IFSOCK
        for (i32 i = 0; i < 8; i++) fs[i] = 0;
        put_stat((u8 *)buf, (const u8 *)fs);
        *(u32 *)((u8 *)buf + 4) = 0140777;
        return 0;
    }
    if (is_pipe(fd)) {  // PIPEFS's getattr: a FIFO, one link, dev 14, the times of its creation
        Obj *o = vobj(fd);
        for (i32 i = 0; i < 8; i++) fs[i] = 0;
        fs[0] = 14, fs[1] = o->pipe->ino + (o->kind == K_PIPEW), fs[3] = 1, fs[5] = fs[6] = fs[7] = o->pipe->ts;
        put_stat((u8 *)buf, (const u8 *)fs);
        *(u32 *)((u8 *)buf + 4) = 010600;
        return 0;
    }
    fd = rfd(fd);
    i32 e = w_fd_filestat_get(fd, fs);
    if (e) return -e;
    put_stat((u8 *)buf, (const u8 *)fs);
    if (fd_std(fd)) *(u32 *)((u8 *)buf + 4) = 0020666;  // the standard streams are character devices (Pyodide's fstat(1))
    return 0;
}

EXPORT("__syscall_newfstatat") i32 sc_newfstatat(i32 dirfd, const char *path, void *buf, i32 flags) {
    if (!path[0] && (flags & 0x1000)) {  // AT_EMPTY_PATH: the descriptor itself, or the cwd
        if (dirfd != AT_FDCWD) return sc_fstat64(dirfd, buf);
        char dot[2];
        dot[0] = '.', dot[1] = 0;
        return stat_path(AT_FDCWD, dot, buf, 1);
    }
    return stat_path(dirfd, path, buf, !(flags & 0x100));  // an empty path is ENOENT
}

EXPORT("__syscall_readlinkat") i32 sc_readlinkat(i32 dirfd, const char *path, char *buf, i32 len) {
    char dot[2];
    const char *p;
    i32 n, used = 0, fd = resolve(dirfd, path, &p, &n, dot);
    i32 e = w_path_readlink(fd, p, n, buf, len, &used);
    if (e) return -e;
    if (mt()->ntarget) {  // a link made with an absolute target: what the program stored, not the relative one it holds
        u64 fs[8];
        Meta *r = w_path_filestat_get(fd, 0, p, n, fs) ? 0 : meta_find(fs[0], fs[1]);
        if (r && r->target) {
            i32 tl = slen(r->target);
            used = tl < len ? tl : len;
            for (i32 j = 0; j < used; j++) buf[j] = r->target[j];
        }
    }
    return used;
}

// access: the recorded (or default) mode bits, whoever asks (Pyodide's nodePermissions: any of the user, group, other bits)
EXPORT("__syscall_faccessat") i32 sc_faccessat(i32 dirfd, const char *path, i32 mode, i32 flags) {
    if (mode & ~7) return -FE_INVAL;
    u64 fs[8];
    i32 e = fx_lookup(dirfd, path, !(flags & 0x100), fs);
    if (e) return -e;
    Meta *r = meta_find(fs[0], fs[1]);
    u32 bits = r ? r->mode : def_for((const u8 *)fs);
    if (((mode & 4) && !(bits & 0444)) || ((mode & 2) && !(bits & 0222)) || ((mode & 1) && !(bits & 0111))) return -FE_ACCES;
    return 0;
}

// WASI dirents {d_next u64, d_ino u64, d_namlen u32, d_type u8, name} -> linux_dirent64
// {d_ino u64, d_off i64, d_reclen u16, d_type u8, name\0, padded to 8}
EXPORT("__syscall_getdents64") i32 sc_getdents64(i32 fd, u8 *dirp, i32 count) {
    if (fd < 0 || is_pre(fd)) return -EBADF;
    if (is_virt(fd)) return -FE_NOTDIR;
    fd = rfd(fd);
    u64 *ck = ckp(fd);
    if (!ck) return -ENOMEM;
    i32 cap = count + 512;
    u8 *tmp = (u8 *)malloc((u32)cap);
    if (!tmp) return -ENOMEM;
    i32 used = 0;
    i32 e = w_fd_readdir(fd, tmp, cap, *ck, &used);
    if (e) {
        free(tmp);
        return -e;
    }
    i32 in = 0, out = 0;
    while (in + 24 <= used) {
        u64 next = *(u64 *)(tmp + in), ino = *(u64 *)(tmp + in + 8);
        u32 nl = *(u32 *)(tmp + in + 16);
        u8 wt = tmp[in + 20];
        if (in + 24 + (i32)nl > used) break;  // a truncated last entry: read it again next time
        i32 reclen = (19 + (i32)nl + 1 + 7) & ~7;
        if (out + reclen > count) break;
        u8 *d = dirp + out;
        *(u64 *)(d + 0) = ino;
        *(i64 *)(d + 8) = (i64)next;
        *(u16 *)(d + 16) = (u16)reclen;
        d[18] = wt == 3 ? 4 : wt == 4 ? 8 : wt == 7 ? 10 : wt == 2 ? 2 : wt == 1 ? 6 : 0;
        for (u32 i = 0; i < nl; i++) d[19 + i] = tmp[in + 24 + i];
        for (i32 i = 19 + (i32)nl; i < reclen; i++) d[i] = 0;
        out += reclen;
        *ck = next;
        in += 24 + (i32)nl;
    }
    free(tmp);
    if (out == 0 && in + 24 <= used) return -22;  // EINVAL: the buffer cannot hold one entry
    return out;
}

static i32 is_sock(i32 fd);
WASI("fd_fdstat_get") i32 w_fd_fdstat_get(i32 fd, void *buf);
WASI("fd_fdstat_set_flags") i32 w_fd_fdstat_set_flags(i32 fd, i32 flags);

// the WASI filetype of an open descriptor (a socket is a stream socket), or -errno (EBADF)
static i32 fd_type(i32 fd) {
    if (is_pre(fd)) return -FE_BADF;
    if (is_virt(fd)) return 6;  // (a pipe is a stream too)
    u8 st[24] __attribute__((aligned(8)));
    i32 e = w_fd_fdstat_get(rfd(fd), st);
    return e ? -e : st[0];
}
// can the descriptor seek? The standard streams, sockets and character devices can not (Pyodide: stream.seekable)
static i32 fd_seekable(i32 fd, i32 ft) { return !fd_std(rfd(fd)) && ft != 2 && ft != 5 && ft != 6; }

// fcntl: the flags are WASI's fdflags (append, nonblock) and rights; an invalid descriptor is EBADF for every command (as
// Pyodide's getStreamFromFD). The lock commands of this ABI are F_GETLK 12, F_SETLK 13, F_SETLKW 14: there is one process,
// so a lock is always granted and F_GETLK reports F_UNLCK.
EXPORT("__syscall_fcntl64") i32 sc_fcntl64(i32 fd, i32 cmd, i32 va) {
    if (fd_type(fd) < 0) return -FE_BADF;
    switch (cmd) {
        case 1:  // F_GETFD: FD_CLOEXEC is kept per number (there is no exec: only the answer is real)
            return cloexec_get(fd);
        case 2:  // F_SETFD
            return cloexec_set(fd, *(const i32 *)va & 1);
        case 3: {  // F_GETFL
            if (is_sock(fd)) return 2 | (sock_nb(fd) ? 04000 : 0);  // O_RDWR, O_NONBLOCK
            if (is_pipe(fd)) return (vobj(fd)->kind == K_PIPEW) | vobj(fd)->fl;  // O_WRONLY / O_RDONLY, and what F_SETFL set
            u8 st[24] __attribute__((aligned(8)));
            i32 e = w_fd_fdstat_get(rfd(fd), st);
            if (e) return -e;
            u16 ff = *(u16 *)(st + 2);
            u64 rights = *(u64 *)(st + 8);
            i32 r = (rights & (1ull << 1)) != 0, w = (rights & (1ull << 6)) != 0;
            i32 fl = r && w ? 2 : w ? 1 : 0;  // O_RDWR, O_WRONLY, O_RDONLY
            if (ff & 1) fl |= 02000;          // O_APPEND
            if (ff & 4) fl |= 04000;          // O_NONBLOCK
            return fl;
        }
        case 4: {  // F_SETFL: append and nonblock only
            if (is_sock(fd)) {
                sock_set_nb(fd, (*(const i32 *)va & 04000) != 0);  // va points at the variable arguments
                return 0;
            }
            i32 flags = *(const i32 *)va, ff = 0;  // va points at the variable arguments
            if (is_pipe(fd)) {  // PIPEFS keeps the bits of Emscripten's mask: append, nonblock, async, direct, noatime
                vobj(fd)->fl = (vobj(fd)->fl & ~289792) | (flags & 289792);
                return 0;
            }
            if (flags & 02000) ff |= 1;
            if (flags & 04000) ff |= 4;
            i32 e = w_fd_fdstat_set_flags(rfd(fd), ff);
            return e ? -e : 0;
        }
        case 12: {  // F_GETLK: nobody else holds a lock -> l_type = F_UNLCK
            u16 *fl = va ? *(u16 **)va : 0;
            if (fl) *fl = 2;
            return 0;
        }
        case 13:  // F_SETLK
        case 14:  // F_SETLKW
            return 0;
        case 0:     // F_DUPFD: the lowest free number from the argument on
        case 1030: {  // F_DUPFD_CLOEXEC
            i32 min = *(const i32 *)va;  // va points at the variable arguments
            return min < 0 || min >= MAXFD ? -FE_INVAL : fd_dup(fd, min, 0, cmd == 1030);
        }
        default:
            return -FE_INVAL;
    }
}

// lseek on a descriptor: a directory keeps its readdir cookie here (rewinddir is SEEK_SET 0, seekdir/telldir use the
// d_off of the entries, getdents64 continues from it); the others go to WASI. Sockets can not seek.
EXPORT("fd_seek") i32 x_fd_seek(i32 fd, i64 off, i32 whence, u64 *newoff) {
    if (off > (1ll << 53) || off < -(1ll << 53)) return FE_FBIG;  // the glue's bigintToI53Checked
    if (is_pre(fd)) return FE_BADF;
    if (is_virt(fd)) return FE_SPIPE;
    fd = rfd(fd);
    if ((u32)whence > 2) {  // WASI's enum conversion would trap
        u8 st[24] __attribute__((aligned(8)));
        return w_fd_fdstat_get(fd, st) ? FE_BADF : FE_INVAL;
    }
    i32 e = w_fd_seek(fd, off, whence, newoff);
    if (e != FE_BADF) return e;  // WASI refuses a directory descriptor (EBADF): that one is ours
    u8 st[24] __attribute__((aligned(8)));
    if (w_fd_fdstat_get(fd, st) || st[0] != 3) return e;
    u64 *ck = ckp(fd);
    if (!ck) return ENOMEM;
    i64 pos = whence == 1 ? (i64)*ck + off : off;  // SEEK_SET, SEEK_END (a directory has no size: as SET), SEEK_CUR
    if (whence < 0 || whence > 2 || pos < 0) return FE_INVAL;
    *ck = (u64)pos;
    *newoff = (u64)pos;
    return 0;
}

EXPORT("_emscripten_get_progname") void get_progname(char *buf, i32 len) {  // thisProgram, cut to len-1, always ended
    u64 w[2] = {0, 0};  // "./this.program" from integer constants (no data section)
    w[0] = 0x702e736968742f2eull, w[1] = 0x6d6172676f72ull;
    const char *name = (const char *)w;
    if (len <= 0) return;
    i32 i = 0;
    for (; i < len - 1 && name[i]; i++) buf[i] = name[i];
    buf[i] = 0;
}

static double now_ms(i32 clock) {
    u64 t = 0;
    w_clock_time_get(clock, 1000, &t);
    return (double)t / 1e6;
}
EXPORT("emscripten_date_now") double date_now(void) {  // Date.now(): whole milliseconds
    u64 t = 0;
    w_clock_time_get(0, 1000, &t);
    return (double)(t / 1000000ull);
}
EXPORT("emscripten_get_now") double get_now(void) { return now_ms(1); }
EXPORT("emscripten_get_heap_max") u32 heap_max(void) { return 0xFFFF0000u; }  // getHeapMax(): 4 GiB less a page

EXPORT("emscripten_resize_heap") i32 resize_heap(u32 n) {
    if (n > 0xFFFF0000u) return 0;  // beyond getHeapMax()
    u32 have = (u32)__builtin_wasm_memory_size(0);
    u32 want = (u32)(((u64)n + 65535) / 65536);
    if (want <= have) return 1;
    return __builtin_wasm_memory_grow(0, want - have) == (unsigned long)-1 ? 0 : 1;
}

#endif
