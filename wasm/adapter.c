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
WASI("fd_tell") i32 w_fd_tell(i32 fd, u64 *offset);
WASI("fd_seek") i32 w_fd_seek(i32 fd, i64 offset, i32 whence, u64 *newoffset);
WASI("fd_renumber") i32 w_fd_renumber(i32 from, i32 to);
WASI("fd_datasync") i32 w_fd_datasync(i32 fd);
WASI("proc_exit") __attribute__((noreturn)) void w_proc_exit(i32 code);

// the main module's allocator (resolved from its exports, like any side module's import)
void *malloc(u32 n);
void *calloc(u32 n, u32 size);
void free(void *p);

// The loader's host interface: the only things a wasm module cannot do itself (the host keeps the instances
// and their exports by name). id 0 is the main module (in the dynamic build with this adapter's exports).
#define LOADER(n) __attribute__((import_module("loader"), import_name(n)))
// compile and instantiate the module in [p, p+n) with the main module's memory, table, stack pointer and tags,
// __memory_base = mb, __table_base = tb; `env` functions by name (see the host: the main module, the RTLD_GLOBAL
// libraries, then the dlopen call's scope `scope` and the module's own exports); every GOT.mem/GOT.func import a
// new mutable i32 global = 0, numbered in import order. -> id > 0, or < 0 (the reason is kept for loader.error 11)
LOADER("instantiate") i32 dl_instantiate(const u8 *p, i32 n, u32 mb, u32 tb, u32 scope);
// the module is loaded: its exports join the global namespace (scope 0) or the scope of one dlopen call
LOADER("scope") void dl_scope(i32 id, u32 scope);
LOADER("got_set") void dl_got_set(i32 id, i32 index, u32 value);
// export `name` of module id: a global -> its value, kind 1; a function -> a table slot, kind 2 (the slot it
// already had in the table) or 3 (a new one); absent -> kind 0. out[0] = kind, out[1] = the export's index (kind 3).
LOADER("sym") u32 dl_sym(i32 id, const char *name, i32 n, u32 *out);
// call export `name` (no arguments, no results) if it exists -> 1, else 0
LOADER("call") i32 dl_call(i32 id, const char *name, i32 n);
// set dlerror's text: the failure `code` (see the loader section), the file/library name and one argument
LOADER("error") void dl_error(u32 code, const char *name, i32 nn, const char *arg, i32 an);
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
static i32 sock_nb(i32 fd);
static void sock_set_nb(i32 fd, i32 on);

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

// ---- the current directory (chdir): kept as an absolute path in one malloc'd block, its address in a wasm global.
// A relative path against AT_FDCWD is joined to it into one of two buffers (rename and link resolve two at once).
#define PATHMAX 1024
typedef struct {
    char cwd[PATHMAX];
    char buf[2][PATHMAX];
    i32 flip;
} Cwd;
__asm__(".globaltype cwd_state, i32\ncwd_state:\n");
static Cwd *cwdst(void) {
    Cwd *r;
    __asm__ volatile("global.get cwd_state\n\tlocal.set %0" : "=r"(r));
    if (!r) {
        r = (Cwd *)calloc(1, sizeof(Cwd));
        r->cwd[0] = '/';
        __asm__ volatile("local.get %0\n\tglobal.set cwd_state" : : "r"(r));
    }
    return r;
}

// ---- the open files: the absolute guest path and the open flags of each descriptor opened by openat, so that dup()
// (which WASI 0.1 lacks) can open the same file again: a directory (fdopendir, fwalk, rmtree) or a file. Standard
// streams, sockets and pipes have no path: they are not duplicated.
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
    if (fd >= 0 && fd < MAXFD && fds()->path[fd]) return fds()->path[fd];
    Pre *P = preopens();
    for (i32 k = 0; k < P->n; k++)
        if (P->fd[k] == fd) return P->name[k];
    return 0;
}
// dirfd + path -> an absolute guest path in out (PATHMAX bytes); 0 if it can not be made
static i32 abs_path(i32 dirfd, const char *path, char *out) {
    const char *base = 0;
    if (path[0] != '/') {
        base = dirfd == AT_FDCWD ? cwdst()->cwd : fd_base_path(dirfd);
        if (!base) return 0;
    }
    i32 k = 0;
    if (base) {
        for (const char *q = base; *q; q++) {
            if (k >= PATHMAX - 2) return 0;
            out[k++] = *q;
        }
        if (k == 0 || out[k - 1] != '/') out[k++] = '/';
    }
    for (const char *q = path; *q; q++) {
        if (k >= PATHMAX - 1) return 0;
        out[k++] = *q;
    }
    out[k] = 0;
    return 1;
}
static void fd_forget(i32 fd) {
    if (fd >= 0 && fd < MAXFD && fds()->path[fd]) {
        free(fds()->path[fd]);
        fds()->path[fd] = 0;
    }
}

// A guest path and dirfd -> (WASI fd, path pointer, length). An empty result is ".". The cwd is kept by chdir (the root at first).
static i32 resolve(i32 dirfd, const char *path, const char **out, i32 *len, char *dot) {
    i32 fd = dirfd;
    if (path[0] != '/' && dirfd == AT_FDCWD) {  // relative to the cwd: make it absolute
        Cwd *C = cwdst();
        if (!(C->cwd[0] == '/' && C->cwd[1] == 0)) {
            char *o = C->buf[C->flip];
            i32 k = 0, ok = 1;
            for (const char *q = C->cwd; *q; q++) {
                if (k >= PATHMAX - 2) { ok = 0; break; }
                o[k++] = *q;
            }
            if (ok) {
                o[k++] = '/';
                for (const char *q = path; *q; q++) {
                    if (k >= PATHMAX - 1) { ok = 0; break; }
                    o[k++] = *q;
                }
            }
            if (ok) {
                o[k] = 0;
                C->flip ^= 1;
                path = o;
            }
        }
    }
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
    Cwd *C = cwdst();
    i32 n = slen(C->cwd);
    if (n + 1 > size) return -ERANGE;
    for (i32 k = 0; k <= n; k++) buf[k] = C->cwd[k];
    return n + 1;
}

// chdir: the absolute path, lexically normalized ('.' and '..'), must name a directory
EXPORT("__syscall_chdir") i32 sc_chdir(const char *path) {
    Cwd *C = cwdst();
    char full[PATHMAX], out[PATHMAX];
    i32 k = 0;
    if (path[0] != '/') {
        for (const char *q = C->cwd; *q; q++) {
            if (k >= PATHMAX - 2) return -36;  // ENAMETOOLONG
            full[k++] = *q;
        }
        full[k++] = '/';
    }
    for (const char *q = path; *q; q++) {
        if (k >= PATHMAX - 1) return -36;
        full[k++] = *q;
    }
    full[k] = 0;
    i32 len = 1;
    out[0] = '/';
    for (i32 i = 0; full[i];) {
        while (full[i] == '/') i++;
        i32 st = i;
        while (full[i] && full[i] != '/') i++;
        i32 cl = i - st;
        if (cl == 0 || (cl == 1 && full[st] == '.')) continue;
        if (cl == 2 && full[st] == '.' && full[st + 1] == '.') {
            while (len > 1 && out[len - 1] != '/') len--;
            if (len > 1) len--;  // drop the '/' before it
            continue;
        }
        if (len + cl + 1 >= PATHMAX) return -36;
        if (len > 1) out[len++] = '/';
        for (i32 j = 0; j < cl; j++) out[len++] = full[st + j];
    }
    out[len] = 0;
    u64 fs[8];
    char dot[2];
    const char *p;
    i32 n, fd = resolve(AT_FDCWD, out, &p, &n, dot);
    i32 e = w_path_filestat_get(fd, 1, p, n, fs);
    if (e) return -e;
    if (*((u8 *)fs + 16) != 3) return -54;  // ENOTDIR: the filetype is not "directory"
    for (i32 j = 0; j <= len; j++) C->cwd[j] = out[j];
    return 0;
}

EXPORT("__syscall_fchdir") i32 sc_fchdir(i32 fd) {
    const char *p = fd_base_path(fd);  // a directory opened by openat, or a preopen
    return p ? sc_chdir(p) : -EBADF;
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
    if (out >= 0 && out < MAXFD) {
        cookies()[out] = 0;  // a new descriptor lists its directory from the start
        char ap[PATHMAX];
        fd_forget(out);
        if (abs_path(dirfd, path, ap)) {
            i32 n2 = slen(ap) + 1;
            char *copy = (char *)malloc(n2);
            for (i32 j = 0; j < n2; j++) copy[j] = ap[j];
            fds()->path[out] = copy;
            fds()->flags[out] = flags;
        }
    }
    return out;
}

// dup(): the same file opened again, at the same position (a copy of it: WASI 0.1 can not share the offset)
EXPORT("__syscall_dup") i32 sc_dup(i32 fd) {
    if (fd < 0 || fd >= MAXFD || !fds()->path[fd]) return -52;  // ENOSYS: a stream, a socket or a pipe
    i32 flags = fds()->flags[fd] & ~(0100 | 0200 | 01000);       // not O_CREAT, O_EXCL, O_TRUNC again
    char ap[PATHMAX];
    i32 n = slen(fds()->path[fd]);
    for (i32 j = 0; j <= n; j++) ap[j] = fds()->path[fd][j];
    i32 nfd = sc_openat(AT_FDCWD, ap, flags, 0);
    if (nfd < 0) return nfd;
    u64 pos = 0;
    if (!(flags & 0200000) && !w_fd_tell(fd, &pos)) w_fd_seek(nfd, (i64)pos, 0, &pos);
    return nfd;
}

EXPORT("__syscall_dup3") i32 sc_dup3(i32 oldfd, i32 newfd, i32 flags) {
    (void)flags;
    if (oldfd == newfd) return -28;  // EINVAL
    i32 d = sc_dup(oldfd);
    if (d < 0) return d;
    i32 e = w_fd_renumber(d, newfd);  // closes newfd
    if (e) {
        w_fd_close(d);
        fd_forget(d);
        return -e;
    }
    fd_forget(newfd);
    if (d < MAXFD && newfd >= 0 && newfd < MAXFD) {  // the record follows the number
        fds()->path[newfd] = fds()->path[d];
        fds()->flags[newfd] = fds()->flags[d];
        fds()->path[d] = 0;
    }
    return newfd;
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
    if (is_sock(fd) && op == 0x5421) {  // FIONBIO
        const i32 *argp = va ? *(const i32 **)va : 0;  // va points at the variable arguments; the first is &flag
        sock_set_nb(fd, argp && *argp != 0);
        return 0;
    }
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
            if (is_sock(fd)) return 2 | (sock_nb(fd) ? 04000 : 0);  // O_RDWR, O_NONBLOCK
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
            if (is_sock(fd)) {
                sock_set_nb(fd, (*(const i32 *)va & 04000) != 0);  // va points at the variable arguments
                return 0;
            }
            i32 flags = *(const i32 *)va, ff = 0;  // va points at the variable arguments
            if (flags & 02000) ff |= 1;
            if (flags & 04000) ff |= 4;
            i32 e = w_fd_fdstat_set_flags(fd, ff);
            return e ? -e : 0;
        }
        case 6:  // F_SETLK
        case 7:  // F_SETLKW: one process, so a lock is always granted
            return 0;
        case 0:     // F_DUPFD (the minimum number is not honoured)
        case 1030:  // F_DUPFD_CLOEXEC
            return sc_dup(fd);
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

static void vec_push(Vec *a, void *x) {
    if (a->n == a->cap) {
        i32 cap = a->cap ? a->cap * 2 : 16;
        void **nv = (void **)malloc((u32)cap * sizeof(void *));
        for (i32 i = 0; i < a->n; i++) nv[i] = a->v[i];
        free(a->v);
        a->v = nv, a->cap = cap;
    }
    a->v[a->n++] = x;
}

typedef struct {
    i32 id;  // the host's instance, -1 while it loads
    u32 base, memsize, tbase, tsize;
    char *name;  // the normalized path
    i32 global, ready;
} Lib;
typedef struct {
    i32 handle;
    Lib *lib;
} Hnd;
typedef struct {
    Vec libs;  // Lib *, in load order
    Vec hnds;  // Hnd *: dlopen handle -> library (the latest dlopen of a handle wins)
    u32 scopes;  // dlopen calls so far: the number of a call's scope
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

// read a whole file into malloc'd memory -> 0, or 1 (no such file) or 8 (cannot be read: a directory, no access)
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

// PATH.normalize of the glue: the key of a library ("a//b/../c.so" -> "a/c.so"); malloc'd
static char *norm_path(const char *s) {
    i32 n = slen(s), abs = n > 0 && s[0] == '/', trail = n > 0 && s[n - 1] == '/', len = 0, i = 0;
    char *o = (char *)malloc((u32)n + 4);
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
    i32 k = 0;
    if (abs) r[k++] = '/';
    for (i32 j = 0; j < len; j++) r[k++] = o[j];
    if (len == 0 && !abs) r[k++] = '.';
    if (len > 0 && trail) r[k++] = '/';
    r[k] = 0;
    free(o);
    return r;
}

static i32 base_eq(const char *a, const char *b) {  // equal file names (the part after the last '/')
    const char *x = a, *y = b;
    for (const char *p = a; *p; p++) if (*p == '/') x = p + 1;
    for (const char *p = b; *p; p++) if (*p == '/') y = p + 1;
    return eq((const u8 *)x, slen(x), y, slen(y));
}

// the loader.error codes (the host words them):
//  1 no such file (arg: the name)       2 no wasm magic number            3 dylink.0 is not the first section
//  4 the first section is not dylink.0  5 a length that is not a multiple of 4 (the glue's Uint32Array)
//  6 truncated or malformed             7 undefined symbol (arg)          8 cannot be read
//  9 out of memory or table            10 NEEDED libraries nested too deep  11 the engine's own reason
//  12 dlsym: unknown symbol (arg) in the library (name; no name: the main module)     +256: from emscripten_dlopen
#define MAXDEPTH 512
static Lib *fail(Libs *L, u32 code, const u8 *arg, i32 n) {
    free(L->arg);
    L->code = code, L->arg = 0, L->argn = 0;
    if (arg) {
        L->arg = (char *)malloc((u32)n + 1);
        for (i32 i = 0; i < n; i++) L->arg[i] = (char)arg[i];
        L->arg[n] = 0, L->argn = n;
    }
    return 0;
}

typedef struct {  // what dylink.0 says
    u32 memsize, memalign, tsize;
    u32 needed, needed_end;  // the NEEDED subsection's payload (0: none)
    u32 weak, weak_end;      // the import-info subsection's payload
    u32 rpath, rpath_end;    // the runtime-path subsection's payload
    u32 next;                // where the sections after dylink.0 begin
} Meta;

// The glue's getDylinkMetadata, with its checks and its words, and every offset checked against the file's size.
// -> 0, or the loader.error code
static u32 parse_dylink(const u8 *b, u32 size, Meta *m) {
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

static i32 is_weak(const u8 *b, const Meta *m, const u8 *nm, i32 n) {
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

// the module's runtime paths as one "a:b" string, $ORIGIN replaced by the module's folder; malloc'd
static char *runtime_paths(const u8 *b, const Meta *m, const char *path) {
    i32 dl = 0;
    for (i32 i = 0; path[i]; i++) if (path[i] == '/') dl = i;
    char *out = (char *)malloc(1);
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

// a NEEDED library: already loaded (by file name), or next to the module that needs it, or in /lib
static Lib *load_needed(Libs *L, const char *from, const char *rpath, const u8 *name, i32 n, i32 global, u32 scope,
                        i32 depth) {
    char *nm = (char *)malloc((u32)n + 1);
    for (i32 i = 0; i < n; i++) nm[i] = (char)name[i];
    nm[n] = 0;
    Lib *x = 0;
    for (i32 k = 0; k < L->libs.n && !x; k++)
        if (base_eq(((Lib *)L->libs.v[k])->name, nm)) x = (Lib *)L->libs.v[k];
    if (x) {
        free(nm);
        return load_lib(L, x->name, global, scope, depth + 1, 0);  // joins the scope, or the global namespace
    }
    if (nm[0] != '/') {  // the glue's search first; what it finds is the library
        char *buf = (char *)malloc(512);
        char *found = _emscripten_find_dylib(buf, rpath, nm, 512);
        if (found) {
            char *q = norm_path(found);
            x = load_lib(L, q, global, scope, depth + 1, 0);
            free(q);
        }
        free(buf);
        if (x || (found && L->code != 1)) {
            free(nm);
            return x;
        }
    }
    // and beyond it, where wheels put their libraries: next to the module that needs it, then /lib
    i32 dl = 0;
    for (i32 i = 0; from[i]; i++) if (from[i] == '/') dl = i + 1;
    if (nm[0] == '/') dl = 0;  // an absolute name is used as it is
    char *p = (char *)malloc((u32)(dl + n + 8));
    for (i32 i = 0; i < dl; i++) p[i] = from[i];
    for (i32 i = 0; i <= n; i++) p[dl + i] = nm[i];
    char *q = norm_path(p);
    x = load_lib(L, q, global, scope, depth + 1, 0);
    free(q);
    if (!x && L->code == 1) {  // /lib/<name>
        p[0] = '/', p[1] = 'l', p[2] = 'i', p[3] = 'b', p[4] = '/';
        for (i32 i = 0; i <= n; i++) p[5 + i] = nm[i];
        x = load_lib(L, p, global, scope, depth + 1, 0);
        if (!x && L->code == 1) fail(L, 1, name, n);  // the glue names the NEEDED library, as it was written
    }
    free(p), free(nm);
    return x;
}

static void lib_drop(Libs *L, Lib *x) {
    i32 j = 0;
    for (i32 k = 0; k < L->libs.n; k++) if (L->libs.v[k] != x) L->libs.v[j++] = L->libs.v[k];
    L->libs.n = j;
    free(x->name), free(x);
}

// a symbol of module `id` as the GOT wants it: a data address (base added) or a table slot; out[0] = 0: none
static u32 sym_of(i32 id, u32 base, const u8 *nm, i32 n, u32 *out) {
    u32 v = dl_sym(id, (const char *)nm, n, out);
    if (out[0] == 1) v += base;
    return v;
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
            if (x->ready) dl_scope(x->id, 0);
        }
        return x;
    }
    if (depth > MAXDEPTH) return fail(L, 10, 0, 0);

    u8 *b = 0;
    i32 size = 0, own = 1;
    u32 hd = handle ? ((const u32 *)(handle + 28))[0] : 0, hs = handle ? ((const u32 *)(handle + 32))[0] : 0;
    if (hd && hs) {  // the bytes were handed over with the handle
        b = (u8 *)hd, size = (i32)hs, own = 0;
    } else {
        i32 e = read_file(path, &b, &size);
        if (e) return fail(L, (u32)e, (const u8 *)path, plen);
    }
    Meta m;
    u32 code = parse_dylink(b, (u32)size, &m);
    if (code) {
        if (own) free(b);
        return fail(L, code, 0, 0);
    }

    Lib *x = (Lib *)calloc(1, sizeof(Lib));  // registered before its NEEDED libraries load: a cycle finds it
    x->id = -1, x->global = global;
    x->name = (char *)malloc((u32)plen + 1);
    for (i32 k = 0; k <= plen; k++) x->name[k] = path[k];
    vec_push(&L->libs, x);

    // the libraries it needs come first (their symbols resolve its imports)
    GotImp *got = 0;
    i32 nimp_got = 0;
    u32 base = 0, tbase = 0;
    char *rpath = 0;
    if (m.needed) {
        rpath = runtime_paths(b, &m, path);
        Rd r = {b, m.needed, m.needed_end, 0};
        u32 cnt = rd_leb(&r);
        for (u32 k = 0; k < cnt && !r.bad; k++) {
            u32 nl;
            const u8 *nn = rd_name(&r, &nl);
            if (r.bad) break;
            if (!load_needed(L, path, rpath, nn, (i32)nl, global, scope, depth)) goto failed;
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
        u32 out[2], v = sym_of(0, 0, nm, n, out);
        for (i32 k = 0; out[0] == 0 && k < L->libs.n; k++) {
            Lib *o = (Lib *)L->libs.v[k];
            if (o->ready) v = sym_of(o->id, o->base, nm, n, out);
        }
        if (out[0] == 0) v = sym_of(id, base, nm, n, out);
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
    if (x->global) dl_scope(id, 0);
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
    char *name = norm_path((const char *)(handle + 36));
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
        h->handle = (i32)handle;
        vec_push(&L->hnds, h);
    }
    h->lib = x;
    handle[8] = 1;
    ((u32 *)(handle + 12))[0] = x->base, ((u32 *)(handle + 12))[1] = x->memsize;
    ((u32 *)(handle + 12))[2] = x->tbase, ((u32 *)(handle + 12))[3] = x->tsize;
    return 1;
}

EXPORT("_dlopen_js") i32 dlopen_js(u8 *handle) { return dl_open(handle, 0); }

// emscripten_dlopen: the glue loads asynchronously and calls back from a promise; here the load is done at once
// and the callback follows (a callback is a table index: onsuccess(handle, user_data) or onerror(handle, user_data))
EXPORT("_emscripten_dlopen_js") void emscripten_dlopen_js(u8 *handle, u32 onsuccess, u32 onerror, u32 user_data) {
    u32 cb = dl_open(handle, 1) ? onsuccess : onerror;
    if (cb) ((void (*)(u32, u32))cb)((u32)handle, user_data);
}

EXPORT("_dlsym_js") u32 dlsym_js(i32 handle, const char *sym, u32 *index) {
    Libs *L = libs();
    Lib *lib = 0;
    for (i32 k = L->hnds.n - 1; k >= 0 && !lib; k--)
        if (((Hnd *)L->hnds.v[k])->handle == handle) lib = ((Hnd *)L->hnds.v[k])->lib;
    u32 out[2] = {0, 0}, v = 0;
    i32 n = slen(sym);
    if (lib) {
        v = sym_of(lib->id, lib->base, (const u8 *)sym, n, out);
    } else {  // not a library loaded by dlopen: the main module (dlopen(NULL), RTLD_DEFAULT), then the RTLD_GLOBAL libraries
        v = sym_of(0, 0, (const u8 *)sym, n, out);
        for (i32 k = 0; out[0] == 0 && k < L->libs.n; k++) {
            Lib *o = (Lib *)L->libs.v[k];
            if (o->ready && o->global) v = sym_of(o->id, o->base, (const u8 *)sym, n, out);
        }
    }
    if (out[0] == 0) {
        dl_error(12, lib ? lib->name : 0, lib ? slen(lib->name) : 0, sym, n);
        return 0;
    }
    if (out[0] == 3) *index = out[1];
    return v;
}

// ================================================================== mmap of a file: _mmap_js / _munmap_js / _msync_js
// What the glue does for a file (NODEFS): the bytes are copied into the heap, a block of whole 64 KiB pages from the
// main module's memalign (zeroed past the end of the file), and a shared writable mapping is written back with
// pwrite on msync and munmap. A private mapping never writes back. The copy is not live: a write(2) to the file
// after the mmap is not seen through it (and the other way round, until msync). Anonymous mappings are the libc's.
// The write-back stops at the end of the file as it is then (the glue would extend the file with zeros).
// A shared writable mapping keeps a descriptor of its own (a dup, as POSIX lets the mapping outlive the descriptor
// it was made from; the glue looks the descriptor up again at msync and munmap and fails with EBADF when it was closed).
WASI("fd_pread") i32 w_fd_pread(i32 fd, const void *iovs, i32 n, u64 offset, i32 *nread);
WASI("fd_pwrite") i32 w_fd_pwrite(i32 fd, const void *iovs, i32 n, u64 offset, i32 *nwritten);
void *emscripten_builtin_memalign(u32 align, u32 size);
i32 x_fd_fdstat_get(i32 fd, u8 *buf);
i32 x_fd_close(i32 fd);
#define PROT_WRITE 2
#define MAP_PRIVATE 2
#define MM_CHUNK (8u << 20)

typedef struct {
    u32 addr;
    i32 fd;  // the mapping's own descriptor, -1 when it could not be made (the caller's is used then)
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
static i32 mm_file(i32 fd, u64 *rights) {
    u8 st[24] __attribute__((aligned(8)));
    i32 e = x_fd_fdstat_get(fd, st);
    if (e) return -e;
    if (rights) *rights = *(u64 *)(st + 8);
    return st[0] == 4 ? 0 : -43;  // ENODEV
}

EXPORT("_mmap_js") i32 mmap_js(u32 len, i32 prot, i32 flags, i32 fd, i64 offset, i32 *allocated, u32 *addr) {
    u64 rights = 0;
    u8 st[24] __attribute__((aligned(8)));
    i32 e = x_fd_fdstat_get(fd, st);
    if (e) return -e;  // EBADF
    rights = *(u64 *)(st + 8);
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
        e = w_fd_pread(fd, iov, 1, (u64)offset + got, &r);
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
        m->addr = (u32)ptr, m->fd = sc_dup(fd);
        if (m->fd < 0) m->fd = -1;
        vec_push(maps(), m);
    }
    *allocated = 1, *addr = (u32)ptr;
    return 0;
}

// the bytes of a shared writable mapping back to the file (up to its present end)
static i32 mm_write_back(u32 addr, u32 len, i32 fd, i64 offset) {
    u64 fs[8];
    i32 e = w_fd_filestat_get(fd, fs);
    if (e) return -e;
    if (offset < 0 || (u64)offset >= fs[4]) return 0;
    u64 left = fs[4] - (u64)offset;
    u32 n = left < len ? (u32)left : len, done = 0;
    while (done < n) {
        u32 iov[2];
        iov[0] = addr + done, iov[1] = n - done < MM_CHUNK ? n - done : MM_CHUNK;
        i32 w = 0;
        e = w_fd_pwrite(fd, iov, 1, (u64)offset + done, &w);
        if (e) return -e;
        if (w == 0) return -29;  // EIO
        done += (u32)w;
    }
    return 0;
}

EXPORT("_msync_js") i32 msync_js(u32 addr, u32 len, i32 prot, i32 flags, i32 fd, i64 offset) {
    if (offset < 0) return -28;
    Map *m = map_find(addr, 0);
    if (m && m->fd >= 0) fd = m->fd;
    i32 e = mm_file(fd, 0);
    if (e) return e;
    if ((flags & MAP_PRIVATE) || !(prot & PROT_WRITE)) return 0;  // nothing was changed that the file should get
    return mm_write_back(addr, len, fd, offset);
}

EXPORT("_munmap_js") i32 munmap_js(u32 addr, u32 len, i32 prot, i32 flags, i32 fd, i64 offset) {
    if (!(prot & PROT_WRITE) || (flags & MAP_PRIVATE)) return 0;
    i32 e = msync_js(addr, len, prot, flags, fd, offset);
    Map *m = map_find(addr, 1);
    if (m) {
        if (m->fd >= 0) x_fd_close(m->fd);
        free(m);
    }
    return e;
}

// ================================================================== emscripten_log: _emscripten_log_formatted / emscripten_log_impl_js
// The glue prints with console.error / warn / info / debug / log, which Node sends to stderr (error, warn) or stdout
// (the others), and with err / out for the flags that do not ask for the console. All of them are one line:
// error and warn go to stderr, everything else to stdout. The call stack that EM_LOG_C_STACK / EM_LOG_JS_STACK ask
// for is JavaScript's (new Error().stack): there is none here, the message is printed without it.
WASI("fd_write") i32 w_fd_write(i32 fd, const void *iovs, i32 n, i32 *nwritten);
static void write_all(i32 fd, const char *s, i32 n) {  // WASI may write less than asked: again until it is all out
    while (n > 0) {
        u32 iov[2];
        iov[0] = (u32)s, iov[1] = (u32)n;
        i32 w = 0;
        if (w_fd_write(fd, iov, 1, &w) || w <= 0) return;
        s += w, n -= w;
    }
}
static void log_line(i32 fd, const char *s, i32 n) {
    char nl[2];
    nl[0] = 10, nl[1] = 0;
    write_all(fd, s, n);
    write_all(fd, nl, 1);
}

EXPORT("emscripten_log_impl_js") void log_impl_js(const char *s) { log_line(2, s, slen(s)); }

EXPORT("_emscripten_log_formatted") void log_formatted(i32 flags, const char *s) {
    i32 n = slen(s);
    if (flags & 24)  // the glue strips trailing white space before it appends the stack
        while (n > 0 && (s[n - 1] == ' ' || (s[n - 1] >= 9 && s[n - 1] <= 13))) n--;
    log_line((flags & 6) ? 2 : 1, s, n);
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

#include "ffi_calls.h"  // generated: Arg and ffi_dispatch (tools/gen_ffi.py)

// libffi type -> class of the wasm value: 0 i32 (integers, pointers), 1 i64, 2 f32, 3 f64; -1: not supported
static i32 ffi_class(u16 t) {
    switch (t) {
        case 1: case 5: case 6: case 7: case 8: case 9: case 10: case 14: return 0;
        case 11: case 12: return 1;  // UINT64, SINT64
        case 2: return 2;            // FLOAT
        case 3: return 3;            // DOUBLE
        default: return -1;          // long double, structs by value
    }
}

EXPORT("ffi_call_js") void ffi_call_js(ffi_cif_t *cif, u32 fn, void *rvalue, void **avalue) {
    u32 n = cif->nargs;
    {  // floats and 64-bit values: the generated dispatch (up to 4 arguments)
        i32 mixed = 0, rcls = cif->rtype->type == 0 ? -2 : ffi_class(cif->rtype->type);  // -2: void, -1: unsupported
        if (rcls != 0 && rcls != -2) mixed = 1;
        for (u32 i = 0; i < n && n <= 8; i++)
            if (ffi_class(cif->arg_types[i]->type) != 0) mixed = 1;
        if (mixed) {
            if (n > 4 || rcls == -1) __builtin_trap();  // more than 4 mixed arguments, a struct or a long double
            Arg args[4], ret;
            u32 pid = 0;
            for (u32 i = 0; i < n; i++) {
                i32 c = ffi_class(cif->arg_types[i]->type);
                if (c < 0) __builtin_trap();
                const void *p = avalue[i];
                if (c == 0) args[i].i = int_arg(cif->arg_types[i], p);
                else if (c == 1) args[i].l = *(const u64 *)p;
                else if (c == 2) args[i].f = *(const float *)p;
                else args[i].d = *(const double *)p;
                pid = pid * 4 + (u32)c;
            }
            u32 base = n == 0 ? 0 : n == 1 ? 1 : n == 2 ? 5 : n == 3 ? 21 : 85;
            ffi_dispatch(fn, (base + pid) * 5 + (u32)(rcls == -2 ? 0 : rcls + 1), args, &ret);
            if (rcls == 0) *(u32 *)rvalue = ret.i;
            else if (rcls == 1) *(u64 *)rvalue = ret.l;
            else if (rcls == 2) *(float *)rvalue = ret.f;
            else if (rcls == 3) *(double *)rvalue = ret.d;
            return;
        }
    }
    u32 a[8];
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
// descriptor (see the table below). The main module's fd_read / fd_write / fd_close / fd_fdstat_get come here first
// (OpenSSL reads and writes its socket with read() and write()); other descriptors pass on to WASI.
#define NET(n) __attribute__((import_module("net"), import_name(n)))
NET("socket") i32 net_socket(i32 domain, i32 type, i32 proto);  // -> handle, or -errno
NET("connect") i32 net_connect(i32 h, i32 family, i32 port, const u8 *addr);
NET("send") i32 net_send(i32 h, const u8 *p, i32 n);
NET("recv") i32 net_recv(i32 h, u8 *p, i32 n, i32 peek);
NET("poll") i32 net_poll(i32 h, i32 events, i32 timeout_ms);  // -> revents
NET("pollv") i32 net_pollv(i32 n, const i32 *hs, const i32 *events, i32 timeout_ms, i32 *revents);  // several sockets at once
NET("close") i32 net_close(i32 h);
NET("shutdown") i32 net_shutdown(i32 h, i32 how);
NET("name") i32 net_name(i32 h, i32 peer, u8 *addr4, i32 *port);  // the local or peer IPv4 address and port
NET("resolve") i32 net_resolve(const char *name, i32 n, u8 *addr4);  // -> 0, or -errno

// A socket takes a real WASI descriptor number (a directory opened as a placeholder), so that numbers stay small
// (select() takes less than 1024) and never clash with files; the table is indexed by that number.
typedef struct {
    i32 h[MAXFD];  // the host's handle + 1; 0: not a socket
    u8 nb[MAXFD];  // O_NONBLOCK: SOCK_NONBLOCK, ioctl(FIONBIO), fcntl(F_SETFL), set by the program
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
static i32 is_sock(i32 fd) { return fd >= 0 && fd < MAXFD && socks()->h[fd]; }
static i32 hof(i32 fd) { return socks()->h[fd] - 1; }
static i32 sock_nb(i32 fd) { return socks()->nb[fd]; }
static void sock_set_nb(i32 fd, i32 on) { socks()->nb[fd] = (u8)(on != 0); }

#define EAGAIN_ 6
#define ENOTSOCK_ 57
#define MSG_DONTWAIT 0x40
// a socket that must not block: does it have what is asked (events: 1 read, 4 write)? EAGAIN if not
static i32 would_block(i32 fd, i32 flags, i32 events) {
    if (!sock_nb(fd) && !(flags & MSG_DONTWAIT)) return 0;
    return !(net_poll(hof(fd), events, 0) & events);
}

EXPORT("__syscall_socket") i32 sc_socket(i32 domain, i32 type, i32 proto, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    u64 all = (1ull << 30) - 1, writes = (1ull << 6) | (1ull << 0) | (1ull << 8) | (1ull << 22);
    i32 fd = -1;
    char dot[2];  // "." built on the stack: a string literal would be a data section
    dot[0] = '.', dot[1] = 0;
    i32 e = w_path_open(PREOPEN, 1, dot, 1, 2 /* O_DIRECTORY */, all & ~writes, 0, 0, &fd);  // the placeholder
    if (e) return -33;  // EMFILE
    if (fd < 0 || fd >= MAXFD) {
        w_fd_close(fd);
        return -33;
    }
    i32 h = net_socket(domain, type & ~(04000 | 02000000), proto);  // without SOCK_NONBLOCK, SOCK_CLOEXEC
    if (h < 0) {
        w_fd_close(fd);
        return h;
    }
    socks()->h[fd] = h + 1;
    socks()->nb[fd] = (type & 04000) != 0;  // SOCK_NONBLOCK
    return fd;
}

EXPORT("__syscall_connect") i32 sc_connect(i32 fd, const u8 *sa, i32 len, i32 a, i32 b, i32 c) {
    (void)len, (void)a, (void)b, (void)c;
    if (!is_sock(fd)) return -ENOTSOCK_;
    // a non-blocking socket connects at once on the host (it can block there) and reports success, not EINPROGRESS
    i32 family = *(const u16 *)sa, port = (sa[2] << 8) | sa[3];
    return net_connect(hof(fd), family, port, family == 10 ? sa + 8 : sa + 4);
}

EXPORT("__syscall_sendto") i32 sc_sendto(i32 fd, const u8 *p, i32 n, i32 flags, i32 addr, i32 alen) {
    (void)addr, (void)alen;
    if (!is_sock(fd)) return -ENOTSOCK_;
    if (would_block(fd, flags, 4)) return -EAGAIN_;
    return net_send(hof(fd), p, n);
}

EXPORT("__syscall_recvfrom") i32 sc_recvfrom(i32 fd, u8 *p, i32 n, i32 flags, i32 addr, i32 alen) {
    (void)addr, (void)alen;
    if (!is_sock(fd)) return -ENOTSOCK_;
    if (would_block(fd, flags, 1)) return -EAGAIN_;
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

// struct pollfd {int fd; short events, revents;}. Sockets are polled by the host, all in one call, with the timeout;
// a file is always ready for what it is asked (POLLIN, POLLOUT); a descriptor that is not open is POLLNVAL; a negative
// one is ignored. A file that is ready, or an invalid descriptor, makes the sockets answer at once (nothing to wait for).
#define POLLNVAL 32
static i32 do_poll(u8 *fds, i32 n, i32 timeout) {
    i32 ready = 0, nsock = 0, immediate = 0;
    i32 *buf = n > 0 ? (i32 *)malloc((u32)n * 3 * 4) : 0;  // handles, events, revents of the sockets
    i32 *hs = buf, *evs = buf + n, *revs = buf + 2 * n;
    for (i32 k = 0; k < n; k++) {
        i32 fd = *(i32 *)(fds + 8 * k);
        i16 ev = *(i16 *)(fds + 8 * k + 4), rev = 0;
        if (fd >= 0 && is_sock(fd)) {
            hs[nsock] = hof(fd), evs[nsock] = ev & 5, revs[nsock] = 0;
            nsock++;
        } else if (fd >= 0) {
            u8 st[24] __attribute__((aligned(8)));
            if (w_fd_fdstat_get(fd, st)) rev = POLLNVAL;
            else rev = (i16)(ev & 5);
            if (rev) immediate = 1;
        }
        *(i16 *)(fds + 8 * k + 6) = rev;
    }
    if (nsock) net_pollv(nsock, hs, evs, immediate ? 0 : timeout, revs);
    else if (!immediate && timeout > 0) {  // nothing to wait for but time: the host's clock
        i32 none = 0;
        net_pollv(0, &none, &none, timeout, &none);
    }
    i32 j = 0;
    for (i32 k = 0; k < n; k++) {
        i32 fd = *(i32 *)(fds + 8 * k);
        if (fd >= 0 && is_sock(fd)) *(i16 *)(fds + 8 * k + 6) = (i16)revs[j++];
        if (*(i16 *)(fds + 8 * k + 6)) ready++;
    }
    if (buf) free(buf);
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
    if (would_block(fd, 0, 1)) return EAGAIN_;
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
    if (would_block(fd, 0, 4)) return EAGAIN_;
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
    if (!is_sock(fd)) {
        fd_forget(fd);
        return w_fd_close(fd);
    }
    net_close(hof(fd));
    socks()->h[fd] = 0;
    socks()->nb[fd] = 0;
    return w_fd_close(fd);  // the placeholder
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

// ================================================================== owners, nodes, messages, failures
// Every file belongs to uid/gid 0 in this world, so chown to 0 (or -1: unchanged) changes nothing and succeeds,
// and to anyone else is not permitted.
static i32 chown_result(i32 uid, i32 gid) { return (uid == -1 || uid == 0) && (gid == -1 || gid == 0) ? 0 : -63; }  // EPERM

EXPORT("__syscall_fchownat") i32 sc_fchownat(i32 dirfd, const char *path, i32 uid, i32 gid, i32 flags) {
    u64 fs[8];
    char dot[2];
    const char *p;
    i32 n, fd = resolve(dirfd, path, &p, &n, dot);
    i32 e = w_path_filestat_get(fd, (flags & 0x100) ? 0 : 1, p, n, fs);  // AT_SYMLINK_NOFOLLOW; it must exist
    return e ? -e : chown_result(uid, gid);
}

EXPORT("__syscall_fchown32") i32 sc_fchown32(i32 fd, i32 uid, i32 gid) {
    u64 fs[8];
    i32 e = w_fd_filestat_get(fd, fs);
    return e ? -e : chown_result(uid, gid);
}

// mknod: a regular file only; devices and FIFOs do not exist here
EXPORT("__syscall_mknodat") i32 sc_mknodat(i32 dirfd, const char *path, i32 mode, i32 dev) {
    (void)dev;
    i32 type = mode & 0170000;
    if (type != 0 && type != 0100000) return -52;  // ENOSYS
    i32 fd = sc_openat(dirfd, path, 0100 | 0200 | 1, 0);  // O_CREAT | O_EXCL | O_WRONLY
    if (fd < 0) return fd;
    x_fd_close(fd);
    return 0;
}

// sendmsg / recvmsg on a stream socket: the iovec of the message, no addresses and no control data
// (struct msghdr of wasm32: name, namelen, iov, iovlen, control, controllen, flags)
EXPORT("__syscall_sendmsg") i32 sc_sendmsg(i32 fd, const u32 *msg, i32 flags, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    if (!is_sock(fd)) return -ENOTSOCK_;
    if (would_block(fd, flags, 4)) return -EAGAIN_;
    const u32 *iov = (const u32 *)msg[2];
    i32 total = 0;
    for (u32 k = 0; k < msg[3]; k++) {
        i32 r = net_send(hof(fd), (const u8 *)iov[2 * k], (i32)iov[2 * k + 1]);
        if (r < 0) return total ? total : r;
        total += r;
        if (r < (i32)iov[2 * k + 1]) break;
    }
    return total;
}

EXPORT("__syscall_recvmsg") i32 sc_recvmsg(i32 fd, u32 *msg, i32 flags, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    if (!is_sock(fd)) return -ENOTSOCK_;
    if (would_block(fd, flags, 1)) return -EAGAIN_;
    const u32 *iov = (const u32 *)msg[2];
    msg[1] = 0;  // msg_namelen: no source address
    msg[5] = 0;  // msg_controllen: no control data (CPython parses the buffer by this length)
    msg[6] = 0;  // msg_flags
    for (u32 k = 0; k < msg[3]; k++)
        if (iov[2 * k + 1]) return net_recv(hof(fd), (u8 *)iov[2 * k], (i32)iov[2 * k + 1], flags & 2);  // MSG_PEEK
    return 0;
}

// system(): there are no processes (and system(NULL) says there is no shell)
EXPORT("_emscripten_system") i32 sc_system(const char *cmd) { return cmd ? -1 : 0; }

// abort() and a failed assert() end the program: they were stubs that returned, so the program went on. The
// messages are built from integer constants (no data section).
static void err_write(const char *s) {
    u32 iov[2];
    iov[0] = (u32)s, iov[1] = (u32)slen(s);
    i32 n;
    w_fd_write(2, iov, 1, &n);
}
EXPORT("__assert_fail") void sc_assert_fail(const char *cond, const char *file, i32 line, const char *func) {
    (void)line, (void)func;
    u64 m[3];
    m[0] = 0x6f69747265737341ull, m[1] = 0x64656c696166206eull, m[2] = 0x000000000000203aull;  // "Assertion failed: " (the last chunk ends with the NUL of the string)
    u8 head[24];
    for (i32 k = 0; k < 3; k++)
        for (i32 j = 0; j < 8; j++) head[k * 8 + j] = (u8)(m[k] >> (8 * j));
    head[18] = 0;
    err_write((const char *)head);
    err_write(cond ? cond : (const char *)head + 18);
    u8 sp[2];
    sp[0] = ' ', sp[1] = 0;
    err_write((const char *)sp);
    err_write(file ? file : (const char *)sp + 1);
    u8 nl[2];
    nl[0] = '\n', nl[1] = 0;
    err_write((const char *)nl);
    __builtin_trap();
}
EXPORT("_abort_js") void sc_abort_js(void) {
    u64 m[2];
    m[0] = 0x0a292874726f6261ull, m[1] = 0;  // "abort()\n"
    err_write((const char *)m);
    __builtin_trap();
}
