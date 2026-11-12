// The adapter's malloc'd state block, the preopens, and their wasm globals. Included only by adapter.c.
#ifndef ADAPTER_STATE_H
#define ADAPTER_STATE_H

#include "common.h"

// per open directory: the snapshot of its listing (kept in its Obj, vfd.h). Pyodide's getdents reads the names once and serves
// them by the position; so does this: `buf` holds the WASI dirent records of the whole directory ({d_next u64, d_ino u64,
// d_namlen u32, d_type u8, name}, `len` bytes), read at the first getdents64, `off` is the directory's position as lseek and
// getdents64 see it (entry index * DIR_STEP, Emscripten's struct size), (cpos, cidx) the byte position of entry number cidx,
// so that reading in order does not walk the records again.
#define DIR_STEP 280
typedef struct {
    u8 *buf;
    u32 len, cpos, cidx;
    u64 off;
    i32 loaded;
} Snap;
static void snap_free(Snap *s) {
    if (s->buf) free(s->buf);
    free(s);
}

static i32 slen(const char *p) {
    i32 n = 0;
    while (p[n]) n++;
    return n;
}

// The preopens, read once (fd_prestat_get / fd_prestat_dir_name, as wasi-libc does): an absolute path
// goes to the preopen with the longest matching prefix, the rest of the path relative to it. Their numbers are WASI's and
// internal: no guest number maps to one (vfd.h), so a guest call can never name a preopen.
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
