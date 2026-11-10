// The adapter's malloc'd state block, the preopens, and their wasm globals. Included only by adapter.c.
#ifndef ADAPTER_STATE_H
#define ADAPTER_STATE_H

#include "common.h"

// ---- state: one malloc'd block, its address in a wasm global (no data section)
__asm__(".globaltype adapter_state, i32\nadapter_state:\n");
static inline u64 *state_get(void) {
    u64 *r;
    __asm__ volatile("global.get adapter_state\n\tlocal.set %0" : "=r"(r));
    return r;
}
static inline void state_set(u64 *v) {
    __asm__ volatile("local.get %0\n\tglobal.set adapter_state" : : "r"(v));
}
// per descriptor: the next fd_readdir cookie (a table that grows with the descriptor numbers)
typedef struct {
    u32 cap;
    u64 *v;
} Ck;
static u64 *ckp(i32 fd) {  // 0 when out of memory
    Ck *c = (Ck *)state_get();
    if (!c) {
        c = (Ck *)calloc(1, sizeof(Ck));
        if (!c) return 0;
        state_set((u64 *)c);
    }
    if ((u32)fd >= c->cap) {
        u32 nc = c->cap ? c->cap : 256;
        while (nc <= (u32)fd) nc *= 2;
        u64 *nv = (u64 *)calloc(nc, 8);
        if (!nv) return 0;
        for (u32 i = 0; i < c->cap; i++) nv[i] = c->v[i];
        if (c->v) free(c->v);
        c->v = nv;
        c->cap = nc;
    }
    return &c->v[fd];
}

static i32 slen(const char *p) {
    i32 n = 0;
    while (p[n]) n++;
    return n;
}

// The preopens, read once (fd_prestat_get / fd_prestat_dir_name, as wasi-libc does): an absolute path
// goes to the preopen with the longest matching prefix, the rest of the path relative to it.
#define MAXPRE 16
typedef struct {
    i32 n;
    i32 fd[MAXPRE];
    i32 len[MAXPRE];
    char name[MAXPRE][64];
} Pre;
__asm__(".globaltype pre_state, i32\npre_state:\n");
static Pre *preopens(void) {
    Pre *r;
    __asm__ volatile("global.get pre_state\n\tlocal.set %0" : "=r"(r));
    if (!r) {
        r = (Pre *)malloc(sizeof(Pre));
        r->n = 0;
        for (i32 fd = 3; fd < 3 + 64 && r->n < MAXPRE; fd++) {
            u32 st[2];
            if (w_fd_prestat_get(fd, st)) break;
            if (st[0] != 0 || st[1] >= 63) continue;
            w_fd_prestat_dir_name(fd, r->name[r->n], (i32)st[1]);
            i32 l = (i32)st[1];
            while (l > 1 && r->name[r->n][l - 1] == '/') l--;  // "/dev/" -> "/dev"
            r->name[r->n][l] = 0;
            r->fd[r->n] = fd, r->len[r->n] = l;
            r->n++;
        }
        __asm__ volatile("local.get %0\n\tglobal.set pre_state" : : "r"(r));
    }
    return r;
}

#endif
