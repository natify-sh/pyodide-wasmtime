// Writing files (what installing a wheel needs). Included only by adapter.c.
#ifndef ADAPTER_WRITES_H
#define ADAPTER_WRITES_H

#include "common.h"
#include "state.h"
#include "cwd.h"
#include "metadata.h"
#include "openfiles.h"

// ================================================================== writing files (what installing a wheel needs)

EXPORT("__syscall_mkdirat") i32 sc_mkdirat(i32 dirfd, const char *path, i32 mode) {
    char dot[2];
    const char *p;
    i32 n, fd = resolve(dirfd, path, &p, &n, dot);
    i32 de = dir_denies(fd, p, n, 1);
    if (de) return -de;
    i32 e = w_mkdir(fd, p, n);
    if (e) return -e;
    u64 fs[8];
    if (!w_path_filestat_get(fd, 0, p, n, fs)) meta_created((const u8 *)fs, (u32)mode, 01777);
    return 0;
}

EXPORT("__syscall_unlinkat") i32 sc_unlinkat(i32 dirfd, const char *path, i32 flags) {
    if (flags && flags != 0x200) return -FE_INVAL;  // only AT_REMOVEDIR is a flag of unlinkat
    char dot[2];
    const char *p;
    i32 n, fd = resolve(dirfd, path, &p, &n, dot);
    u64 key[2];
    i32 doomed = meta_doomed(fd, p, n, key);
    i32 de = dir_denies(fd, p, n, 0);
    if (de) return -de;
    i32 e = (flags & 0x200) ? w_rmdir(fd, p, n) : w_unlink(fd, p, n);  // AT_REMOVEDIR
    if (e) return -e;
    if (doomed) meta_release(key[0], key[1]);
    return 0;
}

EXPORT("__syscall_rmdir") i32 sc_rmdir(const char *path) { return sc_unlinkat(AT_FDCWD, path, 0x200); }

static void relink(i32 dirfd, const char *path);
static void relink_tree(const char *abs, i32 depth);
EXPORT("__syscall_renameat") i32 sc_renameat(i32 olddirfd, const char *oldpath, i32 newdirfd, const char *newpath) {
    char d1[2], d2[2];
    const char *p1, *p2;
    i32 n1, n2, f1 = resolve(olddirfd, oldpath, &p1, &n1, d1), f2 = resolve(newdirfd, newpath, &p2, &n2, d2);
    u64 key[2];
    i32 doomed = meta_doomed(f2, p2, n2, key);  // a file or directory that the rename replaces
    i32 de = dir_denies(f1, p1, n1, 0);
    if (!de) de = dir_denies(f2, p2, n2, 2);
    if (de) return -de;
    i32 e = w_rename(f1, p1, n1, f2, p2, n2);
    if (e) return -e;
    if (doomed) {
        u64 fs[8];
        if (w_path_filestat_get(f2, 0, p2, n2, fs) || fs[0] != key[0] || fs[1] != key[1]) meta_release(key[0], key[1]);
    }
    if (mt()->ntarget) {
        relink(newdirfd, newpath);  // a symlink with a stored absolute target is made again for its new place
        u64 ns[8];
        if (!w_path_filestat_get(f2, 0, p2, n2, ns) && *((u8 *)ns + 16) == 3) {  // a directory: every such link inside it too
            char *abs = absdup(newdirfd, newpath);
            if (abs) {
                relink_tree(abs, 0);
                free(abs);
            }
        }
    }
    return 0;
}

EXPORT("__syscall_ftruncate64") i32 sc_ftruncate64(i32 fd, i64 len) {
    i32 e = w_fd_set_size(fd, (u64)len);
    return e ? -e : 0;
}

EXPORT("__syscall_truncate64") i32 sc_truncate64(const char *path, i64 len) {
    char dot[2];
    const char *p;
    i32 n, fd = resolve(AT_FDCWD, path, &p, &n, dot), out = -1;
    i32 e = w_path_open(fd, 1, p, n, 0, (1ull << 6) | (1ull << 22), 0, 0, &out);  // rights: FD_WRITE (opens it for writing), FD_FILESTAT_SET_SIZE
    if (e) return -e;
    e = w_fd_set_size(out, (u64)len);
    w_fd_close(out);
    return e ? -e : 0;
}

// fallocate as Pyodide's: mode 0 only (EOPNOTSUPP for KEEP_SIZE, PUNCH_HOLE...), the size grows to offset + len if it is smaller
EXPORT("__syscall_fallocate") i32 sc_fallocate(i32 fd, i32 mode, i64 offset, i64 len) {
    if (offset > (1ll << 53) || len > (1ll << 53) || offset < -(1ll << 53) || len < -(1ll << 53)) return -FE_FBIG;
    if (mode != 0) return -FE_OPNOTSUPP;
    if (offset < 0 || len < 0) return -FE_INVAL;
    i32 ft = fd_type(fd);
    if (ft < 0) return ft;
    if (!fd_seekable(fd, ft)) return -FE_SPIPE;
    u64 fs[8];
    i32 e = w_fd_filestat_get(fd, fs);
    if (e) return -e;
    if ((u64)(offset + len) > fs[4]) {  // growing is a write: the recorded mode must allow it (Pyodide's ftruncate checks)
        Meta *r = meta_find(fs[0], fs[1]);
        if (r && !(r->mode & 0222)) return -FE_ACCES;
        e = w_fd_set_size(fd, (u64)(offset + len));
    }
    return e ? -e : 0;
}

// fdatasync: an open descriptor is synced; a stream (nothing to sync, WASI says EINVAL) succeeds, as in Pyodide
EXPORT("__syscall_fdatasync") i32 sc_fdatasync(i32 fd) {
    i32 ft = fd_type(fd);
    if (ft < 0) return ft;
    if (is_sock(fd) || fd <= 2) return 0;
    i32 e = w_fd_datasync(fd);
    // EBADF here is the missing right of a read-only descriptor (a valid one, checked above): nothing to sync
    return e == 0 || e == FE_INVAL || e == FE_BADF || e == 58 /* ENOTSUP */ ? 0 : -e;
}

// advice only (nothing to do), but a bad descriptor is EBADF and a stream or a socket is ESPIPE
EXPORT("__syscall_fadvise64") i32 sc_fadvise64(i32 fd, i64 offset, i64 len, i32 advice) {
    (void)offset, (void)len, (void)advice;
    i32 ft = fd_type(fd);
    if (ft < 0) return ft;
    return fd_seekable(fd, ft) ? 0 : -FE_SPIPE;
}

// A symlink with an absolute target: wasmtime refuses it (EPERM), so the link holds the relative path from its own
// directory (both are in the guest's root, or in the same mount) and the metadata table keeps what the program
// stored, which readlink returns. -> the relative target (malloc'd), or 0 and an errno in *err.
static char *rel_target(i32 dirfd, const char *linkpath, const char *target, i32 *err) {
    char *la = absdup(dirfd, linkpath), *ta = absdup(AT_FDCWD, target), *real = 0, *r = 0;
    *err = !ta || (!la && linkpath[0] == '/') ? ENOMEM : FE_BADF;
    if (la && ta) {
        i32 j = slen(la);
        while (j > 1 && la[j - 1] == '/') la[--j] = 0;
        while (j > 0 && la[j - 1] != '/') j--;
        if (j > 1) la[j - 1] = 0;
        else la[j] = 0;  // the root
        *err = phys(la, la, 1, &real);  // the real directory of the link
        if (!*err) {
            char d1[2], d2[2];
            const char *p1, *p2;
            i32 n1, n2, f1 = resolve(AT_FDCWD, real, &p1, &n1, d1), f2 = resolve(AT_FDCWD, ta, &p2, &n2, d2);
            if (f1 != f2) {
                *err = FE_XDEV;  // the link and the target are in different mounts: not representable
            } else {
                i32 up = ncomp(p1);
                r = (char *)malloc((u32)(up * 3 + n2 + 1));
                if (!r) {
                    *err = ENOMEM;
                    goto done;
                }
                i32 k = 0;
                for (i32 i = 0; i < up; i++) r[k++] = '.', r[k++] = '.', r[k++] = '/';
                for (i32 i = 0; i < n2; i++) r[k++] = p2[i];
                if (k > 0 && r[k - 1] == '/') k--;
                r[k] = 0;
                if (k == 0) r[0] = '.', r[1] = 0;
            }
        }
    }
done:
    if (la) free(la);
    if (ta) free(ta);
    if (real) free(real);
    return r;
}

EXPORT("__syscall_symlinkat") i32 sc_symlinkat(const char *target, i32 newdirfd, const char *linkpath) {
    char dot[2];
    const char *p;
    i32 n, fd, err = 0;
    char *rel = 0;
    if (target[0] == '/') {
        rel = rel_target(newdirfd, linkpath, target, &err);
        if (!rel) return -err;
    }
    fd = resolve(newdirfd, linkpath, &p, &n, dot);  // after rel_target, which uses the path buffers too
    const char *use = rel ? rel : target;
    i32 de = dir_denies(fd, p, n, 1);
    if (de) {
        if (rel) free(rel);
        return -de;
    }
    i32 e = w_symlink(use, slen(use), fd, p, n);
    if (rel) free(rel);
    if (e) return -e;
    if (target[0] == '/') {  // remember what was stored
        u64 fs[8];
        if (!w_path_filestat_get(fd, 0, p, n, fs)) {
            Meta *m = meta_put(fs[0], fs[1], 0777, 0, 0, 7);
            char *tcopy = m ? dupn(target, (u32)slen(target)) : 0;
            if (tcopy) m->target = tcopy, mt()->ntarget++;
        }
    }
    return 0;
}

// A symlink made with an absolute target holds a path relative to its directory: after a rename to another directory it
// is made again for the new place (the record follows to the new inode)
static void relink(i32 dirfd, const char *path) {
    char dot[2];
    const char *p;
    i32 n, fd = resolve(dirfd, path, &p, &n, dot);
    u64 fs[8];
    if (w_path_filestat_get(fd, 0, p, n, fs)) return;
    Meta *r = meta_find(fs[0], fs[1]);
    if (!r || !r->target || *((u8 *)fs + 16) != 7) return;
    char *target = dupn(r->target, (u32)slen(r->target));
    if (!target) return;
    u32 mode = r->mode, uid = r->uid, gid = r->gid;
    u64 dev = fs[0], ino = fs[1];
    i32 err;
    char *rel = rel_target(dirfd, path, target, &err);
    if (rel) {
        fd = resolve(dirfd, path, &p, &n, dot);
        if (!w_unlink(fd, p, n) && !w_symlink(rel, slen(rel), fd, p, n)) {
            meta_del(dev, ino);
            if (!w_path_filestat_get(fd, 0, p, n, fs)) {
                Meta *m = meta_put(fs[0], fs[1], mode, uid, gid, 7);
                if (m) {
                    m->target = target;
                    mt()->ntarget++;
                    target = 0;
                }
            }
        }
        free(rel);
    }
    if (target) free(target);
}

// every symlink under the directory `abs` that has a stored absolute target is made again (symlinks are not followed)
static void relink_tree(const char *abs, i32 depth) {
    if (depth > 200) return;
    char dot[2];
    const char *p;
    i32 n, fd = resolve(AT_FDCWD, abs, &p, &n, dot), dfd = -1;
    u64 all = (1ull << 30) - 1;
    if (w_path_open(fd, 0, p, n, 2 /* O_DIRECTORY */, all & ~((1ull << 6) | (1ull << 22)), 0, 0, &dfd)) return;
    u32 cap = 4096;
    u8 *buf = (u8 *)malloc(cap);
    u64 cookie = 0;
    while (buf) {
        i32 used = 0;
        if (w_fd_readdir(dfd, buf, (i32)cap, cookie, &used) || used == 0) break;
        i32 in = 0;
        while (in + 24 <= used) {
            u64 next = *(u64 *)(buf + in);
            u32 nl = *(u32 *)(buf + in + 16);
            u8 ft = buf[in + 20];
            if (in + 24 + (i32)nl > used) break;
            char *name = dupn((const char *)buf + in + 24, nl);
            in += 24 + (i32)nl;
            cookie = next;
            if (!name) continue;
            if (!(nl == 1 && name[0] == '.') && !(nl == 2 && name[0] == '.' && name[1] == '.') && (ft == 7 || ft == 3)) {
                u32 al = (u32)slen(abs);
                char *child = (char *)malloc(al + nl + 2);
                if (child) {
                    for (u32 i = 0; i < al; i++) child[i] = abs[i];
                    u32 k = al;
                    if (k == 0 || child[k - 1] != '/') child[k++] = '/';
                    for (u32 i = 0; i <= nl; i++) child[k + i] = name[i];
                    if (ft == 7) relink(AT_FDCWD, child);
                    else relink_tree(child, depth + 1);
                    free(child);
                }
            }
            free(name);
        }
        if (in == 0) {  // one entry does not fit the buffer: a bigger one
            free(buf);
            cap *= 2;
            buf = (u8 *)malloc(cap);
        }
    }
    if (buf) free(buf);
    w_fd_close(dfd);
}

EXPORT("__syscall_linkat") i32 sc_linkat(i32 olddirfd, const char *oldpath, i32 newdirfd, const char *newpath, i32 flags) {
    char d1[2], d2[2];
    const char *p1, *p2;
    char *real = 0;
    if (flags & ~0x400) return -FE_INVAL;
    if (flags & 0x400) {  // AT_SYMLINK_FOLLOW: wasmtime refuses it, so the link is followed here and the file linked
        char *abs = absdup(olddirfd, oldpath);
        if (!abs) return -FE_BADF;
        i32 pe = phys(abs, abs, 1, &real);
        free(abs);
        if (pe) return -pe;
        oldpath = real;
        olddirfd = AT_FDCWD;
    }
    i32 n1, n2, f1 = resolve(olddirfd, oldpath, &p1, &n1, d1), f2 = resolve(newdirfd, newpath, &p2, &n2, d2);
    i32 e = dir_denies(f2, p2, n2, 1);
    if (!e) e = w_link(f1, 0, p1, n1, f2, p2, n2);
    if (real) free(real);
    return e ? -e : 0;
}

// the process runs as root of a single-user world (as Pyodide's JavaScript glue answers)
EXPORT("__syscall_getuid32_js") i32 sc_getuid(void) { return 0; }
EXPORT("__syscall_geteuid32") i32 sc_geteuid(void) { return 0; }
EXPORT("__syscall_getgid32") i32 sc_getgid(void) { return 0; }
EXPORT("__syscall_getegid32") i32 sc_getegid(void) { return 0; }
// the umask is kept here (WASI has none): the previous mask is returned, creation calls apply it to the recorded mode
EXPORT("__syscall_umask_js") i32 sc_umask(i32 mask) {
    MetaT *t = mt();
    i32 old = (i32)t->umask;
    t->umask = (u32)mask & 0777;
    return old;
}

// exit(): the process ends, with the code (Emscripten's JavaScript glue throws; here WASI says it)
EXPORT("exit") void sc_exit(i32 code) { w_proc_exit(code); }

// utimensat: the times are WASI's (path_filestat_set_times, fd_filestat_set_times). UTIME_NOW and UTIME_OMIT are
// the special nanoseconds; a null path (futimens) or an empty one is the descriptor itself, as Pyodide's allowEmpty.
EXPORT("__syscall_utimensat") i32 sc_utimensat(i32 dirfd, const char *path, const u8 *times, i32 flags) {
    u64 tv[2] = {0, 0};
    i32 ff = 0;
    if (!times) {
        ff = 2 | 8;
    } else {
        for (i32 k = 0; k < 2; k++) {
            i64 sec = *(const i64 *)(times + 16 * k);
            i32 ns = *(const i32 *)(times + 16 * k + 8);
            if (ns == 0x3fffffff) {  // UTIME_NOW
                ff |= 2 << (2 * k);
            } else if (ns != 0x3ffffffe) {  // not UTIME_OMIT
                if (ns < 0 || ns >= 1000000000 || sec < 0 || sec > 18446744072ll) return -FE_INVAL;
                tv[k] = (u64)sec * 1000000000ull + (u64)ns;
                ff |= 1 << (2 * k);
            }
        }
    }
    if (path && path[0]) {
        char dot[2];
        const char *p;
        i32 n, fd = resolve(dirfd, path, &p, &n, dot);
        i32 e = w_path_set_times(fd, (flags & 0x100) ? 0 : 1, p, n, tv[0], tv[1], ff);  // AT_SYMLINK_NOFOLLOW
        return e ? -e : 0;
    }
    i32 e;
    if (dirfd == AT_FDCWD) {
        char dot[2];
        dot[0] = '.', dot[1] = 0;
        const char *p;
        i32 n, fd = resolve(AT_FDCWD, dot, &p, &n, dot);
        e = w_path_set_times(fd, 1, p, n, tv[0], tv[1], ff);
    } else {
        e = w_fd_set_times(dirfd, tv[0], tv[1], ff);
    }
    return e ? -e : 0;
}

// chmod: the permission bits (and setuid, setgid, sticky) of the record; the file must exist
static i32 set_mode(const u64 *fs, i32 mode) {
    Meta *r = meta_for((const u8 *)fs);
    if (!r) return -ENOMEM;
    meta_setmode(mt(), r, (u32)mode & 07777);
    return 0;
}
EXPORT("__syscall_chmod") i32 sc_chmod(const char *path, i32 mode) {
    u64 fs[8];
    i32 e = fx_lookup(AT_FDCWD, path, 1, fs);
    return e ? -e : set_mode(fs, mode);
}
EXPORT("__syscall_fchmod") i32 sc_fchmod(i32 fd, i32 mode) {
    u64 fs[8];
    i32 e = w_fd_filestat_get(fd, fs);
    if (e) return -e;
    return is_sock(fd) ? 0 : set_mode(fs, mode);
}
EXPORT("__syscall_fchmodat2") i32 sc_fchmodat2(i32 dirfd, const char *path, i32 mode, i32 flags) {
    u64 fs[8];
    i32 e = fx_lookup(dirfd, path, !(flags & 0x100), fs);  // AT_SYMLINK_NOFOLLOW: the link itself, as Pyodide
    return e ? -e : set_mode(fs, mode);
}

#endif
