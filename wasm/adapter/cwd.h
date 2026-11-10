// The current directory and the path buffers. Included only by adapter.c.
#ifndef ADAPTER_CWD_H
#define ADAPTER_CWD_H

#include "common.h"

// ---- the current directory (chdir): kept as an absolute path in one malloc'd block, its address in a wasm global.
// A relative path against AT_FDCWD is joined to it into one of two buffers (rename and link resolve two at once).
// The cwd, the two path buffers and the path records of the open files are malloc'd and grow with the path: no length
// limit of their own (the host's operating system has its own).
typedef struct {
    char *cwd;
    char *b[2];
    u32 cap[2];
    i32 flip;
} Cwd;
__asm__(".globaltype cwd_state, i32\ncwd_state:\n");
static Cwd *cwdst(void) {
    Cwd *r;
    __asm__ volatile("global.get cwd_state\n\tlocal.set %0" : "=r"(r));
    if (!r) {
        r = (Cwd *)calloc(1, sizeof(Cwd));
        r->cwd = (char *)malloc(2);
        r->cwd[0] = '/';
        r->cwd[1] = 0;
        __asm__ volatile("local.get %0\n\tglobal.set cwd_state" : : "r"(r));
    }
    return r;
}
static char *slot(i32 k, u32 need) {  // a path buffer of at least `need` bytes, or 0 (out of memory)
    Cwd *C = cwdst();
    if (C->cap[k] < need) {
        char *nb = (char *)malloc(need);
        if (!nb) return 0;
        if (C->b[k]) free(C->b[k]);
        C->b[k] = nb;
        C->cap[k] = need;
    }
    return C->b[k];
}
static char *dupn(const char *s, u32 n) {  // a malloc'd copy of n bytes and a NUL, or 0
    char *r = (char *)malloc(n + 1);
    if (!r) return 0;
    for (u32 i = 0; i < n; i++) r[i] = s[i];
    r[n] = 0;
    return r;
}

#endif
