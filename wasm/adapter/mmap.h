// Mmap of a file: _mmap_js / _munmap_js / _msync_js. Included only by adapter.c.
#ifndef ADAPTER_MMAP_H
#define ADAPTER_MMAP_H

#include "common.h"
#include "loader.h"
#include "openfiles.h"

// ================================================================== mmap of a file: _mmap_js / _munmap_js / _msync_js
// What the glue does for a file (NODEFS): the bytes are copied into the heap, a block of whole 64 KiB pages from the
// main module's memalign (zeroed past the end of the file), and a shared writable mapping is written back with
// pwrite on msync and munmap. A private mapping never writes back. The copy is not live: a write(2) to the file
// after the mmap is not seen through it (and the other way round, until msync). Anonymous mappings are the libc's.
// The write-back is the whole mapping, which extends a truncated file (as MEMFS does).
// A shared writable mapping keeps a reference to the file's object (as POSIX lets the mapping outlive the descriptor it was
// made from; the glue looks the descriptor up again at msync and munmap and fails with EBADF when it was closed: a deliberate
// difference, decided by the owner). The reference is no number: the guest can close and reuse its numbers freely.
WASI("fd_pread") i32 w_fd_pread(i32 fd, const void *iovs, i32 n, u64 offset, i32 *nread);
WASI("fd_pwrite") i32 w_fd_pwrite(i32 fd, const void *iovs, i32 n, u64 offset, i32 *nwritten);
void *emscripten_builtin_memalign(u32 align, u32 size);
#define PROT_WRITE 2
#define MAP_PRIVATE 2
#define MM_CHUNK (8u << 20)

typedef struct {
    u32 addr;
    Obj *o;  // the file's object, one reference of the mapping's own (obj_unref at munmap), for a shared writable mapping
} Map;
__asm__(".globaltype map_state, i32\nmap_state:\n");
static Vec *maps(void) {
    Vec *r;
    __asm__ volatile("global.get map_state\n\tlocal.set %0" : "=r"(r));
    if (!r) {
        r = (Vec *)calloc(1, sizeof(Vec));
        __asm__ volatile("local.get %0\n\tglobal.set map_state" : : "r"(r));
    }
    return r;
}
static Map *map_find(u32 addr, i32 forget) {
    Vec *M = maps();
    for (i32 k = 0; k < M->n; k++) {
        Map *m = (Map *)M->v[k];
        if (m->addr != addr) continue;
        if (forget) M->v[k] = M->v[--M->n];
        return m;
    }
    return 0;
}

// the descriptor's file type check of the glue: EBADF, then ENODEV for anything but a regular file
static i32 mm_file(const Obj *o, u64 *rights) {
    u8 st[24] __attribute__((aligned(8)));
    if (!o) return -EBADF;
    if (o->kind != K_FILE) return -43;  // ENODEV
    i32 e = w_fd_fdstat_get(o->w, st);
    if (e) return -e;
    if (rights) *rights = *(u64 *)(st + 8);
    return st[0] == 4 ? 0 : -43;  // ENODEV
}

EXPORT("_mmap_js") i32 mmap_js(u32 len, i32 prot, i32 flags, i32 fd, i64 offset, i32 *allocated, u32 *addr) {
    u8 st[24] __attribute__((aligned(8)));
    Obj *ob = vobj(fd);
    if (!ob) return -EBADF;
    if (ob->kind != K_FILE) return -43;  // ENODEV: a socket or a pipe
    i32 e = w_fd_fdstat_get(ob->w, st);
    if (e) return -e;  // EBADF
    u64 rights = *(u64 *)(st + 8);
    i32 rd = (rights & (1ull << 1)) != 0, wr = (rights & (1ull << 6)) != 0;
    if ((prot & PROT_WRITE) && !(flags & MAP_PRIVATE) && !(rd && wr)) return -2;  // EACCES: shared + writable needs O_RDWR
    if (wr && !rd) return -2;                                                       // EACCES: O_WRONLY
    if (st[0] != 4) return -43;                                                     // ENODEV: not a regular file
    if (!len || offset < 0) return -28;                                             // EINVAL
    u64 size = ((u64)len + 65535) & ~65535ull;
    if (size > 0x7fff0000ull) return -48;  // ENOMEM
    u8 *ptr = (u8 *)emscripten_builtin_memalign(65536, (u32)size);
    if (!ptr) return -48;
    u32 got = 0;
    while (got < len) {
        u32 iov[2];
        iov[0] = (u32)(ptr + got), iov[1] = len - got < MM_CHUNK ? len - got : MM_CHUNK;  // wasmtime refuses a big read
        i32 r = 0;
        e = w_fd_pread(rfd(fd), iov, 1, (u64)offset + got, &r);
        if (e) {
            free(ptr);
            return -e;
        }
        if (r == 0) break;  // past the end of the file
        got += (u32)r;
    }
    for (u64 i = got; i < size; i++) ptr[i] = 0;
    if ((prot & PROT_WRITE) && !(flags & MAP_PRIVATE)) {
        Map *m = (Map *)malloc(sizeof(Map));
        Vec *M = maps();
        if (m) m->addr = (u32)ptr, m->o = ob;
        if (!m || !M || !vec_push(M, m)) {
            free(m);
            free(ptr);
            return -48;  // ENOMEM
        }
        ob->ref++;
    }
    *allocated = 1, *addr = (u32)ptr;
    return 0;
}

// the bytes of a mapping back to the file: the whole length, as MEMFS's msync writes it (a truncated file grows again).
// A descriptor without write rights (a read-only shared mapping) is opened again for writing by its path.
static i32 mm_write_back(u32 addr, u32 len, const Obj *o, i64 offset, u64 rights) {
    i32 wfd = o->w, e = 0;
    if (!(rights & (1ull << 6)) && o->path) {
        wfd = open_at(AT_FDCWD, o->path, (o->oflags & ~(3 | 0100 | 0200 | 01000)) | 2, 0, 1);
        if (wfd < 0) return wfd;
    }
    for (u32 done = 0; done < len && !e;) {
        u32 iov[2];
        iov[0] = addr + done, iov[1] = len - done < MM_CHUNK ? len - done : MM_CHUNK;
        i32 w = 0;
        e = w_fd_pwrite(wfd, iov, 1, (u64)offset + done, &w);
        if (e) e = -e;
        else if (w == 0) e = -29;  // EIO
        else done += (u32)w;
    }
    if (wfd != o->w) w_fd_close(wfd);  // (the reopened one: ours, no guest number)
    return e;
}

EXPORT("_msync_js") i32 msync_js(u32 addr, u32 len, i32 prot, i32 flags, i32 fd, i64 offset) {
    (void)prot;  // the glue does not look at it either
    if (offset < 0) return -28;
    Map *m = map_find(addr, 0);
    const Obj *o = m ? m->o : vobj(fd);  // the mapping's own reference, else the caller's number
    u64 rights = 0;
    i32 e = mm_file(o, &rights);
    if (e) return e;
    if (flags & MAP_PRIVATE) return 0;  // the glue returns before it writes
    return mm_write_back(addr, len, o, offset, rights);
}

EXPORT("_munmap_js") i32 munmap_js(u32 addr, u32 len, i32 prot, i32 flags, i32 fd, i64 offset) {
    if (!(prot & PROT_WRITE) || (flags & MAP_PRIVATE)) return 0;
    i32 e = msync_js(addr, len, prot, flags, fd, offset);
    Map *m = map_find(addr, 1);
    if (m) {
        obj_unref(m->o);
        free(m);
    }
    return e;
}

#endif
