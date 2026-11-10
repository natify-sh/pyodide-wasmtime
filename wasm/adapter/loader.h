// The dynamic loader: _dlopen_js / _dlsym_js. Included only by adapter.c.
#ifndef ADAPTER_LOADER_H
#define ADAPTER_LOADER_H

#include "common.h"
#include "state.h"
#include "openfiles.h"

// ================================================================== the loader: _dlopen_js / _dlsym_js
// What Emscripten's JavaScript glue does in loadDynamicLibrary / loadWebAssemblyModule, in wasm; the host is asked
// only to instantiate, to look up an export by name, to set a GOT global, to call an export, to put a library into
// the global namespace or into the scope of one dlopen call, and to word the dlerror text (the adapter has no
// strings: it says which failure, the host has the text).
//
// Resolution as the glue has it. The GOT (GOT.mem / GOT.func imports) is one table by name for all libraries and
// the first definition wins: the main module, then the libraries in the order they were loaded (RTLD_LOCAL or
// not), then the module's own exports; a name found nowhere is an error unless the import is weak. The `env`
// functions (the host binds them) see the main module and the RTLD_GLOBAL libraries, then, when first called,
// the scope of the dlopen call (its NEEDED libraries) and the module's own exports. dlsym(handle) sees that
// library's own exports; dlsym(NULL/RTLD_DEFAULT) the main module and the RTLD_GLOBAL libraries. dlclose is the C
// library's: the glue only counts, it never unloads, and neither do we.

typedef struct {  // a growable vector of pointers (the allocator we are given has no realloc)
    i32 n, cap;
    void **v;
} Vec;

static i32 vec_push(Vec *a, void *x) {  // 0 when there is no memory for it
    if (a->n == a->cap) {
        i32 cap = a->cap ? a->cap * 2 : 16;
        void **nv = (void **)malloc((u32)cap * sizeof(void *));
        if (!nv) return 0;
        for (i32 i = 0; i < a->n; i++) nv[i] = a->v[i];
        free(a->v);
        a->v = nv, a->cap = cap;
    }
    a->v[a->n++] = x;
    return 1;
}

typedef struct {
    i32 id;  // the host's instance, -1 while it loads
    u32 base, memsize, tbase, tsize;
    char *name;  // the normalized path
    i32 global, ready;
    u32 gseq;  // the order in which libraries became RTLD_GLOBAL (the glue's mergeLibSymbols): the first one wins
} Lib;
typedef struct {
    i32 handle;
    Lib *lib;
} Hnd;
typedef struct {
    Vec libs;  // Lib *, in load order
    Vec hnds;  // Hnd *: dlopen handle -> library (the latest dlopen of a handle wins)
    u32 scopes;  // dlopen calls so far: the number of a call's scope
    u32 gcount;  // libraries made global so far
    u32 code;  // why the load in progress failed (an error code of loader.error) and its argument
    char *arg;
    i32 argn;
} Libs;

__asm__(".globaltype loader_state, i32\nloader_state:\n");
static Libs *libs(void) {
    Libs *r;
    __asm__ volatile("global.get loader_state\n\tlocal.set %0" : "=r"(r));
    if (!r) {
        r = (Libs *)calloc(1, sizeof(Libs));
        __asm__ volatile("local.get %0\n\tglobal.set loader_state" : : "r"(r));
    }
    return r;
}

// A reader that never leaves [i, end): every length that comes from a file goes through it.
typedef struct {
    const u8 *b;
    u32 i, end;
    i32 bad;
} Rd;
static u32 rd_leb(Rd *r) {  // an unsigned LEB128 of at most 5 bytes
    u32 v = 0, s = 0;
    for (;;) {
        if (r->i >= r->end || s >= 35) {
            r->bad = 1;
            return 0;
        }
        u8 c = r->b[r->i++];
        v |= (u32)(c & 0x7F) << s;
        s += 7;
        if (!(c & 0x80)) return v;
    }
}
static u8 rd_u8(Rd *r) {
    if (r->i >= r->end) {
        r->bad = 1;
        return 0;
    }
    return r->b[r->i++];
}
static const u8 *rd_name(Rd *r, u32 *n) {  // a length and that many bytes
    u32 l = rd_leb(r);
    if (r->bad || l > r->end - r->i) {
        r->bad = 1, *n = 0;
        return r->b;
    }
    const u8 *p = r->b + r->i;
    r->i += l, *n = l;
    return p;
}
static void rd_limits(Rd *r) {  // wasm32 limits: flags, min, [max]
    u32 f = rd_leb(r);
    rd_leb(r);
    if (f & 1) rd_leb(r);
}

static i32 eq(const u8 *a, i32 an, const char *b, i32 bn) {
    if (an != bn) return 0;
    for (i32 i = 0; i < an; i++)
        if (a[i] != (u8)b[i]) return 0;
    return 1;
}

static i32 is8(const u8 *p, i32 n, u64 v) {  // a name of 8 bytes equal to the little-endian constant v
    return n == 8 && (((u64)p[0]) | ((u64)p[1] << 8) | ((u64)p[2] << 16) | ((u64)p[3] << 24) | ((u64)p[4] << 32) |
                      ((u64)p[5] << 40) | ((u64)p[6] << 48) | ((u64)p[7] << 56)) == v;
}
#define N_DYLINK 0x302e6b6e696c7964ull    // "dylink.0"
#define N_GOTFUNC 0x636e75662e544f47ull   // "GOT.func"
static i32 is_gotmem(const u8 *p, i32 n) { return n == 7 && p[0] == 'G' && p[1] == 'O' && p[2] == 'T' && p[3] == '.' && p[4] == 'm' && p[5] == 'e' && p[6] == 'm'; }

// read a whole file into malloc'd memory -> 0, or 1 (no such file), 8 (cannot be read: a directory, no access) or 9 (no memory)
static i32 read_file(const char *path, u8 **buf, i32 *size) {
    char dot[2];
    const char *p;
    i32 n, fd = resolve(AT_FDCWD, path, &p, &n, dot), h = -1;
    i32 e = w_path_open(fd, 1, p, n, 0, (1ull << 1) | (1ull << 2) | (1ull << 21), 0, 0, &h);
    if (e) return e == 44 || e == 54 ? 1 : 8;  // ENOENT, ENOTDIR
    u64 fs[8];
    if (w_fd_filestat_get(h, fs) || *((u8 *)fs + 16) != 4 || fs[4] > 0x7fffffffull) {  // a regular file only
        w_fd_close(h);
        return 8;
    }
    i32 len = (i32)fs[4];
    u8 *b = (u8 *)malloc((u32)len + 1);
    if (!b) {
        w_fd_close(h);
        return 9;  // out of memory
    }
    i32 got = 0;
    while (got < len) {
        u32 iov[2];
        iov[0] = (u32)(b + got);
        iov[1] = (u32)(len - got < (8 << 20) ? len - got : (8 << 20));  // wasmtime refuses a big read
        i32 r = 0;
        if (w_fd_read(h, iov, 1, &r) || r == 0) break;
        got += r;
    }
    w_fd_close(h);
    *buf = b, *size = got;
    return 0;
}

// PATH.normalize of the glue: the key of a library ("a//b/../c.so" -> "a/c.so"); malloc'd, 0 without memory
static char *norm_path(const char *s) {
    i32 n = slen(s), abs = n > 0 && s[0] == '/', trail = n > 0 && s[n - 1] == '/', len = 0, i = 0;
    char *o = (char *)malloc((u32)n + 4);
    if (!o) return 0;
    while (i < n) {
        while (i < n && s[i] == '/') i++;
        i32 st = i;
        while (i < n && s[i] != '/') i++;
        i32 l = i - st;
        if (l == 0 || (l == 1 && s[st] == '.')) continue;
        if (l == 2 && s[st] == '.' && s[st + 1] == '.') {
            i32 p = len;
            while (p > 0 && o[p - 1] != '/') p--;  // the start of the last segment
            if (len > 0 && !(len - p == 2 && o[p] == '.' && o[p + 1] == '.')) {
                len = p > 0 ? p - 1 : 0;
                continue;
            }
            if (abs) continue;  // above the root: dropped
        }
        if (len > 0) o[len++] = '/';
        for (i32 j = 0; j < l; j++) o[len++] = s[st + j];
    }
    char *r = (char *)malloc((u32)len + 4);
    if (!r) {
        free(o);
        return 0;
    }
    i32 k = 0;
    if (abs) r[k++] = '/';
    for (i32 j = 0; j < len; j++) r[k++] = o[j];
    if (len == 0 && !abs) r[k++] = '.';
    if (len > 0 && trail) r[k++] = '/';
    r[k] = 0;
    free(o);
    return r;
}

// the loader.error codes (the host words them):
//  1 no such file (arg: the name)       2 no wasm magic number            3 dylink.0 is not the first section
//  4 the first section is not dylink.0  5 a length that is not a multiple of 4 (the glue's Uint32Array)
//  6 truncated or malformed             7 undefined symbol (arg)          8 cannot be read
//  9 out of memory or table            10 NEEDED libraries nested too deep  11 the engine's own reason
//  12 dlsym: unknown symbol (arg) in the library (name; no name: the main module)     +256: from emscripten_dlopen
static Lib *fail(Libs *L, u32 code, const u8 *arg, i32 n) {
    free(L->arg);
    L->code = code, L->arg = 0, L->argn = 0;
    if (arg) {
        L->arg = (char *)malloc((u32)n + 1);
        if (L->arg) {
            for (i32 i = 0; i < n; i++) L->arg[i] = (char)arg[i];
            L->arg[n] = 0, L->argn = n;
        }
    }
    return 0;
}

typedef struct {  // what dylink.0 says
    u32 memsize, memalign, tsize;
    u32 needed, needed_end;  // the NEEDED subsection's payload (0: none)
    u32 weak, weak_end;      // the import-info subsection's payload
    u32 rpath, rpath_end;    // the runtime-path subsection's payload
    u32 next;                // where the sections after dylink.0 begin
} DyMeta;

// The glue's getDylinkMetadata, with its checks and its words, and every offset checked against the file's size.
// -> 0, or the loader.error code
static u32 parse_dylink(const u8 *b, u32 size, DyMeta *m) {
    m->memsize = m->memalign = m->tsize = m->needed = m->needed_end = m->weak = m->weak_end = 0;
    m->rpath = m->rpath_end = 0;
    if ((size < 24 ? size : 24) % 4) return 5;
    if (size < 4 || b[0] != 0 || b[1] != 'a' || b[2] != 's' || b[3] != 'm') return 2;
    if (size <= 8 || b[8] != 0) return 3;
    Rd r = {b, 9, size, 0};
    u32 sl = rd_leb(&r), nl;
    if (r.bad || sl > size - r.i) return 6;
    Rd d = {b, r.i, r.i + sl, 0};
    const u8 *nm = rd_name(&d, &nl);
    if (d.bad) return 6;
    if (!is8(nm, (i32)nl, N_DYLINK)) return 4;
    m->next = d.end;
    while (d.i < d.end && !d.bad) {
        u8 sub = rd_u8(&d);
        u32 ss = rd_leb(&d);
        if (d.bad) break;
        if (sub == 1) {
            m->memsize = rd_leb(&d), m->memalign = rd_leb(&d), m->tsize = rd_leb(&d);
            rd_leb(&d);
        } else if (sub == 2 || sub == 4 || sub == 3 || sub == 5) {
            u32 start = d.i, cnt = rd_leb(&d);
            if (sub == 2) m->needed = start;
            if (sub == 4) m->weak = start;
            if (sub == 5) m->rpath = start;
            if (sub == 3 || sub == 4) {  // names and flags
                for (u32 k = 0; k < cnt && !d.bad; k++) {
                    u32 n;
                    if (sub == 4) rd_name(&d, &n);
                    rd_name(&d, &n);
                    rd_leb(&d);
                }
            } else {
                for (u32 k = 0; k < cnt && !d.bad; k++) {
                    u32 n;
                    rd_name(&d, &n);
                }
            }
            if (sub == 2) m->needed_end = d.i;
            if (sub == 4) m->weak_end = d.i;
            if (sub == 5) m->rpath_end = d.i;
        } else {
            if (ss > d.end - d.i) return 6;
            d.i += ss;
        }
    }
    return d.bad ? 6 : 0;
}

typedef struct {
    const u8 *name;
    i32 n;
    i32 func;  // 1: GOT.func, 0: GOT.mem
} GotImp;

static i32 is_weak(const u8 *b, const DyMeta *m, const u8 *nm, i32 n) {
    if (!m->weak) return 0;
    Rd r = {b, m->weak, m->weak_end, 0};
    u32 cnt = rd_leb(&r);
    for (u32 k = 0; k < cnt && !r.bad; k++) {
        u32 ml, fl;
        rd_name(&r, &ml);
        const u8 *f = rd_name(&r, &fl);
        u32 flags = rd_leb(&r);
        if (!r.bad && (flags & 3) == 1 && eq(f, (i32)fl, (const char *)nm, n)) return 1;
    }
    return 0;
}

static Lib *load_lib(Libs *L, const char *path, i32 global, u32 scope, i32 depth, const u8 *handle);

// the main module's search for a NEEDED library (the glue's findLibraryFS): the runtime paths of the module
// ($ORIGIN is its folder), LD_LIBRARY_PATH
char *_emscripten_find_dylib(char *buf, const char *rpath, const char *name, u32 size);

// the module's runtime paths as one "a:b" string, $ORIGIN replaced by the module's folder; malloc'd, 0 without memory
static char *runtime_paths(const u8 *b, const DyMeta *m, const char *path) {
    i32 dl = 0;
    for (i32 i = 0; path[i]; i++) if (path[i] == '/') dl = i;
    char *out = (char *)malloc(1);
    if (!out) return 0;
    out[0] = 0;
    if (!m->rpath) return out;
    Rd r = {b, m->rpath, m->rpath_end, 0};
    u32 cnt = rd_leb(&r);
    i32 len = 0;
    for (u32 k = 0; k < cnt && !r.bad; k++) {
        u32 n;
        const u8 *p = rd_name(&r, &n);
        if (r.bad) break;
        i32 origin = n >= 7 && p[0] == '$' && p[1] == 'O' && p[2] == 'R' && p[3] == 'I' && p[4] == 'G' && p[5] == 'I' && p[6] == 'N';
        char *o = (char *)malloc((u32)len + n + (u32)dl + 3);
        if (!o) {
            free(out);
            return 0;
        }
        for (i32 i = 0; i < len; i++) o[i] = out[i];
        free(out);
        out = o;
        if (len) out[len++] = ':';
        if (origin) {
            for (i32 i = 0; i < dl; i++) out[len++] = path[i];
            if (dl == 0 && path[0] == '/') out[len++] = '/';
            p += 7, n -= 7;
        }
        for (u32 i = 0; i < n; i++) out[len++] = (char)p[i];
        out[len] = 0;
    }
    return out;
}

// the load of `path` failed because that file is not there (not because something it needs is)
static i32 missing(Libs *L, const char *path) { return L->code == 1 && L->arg && eq((const u8 *)L->arg, L->argn, path, slen(path)); }

// A NEEDED library, as the glue finds it: the main module's search (runtime paths with $ORIGIN, LD_LIBRARY_PATH), else
// the name as written; the library is then the one with that full (normalized) name. Nothing else is tried.
static Lib *load_needed(Libs *L, const char *rpath, const u8 *name, i32 n, i32 global, u32 scope,
                        i32 depth) {
    char *nm = (char *)malloc((u32)n + 1);
    char *buf = (char *)malloc(512);
    Lib *x = 0;
    if (!nm || !buf) {
        free(nm), free(buf);
        return fail(L, 9, 0, 0);
    }
    for (i32 i = 0; i < n; i++) nm[i] = (char)name[i];
    nm[n] = 0;
    char *found = nm[0] != '/' ? _emscripten_find_dylib(buf, rpath, nm, 512) : 0;
    char *q = norm_path(found ? found : nm);  // the glue's candidate
    if (!q) {
        free(nm), free(buf);
        return fail(L, 9, 0, 0);
    }
    x = load_lib(L, q, global, scope, depth + 1, 0);
    i32 gone = !x && missing(L, q);
    free(q);
    if (!x && !found && gone) fail(L, 1, name, n);  // the glue names the NEEDED library, as it was written
    free(nm), free(buf);
    return x;
}

static void lib_drop(Libs *L, Lib *x) {
    i32 j = 0;
    for (i32 k = 0; k < L->libs.n; k++) if (L->libs.v[k] != x) L->libs.v[j++] = L->libs.v[k];
    L->libs.n = j;
    free(x->name), free(x);
}

// a symbol of module `id`: out[0] = 0: none; 1: a number (the host has made it what the glue's relocateExports and
// ToInt32 make of the global, the memory base included); 2, 3: a table slot. out[1] goes in as 1 for dlsym: the host
// then answers a mutable reference global with 0 and ends the process for a mutable i64 (the glue's TypeError), while
// the GOT does not see those two.
static u32 sym_of(i32 id, const u8 *nm, i32 n, u32 *out, i32 for_dlsym) {
    out[0] = 0, out[1] = (u32)for_dlsym;  // the host leaves them alone when it fails
    return dl_sym(id, (const char *)nm, n, out);
}

static Lib *load_lib(Libs *L, const char *path, i32 global, u32 scope, i32 depth, const u8 *handle) {
    i32 plen = slen(path);
    for (i32 k = 0; k < L->libs.n; k++) {  // the same file again: the same instance
        Lib *x = (Lib *)L->libs.v[k];
        if (!eq((const u8 *)x->name, slen(x->name), path, plen)) continue;
        if (!global) {
            if (scope && x->ready) dl_scope(x->id, scope);
        } else if (!x->global) {
            x->global = 1;
            if (x->ready) x->gseq = ++L->gcount, dl_scope(x->id, 0);
        }
        return x;
    }
    if (depth > host_depth()) return fail(L, 10, 0, 0);

    u8 *b = 0;
    i32 size = 0, own = 1;
    u32 hd = handle ? ((const u32 *)(handle + 28))[0] : 0, hs = handle ? ((const u32 *)(handle + 32))[0] : 0;
    if (hd && hs) {  // the bytes were handed over with the handle
        b = (u8 *)hd, size = (i32)hs, own = 0;
    } else {
        i32 e = read_file(path, &b, &size);
        if (e) return fail(L, (u32)e, (const u8 *)path, plen);
    }
    DyMeta m;
    u32 code = parse_dylink(b, (u32)size, &m);
    if (code) {
        if (own) free(b);
        return fail(L, code, 0, 0);
    }

    Lib *x = (Lib *)calloc(1, sizeof(Lib));  // registered before its NEEDED libraries load: a cycle finds it
    if (x) x->name = (char *)malloc((u32)plen + 1);
    if (!x || !x->name || !vec_push(&L->libs, x)) {
        if (x) free(x->name);
        free(x);
        if (own) free(b);
        return fail(L, 9, 0, 0);
    }
    x->id = -1, x->global = global;
    for (i32 k = 0; k <= plen; k++) x->name[k] = path[k];

    // the libraries it needs come first (their symbols resolve its imports)
    GotImp *got = 0;
    i32 nimp_got = 0;
    u32 base = 0, tbase = 0;
    char *rpath = 0;
    if (m.needed) {
        rpath = runtime_paths(b, &m, path);
        if (!rpath) {
            fail(L, 9, 0, 0);
            goto failed;
        }
        Rd r = {b, m.needed, m.needed_end, 0};
        u32 cnt = rd_leb(&r);
        for (u32 k = 0; k < cnt && !r.bad; k++) {
            u32 nl;
            const u8 *nn = rd_name(&r, &nl);
            if (r.bad) break;
            if (!load_needed(L, rpath, nn, (i32)nl, global, scope, depth)) goto failed;
        }
        if (r.bad) {
            fail(L, 6, 0, 0);
            goto failed;
        }
    }

    // the GOT imports, in import order
    {
        u32 pos = m.next;
        Rd imp = {b, 0, 0, 0};
        while (pos < (u32)size) {
            Rd s = {b, pos, (u32)size, 0};
            u8 sid = rd_u8(&s);
            u32 len = rd_leb(&s);
            if (s.bad || len > (u32)size - s.i) {
                fail(L, 6, 0, 0);
                goto failed;
            }
            if (sid == 2) imp = (Rd){b, s.i, s.i + len, 0};
            pos = s.i + len;
        }
        if (imp.end) {
            u32 cnt = rd_leb(&imp);
            if (imp.bad || cnt > imp.end - imp.i || cnt > (1u << 22)) {  // every import takes 3 bytes or more
                fail(L, 6, 0, 0);
                goto failed;
            }
            got = (GotImp *)malloc(cnt * sizeof(GotImp) + 1);
            if (!got) {
                fail(L, 9, 0, 0);
                goto failed;
            }
            for (u32 k = 0; k < cnt && !imp.bad; k++) {
                u32 ml, fl;
                const u8 *mod = rd_name(&imp, &ml);
                const u8 *f = rd_name(&imp, &fl);
                u8 kind = rd_u8(&imp);
                if (kind == 0) {
                    rd_leb(&imp);
                } else if (kind == 1) {
                    rd_u8(&imp);
                    rd_limits(&imp);
                } else if (kind == 2) {
                    rd_limits(&imp);
                } else if (kind == 3) {
                    u8 vt = rd_u8(&imp);
                    if (vt == 0x63 || vt == 0x64) rd_leb(&imp);  // a reference type with a heap type (an index)
                    rd_u8(&imp);                                 // mutability
                    if (!imp.bad && (is_gotmem(mod, (i32)ml) || is8(mod, (i32)ml, N_GOTFUNC))) {
                        got[nimp_got].name = f;
                        got[nimp_got].n = (i32)fl;
                        got[nimp_got].func = is8(mod, (i32)ml, N_GOTFUNC);
                        nimp_got++;
                    }
                } else if (kind == 4) {
                    rd_u8(&imp);
                    rd_leb(&imp);
                } else {
                    imp.bad = 1;
                }
            }
            if (imp.bad) {
                fail(L, 6, 0, 0);
                goto failed;
            }
        }
    }

    // memory from the main module's calloc, aligned; table slots at the end of the table
    {
        if (m.memalign > 24 || (u64)m.memsize + (1u << m.memalign) > 0x7fff0000ull) {
            fail(L, 9, 0, 0);
            goto failed;
        }
        u32 align = 1u << m.memalign;
        if (m.memsize) {
            u32 raw = (u32)calloc(m.memsize + align, 1);
            if (!raw) {
                fail(L, 9, 0, 0);
                goto failed;
            }
            base = (raw + align - 1) & ~(align - 1);
        }
        tbase = table_grow(0);
        if (m.tsize) tbase = table_grow(m.tsize);
        if (tbase == (u32)-1) {
            fail(L, 9, 0, 0);
            goto failed;
        }
    }

    i32 id = dl_instantiate(b, size, base, tbase, scope);
    if (id < 0) {
        fail(L, 11, 0, 0);
        goto failed;
    }
    x->id = id;

    // GOT: the first definition wins (the main module, the libraries loaded before, the module's own)
    for (i32 g = 0; g < nimp_got; g++) {
        const u8 *nm = got[g].name;
        i32 n = got[g].n;
        u32 out[2], v = sym_of(0, nm, n, out, 0);
        for (i32 k = 0; out[0] == 0 && k < L->libs.n; k++) {
            Lib *o = (Lib *)L->libs.v[k];
            if (o->ready) v = sym_of(o->id, nm, n, out, 0);
        }
        if (out[0] == 0) v = sym_of(id, nm, n, out, 0);
        if (out[0] == 0) {
            if (is_weak(b, &m, nm, n)) continue;
            fail(L, 7, nm, n);
            goto failed;
        }
        dl_got_set(id, g, v);
    }

    {
        u64 relocs[3], ctors[3];
        relocs[0] = 0x615f6d7361775f5full, relocs[1] = 0x7461645f796c7070ull, relocs[2] = 0x73636f6c65725f61ull;
        ctors[0] = 0x635f6d7361775f5full, ctors[1] = 0x726f74635f6c6c61ull, ctors[2] = 0x73ull;
        dl_call(id, (const char *)relocs, 24);  // __wasm_apply_data_relocs
        dl_call(id, (const char *)ctors, 17);   // __wasm_call_ctors
    }

    x->base = base, x->memsize = m.memsize, x->tbase = tbase, x->tsize = m.tsize;
    x->ready = 1;
    if (x->global) x->gseq = ++L->gcount, dl_scope(id, 0);
    else if (scope) dl_scope(id, scope);
    if (own) free(b);
    free(got), free(rpath);
    return x;

failed:
    lib_drop(L, x);
    if (own) free(b);
    free(got), free(rpath);
    return 0;
}

static i32 dl_open(u8 *handle, i32 async) {
    Libs *L = libs();
    if (!L) return 0;
    char *name = norm_path((const char *)(handle + 36));
    if (!name) {
        dl_error(9 | (async ? 256 : 0), (const char *)(handle + 36), slen((const char *)(handle + 36)), 0, 0);
        return 0;
    }
    i32 global = (((const i32 *)(handle + 4))[0] & 256) != 0;
    u32 scope = global ? 0 : ++L->scopes;
    free(L->arg);
    L->code = 0, L->arg = 0, L->argn = 0;
    Lib *x = load_lib(L, name, global, scope, 0, handle);
    if (!x) {
        const char *shown = async ? (const char *)(handle + 36) : name;  // the glue names the file as written
        dl_error(L->code | (async ? 256 : 0), shown, slen(shown), L->arg, L->argn);
        free(name);
        return 0;
    }
    free(name);
    Hnd *h = 0;
    for (i32 k = 0; k < L->hnds.n && !h; k++)
        if (((Hnd *)L->hnds.v[k])->handle == (i32)handle) h = (Hnd *)L->hnds.v[k];
    if (!h) {
        h = (Hnd *)malloc(sizeof(Hnd));
        if (h) h->handle = (i32)handle;
        if (!h || !vec_push(&L->hnds, h)) {
            free(h);
            dl_error(9 | (async ? 256 : 0), (const char *)(handle + 36), slen((const char *)(handle + 36)), 0, 0);
            return 0;
        }
    }
    h->lib = x;
    handle[8] = 1;
    ((u32 *)(handle + 12))[0] = x->base, ((u32 *)(handle + 12))[1] = x->memsize;
    ((u32 *)(handle + 12))[2] = x->tbase, ((u32 *)(handle + 12))[3] = x->tsize;
    return 1;
}

EXPORT("_dlopen_js") i32 dlopen_js(u8 *handle) { return dl_open(handle, 0); }

// emscripten_dlopen: the glue loads asynchronously and calls back from a promise, after the caller returned. There is no
// event loop here: the load and the callback are a pending call of the interpreter (Py_AddPendingCall), which runs at
// its next safe point after emscripten_dlopen returned (a callback is a table index: onsuccess(handle, user_data) or
// onerror(handle, user_data)). The pending call is this adapter's own export, looked up by name for its table slot.
EXPORT("__emscripten_dlopen_async") i32 dlopen_async(u32 *job) {
    u32 handle = job[0], onsuccess = job[1], onerror = job[2], user_data = job[3];
    free(job);
    u32 cb = dl_open((u8 *)handle, 1) ? onsuccess : onerror;
    if (cb) ((void (*)(u32, u32))cb)(handle, user_data);
    return 0;
}

EXPORT("_emscripten_dlopen_js") void emscripten_dlopen_js(u8 *handle, u32 onsuccess, u32 onerror, u32 user_data) {
    u32 *job = (u32 *)malloc(16);
    u64 add[3], own[4];
    u32 out[2], pend = 0, fn = 0;
    add[0] = 0x65506464415f7950ull, add[1] = 0x6c6143676e69646eull, add[2] = 0x6cull;  // "Py_AddPendingCall"
    own[0] = 0x697263736d655f5full, own[1] = 0x6f6c645f6e657470ull, own[2] = 0x6e7973615f6e6570ull, own[3] = 0x63ull;
    // "__emscripten_dlopen_async"
    if (job) {
        job[0] = (u32)handle, job[1] = onsuccess, job[2] = onerror, job[3] = user_data;
        pend = dl_sym(0, (const char *)add, 17, out);
        if (out[0] == 2 || out[0] == 3) {
            fn = dl_sym(0, (const char *)own, 25, out);
            if ((out[0] == 2 || out[0] == 3) && ((i32(*)(u32, u32))pend)(fn, (u32)job) == 0) return;
        }
        dlopen_async(job);  // no pending calls (not the case in Pyodide's Python): at once
    }
}

EXPORT("_dlsym_js") u32 dlsym_js(i32 handle, const char *sym, u32 *index) {
    Libs *L = libs();
    if (!L) return 0;
    Lib *lib = 0;
    for (i32 k = L->hnds.n - 1; k >= 0 && !lib; k--)
        if (((Hnd *)L->hnds.v[k])->handle == handle) lib = ((Hnd *)L->hnds.v[k])->lib;
    u32 out[2] = {0, 0}, v = 0;
    i32 n = slen(sym);
    if (lib) {
        v = sym_of(lib->id, (const u8 *)sym, n, out, 1);
    } else {  // not a library loaded by dlopen: the main module (dlopen(NULL), RTLD_DEFAULT), then the RTLD_GLOBAL libraries
        v = sym_of(0, (const u8 *)sym, n, out, 1);
        for (u32 seq = 1; out[0] == 0 && seq <= L->gcount; seq++)  // in the order they became global
            for (i32 k = 0; out[0] == 0 && k < L->libs.n; k++) {
                Lib *o = (Lib *)L->libs.v[k];
                if (o->ready && o->global && o->gseq == seq) v = sym_of(o->id, (const u8 *)sym, n, out, 1);
            }
    }
    if (out[0] == 0) {
        dl_error(12, lib ? lib->name : 0, lib ? slen(lib->name) : 0, sym, n);
        return 0;
    }
    if (out[0] == 3) *index = out[1];
    return v;
}

#endif
