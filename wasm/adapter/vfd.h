// Virtual descriptors: dup, dup2, F_DUPFD, pipes and the objects that sockets live in. Included only by adapter.c.
#ifndef ADAPTER_VFD_H
#define ADAPTER_VFD_H

#include "common.h"
#include "state.h"
#include "metadata.h"

// A guest descriptor number is always a real WASI descriptor (so the numbers never clash with the ones the adapter opens
// itself; WASI's allocator gives neither the lowest free number nor the last freed one: after close(0) an open gives 4
// where a kernel gives 0, the known gap that the renumbering of BACKLOG W5 closes). What a number stands for is an OBJECT, shared by the numbers that dup()
// made of it: a file or directory (K_FILE: the WASI descriptor that really holds it, `w`; the file offset is its own,
// so it is shared), a socket (K_SOCK: the host's handle in `w`), the two ends of a pipe (K_PIPER, K_PIPEW). A number
// without an entry is a plain WASI descriptor (opened by openat, or a standard stream) that nobody has duplicated.
// The numbers of an object that are not the holder of its WASI descriptor are placeholders: a directory opened only to
// have the number. When the holder's number is closed and others remain, the real descriptor moves to one of them
// (fd_renumber), so that a number is free in WASI exactly when it is free for the guest.
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
    Pipe *pipe;
} Obj;
typedef struct {
    Obj *o[MAXFD];
    u8 cloexec[MAXFD];  // FD_CLOEXEC, per number (every descriptor, also the ones with no object)
    u8 stdgone;         // bit n: the number n (0..2) was closed once, so it is no standard stream any more
    u32 npipe;
} Vt;
__asm__(".globaltype vt_state, i32\nvt_state:\n");
static Vt *vt(void) {
    Vt *r;
    __asm__ volatile("global.get vt_state\n\tlocal.set %0" : "=r"(r));
    if (!r) {
        r = (Vt *)calloc(1, sizeof(Vt));
        __asm__ volatile("local.get %0\n\tglobal.set vt_state" : : "r"(r));
    }
    return r;
}
static void fd_forget(i32 fd);
static void meta_closing(i32 fd);
static void fd_move_meta(i32 from, i32 to);
static void sock_close(i32 h);

static Obj *vobj(i32 fd) { return fd >= 0 && fd < MAXFD && vt() ? vt()->o[fd] : 0; }
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
// the WASI descriptor that holds the file behind a guest number (the number itself for a plain one, a socket, a pipe)
static i32 rfd(i32 fd) {
    Obj *o = vobj(fd);
    return o && o->kind == K_FILE ? o->w : fd;
}
// is the (WASI) descriptor a standard stream?
static i32 fd_std(i32 w) {  // by the object (a number below 3 that was closed and opened again is a file)
    Obj *o = vobj(w);
    if (o) return o->std;
    return w >= 0 && w <= 2 && !(vt() && (vt()->stdgone >> w & 1));
}
// A standard stream or a directory takes F_SETFL/FIONBIO as Pyodide does (and WASI refuses: EBADF), keeping the flag in the
// number's object (made here for a plain descriptor), so that F_GETFL and the duplicates agree. 0 or -errno.
static i32 nb_keeps(i32 fd) {
    u8 st[24] __attribute__((aligned(8)));
    return !is_virt(fd) && (fd_std(rfd(fd)) || (!w_fd_fdstat_get(rfd(fd), st) && st[0] == 3));
}
static i32 nb_set(i32 fd, i32 on) {
    Vt *T = vt();
    if (!T) return -ENOMEM;
    if (fd < 0 || fd >= MAXFD) return 0;  // a number the table has no slot for (WASI gave it above MAXFD): accepted, not kept
    if (!T->o[fd]) {
        Obj *o = (Obj *)calloc(1, sizeof(Obj));
        if (!o) return -ENOMEM;
        o->kind = K_FILE, o->ref = 1, o->w = fd, o->std = (u8)fd_std(fd);
        T->o[fd] = o;
    }
    T->o[fd]->nb = (u8)(on != 0);
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

// a placeholder descriptor: a directory opened, so the number is a real WASI one. WASI's number, or -errno
static i32 ph_open(void) {
    u64 all = (1ull << 30) - 1, writes = (1ull << 6) | (1ull << 0) | (1ull << 8) | (1ull << 22);
    i32 fd = -1;
    char dot[2];  // "." built on the stack: a string literal would be a data section
    dot[0] = '.', dot[1] = 0;
    i32 e = w_path_open(PREOPEN, 1, dot, 1, 2 /* O_DIRECTORY */, all & ~writes, 0, 0, &fd);
    if (e || fd < 0) return -33;  // EMFILE
    return fd;
}
// WASI may hand out a number of MAXFD or more (after many files were opened and closed): those are held (up to HOLD, once
// per allocation) while more are opened, until a number below MAXFD comes; then the held are closed again.
#define HOLD 8192
// a placeholder for a new number, any one below MAXFD. -errno
static i32 sock_fd(void) {
    i32 r, held = 0, *hv = 0;
    for (;;) {
        r = ph_open();
        if (r < 0 || r < MAXFD) break;
        if (!hv) hv = (i32 *)calloc(HOLD, 4);
        if (!hv || held == HOLD) {
            w_fd_close(r);
            r = -33;
            break;
        }
        hv[held++] = r;
    }
    while (held > 0) w_fd_close(hv[--held]);
    free(hv);
    return r;
}
// the lowest free number from `min` on (exactly `min` if `exact`: a dup2 target, free by now), as a placeholder. WASI
// hands out neither the lowest number nor the last freed (see the top): so placeholders are opened until the wanted number
// comes, and the others closed again, the highest first (the lowest is then the next to be given out). The numbers of
// MAXFD and above are held in one list for the whole allocation (opening them again for every placeholder made a dup
// after many opens and closes take seconds).
static i32 fd_alloc(i32 min, i32 exact) {
    u8 st[24] __attribute__((aligned(8)));
    i32 k = min, fd, nhi = 0, *hi = 0;
    while (k < MAXFD && !w_fd_fdstat_get(k, st)) k++;
    if (k >= MAXFD || (exact && k != min)) return exact ? -EBADF : -33;  // EMFILE
    u8 *held = 0;
    for (;;) {
        fd = ph_open();
        if (fd < 0 || fd == k) break;
        if (fd < MAXFD) {
            if (!held) held = (u8 *)calloc(MAXFD, 1);
            if (!held) {
                w_fd_close(fd);
                fd = -ENOMEM;
                break;
            }
            held[fd] = 1;
        } else {
            if (!hi) hi = (i32 *)calloc(HOLD, 4);
            if (!hi || nhi == HOLD) {
                w_fd_close(fd);
                fd = -33;
                break;
            }
            hi[nhi++] = fd;
        }
    }
    while (nhi > 0) w_fd_close(hi[--nhi]);
    free(hi);
    if (held) {
        for (i32 j = MAXFD - 1; j >= 0; j--)
            if (held[j]) w_fd_close(j);
        free(held);
    }
    return fd;
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
static i32 fd_release(i32 fd) {  // close(): the number goes; the object when it was the last one
    Obj *o = vobj(fd);
    if (fd >= 0 && fd <= 2 && vt()) vt()->stdgone |= (u8)(1 << fd);
    if (!o) {  // a plain descriptor
        if (fd >= 0 && fd < MAXFD && vt()) vt()->cloexec[fd] = 0;
        if (mt()->norphan) meta_closing(fd);
        fd_forget(fd);
        return w_fd_close(fd);
    }
    Vt *T = vt();
    T->o[fd] = 0, T->cloexec[fd] = 0;
    o->ref--;
    if (o->kind == K_FILE && o->w == fd) {  // the holder of the real descriptor
        if (o->ref > 0) {                   // it moves to another number of the object
            i32 m = 0;
            while (T->o[m] != o) m++;
            i32 e = w_fd_renumber(fd, m);
            if (e) {  // can not happen (m is open); keep the object whole
                T->o[fd] = o, o->ref++;
                return e;
            }
            fd_move_meta(fd, m);
            o->w = m;
            return 0;
        }
        free(o);
        if (mt()->norphan) meta_closing(fd);
        fd_forget(fd);
        return w_fd_close(fd);
    }
    if (o->ref == 0) {
        if (o->kind == K_SOCK) {
            sock_close(o->w);
        } else if (o->kind != K_FILE) {
            Pipe *p = o->pipe;
            if (o->kind == K_PIPER) p->ropen = 0, pipe_drop(p);
            else p->wopen = 0;
            if (!p->ropen && !p->wopen) free(p);
        }
        free(o);
    }
    return w_fd_close(fd);
}

// ---- dup: a new number (the lowest free from `min`, or exactly `min`, which is closed first) for the object of `old`
static i32 fd_dup(i32 old, i32 min, i32 exact, i32 cloexec) {
    Vt *T = vt();
    u8 st[24] __attribute__((aligned(8)));
    if (!T || old < 0 || old >= MAXFD || (!T->o[old] && w_fd_fdstat_get(old, st))) return -EBADF;
    if (exact && (T->o[min] || !w_fd_fdstat_get(min, st))) fd_release(min);
    Obj *o = T->o[old], *fresh = 0;
    if (!o) {  // from now on the plain descriptor has an object
        fresh = o = (Obj *)calloc(1, sizeof(Obj));
        if (!o) return -ENOMEM;
        o->kind = K_FILE, o->ref = 1, o->w = old, o->std = (u8)fd_std(old);
    }
    i32 p = fd_alloc(min, exact);
    if (p < 0) {
        free(fresh);
        return p;
    }
    if (fresh) T->o[old] = fresh;
    o->ref++;
    T->o[p] = o, T->cloexec[p] = (u8)cloexec;
    return p;
}
EXPORT("__syscall_dup") i32 sc_dup(i32 fd) { return is_pre(fd) ? -EBADF : fd_dup(fd, 0, 0, 0); }
EXPORT("__syscall_dup3") i32 sc_dup3(i32 oldfd, i32 newfd, i32 flags) {
    if (oldfd == newfd || (flags & ~02000000)) return -FE_INVAL;  // O_CLOEXEC only
    if (newfd < 0 || newfd >= MAXFD || is_pre(oldfd) || is_pre(newfd)) return -EBADF;
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
    i32 a = p && r && w && T ? fd_alloc(0, 0) : -ENOMEM, b = a < 0 ? a : fd_alloc(0, 0);
    if (a < 0 || b < 0) {
        if (a >= 0) w_fd_close(a);
        free(p), free(r), free(w);
        return a < 0 ? a : b;
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
