// Virtual descriptors: dup, dup2, F_DUPFD, pipes and the objects that sockets live in. Included only by adapter.c.
#ifndef ADAPTER_VFD_H
#define ADAPTER_VFD_H

#include "common.h"
#include "state.h"
#include "metadata.h"

// A guest descriptor number is an index into the table Vt, and nothing else: it has no relation to the number of any WASI
// descriptor (WASI's allocator hands out neither the lowest free number nor the last freed one; the guest's numbers are a
// kernel's: the first open is 3, every new number is the LOWEST free one, dup2 may name any number below MAXFD). What a
// number stands for is an OBJECT (an open file description), shared by the numbers that dup() made of it, with a
// reference count: a file or directory (K_FILE: the WASI descriptor that really holds it, `w`, which never changes while
// the object lives; the file offset is its own, so it is shared; also its path, open flags and directory snapshot), a
// socket (K_SOCK: the host's handle in `w`), the two ends of a pipe (K_PIPER, K_PIPEW). A number without an object is
// free (EBADF). The standard streams are the objects of the numbers 0..2 from the table's creation (K_FILE, w = 0..2).
// WASI descriptors that the adapter opens for itself (the preopens, a path walk, mmap's write-back) are no guest numbers
// and are never in the table: a guest number can not name them.
// Every call that takes a guest number goes through vobj(), rfd(), or a function below that does; a guest number is never
// passed on to a w_fd_* call as it is (rfd() gives -1 for a number that is not a file, which WASI answers with EBADF).
// The pipes are Pyodide's PIPEFS: a list of 8192-byte buckets, no capacity limit and no EPIPE (a write always succeeds
// in full), a read of an empty pipe is EAGAIN. The one deliberate difference (the owner's decision): an empty pipe
// whose write end is closed reads 0 (end of file), where PIPEFS says EAGAIN.
#define K_FILE 1
#define K_SOCK 2
#define K_PIPER 3
#define K_PIPEW 4
#define BKT 8192
#define FE_AGAIN 6
#define FE_FAULT 21
#define FE_MFILE 33
typedef struct Bkt {
    struct Bkt *next;
    u32 r, w;
    u8 d[BKT];
} Bkt;
typedef struct {
    Bkt *head, *tail;
    u32 size, ino;  // the bytes buffered; the number the ends' inodes are made from
    u64 ts;         // the creation time: the times of fstat
    u8 ropen, wopen;
} Pipe;
typedef struct {
    i32 kind, ref, w;
    i32 fl;  // a pipe end's status flags (F_SETFL)
    u8 nb;   // O_NONBLOCK of a socket, a standard stream or a directory (WASI can not hold it for the last two)
    u8 std;  // a standard stream (fstat says character device)
    u8 isdir;  // a file object: 0 not asked yet, 1 a directory, 2 no directory (the type of an open file never changes)
    Pipe *pipe;
    // K_FILE opened by openat: the absolute guest path and the open flags (what mmap's write-back opens again; the path is
    // 0 when it could not be kept), and the snapshot of a directory's listing, read at its first getdents64 (lseek(fd, 0,
    // SEEK_SET) drops it, the last unref frees it)
    char *path;
    i32 oflags;
    Snap *snap;
} Obj;
typedef struct {
    Obj *o[MAXFD];
    u8 cloexec[MAXFD];  // FD_CLOEXEC, per number (not per object: a new number from dup() starts without it)
    u32 npipe;
} Vt;
__asm__(".globaltype vt_state, i32\nvt_state:\n");
static Vt *vt(void) {
    Vt *r;
    __asm__ volatile("global.get vt_state\n\tlocal.set %0" : "=r"(r));
    if (!r) {
        r = (Vt *)calloc(1, sizeof(Vt));
        if (r) {
            for (i32 k = 0; k < 3; k++) {  // the standard streams: the numbers 0..2 are their WASI descriptors
                Obj *o = (Obj *)calloc(1, sizeof(Obj));
                if (!o) continue;
                o->kind = K_FILE, o->ref = 1, o->w = k, o->std = 1;
                r->o[k] = o;
            }
        }
        __asm__ volatile("local.get %0\n\tglobal.set vt_state" : : "r"(r));
    }
    return r;
}
static void meta_closing(const Obj *o);
static void sock_close(i32 h);

// the object of a number; 0 for a free number, a negative one, or one past the table (a guest-controlled value, up to 2^31)
static Obj *vobj(i32 fd) {
    Vt *T = fd >= 0 && fd < MAXFD ? vt() : 0;
    return T ? T->o[fd] : 0;
}
static i32 is_sock(i32 fd) {
    Obj *o = vobj(fd);
    return o && o->kind == K_SOCK;
}
static i32 is_pipe(i32 fd) {
    Obj *o = vobj(fd);
    return o && (o->kind == K_PIPER || o->kind == K_PIPEW);
}
static i32 is_virt(i32 fd) {  // not a file: a socket or a pipe end
    Obj *o = vobj(fd);
    return o && o->kind != K_FILE;
}
static i32 hof(i32 fd) { return vobj(fd)->w; }
static i32 sock_nb(i32 fd) { return vobj(fd)->nb; }
static void sock_set_nb(i32 fd, i32 on) { vobj(fd)->nb = (u8)(on != 0); }
// the WASI descriptor that holds the file behind a guest number: -1 for a number that is no file (free, a socket, a pipe;
// WASI answers EBADF for it); AT_FDCWD stays AT_FDCWD (the *at calls' "no directory")
static i32 rfd(i32 fd) {
    Obj *o = vobj(fd);
    return o && o->kind == K_FILE ? o->w : fd == AT_FDCWD ? fd : -1;
}
// is the number a standard stream? By the object: a number below 3 that was closed and opened again is a file, and a
// duplicate of a standard stream is one
static i32 fd_std(i32 fd) {
    Obj *o = vobj(fd);
    return o && o->std;
}
// A standard stream or a directory takes F_SETFL/FIONBIO as Pyodide does (and WASI refuses: EBADF), keeping the flag in the
// number's object, so that F_GETFL and the duplicates agree.
static i32 nb_keeps(i32 fd) {
    u8 st[24] __attribute__((aligned(8)));
    Obj *o = vobj(fd);
    return o && o->kind == K_FILE && (o->std || (!w_fd_fdstat_get(o->w, st) && st[0] == 3));
}
// ENOTDIR for a relative path under a dirfd that is an open object but no directory (a pipe, a socket, a file, a standard
// stream; Linux), else 0: a free number stays EBADF (WASI), and an absolute path has no use for the directory
static i32 notdir(i32 dirfd, const char *path) {
    u8 st[24] __attribute__((aligned(8)));
    Obj *o = path[0] == '/' ? 0 : vobj(dirfd);
    if (!o) return 0;
    if (o->kind == K_FILE && !o->std) {
        if (!o->isdir) o->isdir = !w_fd_fdstat_get(o->w, st) && st[0] == 3 ? 1 : 2;  // one host call per object
        if (o->isdir == 1) return 0;
    }
    return path[0] ? FE_NOTDIR : FE_NOENT;  // an empty path is ENOENT first (Linux)
}
static i32 nb_set(i32 fd, i32 on) {  // 0 or -errno
    Obj *o = vobj(fd);
    if (!o) return -EBADF;
    o->nb = (u8)(on != 0);
    return 0;
}
static i32 cloexec_get(i32 fd) {  // -ENOMEM when the table can not be made
    Vt *T = vt();
    return !T ? -ENOMEM : fd >= 0 && fd < MAXFD ? T->cloexec[fd] : 0;
}
static i32 cloexec_set(i32 fd, i32 on) {
    Vt *T = vt();
    if (!T) return -ENOMEM;
    if (fd >= 0 && fd < MAXFD) T->cloexec[fd] = (u8)(on != 0);
    return 0;
}

// the lowest free number from `min` on, or -EMFILE (the table is full above `min`); the caller puts an object there at once
static i32 fd_new(i32 min) {
    Vt *T = vt();
    if (!T) return -ENOMEM;
    for (i32 k = min < 0 ? 0 : min; k < MAXFD; k++)
        if (!T->o[k]) return k;
    return -FE_MFILE;
}

// ---- close
static void pipe_drop(Pipe *p) {  // the buffered bytes are of no use to a pipe nobody reads
    while (p->head) {
        Bkt *b = p->head;
        p->head = b->next;
        free(b);
    }
    p->tail = 0, p->size = 0;
}
// One reference of an object goes (a number was closed, or mmap let go of its own); the last one ends the object: the file's
// WASI descriptor is closed (-> its errno), the socket, the pipe end. Nothing may point at the object then.
static i32 obj_unref(Obj *o) {
    if (--o->ref > 0) return 0;
    i32 e = 0;
    if (o->kind == K_FILE) {
        if (mt()->norphan) meta_closing(o);
        if (o->snap) snap_free(o->snap);
        free(o->path);
        e = w_fd_close(o->w);
    } else if (o->kind == K_SOCK) {
        sock_close(o->w);
    } else {
        Pipe *p = o->pipe;
        if (o->kind == K_PIPER) p->ropen = 0, pipe_drop(p);
        else p->wopen = 0;
        if (!p->ropen && !p->wopen) free(p);
    }
    free(o);
    return e;
}
static i32 fd_release(i32 fd) {  // close(): the number goes, the object when it was the last one. A WASI errno
    Obj *o = vobj(fd);
    if (!o) return FE_BADF;
    vt()->o[fd] = 0, vt()->cloexec[fd] = 0;
    return obj_unref(o);
}

// ---- dup: a new number (the lowest free from `min`, or exactly `min`, which is closed first) for the object of `old`.
// `min` is below MAXFD (the callers check). The new number has FD_CLOEXEC only if asked.
static i32 fd_dup(i32 old, i32 min, i32 exact, i32 cloexec) {
    Obj *o = vobj(old);
    if (!o) return -EBADF;
    Vt *T = vt();  // (not 0: vobj found an object)
    i32 p = min;
    if (exact) {
        if (T->o[p]) fd_release(p);  // (`old` keeps the object alive, also when both numbers are of it)
    } else if ((p = fd_new(min)) < 0) {
        return p;
    }
    o->ref++;
    T->o[p] = o, T->cloexec[p] = (u8)cloexec;
    return p;
}
EXPORT("__syscall_dup") i32 sc_dup(i32 fd) { return fd_dup(fd, 0, 0, 0); }
EXPORT("__syscall_dup3") i32 sc_dup3(i32 oldfd, i32 newfd, i32 flags) {
    if (oldfd == newfd || (flags & ~02000000)) return -FE_INVAL;  // O_CLOEXEC only
    if (newfd < 0 || newfd >= MAXFD) return -EBADF;
    return fd_dup(oldfd, newfd, 1, (flags & 02000000) != 0);
}

// ---- pipes
static i32 pipe_read(Obj *o, const u32 *iov, i32 n, i32 *nread) {
    if (o->kind != K_PIPER) return FE_BADF;  // the write end
    Pipe *p = o->pipe;
    i32 tot = 0;
    for (i32 k = 0; k < n; k++) {
        u8 *dst = (u8 *)iov[2 * k];
        u32 len = iov[2 * k + 1];
        if (!len) continue;
        if (!p->size) {
            if (tot || !p->wopen) break;  // (PIPEFS: always EAGAIN)
            return FE_AGAIN;
        }
        while (len && p->size) {
            Bkt *b = p->head;
            u32 c = b->w - b->r;
            if (c > len) c = len;
            for (u32 i = 0; i < c; i++) dst[i] = b->d[b->r + i];
            b->r += c, p->size -= c, len -= c, dst += c, tot += (i32)c;
            if (b->r == b->w) {
                p->head = b->next;
                if (!p->head) p->tail = 0;
                free(b);
            }
        }
        if (len) break;
    }
    *nread = tot;
    return 0;
}
static i32 pipe_write(Obj *o, const u32 *iov, i32 n, i32 *nw) {
    if (o->kind != K_PIPEW) return FE_BADF;  // the read end
    Pipe *p = o->pipe;
    i32 tot = 0;
    for (i32 k = 0; k < n; k++) {
        const u8 *src = (const u8 *)iov[2 * k];
        u32 len = iov[2 * k + 1];
        while (len) {
            if (!p->ropen) {  // nobody can read it: dropped (PIPEFS keeps it; no error either way)
                tot += (i32)len;
                break;
            }
            Bkt *b = p->tail;
            if (!b || b->w == BKT) {
                b = (Bkt *)malloc(sizeof(Bkt));
                if (!b) {
                    if (tot) goto done;
                    return ENOMEM;
                }
                b->next = 0, b->r = b->w = 0;
                if (p->tail) p->tail->next = b;
                else p->head = b;
                p->tail = b;
            }
            u32 c = BKT - b->w;
            if (c > len) c = len;
            for (u32 i = 0; i < c; i++) b->d[b->w + i] = src[i];
            b->w += c, p->size += c, src += c, len -= c, tot += (i32)c;
        }
    }
done:
    *nw = tot;
    return 0;
}
// PIPEFS's poll mask; the caller keeps what it asked for, and POLLERR, POLLHUP, POLLNVAL
static i32 pipe_mask(Obj *o) {
    Pipe *p = o->pipe;
    if (o->kind == K_PIPEW) return 256 | 4 | (p->ropen ? 0 : 8);
    return (p->size ? 64 | 1 : 0) | (p->wopen ? 0 : 16 | 1);
}

EXPORT("__syscall_pipe2") i32 sc_pipe2(i32 *out, i32 flags) {
    if (!out) return -FE_FAULT;
    if (flags & ~(02000000 | 04000)) return -FE_OPNOTSUPP;  // O_CLOEXEC, O_NONBLOCK
    Vt *T = vt();
    Pipe *p = (Pipe *)calloc(1, sizeof(Pipe));
    Obj *r = (Obj *)calloc(1, sizeof(Obj)), *w = (Obj *)calloc(1, sizeof(Obj));
    i32 a = p && r && w ? fd_new(0) : -ENOMEM, b = a;
    if (a >= 0) {
        T->o[a] = r;  // taken for a moment, so that the write end's number is the next free one
        b = fd_new(0);
        T->o[a] = 0;
    }
    if (b < 0) {  // (nothing is in the table: no number is left half made)
        free(p), free(r), free(w);
        return b;
    }
    p->ropen = p->wopen = 1, p->ino = 2 * ++T->npipe;  // the read end's inode; the write end's is the next
    w_clock_time_get(0, 1000, &p->ts);
    r->kind = K_PIPER, w->kind = K_PIPEW;
    r->ref = w->ref = 1, r->pipe = w->pipe = p, r->fl = w->fl = flags & 04000;
    T->o[a] = r, T->o[b] = w;
    T->cloexec[a] = T->cloexec[b] = (flags & 02000000) != 0;
    out[0] = a, out[1] = b;
    return 0;
}

#endif
