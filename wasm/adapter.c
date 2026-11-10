// Emscripten `env` imports of pyodide.asm.wasm answered over WASI preview1, as a wasm module.
//
// Shape (after Wasmtime's wasi-preview1-component-adapter): built as an Emscripten-style side module
// (-fPIC -shared) with NO data section and no stack of its own: it imports the main module's memory,
// table and __stack_pointer and works on the main module's pointers directly. Its only state (directory
// cookies) is one block from the main module's malloc, kept in a wasm global.
//
// Paths: every absolute path and every path relative to AT_FDCWD (the cwd is always "/") goes to the
// first preopen (fd 3), which the host maps to the guest's "/". Emscripten's errno values are WASI's,
// so a WASI error is returned as is (negated, as a syscall does).

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef int i32;
typedef short i16;
typedef unsigned long long u64;
typedef long long i64;

#define WASI(n) __attribute__((import_module("wasi_snapshot_preview1"), import_name(n)))
#define EXPORT(n) __attribute__((export_name(n), visibility("default")))

WASI("path_open") i32 w_path_open(i32 fd, i32 lookup, const char *p, i32 n, i32 oflags, u64 rights, u64 inh, i32 fdflags, i32 *out);
WASI("path_filestat_get") i32 w_path_filestat_get(i32 fd, i32 lookup, const char *p, i32 n, void *buf);
WASI("fd_filestat_get") i32 w_fd_filestat_get(i32 fd, void *buf);
WASI("path_readlink") i32 w_path_readlink(i32 fd, const char *p, i32 n, char *buf, i32 len, i32 *used);
WASI("fd_readdir") i32 w_fd_readdir(i32 fd, void *buf, i32 len, u64 cookie, i32 *used);
WASI("clock_time_get") i32 w_clock_time_get(i32 id, u64 precision, u64 *out);

WASI("fd_prestat_get") i32 w_fd_prestat_get(i32 fd, u32 *buf);
WASI("fd_prestat_dir_name") i32 w_fd_prestat_dir_name(i32 fd, char *path, i32 len);
WASI("fd_read") i32 w_fd_read(i32 fd, const void *iovs, i32 n, i32 *nread);
WASI("fd_close") i32 w_fd_close(i32 fd);
WASI("path_create_directory") i32 w_mkdir(i32 fd, const char *p, i32 n);
WASI("path_unlink_file") i32 w_unlink(i32 fd, const char *p, i32 n);
WASI("path_remove_directory") i32 w_rmdir(i32 fd, const char *p, i32 n);
WASI("path_rename") i32 w_rename(i32 fd, const char *p, i32 n, i32 fd2, const char *p2, i32 n2);
WASI("fd_filestat_set_size") i32 w_fd_set_size(i32 fd, u64 size);
WASI("path_symlink") i32 w_symlink(const char *old, i32 oldn, i32 fd, const char *new_, i32 newn);
WASI("path_link") i32 w_link(i32 ofd, i32 oflags, const char *op, i32 on, i32 nfd, const char *np, i32 nn);
WASI("fd_allocate") i32 w_fd_allocate(i32 fd, u64 offset, u64 len);
WASI("fd_datasync") i32 w_fd_datasync(i32 fd);
WASI("proc_exit") __attribute__((noreturn)) void w_proc_exit(i32 code);

// the main module's allocator (resolved from its exports, like any side module's import)
void *malloc(u32 n);
void *calloc(u32 n, u32 size);
void free(void *p);

// The loader's host interface: the only things a wasm module cannot do itself (the host keeps the instances
// and their exports by name). id 0 is the main module.
#define LOADER(n) __attribute__((import_module("loader"), import_name(n)))
// compile and instantiate the module in [p, p+n) with the main module's memory, table, stack pointer and tags,
// __memory_base = mb, __table_base = tb; `env` functions by name from the main module and the modules loaded
// before; every GOT.mem/GOT.func import a new mutable i32 global = 0, numbered in import order. -> id > 0, or < 0
LOADER("instantiate") i32 dl_instantiate(const u8 *p, i32 n, u32 mb, u32 tb);
LOADER("got_set") void dl_got_set(i32 id, i32 index, u32 value);
// export `name` of module id: a global -> its value, kind 1; a function -> a table slot (made once), kind 2;
// absent -> kind 0. out[0] = kind, out[1] = the export's index.
LOADER("sym") u32 dl_sym(i32 id, const char *name, i32 n, u32 *out);
// call export `name` (no arguments, no results) if it exists -> 1, else 0
LOADER("call") i32 dl_call(i32 id, const char *name, i32 n);
// the main module's table, grown by n null entries -> the old size (the trampoline module's table.grow)
__attribute__((import_module("aux"), import_name("table_grow"))) u32 table_grow(u32 n);

#define AT_FDCWD (-100)
#define PREOPEN 3
#define ENOTTY 59
#define ERANGE 68
#define EBADF 8
#define ENOMEM 48
#define MAXFD 1024

static i32 is_sock(i32 fd);  // a socket descriptor (the sockets section, at the end)

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
static u64 *cookies(void) {  // per descriptor: the next fd_readdir cookie
    u64 *s = state_get();
    if (!s) {
        s = (u64 *)malloc(MAXFD * 8);
        for (i32 i = 0; i < MAXFD; i++) s[i] = 0;
        state_set(s);
    }
    return s;
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

// A guest path and dirfd -> (WASI fd, path pointer, length). An empty result is ".". The cwd is "/".
static i32 resolve(i32 dirfd, const char *path, const char **out, i32 *len, char *dot) {
    i32 fd = dirfd;
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

// WASI filestat (64 bytes) -> Emscripten struct stat (96 bytes)
static void put_stat(u8 *dst, const u8 *fs) {
    u64 dev = *(const u64 *)(fs + 0), ino = *(const u64 *)(fs + 8);
    u8 ft = fs[16];
    u64 nlink = *(const u64 *)(fs + 24), size = *(const u64 *)(fs + 32);
    u64 at = *(const u64 *)(fs + 40), mt = *(const u64 *)(fs + 48), ct = *(const u64 *)(fs + 56);
    u32 mode = ft == 3 ? 0040755 : ft == 4 ? 0100644 : ft == 7 ? 0120777 : ft == 2 ? 0020666 : ft == 1 ? 0060666 : 0100644;
    for (i32 i = 0; i < 96; i++) dst[i] = 0;
    *(u32 *)(dst + 0) = (u32)dev;
    *(u32 *)(dst + 4) = mode;
    *(u32 *)(dst + 8) = (u32)nlink;
    *(i64 *)(dst + 24) = (i64)size;
    *(u32 *)(dst + 32) = 4096;
    *(u32 *)(dst + 36) = (u32)((size + 511) / 512);
    *(i64 *)(dst + 40) = (i64)(at / 1000000000ull);
    *(u32 *)(dst + 48) = (u32)(at % 1000000000ull);
    *(i64 *)(dst + 56) = (i64)(mt / 1000000000ull);
    *(u32 *)(dst + 64) = (u32)(mt % 1000000000ull);
    *(i64 *)(dst + 72) = (i64)(ct / 1000000000ull);
    *(u32 *)(dst + 80) = (u32)(ct % 1000000000ull);
    *(u64 *)(dst + 88) = ino;
}

static i32 stat_path(i32 dirfd, const char *path, void *buf, i32 follow) {
    u64 fs[8];
    char dot[2];
    const char *p;
    i32 n, fd = resolve(dirfd, path, &p, &n, dot);
    i32 e = w_path_filestat_get(fd, follow ? 1 : 0, p, n, fs);
    if (e) return -e;
    put_stat((u8 *)buf, (const u8 *)fs);
    return 0;
}

EXPORT("__syscall_getcwd") i32 sc_getcwd(char *buf, i32 size) {
    if (size < 2) return -ERANGE;
    buf[0] = '/';
    buf[1] = 0;
    return 2;
}

EXPORT("__syscall_openat") i32 sc_openat(i32 dirfd, const char *path, i32 flags, i32 va) {
    (void)va;
    char dot[2];
    const char *p;
    i32 n, fd = resolve(dirfd, path, &p, &n, dot);
    i32 acc = flags & 3, oflags = 0, fdflags = 0;
    if (flags & 0100) oflags |= 1;       // O_CREAT
    if (flags & 0200000) oflags |= 2;    // O_DIRECTORY
    if (flags & 0200) oflags |= 4;       // O_EXCL
    if (flags & 01000) oflags |= 8;      // O_TRUNC
    if (flags & 02000) fdflags |= 1;     // O_APPEND
    if (flags & 04000) fdflags |= 4;     // O_NONBLOCK
    u64 all = (1ull << 30) - 1, writes = (1ull << 6) | (1ull << 0) | (1ull << 8) | (1ull << 22);
    u64 reads = (1ull << 1) | (1ull << 14);
    u64 rights = acc == 0 ? all & ~writes : acc == 1 ? all & ~reads : all;
    i32 out = -1;
    i32 e = w_path_open(fd, (flags & 0400000) ? 0 : 1, p, n, oflags, rights, all, fdflags, &out);
    if (e) return -e;
    if (out >= 0 && out < MAXFD) cookies()[out] = 0;  // a new descriptor lists its directory from the start
    return out;
}

EXPORT("__syscall_stat64") i32 sc_stat64(const char *path, void *buf) { return stat_path(AT_FDCWD, path, buf, 1); }
EXPORT("__syscall_lstat64") i32 sc_lstat64(const char *path, void *buf) { return stat_path(AT_FDCWD, path, buf, 0); }

EXPORT("__syscall_fstat64") i32 sc_fstat64(i32 fd, void *buf) {
    u64 fs[8];
    if (is_sock(fd)) {  // a socket: S_IFSOCK
        for (i32 i = 0; i < 8; i++) fs[i] = 0;
        put_stat((u8 *)buf, (const u8 *)fs);
        *(u32 *)((u8 *)buf + 4) = 0140777;
        return 0;
    }
    i32 e = w_fd_filestat_get(fd, fs);
    if (e) return -e;
    put_stat((u8 *)buf, (const u8 *)fs);
    return 0;
}

EXPORT("__syscall_newfstatat") i32 sc_newfstatat(i32 dirfd, const char *path, void *buf, i32 flags) {
    if (!path[0]) return sc_fstat64(dirfd, buf);  // AT_EMPTY_PATH
    return stat_path(dirfd, path, buf, !(flags & 0x100));
}

EXPORT("__syscall_readlinkat") i32 sc_readlinkat(i32 dirfd, const char *path, char *buf, i32 len) {
    char dot[2];
    const char *p;
    i32 n, used = 0, fd = resolve(dirfd, path, &p, &n, dot);
    i32 e = w_path_readlink(fd, p, n, buf, len, &used);
    return e ? -e : used;
}

EXPORT("__syscall_faccessat") i32 sc_faccessat(i32 dirfd, const char *path, i32 mode, i32 flags) {
    (void)mode;
    u64 fs[8];
    char dot[2];
    const char *p;
    i32 n, fd = resolve(dirfd, path, &p, &n, dot);
    i32 e = w_path_filestat_get(fd, (flags & 0x100) ? 0 : 1, p, n, fs);
    return e ? -e : 0;
}

// WASI dirents {d_next u64, d_ino u64, d_namlen u32, d_type u8, name} -> linux_dirent64
// {d_ino u64, d_off i64, d_reclen u16, d_type u8, name\0, padded to 8}
EXPORT("__syscall_getdents64") i32 sc_getdents64(i32 fd, u8 *dirp, i32 count) {
    if (fd < 0 || fd >= MAXFD) return -EBADF;
    u64 *ck = cookies();
    i32 cap = count + 512;
    u8 *tmp = (u8 *)malloc((u32)cap);
    if (!tmp) return -ENOMEM;
    i32 used = 0;
    i32 e = w_fd_readdir(fd, tmp, cap, ck[fd], &used);
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
        ck[fd] = next;
        in += 24 + (i32)nl;
    }
    free(tmp);
    if (out == 0 && in + 24 <= used) return -22;  // EINVAL: the buffer cannot hold one entry
    return out;
}

EXPORT("__syscall_ioctl") i32 sc_ioctl(i32 fd, i32 op, i32 va) {
    (void)va;
    if (is_sock(fd) && op == 0x5421) return 0;  // FIONBIO: the host's sockets block; poll() keeps the timeouts
    return -ENOTTY;
}

static i32 is_sock(i32 fd);
WASI("fd_fdstat_get") i32 w_fd_fdstat_get(i32 fd, void *buf);
WASI("fd_fdstat_set_flags") i32 w_fd_fdstat_set_flags(i32 fd, i32 flags);

// fcntl: the flags are WASI's fdflags (append, nonblock) and rights; descriptors can not be duplicated in WASI 0.1 (ENOSYS).
EXPORT("__syscall_fcntl64") i32 sc_fcntl64(i32 fd, i32 cmd, i32 va) {
    switch (cmd) {
        case 1:  // F_GETFD: FD_CLOEXEC is not kept (there is no exec)
        case 2:  // F_SETFD
            return 0;
        case 3: {  // F_GETFL
            if (is_sock(fd)) return 2;  // O_RDWR
            u8 st[24] __attribute__((aligned(8)));
            i32 e = w_fd_fdstat_get(fd, st);
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
            if (is_sock(fd)) return 0;
            i32 ff = 0;
            if (va & 02000) ff |= 1;
            if (va & 04000) ff |= 4;
            i32 e = w_fd_fdstat_set_flags(fd, ff);
            return e ? -e : 0;
        }
        case 6:  // F_SETLK
        case 7:  // F_SETLKW: one process, so a lock is always granted
            return 0;
        case 0:     // F_DUPFD
        case 1030:  // F_DUPFD_CLOEXEC
            return -52;  // ENOSYS
        default:
            return -28;  // EINVAL
    }
}

EXPORT("_emscripten_get_progname") void get_progname(char *buf, i32 len) {
    if (len < 7) return;
    buf[0] = 'p', buf[1] = 'y', buf[2] = 't', buf[3] = 'h', buf[4] = 'o', buf[5] = 'n', buf[6] = 0;
}

static double now_ms(i32 clock) {
    u64 t = 0;
    w_clock_time_get(clock, 1000, &t);
    return (double)t / 1e6;
}
EXPORT("emscripten_date_now") double date_now(void) { return now_ms(0); }
EXPORT("emscripten_get_now") double get_now(void) { return now_ms(1); }
EXPORT("emscripten_get_heap_max") i32 heap_max(void) { return 0x7FFF0000; }

EXPORT("emscripten_resize_heap") i32 resize_heap(u32 n) {
    u32 have = (u32)__builtin_wasm_memory_size(0);
    u32 want = (u32)(((u64)n + 65535) / 65536);
    if (want <= have) return 1;
    return __builtin_wasm_memory_grow(0, want - have) == (unsigned long)-1 ? 0 : 1;
}

// ================================================================== the loader: _dlopen_js / _dlsym_js
// What Emscripten's JavaScript glue does in loadWebAssemblyModule, in wasm; the host is asked only to
// instantiate, to look up an export by name, to set a GOT global and to call an export.

#define MAXLIB 256
typedef struct {
    i32 handle, id;
    u32 base, memsize, tbase, tsize;
    char *name;
} Lib;
typedef struct {
    i32 n;
    Lib lib[MAXLIB];
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

static u32 uleb(const u8 *b, i32 *i) {
    u32 r = 0, s = 0;
    for (;;) {
        u8 c = b[(*i)++];
        r |= (u32)(c & 0x7F) << s;
        s += 7;
        if (!(c & 0x80)) return r;
    }
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

// read a whole file into malloc'd memory
static u8 *read_file(const char *path, i32 *size) {
    char dot[2];
    const char *p;
    i32 n, fd = resolve(AT_FDCWD, path, &p, &n, dot), h = -1;
    if (w_path_open(fd, 1, p, n, 0, (1ull << 1) | (1ull << 2) | (1ull << 21), 0, 0, &h)) return 0;
    u64 fs[8];
    if (w_fd_filestat_get(h, fs)) {
        w_fd_close(h);
        return 0;
    }
    i32 len = (i32)fs[4];
    u8 *buf = (u8 *)malloc((u32)len + 1);
    i32 got = 0;
    while (got < len) {
        u32 iov[2];
        iov[0] = (u32)(buf + got);
        iov[1] = (u32)(len - got);
        i32 r = 0;
        if (w_fd_read(h, iov, 1, &r) || r == 0) break;
        got += r;
    }
    w_fd_close(h);
    *size = got;
    return buf;
}

typedef struct {
    const u8 *name;
    i32 n;
    i32 func;  // 1: GOT.func, 0: GOT.mem
} GotImp;

static i32 base_eq(const char *a, const char *b) {  // equal file names (the part after the last '/')
    const char *x = a, *y = b;
    for (const char *p = a; *p; p++) if (*p == '/') x = p + 1;
    for (const char *p = b; *p; p++) if (*p == '/') y = p + 1;
    return eq((const u8 *)x, slen(x), y, slen(y));
}

static Lib *load_lib(const char *path, i32 depth);

// a NEEDED library: already loaded (by file name), or next to the module that needs it, or in /lib
static i32 load_needed(const char *from, const u8 *name, i32 n, i32 depth) {
    Libs *L = libs();
    char *nm = (char *)malloc((u32)n + 1);
    for (i32 i = 0; i < n; i++) nm[i] = (char)name[i];
    nm[n] = 0;
    for (i32 k = 0; k < L->n; k++)
        if (base_eq(L->lib[k].name, nm)) {
            free(nm);
            return 1;
        }
    i32 dl = 0;
    for (i32 i = 0; from[i]; i++) if (from[i] == '/') dl = i + 1;
    char *p = (char *)malloc((u32)(dl + n + 8));
    for (i32 i = 0; i < dl; i++) p[i] = from[i];
    for (i32 i = 0; i <= n; i++) p[dl + i] = nm[i];
    Lib *x = load_lib(p, depth + 1);
    if (!x) {  // /lib/<name>
        p[0] = '/', p[1] = 'l', p[2] = 'i', p[3] = 'b', p[4] = '/';
        for (i32 i = 0; i <= n; i++) p[5 + i] = nm[i];
        x = load_lib(p, depth + 1);
    }
    free(p), free(nm);
    return x != 0;
}

static Lib *load_lib(const char *path, i32 depth) {
    Libs *L = libs();
    i32 plen = slen(path);
    for (i32 k = 0; k < L->n; k++)  // the same file again: the same instance
        if (eq((const u8 *)L->lib[k].name, slen(L->lib[k].name), path, plen)) return &L->lib[k];
    if (L->n >= MAXLIB || depth > 8) return 0;
    i32 size = 0;
    u8 *b = read_file(path, &size);
    if (!b) return 0;

    // dylink.0 (mem_info, needed), the imports (GOT.*), the exports (names), in one pass over the sections
    u32 memsize = 0, memalign = 0, tsize = 0;
    i32 nexp = 0, nimp_got = 0;
    const u8 *exp_sec = 0, *imp_sec = 0, *needed = 0;
    i32 i = 8;
    while (i < size) {
        u8 sid = b[i++];
        u32 len = uleb(b, &i);
        i32 end = i + (i32)len;
        if (sid == 0) {
            i32 j = i;
            u32 nl = uleb(b, &j);
            if (is8(b + j, (i32)nl, N_DYLINK)) {
                j += (i32)nl;
                while (j < end) {
                    u8 sub = b[j++];
                    u32 sl = uleb(b, &j);
                    i32 k = j;
                    if (sub == 1) {
                        memsize = uleb(b, &k);
                        memalign = uleb(b, &k);
                        tsize = uleb(b, &k);
                    } else if (sub == 2) {
                        needed = b + j;
                    }
                    j += (i32)sl;
                }
            }
        } else if (sid == 2) {
            imp_sec = b + i;
        } else if (sid == 7) {
            exp_sec = b + i;
        }
        i = end;
    }

    // the libraries it needs come first (their symbols resolve its imports)
    if (needed) {
        i32 j = 0;
        u32 cnt = uleb(needed, &j);
        for (u32 k = 0; k < cnt; k++) {
            u32 nl = uleb(needed, &j);
            if (!load_needed(path, needed + j, (i32)nl, depth)) {
                free(b);
                return 0;
            }
            j += (i32)nl;
        }
    }

    // the GOT imports in import order, and the export names
    GotImp *got = 0;
    if (imp_sec) {
        i32 j = 0;
        u32 cnt = uleb(imp_sec, &j);
        got = (GotImp *)malloc(cnt * sizeof(GotImp) + 1);
        for (u32 k = 0; k < cnt; k++) {
            u32 ml = uleb(imp_sec, &j);
            const u8 *m = imp_sec + j;
            j += (i32)ml;
            u32 fl = uleb(imp_sec, &j);
            const u8 *f = imp_sec + j;
            j += (i32)fl;
            u8 kind = imp_sec[j++];
            if (kind == 0) {
                uleb(imp_sec, &j);
            } else if (kind == 1) {
                j++;
                u32 lf = uleb(imp_sec, &j);
                uleb(imp_sec, &j);
                if (lf & 1) uleb(imp_sec, &j);
            } else if (kind == 2) {
                u32 lf = uleb(imp_sec, &j);
                uleb(imp_sec, &j);
                if (lf & 1) uleb(imp_sec, &j);
            } else if (kind == 3) {
                j += 2;  // value type (a plain one: GOT globals are i32), mutability
                if (is_gotmem(m, (i32)ml) || is8(m, (i32)ml, N_GOTFUNC)) {
                    got[nimp_got].name = f;
                    got[nimp_got].n = (i32)fl;
                    got[nimp_got].func = is8(m, (i32)ml, N_GOTFUNC);
                    nimp_got++;
                }
            } else if (kind == 4) {
                j++;
                uleb(imp_sec, &j);
            }
        }
    }
    const u8 **ename = 0;
    i32 *elen = 0;
    if (exp_sec) {
        i32 j = 0;
        u32 cnt = uleb(exp_sec, &j);
        ename = (const u8 **)malloc(cnt * sizeof(u8 *) + 1);
        elen = (i32 *)malloc(cnt * sizeof(i32) + 1);
        for (u32 k = 0; k < cnt; k++) {
            u32 nl = uleb(exp_sec, &j);
            ename[nexp] = exp_sec + j;
            elen[nexp++] = (i32)nl;
            j += (i32)nl;
            j++;
            uleb(exp_sec, &j);
        }
    }

    // memory from the main module's calloc, aligned; table slots at the end of the table
    u32 align = 1u << memalign, base = 0;
    if (memsize) {
        u32 raw = (u32)calloc(memsize + align, 1);
        base = (raw + align - 1) & ~(align - 1);
    }
    u32 tbase = table_grow(0);
    if (tsize) tbase = table_grow(tsize);

    i32 id = dl_instantiate(b, size, base, tbase);
    if (id < 0) {
        free(b), free(got), free(ename), free(elen);
        return 0;
    }

    // GOT: the module's own symbols (base + value, or a slot), else the main module's, else a module loaded
    // before (its base + value for data)
    u32 out[2];
    for (i32 g = 0; g < nimp_got; g++) {
        const u8 *nm = got[g].name;
        i32 n = got[g].n, own = 0;
        for (i32 e = 0; e < nexp && !own; e++) own = eq(ename[e], elen[e], (const char *)nm, n);
        u32 v = 0;
        if (own) {
            v = dl_sym(id, (const char *)nm, n, out);
            if (out[0] == 1) v += base;
        } else {
            v = dl_sym(0, (const char *)nm, n, out);
            for (i32 k = 0; out[0] == 0 && k < L->n; k++) {
                v = dl_sym(L->lib[k].id, (const char *)nm, n, out);
                if (out[0] == 1) v += L->lib[k].base;
            }
        }
        if (out[0]) dl_got_set(id, g, v);
    }

    u64 relocs[3], ctors[3];
    relocs[0] = 0x615f6d7361775f5full, relocs[1] = 0x7461645f796c7070ull, relocs[2] = 0x73636f6c65725f61ull;
    ctors[0] = 0x635f6d7361775f5full, ctors[1] = 0x726f74635f6c6c61ull, ctors[2] = 0x73ull;
    dl_call(id, (const char *)relocs, 24);  // __wasm_apply_data_relocs
    dl_call(id, (const char *)ctors, 17);   // __wasm_call_ctors

    Lib *x = &L->lib[L->n++];
    x->handle = 0, x->id = id, x->base = base, x->memsize = memsize, x->tbase = tbase, x->tsize = tsize;
    x->name = (char *)malloc((u32)plen + 1);
    for (i32 k = 0; k <= plen; k++) x->name[k] = path[k];
    free(b), free(got), free(ename), free(elen);
    return x;
}

EXPORT("_dlopen_js") i32 dlopen_js(u8 *handle) {
    Libs *L = libs();
    Lib *x = load_lib((const char *)(handle + 36), 0);
    if (!x) return 0;
    if (x->handle == 0) {
        x->handle = (i32)handle;
    } else if (x->handle != (i32)handle && L->n < MAXLIB) {  // another handle for the same library
        L->lib[L->n] = *x;
        L->lib[L->n].handle = (i32)handle;
        L->n++;
    }
    handle[8] = 1;
    ((u32 *)(handle + 12))[0] = x->base, ((u32 *)(handle + 12))[1] = x->memsize;
    ((u32 *)(handle + 12))[2] = x->tbase, ((u32 *)(handle + 12))[3] = x->tsize;
    return 1;
}

EXPORT("_dlsym_js") u32 dlsym_js(i32 handle, const char *sym, u32 *index) {
    Libs *L = libs();
    for (i32 k = L->n - 1; k >= 0; k--)
        if (L->lib[k].handle == handle) {
            u32 out[2], v = dl_sym(L->lib[k].id, sym, slen(sym), out);
            if (out[0] == 1) return L->lib[k].base + v;
            if (out[0] == 2) {
                *index = out[1];
                return v;
            }
            return 0;
        }
    return 0;
}

EXPORT("ffi_closure_alloc_js") u32 ffi_closure_alloc_js(u32 size, u32 *code) {
    u32 *closure = (u32 *)malloc(size);
    u32 slot = table_grow(1);  // an empty slot, as getEmptyTableSlot() of the glue
    *code = slot;
    *closure = slot;
    return (u32)closure;
}

EXPORT("ffi_closure_free_js") void ffi_closure_free_js(void *closure) { free(closure); }

// ================================================================== writing files (what installing a wheel needs)

EXPORT("__syscall_mkdirat") i32 sc_mkdirat(i32 dirfd, const char *path, i32 mode) {
    (void)mode;
    char dot[2];
    const char *p;
    i32 n, fd = resolve(dirfd, path, &p, &n, dot);
    i32 e = w_mkdir(fd, p, n);
    return e ? -e : 0;
}

EXPORT("__syscall_unlinkat") i32 sc_unlinkat(i32 dirfd, const char *path, i32 flags) {
    char dot[2];
    const char *p;
    i32 n, fd = resolve(dirfd, path, &p, &n, dot);
    i32 e = (flags & 0x200) ? w_rmdir(fd, p, n) : w_unlink(fd, p, n);  // AT_REMOVEDIR
    return e ? -e : 0;
}

EXPORT("__syscall_rmdir") i32 sc_rmdir(const char *path) { return sc_unlinkat(AT_FDCWD, path, 0x200); }

EXPORT("__syscall_renameat") i32 sc_renameat(i32 olddirfd, const char *oldpath, i32 newdirfd, const char *newpath) {
    char d1[2], d2[2];
    const char *p1, *p2;
    i32 n1, n2, f1 = resolve(olddirfd, oldpath, &p1, &n1, d1), f2 = resolve(newdirfd, newpath, &p2, &n2, d2);
    i32 e = w_rename(f1, p1, n1, f2, p2, n2);
    return e ? -e : 0;
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

EXPORT("__syscall_fallocate") i32 sc_fallocate(i32 fd, i32 mode, i64 offset, i64 len) {
    (void)mode;
    i32 e = w_fd_allocate(fd, (u64)offset, (u64)len);
    return e ? -e : 0;
}

EXPORT("__syscall_fdatasync") i32 sc_fdatasync(i32 fd) {
    i32 e = w_fd_datasync(fd);
    return e ? -e : 0;
}

// advice only: nothing to do (the answer of every libc when the kernel ignores it)
EXPORT("__syscall_fadvise64") i32 sc_fadvise64(i32 fd, i64 offset, i64 len, i32 advice) {
    (void)fd, (void)offset, (void)len, (void)advice;
    return 0;
}

EXPORT("__syscall_symlinkat") i32 sc_symlinkat(const char *target, i32 newdirfd, const char *linkpath) {
    char dot[2];
    const char *p;
    i32 n, fd = resolve(newdirfd, linkpath, &p, &n, dot);
    i32 e = w_symlink(target, slen(target), fd, p, n);  // the target is stored as it is
    return e ? -e : 0;
}

EXPORT("__syscall_linkat") i32 sc_linkat(i32 olddirfd, const char *oldpath, i32 newdirfd, const char *newpath, i32 flags) {
    char d1[2], d2[2];
    const char *p1, *p2;
    i32 n1, n2, f1 = resolve(olddirfd, oldpath, &p1, &n1, d1), f2 = resolve(newdirfd, newpath, &p2, &n2, d2);
    i32 e = w_link(f1, (flags & 0x400) ? 1 : 0, p1, n1, f2, p2, n2);  // AT_SYMLINK_FOLLOW
    return e ? -e : 0;
}

// the process runs as root of a single-user world (as Pyodide's JavaScript glue answers)
EXPORT("__syscall_getuid32_js") i32 sc_getuid(void) { return 0; }
EXPORT("__syscall_geteuid32") i32 sc_geteuid(void) { return 0; }
EXPORT("__syscall_getgid32") i32 sc_getgid(void) { return 0; }
EXPORT("__syscall_getegid32") i32 sc_getegid(void) { return 0; }
EXPORT("__syscall_umask_js") i32 sc_umask(i32 mask) { (void)mask; return 022; }  // the previous mask; WASI has none

// exit(): the process ends, with the code (Emscripten's JavaScript glue throws; here WASI says it)
EXPORT("exit") void sc_exit(i32 code) { w_proc_exit(code); }

// permissions and times: accepted and ignored (WASI preview1 has no modes; times are not needed here)
EXPORT("__syscall_utimensat") i32 sc_utimensat(i32 a, i32 b, i32 c, i32 d) { (void)a, (void)b, (void)c, (void)d; return 0; }
EXPORT("__syscall_chmod") i32 sc_chmod(i32 a, i32 b) { (void)a, (void)b; return 0; }
EXPORT("__syscall_fchmod") i32 sc_fchmod(i32 a, i32 b) { (void)a, (void)b; return 0; }
EXPORT("__syscall_fchmodat2") i32 sc_fchmodat2(i32 a, i32 b, i32 c, i32 d) { (void)a, (void)b, (void)c, (void)d; return 0; }

// ================================================================== ffi_call_js: ctypes calls, for integer/pointer signatures
// libffi's emscripten port calls through JavaScript (`wasmTable.get(fn)(...args)`); here a call_indirect with
// the type that the cif describes, for up to 8 arguments that are integers or pointers and an integer,
// pointer or void result. Anything else (floats, 64-bit, structs) traps rather than calling wrongly.
typedef struct {
    u32 size;
    u16 alignment, type;
    void *elements;
} ffi_type_t;
typedef struct {
    u32 abi, nargs;
    ffi_type_t **arg_types, *rtype;
} ffi_cif_t;

static u32 int_arg(const ffi_type_t *t, const void *p) {
    switch (t->type) {
        case 5: return *(const u8 *)p;                    // UINT8
        case 6: return (u32)(i32) * (const signed char *)p;  // SINT8
        case 7: return *(const u16 *)p;                   // UINT16
        case 8: return (u32)(i32) * (const short *)p;     // SINT16
        case 1: case 9: case 10: case 14: return *(const u32 *)p;  // INT, UINT32, SINT32, POINTER
        default: __builtin_trap();
    }
}

typedef u32 (*f0)(void);
typedef u32 (*f1)(u32);
typedef u32 (*f2)(u32, u32);
typedef u32 (*f3)(u32, u32, u32);
typedef u32 (*f4)(u32, u32, u32, u32);
typedef u32 (*f5)(u32, u32, u32, u32, u32);
typedef u32 (*f6)(u32, u32, u32, u32, u32, u32);
typedef u32 (*f7)(u32, u32, u32, u32, u32, u32, u32);
typedef u32 (*f8)(u32, u32, u32, u32, u32, u32, u32, u32);
typedef void (*v0)(void);
typedef void (*v1)(u32);
typedef void (*v2)(u32, u32);
typedef void (*v3)(u32, u32, u32);
typedef void (*v4)(u32, u32, u32, u32);
typedef void (*v5)(u32, u32, u32, u32, u32);
typedef void (*v6)(u32, u32, u32, u32, u32, u32);
typedef void (*v7)(u32, u32, u32, u32, u32, u32, u32);
typedef void (*v8)(u32, u32, u32, u32, u32, u32, u32, u32);

EXPORT("ffi_call_js") void ffi_call_js(ffi_cif_t *cif, u32 fn, void *rvalue, void **avalue) {
    u32 a[8];
    u32 n = cif->nargs;
    if (n > 8) __builtin_trap();
    for (u32 i = 0; i < 8; i++) a[i] = i < n ? int_arg(cif->arg_types[i], avalue[i]) : 0;
    u16 rt = cif->rtype->type;
    if (rt == 0) {
        switch (n) {
            case 0: ((v0)fn)(); break;
            case 1: ((v1)fn)(a[0]); break;
            case 2: ((v2)fn)(a[0], a[1]); break;
            case 3: ((v3)fn)(a[0], a[1], a[2]); break;
            case 4: ((v4)fn)(a[0], a[1], a[2], a[3]); break;
            case 5: ((v5)fn)(a[0], a[1], a[2], a[3], a[4]); break;
            case 6: ((v6)fn)(a[0], a[1], a[2], a[3], a[4], a[5]); break;
            case 7: ((v7)fn)(a[0], a[1], a[2], a[3], a[4], a[5], a[6]); break;
            default: ((v8)fn)(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]); break;
        }
        return;
    }
    if (!(rt == 1 || (rt >= 5 && rt <= 10) || rt == 14)) __builtin_trap();
    u32 r;
    switch (n) {
        case 0: r = ((f0)fn)(); break;
        case 1: r = ((f1)fn)(a[0]); break;
        case 2: r = ((f2)fn)(a[0], a[1]); break;
        case 3: r = ((f3)fn)(a[0], a[1], a[2]); break;
        case 4: r = ((f4)fn)(a[0], a[1], a[2], a[3]); break;
        case 5: r = ((f5)fn)(a[0], a[1], a[2], a[3], a[4]); break;
        case 6: r = ((f6)fn)(a[0], a[1], a[2], a[3], a[4], a[5]); break;
        case 7: r = ((f7)fn)(a[0], a[1], a[2], a[3], a[4], a[5], a[6]); break;
        default: r = ((f8)fn)(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]); break;
    }
    *(u32 *)rvalue = r;
}

// ================================================================== sockets: Emscripten's socket calls over the host's
// WASI preview1 cannot create or connect a socket, so the host gives a few operations; a socket is a guest
// descriptor SOCKBASE + slot. The main module's fd_read / fd_write / fd_close / fd_fdstat_get come here first
// (OpenSSL reads and writes its socket with read() and write()); other descriptors pass on to WASI.
#define NET(n) __attribute__((import_module("net"), import_name(n)))
NET("socket") i32 net_socket(i32 domain, i32 type, i32 proto);  // -> handle, or -errno
NET("connect") i32 net_connect(i32 h, i32 family, i32 port, const u8 *addr);
NET("send") i32 net_send(i32 h, const u8 *p, i32 n);
NET("recv") i32 net_recv(i32 h, u8 *p, i32 n, i32 peek);
NET("poll") i32 net_poll(i32 h, i32 events, i32 timeout_ms);  // -> revents
NET("close") i32 net_close(i32 h);
NET("shutdown") i32 net_shutdown(i32 h, i32 how);
NET("name") i32 net_name(i32 h, i32 peer, u8 *addr4, i32 *port);  // the local or peer IPv4 address and port
NET("resolve") i32 net_resolve(const char *name, i32 n, u8 *addr4);  // -> 0, or -errno

#define SOCKBASE 4096
#define MAXSOCK 64
typedef struct {
    i32 h[MAXSOCK];  // handle + 1; 0 is free
} Socks;
__asm__(".globaltype sock_state, i32\nsock_state:\n");
static Socks *socks(void) {
    Socks *r;
    __asm__ volatile("global.get sock_state\n\tlocal.set %0" : "=r"(r));
    if (!r) {
        r = (Socks *)calloc(1, sizeof(Socks));
        __asm__ volatile("local.get %0\n\tglobal.set sock_state" : : "r"(r));
    }
    return r;
}
static i32 is_sock(i32 fd) { return fd >= SOCKBASE && fd < SOCKBASE + MAXSOCK && socks()->h[fd - SOCKBASE]; }
static i32 hof(i32 fd) { return socks()->h[fd - SOCKBASE] - 1; }

EXPORT("__syscall_socket") i32 sc_socket(i32 domain, i32 type, i32 proto, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    Socks *S = socks();
    i32 slot = -1;
    for (i32 k = 0; k < MAXSOCK; k++)
        if (!S->h[k]) { slot = k; break; }
    if (slot < 0) return -33;  // EMFILE
    i32 h = net_socket(domain, type & ~(04000 | 02000000), proto);  // without SOCK_NONBLOCK, SOCK_CLOEXEC
    if (h < 0) return h;
    S->h[slot] = h + 1;
    return SOCKBASE + slot;
}

EXPORT("__syscall_connect") i32 sc_connect(i32 fd, const u8 *sa, i32 len, i32 a, i32 b, i32 c) {
    (void)len, (void)a, (void)b, (void)c;
    if (!is_sock(fd)) return -57;  // ENOTSOCK
    i32 family = *(const u16 *)sa, port = (sa[2] << 8) | sa[3];
    return net_connect(hof(fd), family, port, family == 10 ? sa + 8 : sa + 4);
}

EXPORT("__syscall_sendto") i32 sc_sendto(i32 fd, const u8 *p, i32 n, i32 flags, i32 addr, i32 alen) {
    (void)flags, (void)addr, (void)alen;
    if (!is_sock(fd)) return -57;
    return net_send(hof(fd), p, n);
}

EXPORT("__syscall_recvfrom") i32 sc_recvfrom(i32 fd, u8 *p, i32 n, i32 flags, i32 addr, i32 alen) {
    (void)addr, (void)alen;
    if (!is_sock(fd)) return -57;
    return net_recv(hof(fd), p, n, flags & 2);  // MSG_PEEK
}

EXPORT("__syscall_shutdown") i32 sc_shutdown(i32 fd, i32 how, i32 a, i32 b, i32 c, i32 d) {
    (void)a, (void)b, (void)c, (void)d;
    if (!is_sock(fd)) return -57;
    return net_shutdown(hof(fd), how);
}

static i32 sock_name(i32 fd, u8 *sa, u32 *lenp, i32 peer) {
    if (!is_sock(fd)) return -57;
    u8 a4[4];
    i32 port = 0, e = net_name(hof(fd), peer, a4, &port);
    if (e) return e;
    u8 tmp[16];
    for (i32 i = 0; i < 16; i++) tmp[i] = 0;
    *(u16 *)tmp = 2;  // AF_INET
    tmp[2] = (u8)(port >> 8), tmp[3] = (u8)port;
    for (i32 i = 0; i < 4; i++) tmp[4 + i] = a4[i];
    u32 n = *lenp < 16 ? *lenp : 16;
    for (u32 i = 0; i < n; i++) sa[i] = tmp[i];
    *lenp = 16;
    return 0;
}
EXPORT("__syscall_getpeername") i32 sc_getpeername(i32 fd, u8 *sa, u32 *lenp, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    return sock_name(fd, sa, lenp, 1);
}
EXPORT("__syscall_getsockname") i32 sc_getsockname(i32 fd, u8 *sa, u32 *lenp, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    return sock_name(fd, sa, lenp, 0);
}

EXPORT("__syscall_getsockopt") i32 sc_getsockopt(i32 fd, i32 level, i32 opt, i32 *val, u32 *lenp, i32 a) {
    (void)a;
    if (!is_sock(fd)) return -57;
    // SO_TYPE: a stream (ssl checks it; the host's sockets here are TCP); SO_ERROR and the rest: 0 (connect blocks)
    if (val && lenp && *lenp >= 4) *val = (level == 1 && opt == 3) ? 1 : 0, *lenp = 4;
    return 0;
}

// struct pollfd {int fd; short events, revents;}: sockets ask the host, other descriptors are ready
static i32 do_poll(u8 *fds, i32 n, i32 timeout) {
    i32 ready = 0, socks_n = 0;
    for (i32 k = 0; k < n; k++)
        if (is_sock(*(i32 *)(fds + 8 * k))) socks_n++;
    for (i32 k = 0; k < n; k++) {
        i32 fd = *(i32 *)(fds + 8 * k);
        i16 ev = *(i16 *)(fds + 8 * k + 4), rev;
        if (is_sock(fd)) rev = (i16)net_poll(hof(fd), ev, socks_n == 1 ? timeout : 0);
        else rev = fd >= 0 ? (i16)(ev & 5) : 0;  // POLLIN | POLLOUT
        *(i16 *)(fds + 8 * k + 6) = rev;
        if (rev) ready++;
    }
    return ready;
}
EXPORT("__syscall_poll") i32 sc_poll(u8 *fds, i32 n, i32 timeout) { return do_poll(fds, n, timeout); }
EXPORT("__syscall_poll_nonblocking") i32 sc_poll_nb(u8 *fds, i32 n) { return do_poll(fds, n, 0); }

// DNS: one IPv4 address, as Emscripten's own getaddrinfo (a single addrinfo; freeaddrinfo frees ai_addr and ai)
EXPORT("_emscripten_lookup_name") u32 lookup_name(const char *name) {
    u8 a[4];
    if (net_resolve(name, slen(name), a)) return 0;
    return (u32)a[0] | ((u32)a[1] << 8) | ((u32)a[2] << 16) | ((u32)a[3] << 24);
}

EXPORT("getaddrinfo") i32 getaddrinfo_(const char *node, const char *service, const i32 *hint, u32 *out) {
    u8 a[4] = {0, 0, 0, 0};
    i32 flags = hint ? hint[0] : 0, family = hint ? hint[1] : 0, type = hint ? hint[2] : 0, proto = hint ? hint[3] : 0;
    if (family != 0 && family != 2) return -6;  // EAI_FAMILY: IPv4 only
    if (node) {
        if (net_resolve(node, slen(node), a)) return -2;  // EAI_NONAME
    } else if (!(flags & 1)) {                            // not AI_PASSIVE: the loopback address
        a[0] = 127, a[3] = 1;
    }
    i32 port = 0;
    if (service) {
        for (const char *p = service; *p; p++) {
            if (*p < '0' || *p > '9') return -8;  // EAI_SERVICE: numeric ports only
            port = port * 10 + (*p - '0');
        }
    }
    u8 *sa = (u8 *)calloc(1, 16);
    i32 *ai = (i32 *)calloc(1, 32);
    *(u16 *)sa = 2, sa[2] = (u8)(port >> 8), sa[3] = (u8)port;
    for (i32 i = 0; i < 4; i++) sa[4 + i] = a[i];
    ai[0] = flags, ai[1] = 2, ai[2] = type ? type : 1, ai[3] = proto;
    ai[4] = 16, ai[5] = (i32)sa, ai[6] = 0, ai[7] = 0;
    *out = (u32)ai;
    return 0;
}

EXPORT("getnameinfo") i32 getnameinfo_(i32 a, i32 b, i32 c, i32 d, i32 e, i32 f, i32 g) {
    (void)a, (void)b, (void)c, (void)d, (void)e, (void)f, (void)g;
    return -4;  // EAI_FAIL
}

// the main module's WASI calls, for socket descriptors
EXPORT("fd_read") i32 x_fd_read(i32 fd, const u32 *iov, i32 n, i32 *nread) {
    if (!is_sock(fd)) return w_fd_read(fd, iov, n, nread);
    i32 tot = 0;
    for (i32 k = 0; k < n; k++) {
        i32 r = net_recv(hof(fd), (u8 *)iov[2 * k], (i32)iov[2 * k + 1], 0);
        if (r < 0) {
            if (tot) break;
            return -r;
        }
        tot += r;
        if (r < (i32)iov[2 * k + 1]) break;
    }
    *nread = tot;
    return 0;
}

WASI("fd_write") i32 w_fd_write(i32 fd, const void *iovs, i32 n, i32 *nwritten);
EXPORT("fd_write") i32 x_fd_write(i32 fd, const u32 *iov, i32 n, i32 *nw) {
    if (!is_sock(fd)) return w_fd_write(fd, iov, n, nw);
    i32 tot = 0;
    for (i32 k = 0; k < n; k++) {
        i32 r = net_send(hof(fd), (const u8 *)iov[2 * k], (i32)iov[2 * k + 1]);
        if (r < 0) {
            if (tot) break;
            return -r;
        }
        tot += r;
    }
    *nw = tot;
    return 0;
}

EXPORT("fd_close") i32 x_fd_close(i32 fd) {
    if (!is_sock(fd)) return w_fd_close(fd);
    net_close(hof(fd));
    socks()->h[fd - SOCKBASE] = 0;
    return 0;
}

WASI("fd_fdstat_get") i32 w_fd_fdstat_get(i32 fd, void *buf);
EXPORT("fd_fdstat_get") i32 x_fd_fdstat_get(i32 fd, u8 *buf) {
    if (!is_sock(fd)) return w_fd_fdstat_get(fd, buf);
    for (i32 i = 0; i < 24; i++) buf[i] = 0;
    buf[0] = 6;  // SOCKET_STREAM
    *(u64 *)(buf + 8) = (1ull << 30) - 1, *(u64 *)(buf + 16) = (1ull << 30) - 1;
    return 0;
}

// ================================================================== time: Emscripten's JavaScript date helpers, in UTC
// (OpenSSL checks certificate dates through gmtime/timegm; with the stubs every date was a format error).
// struct tm: sec, min, hour, mday, mon, year, wday, yday, isdst (i32 each), gmtoff (long), zone.
static i64 days_from_civil(i64 y, i64 m, i64 d) {  // proleptic Gregorian, H. Hinnant's algorithm
    y -= m <= 2;
    i64 era = (y >= 0 ? y : y - 399) / 400;
    i64 yoe = y - era * 400;
    i64 doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
    i64 doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097 + doe - 719468;
}

static void fill_tm(i64 t, i32 *tm) {
    i64 days = t >= 0 ? t / 86400 : -((-t + 86399) / 86400);
    i64 secs = t - days * 86400;
    tm[0] = (i32)(secs % 60), tm[1] = (i32)(secs / 60 % 60), tm[2] = (i32)(secs / 3600);
    i64 z = days + 719468;
    i64 era = (z >= 0 ? z : z - 146096) / 146097;
    i64 doe = z - era * 146097;
    i64 yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    i64 y = yoe + era * 400, doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    i64 mp = (5 * doy + 2) / 153, d = doy - (153 * mp + 2) / 5 + 1, m = mp + (mp < 10 ? 3 : -9);
    y += m <= 2;
    tm[3] = (i32)d, tm[4] = (i32)(m - 1), tm[5] = (i32)(y - 1900);
    i64 w = (days + 4) % 7;  // 1970-01-01 was a Thursday
    tm[6] = (i32)(w < 0 ? w + 7 : w);
    tm[7] = (i32)(days - days_from_civil(y, 1, 1));
}

EXPORT("_gmtime_js") i32 gmtime_js(i64 t, i32 *tm) {
    fill_tm(t, tm);
    return 0;
}

EXPORT("_localtime_js") i32 localtime_js(i64 t, i32 *tm) {
    fill_tm(t, tm);
    tm[8] = 0, tm[9] = 0;  // no DST, UTC
    return 0;
}

static i64 tm_to_time(i32 *tm) {
    i64 y = (i64)tm[5] + 1900, mon = tm[4];
    y += mon >= 0 ? mon / 12 : -((11 - mon) / 12);
    mon = ((mon % 12) + 12) % 12;
    i64 t = days_from_civil(y, mon + 1, 1) * 86400 + ((i64)tm[3] - 1) * 86400 + (i64)tm[2] * 3600 + (i64)tm[1] * 60 + tm[0];
    fill_tm(t, tm);
    return t;
}
EXPORT("_timegm_js") i64 timegm_js(i32 *tm) { return tm_to_time(tm); }
EXPORT("_mktime_js") i64 mktime_js(i32 *tm) {
    i64 t = tm_to_time(tm);
    tm[8] = 0;
    return t;
}

EXPORT("_tzset_js") void tzset_js(i32 *timezone, i32 *daylight, char *std_name, char *dst_name) {
    *timezone = 0, *daylight = 0;
    std_name[0] = 'U', std_name[1] = 'T', std_name[2] = 'C', std_name[3] = 0;
    dst_name[0] = 'U', dst_name[1] = 'T', dst_name[2] = 'C', dst_name[3] = 0;
}
