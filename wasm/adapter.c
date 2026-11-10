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
WASI("path_filestat_set_times") i32 w_path_set_times(i32 fd, i32 lookup, const char *p, i32 n, u64 atim, u64 mtim, i32 fstflags);
WASI("fd_filestat_set_times") i32 w_fd_set_times(i32 fd, u64 atim, u64 mtim, i32 fstflags);
WASI("fd_fdstat_get") i32 w_fd_fdstat_get(i32 fd, void *buf);
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
// errno values of this ABI (WASI's numbering), for the file functions
#define FE_ACCES 2
#define FE_BADF 8
#define FE_EXIST 20
#define FE_FBIG 22
#define FE_INVAL 28
#define FE_LOOP 32
#define FE_NOENT 44
#define FE_NOSYS 52
#define FE_NOTDIR 54
#define FE_SPIPE 70
#define FE_XDEV 75
#define FE_OPNOTSUPP 138
// the host's view of the files: statvfs of the host folder behind a guest path -> 0, or -errno; writes Emscripten's
// statfs64 (88 bytes)
#define FS(n) __attribute__((import_module("fs"), import_name(n)))
FS("statvfs") i32 fs_statvfs(const char *path, i32 n, u8 *buf);

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
// per descriptor: the next fd_readdir cookie (a table that grows with the descriptor numbers)
typedef struct {
    u32 cap;
    u64 *v;
} Ck;
static u64 *ckp(i32 fd) {
    Ck *c = (Ck *)state_get();
    if (!c) {
        c = (Ck *)calloc(1, sizeof(Ck));
        state_set((u64 *)c);
    }
    if ((u32)fd >= c->cap) {
        u32 nc = c->cap ? c->cap : 256;
        while (nc <= (u32)fd) nc *= 2;
        u64 *nv = (u64 *)calloc(nc, 8);
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
static char *slot(i32 k, u32 need) {  // a path buffer of at least `need` bytes
    Cwd *C = cwdst();
    if (C->cap[k] < need) {
        if (C->b[k]) free(C->b[k]);
        C->b[k] = (char *)malloc(need);
        C->cap[k] = need;
    }
    return C->b[k];
}
static char *dupn(const char *s, u32 n) {  // a malloc'd copy of n bytes and a NUL
    char *r = (char *)malloc(n + 1);
    for (u32 i = 0; i < n; i++) r[i] = s[i];
    r[n] = 0;
    return r;
}

// ---- what WASI has no place for: permission bits, owners, the umask and the original target of a symlink are
// session metadata kept here (like Pyodide's in-memory file system keeps them in its nodes), keyed by the file's
// (st_dev, st_ino): a hash table in one malloc'd block, its address in a wasm global. They live for the interpreter's
// lifetime and are not written to the host's file. A file with no record (it was there before the guest) gets the
// defaults of Pyodide (regular 0644, directory 0755, symlink 0777).
typedef struct {
    u64 dev, ino;
    u32 mode, uid, gid, used;  // used: 0 free, 1 live, 2 deleted
    char *target;              // a symlink made with an absolute target: what the program stored (the link holds a relative one)
} Meta;
typedef struct {
    u32 cap, fill, live, umask, ntarget;
    Meta *e;
} MetaT;
__asm__(".globaltype meta_state, i32\nmeta_state:\n");
static MetaT *mt(void) {
    MetaT *r;
    __asm__ volatile("global.get meta_state\n\tlocal.set %0" : "=r"(r));
    if (!r) {
        r = (MetaT *)calloc(1, sizeof(MetaT));
        r->umask = 022;
        __asm__ volatile("local.get %0\n\tglobal.set meta_state" : : "r"(r));
    }
    return r;
}
static u32 mhash(u64 dev, u64 ino) {
    u64 h = (dev * 0x9E3779B97F4A7C15ull) ^ (ino * 0xC2B2AE3D27D4EB4Full);
    h ^= h >> 29;
    return (u32)h;
}
static Meta *meta_find(u64 dev, u64 ino) {
    MetaT *t = mt();
    if (!t->cap) return 0;
    u32 m = t->cap - 1;
    for (u32 i = mhash(dev, ino) & m;; i = (i + 1) & m) {
        Meta *e = &t->e[i];
        if (e->used == 0) return 0;
        if (e->used == 1 && e->dev == dev && e->ino == ino) return e;
    }
}
static void meta_grow(MetaT *t) {  // rebuild without the deleted ones, at a size that keeps the load under a half
    u32 nc = t->cap ? t->cap : 256;
    while (t->live * 2 >= nc) nc *= 2;
    Meta *ne = (Meta *)calloc(nc, sizeof(Meta));
    for (u32 j = 0; j < t->cap; j++) {
        Meta *o = &t->e[j];
        if (o->used != 1) continue;
        u32 i = mhash(o->dev, o->ino) & (nc - 1);
        while (ne[i].used) i = (i + 1) & (nc - 1);
        ne[i].dev = o->dev, ne[i].ino = o->ino, ne[i].mode = o->mode, ne[i].uid = o->uid, ne[i].gid = o->gid;
        ne[i].used = 1, ne[i].target = o->target;
    }
    if (t->e) free(t->e);
    t->e = ne;
    t->cap = nc;
    t->fill = t->live;
}
static void meta_notarget(MetaT *t, Meta *e) {
    if (e->target) {
        free(e->target);
        e->target = 0;
        t->ntarget--;
    }
}
static Meta *meta_put(u64 dev, u64 ino, u32 mode, u32 uid, u32 gid) {  // a new or replaced record (no symlink target)
    MetaT *t = mt();
    Meta *e = meta_find(dev, ino);
    if (!e) {
        if ((t->fill + 1) * 2 > t->cap) meta_grow(t);
        u32 m = t->cap - 1, i = mhash(dev, ino) & m;
        while (t->e[i].used == 1) i = (i + 1) & m;
        e = &t->e[i];
        if (e->used == 0) t->fill++;
        t->live++;
        e->used = 1;
        e->dev = dev;
        e->ino = ino;
        e->target = 0;
    }
    meta_notarget(t, e);
    e->mode = mode, e->uid = uid, e->gid = gid;
    return e;
}
static void meta_del(u64 dev, u64 ino) {
    MetaT *t = mt();
    Meta *e = meta_find(dev, ino);
    if (!e) return;
    meta_notarget(t, e);
    e->used = 2;
    t->live--;
}
static u32 def_mode(u8 ft) { return ft == 3 ? 0755 : ft == 7 || ft == 5 || ft == 6 ? 0777 : ft == 2 || ft == 1 ? 0666 : 0644; }
static u32 type_bits(u8 ft) {  // S_IF* of a WASI filetype
    return ft == 3 ? 0040000 : ft == 7 ? 0120000 : ft == 2 ? 0020000 : ft == 1 ? 0060000 : ft == 5 || ft == 6 ? 0140000 : 0100000;
}
static Meta *meta_for(const u8 *fs) {  // the record of the file whose WASI filestat is fs, made from the defaults
    u64 dev = *(const u64 *)fs, ino = *(const u64 *)(fs + 8);
    Meta *e = meta_find(dev, ino);
    return e ? e : meta_put(dev, ino, def_mode(fs[16]), 0, 0);
}
// a file made now: its record is the mode asked, without the umask
static void meta_created(const u8 *fs, u32 mode, u32 keep) { meta_put(*(const u64 *)fs, *(const u64 *)(fs + 8), mode & ~mt()->umask & keep, 0, 0); }
// an object that is about to disappear (the last name of a file, or a directory)? -> its (dev, ino) in key
static i32 meta_doomed(i32 fd, const char *p, i32 n, u64 *key) {
    u64 fs[8];
    if (!mt()->live || w_path_filestat_get(fd, 0, p, n, fs)) return 0;
    key[0] = fs[0], key[1] = fs[1];
    return *((u8 *)fs + 16) == 3 || fs[3] <= 1;
}
// May the name be made or removed in the directory that holds it? The directory's recorded mode needs write and search
// (Pyodide's mayCreate / mayDelete, whoever asks). kind 1: a name to make (if it exists the call says EEXIST), 0: a name to
// remove (if it is not there the call says ENOENT), 2: either (the destination of a rename). -> EACCES or 0
static i32 dir_denies(i32 fd, const char *p, i32 n, i32 kind) {
    if (!mt()->live) return 0;
    u64 fs[8];
    i32 missing = w_path_filestat_get(fd, 0, p, n, fs) != 0;
    if (kind != 2 && missing != kind) return 0;
    i32 e = n;
    while (e > 1 && p[e - 1] == '/') e--;
    i32 st = e;
    while (st > 0 && p[st - 1] != '/') st--;  // the last name starts here
    char dot[2];
    dot[0] = '.', dot[1] = 0;
    char *par = st ? dupn(p, (u32)st) : 0;
    i32 err = w_path_filestat_get(fd, 1, par ? par : dot, st ? st : 1, fs);
    if (par) free(par);
    Meta *r = err ? 0 : meta_find(fs[0], fs[1]);
    return r && (!(r->mode & 0222) || !(r->mode & 0111)) ? FE_ACCES : 0;
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
static char *absdup(i32 dirfd, const char *path);
static void fd_forget(i32 fd) {
    if (fd >= 0 && fd < MAXFD && fds()->path[fd]) {
        free(fds()->path[fd]);
        fds()->path[fd] = 0;
    }
}

static i32 ncomp(const char *s) {  // the depth of an absolute path below the root
    i32 n = 0;
    for (i32 i = 0; s[i];) {
        while (s[i] == '/') i++;
        if (!s[i]) break;
        i32 st = i;
        while (s[i] && s[i] != '/') i++;
        i32 l = i - st;
        if (l == 2 && s[st] == '.' && s[st + 1] == '.') {
            if (n) n--;
        } else if (!(l == 1 && s[st] == '.')) {
            n++;
        }
    }
    return n;
}
static i32 has_dotdot(const char *s) {
    for (i32 i = 0; s[i];) {
        while (s[i] == '/') i++;
        i32 st = i;
        while (s[i] && s[i] != '/') i++;
        if (i - st == 2 && s[st] == '.' && s[st + 1] == '.') return 1;
    }
    return 0;
}
// The path to resolve: a path relative to the cwd is made absolute (the cwd is kept here, WASI has none), and a ".."
// that would go above the root is dropped (Linux: "/.." is "/"; WASI would refuse it as an escape). A relative path
// with a ".." to a directory descriptor is made absolute too (WASI's sandbox is the descriptor: it refuses a ".." out of
// it). The result is the path itself when it needs none of this, else a buffer of ours. A relative path to a
// directory descriptor with no known path is left as it is.
static const char *fixpath(i32 dirfd, const char *path) {
    Cwd *C = cwdst();
    i32 rel = path[0] != '/';
    i32 dd = has_dotdot(path);
    i32 compose = rel && ((dirfd == AT_FDCWD && !(C->cwd[0] == '/' && C->cwd[1] == 0)) || (dirfd != AT_FDCWD && dd));
    if (!compose && !dd) return path;
    const char *base = 0;
    if (rel) {
        base = dirfd == AT_FDCWD ? C->cwd : fd_base_path(dirfd);
        if (!base) return path;
    }
    i32 depth = base ? ncomp(base) : 0;
    u32 bl = compose ? (u32)slen(base) : 0;
    char *o = slot(C->flip, bl + (u32)slen(path) + 2);
    C->flip ^= 1;
    i32 k = 0;
    if (compose) {
        for (u32 i = 0; i < bl; i++) o[k++] = base[i];
        if (k == 0 || o[k - 1] != '/') o[k++] = '/';
    }
    for (i32 i = 0; path[i];) {
        while (path[i] == '/') o[k++] = path[i++];
        if (!path[i]) break;
        i32 st = i;
        while (path[i] && path[i] != '/') i++;
        i32 l = i - st;
        if (l == 2 && path[st] == '.' && path[st + 1] == '.') {
            if (depth == 0) {  // above the root: it stays there
                if (path[i] == '/') i++;
                continue;
            }
            depth--;
        } else if (!(l == 1 && path[st] == '.')) {
            depth++;
        }
        for (i32 j = 0; j < l; j++) o[k++] = path[st + j];
    }
    o[k] = 0;
    return o;
}
// an absolute path (malloc'd, ".." above the root dropped), or 0 when the directory descriptor has no known path
static char *absdup(i32 dirfd, const char *path) {
    if (path[0] == '/') {
        const char *f = fixpath(dirfd, path);
        return dupn(f, (u32)slen(f));
    }
    const char *base = dirfd == AT_FDCWD ? cwdst()->cwd : fd_base_path(dirfd);
    if (!base) return 0;
    u32 bl = (u32)slen(base), pl = (u32)slen(path);
    char *t = (char *)malloc(bl + pl + 2);
    for (u32 i = 0; i < bl; i++) t[i] = base[i];
    u32 k = bl;
    if (k == 0 || t[k - 1] != '/') t[k++] = '/';
    for (u32 i = 0; i <= pl; i++) t[k + i] = path[i];
    const char *f = fixpath(AT_FDCWD, t);
    char *r = dupn(f, (u32)slen(f));
    free(t);
    return r;
}

// A guest path and dirfd -> (WASI fd, path pointer, length). An empty result is ".". The cwd is kept by chdir (the root at first).
static i32 resolve(i32 dirfd, const char *path, const char **out, i32 *len, char *dot) {
    i32 fd = dirfd;
    path = fixpath(dirfd, path);
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

// WASI filestat (64 bytes) -> Emscripten struct stat (96 bytes): the type from the WASI filetype, the permission bits
// and owners from the record (or the defaults). st_dev is 32 bits in this ABI: the two halves are folded.
static void put_stat(u8 *dst, const u8 *fs) {
    u64 dev = *(const u64 *)(fs + 0), ino = *(const u64 *)(fs + 8);
    u8 ft = fs[16];
    u64 nlink = *(const u64 *)(fs + 24), size = *(const u64 *)(fs + 32);
    u64 at = *(const u64 *)(fs + 40), mtm = *(const u64 *)(fs + 48), ct = *(const u64 *)(fs + 56);
    Meta *r = meta_find(dev, ino);
    u32 mode = type_bits(ft) | (r ? r->mode : def_mode(ft));
    if (ft == 7 && r && r->target) size = (u64)slen(r->target);  // a symlink's size is the length of its target
    for (i32 i = 0; i < 96; i++) dst[i] = 0;
    *(u32 *)(dst + 0) = (u32)dev ^ (u32)(dev >> 32);
    *(u32 *)(dst + 4) = mode;
    *(u32 *)(dst + 8) = (u32)nlink;
    *(u32 *)(dst + 12) = r ? r->uid : 0;
    *(u32 *)(dst + 16) = r ? r->gid : 0;
    *(i64 *)(dst + 24) = (i64)size;
    *(u32 *)(dst + 32) = 4096;
    *(u32 *)(dst + 36) = (u32)((size + 511) / 512);
    *(i64 *)(dst + 40) = (i64)(at / 1000000000ull);
    *(u32 *)(dst + 48) = (u32)(at % 1000000000ull);
    *(i64 *)(dst + 56) = (i64)(mtm / 1000000000ull);
    *(u32 *)(dst + 64) = (u32)(mtm % 1000000000ull);
    *(i64 *)(dst + 72) = (i64)(ct / 1000000000ull);
    *(u32 *)(dst + 80) = (u32)(ct % 1000000000ull);
    *(u64 *)(dst + 88) = ino;
}

// the WASI filestat of dirfd + path: an empty path is ENOENT (only AT_EMPTY_PATH allows it); -> an errno or 0
static i32 fx_lookup(i32 dirfd, const char *path, i32 follow, u64 *fs) {
    if (!path[0]) return FE_NOENT;
    char dot[2];
    const char *p;
    i32 n, fd = resolve(dirfd, path, &p, &n, dot);
    return w_path_filestat_get(fd, follow ? 1 : 0, p, n, fs);
}

static i32 stat_path(i32 dirfd, const char *path, void *buf, i32 follow) {
    u64 fs[8];
    i32 e = fx_lookup(dirfd, path, follow, fs);
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

// The physical path of `path` (against `base` when relative): the names are walked one by one and every symlink is read
// and followed (the last name only if `follow`), ".." goes to the real parent, a loop of more than 40 links is ELOOP.
// -> 0 and the absolute path in *res (malloc'd), or an errno (positive).
static i32 phys(const char *base, const char *path, i32 follow, char **res) {
    char sl[2];
    sl[0] = '/', sl[1] = 0;
    char *cur = path[0] == '/' ? dupn(sl, 1) : dupn(base, (u32)slen(base));
    char *rest = dupn(path, (u32)slen(path));
    i32 links = 0, err = 0;
    for (i32 i = 0;;) {
        while (rest[i] == '/') i++;
        if (!rest[i]) break;
        i32 st = i;
        while (rest[i] && rest[i] != '/') i++;
        i32 l = i - st;
        if (l == 1 && rest[st] == '.') continue;
        if (l == 2 && rest[st] == '.' && rest[st + 1] == '.') {  // the parent; the root has none
            i32 j = slen(cur) - 1;
            while (j > 0 && cur[j] != '/') j--;
            if (j == 0) cur[1] = 0;
            else cur[j] = 0;
            continue;
        }
        i32 last = 1;
        for (i32 j = i; rest[j]; j++)
            if (rest[j] != '/') {
                last = 0;
                break;
            }
        i32 cl = slen(cur);
        char *cand = (char *)malloc((u32)(cl + l + 2));
        for (i32 j = 0; j < cl; j++) cand[j] = cur[j];
        if (cl == 0 || cand[cl - 1] != '/') cand[cl++] = '/';
        for (i32 j = 0; j < l; j++) cand[cl + j] = rest[st + j];
        cand[cl + l] = 0;
        if (last && !follow) {
            free(cur);
            cur = cand;
            continue;
        }
        u32 cap = 256;
        char *tb;
        i32 used = 0, e;
        for (;;) {
            char dot[2];
            const char *p;
            i32 n, fd = resolve(AT_FDCWD, cand, &p, &n, dot);
            tb = (char *)malloc(cap);
            e = w_path_readlink(fd, p, n, tb, (i32)cap, &used);
            if (e || used < (i32)cap) break;
            free(tb);
            cap *= 2;
        }
        if (e == FE_INVAL) {  // not a link
            free(tb);
            free(cur);
            cur = cand;
            continue;
        }
        free(cand);
        if (e || ++links > 40) {
            free(tb);
            err = e ? e : FE_LOOP;
            break;
        }
        tb[used] = 0;
        u32 rl = (u32)slen(rest + i);
        char *nr = (char *)malloc((u32)used + 1 + rl + 1);
        for (i32 j = 0; j < used; j++) nr[j] = tb[j];
        nr[used] = '/';
        for (u32 j = 0; j <= rl; j++) nr[used + 1 + (i32)j] = rest[i + (i32)j];
        if (tb[0] == '/') {
            free(cur);
            cur = dupn(sl, 1);
        }
        free(tb);
        free(rest);
        rest = nr;
        i = 0;
    }
    free(rest);
    if (err) {
        free(cur);
        return err;
    }
    *res = cur;
    return 0;
}

// chdir is physical: getcwd after chdir through a link shows the real directory, and ".." is its real parent
EXPORT("__syscall_chdir") i32 sc_chdir(const char *path) {
    if (!path[0]) return -FE_NOENT;
    Cwd *C = cwdst();
    char *res;
    i32 e = phys(C->cwd, path, 1, &res);
    if (e) return -e;
    u64 fs[8];
    char dot[2];
    const char *p;
    i32 n, fd = resolve(AT_FDCWD, res, &p, &n, dot);
    e = w_path_filestat_get(fd, 1, p, n, fs);
    Meta *r = e ? 0 : meta_find(fs[0], fs[1]);
    if (e || *((u8 *)fs + 16) != 3 || (r && !(r->mode & 0111))) {  // the search permission, as Pyodide's nodePermissions
        free(res);
        return e ? -e : *((u8 *)fs + 16) != 3 ? -FE_NOTDIR : -FE_ACCES;
    }
    free(C->cwd);
    C->cwd = res;
    return 0;
}

EXPORT("__syscall_fchdir") i32 sc_fchdir(i32 fd) {
    const char *p = fd_base_path(fd);  // a directory opened by openat, or a preopen
    if (p) return sc_chdir(p);
    u8 st[24] __attribute__((aligned(8)));
    return (is_sock(fd) || !w_fd_fdstat_get(fd, st)) ? -FE_NOTDIR : -FE_BADF;  // a stream: not a directory
}

static i32 open_at(i32 dirfd, const char *path, i32 flags, u32 mode) {
    char dot[2];
    const char *p;
    i32 n, fd = resolve(dirfd, path, &p, &n, dot);
    i32 acc = flags & 3, oflags = 0, fdflags = 0, created = 0;
    if (flags & 0100) oflags |= 1;       // O_CREAT
    if (flags & 0200000) oflags |= 2;    // O_DIRECTORY
    if (flags & 0200) oflags |= 4;       // O_EXCL
    if (flags & 01000) oflags |= 8;      // O_TRUNC
    if (flags & 02000) fdflags |= 1;     // O_APPEND
    if (flags & 04000) fdflags |= 4;     // O_NONBLOCK
    if ((flags & 0100) || mt()->live) {  // is it made now? if it exists, may it be opened (its recorded mode)?
        u64 fs[8];
        if (w_path_filestat_get(fd, (flags & 0400000) ? 0 : 1, p, n, fs)) {
            created = (flags & 0100) != 0;
        } else if (!((flags & 0100) && (flags & 0200))) {
            Meta *r = meta_find(fs[0], fs[1]);
            i32 need = acc == 0 ? 4 : acc == 1 ? 2 : 6;
            if (flags & 01000) need |= 2;
            if (r && (((need & 4) && !(r->mode & 0444)) || ((need & 2) && !(r->mode & 0222)))) return -FE_ACCES;
        }
    }
    if (created && dir_denies(fd, p, n, 1)) return -FE_ACCES;
    u64 all = (1ull << 30) - 1, writes = (1ull << 6) | (1ull << 0) | (1ull << 8) | (1ull << 22);
    u64 reads = (1ull << 1) | (1ull << 14);
    u64 rights = acc == 0 ? all & ~writes : acc == 1 ? all & ~reads : all;
    i32 out = -1;
    i32 e = w_path_open(fd, (flags & 0400000) ? 0 : 1, p, n, oflags, rights, all, fdflags, &out);
    if (e) return -e;
    if (created) {
        u64 fs[8];
        if (!w_fd_filestat_get(out, fs)) meta_created((const u8 *)fs, mode, 07777);
    }
    if (out >= 0 && out < MAXFD) {
        *ckp(out) = 0;  // a new descriptor lists its directory from the start
        fd_forget(out);
        char *copy = absdup(dirfd, path);  // the path dup() opens again, of any length
        if (copy) {
            fds()->path[out] = copy;
            fds()->flags[out] = flags;
        }
    }
    return out;
}

// the mode of O_CREAT is the variable argument (va points at it)
EXPORT("__syscall_openat") i32 sc_openat(i32 dirfd, const char *path, i32 flags, i32 va) {
    return open_at(dirfd, path, flags, va ? *(const u32 *)va : 0);
}

// dup(): the same file opened again, at the same position (a copy of it: WASI 0.1 can not share the offset)
EXPORT("__syscall_dup") i32 sc_dup(i32 fd) {
    if (fd < 0 || fd >= MAXFD || !fds()->path[fd]) return -52;  // ENOSYS: a stream, a socket or a pipe
    i32 flags = fds()->flags[fd] & ~(0100 | 0200 | 01000);       // not O_CREAT, O_EXCL, O_TRUNC again
    i32 nfd = sc_openat(AT_FDCWD, fds()->path[fd], flags, 0);  // (the new descriptor's record is another one)
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
    if (newfd >= 0) *ckp(newfd) = 0;  // the cookie of the descriptor that was there is stale
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
    if (fd <= 2) *(u32 *)((u8 *)buf + 4) = 0020666;  // the standard streams are character devices (Pyodide's fstat(1))
    return 0;
}

EXPORT("__syscall_newfstatat") i32 sc_newfstatat(i32 dirfd, const char *path, void *buf, i32 flags) {
    if (!path[0] && (flags & 0x1000)) {  // AT_EMPTY_PATH: the descriptor itself, or the cwd
        if (dirfd != AT_FDCWD) return sc_fstat64(dirfd, buf);
        char dot[2];
        dot[0] = '.', dot[1] = 0;
        return stat_path(AT_FDCWD, dot, buf, 1);
    }
    return stat_path(dirfd, path, buf, !(flags & 0x100));  // an empty path is ENOENT
}

EXPORT("__syscall_readlinkat") i32 sc_readlinkat(i32 dirfd, const char *path, char *buf, i32 len) {
    char dot[2];
    const char *p;
    i32 n, used = 0, fd = resolve(dirfd, path, &p, &n, dot);
    i32 e = w_path_readlink(fd, p, n, buf, len, &used);
    if (e) return -e;
    if (mt()->ntarget) {  // a link made with an absolute target: what the program stored, not the relative one it holds
        u64 fs[8];
        Meta *r = w_path_filestat_get(fd, 0, p, n, fs) ? 0 : meta_find(fs[0], fs[1]);
        if (r && r->target) {
            i32 tl = slen(r->target);
            used = tl < len ? tl : len;
            for (i32 j = 0; j < used; j++) buf[j] = r->target[j];
        }
    }
    return used;
}

// access: the recorded (or default) mode bits, whoever asks (Pyodide's nodePermissions: any of the user, group, other bits)
EXPORT("__syscall_faccessat") i32 sc_faccessat(i32 dirfd, const char *path, i32 mode, i32 flags) {
    if (mode & ~7) return -FE_INVAL;
    u64 fs[8];
    i32 e = fx_lookup(dirfd, path, !(flags & 0x100), fs);
    if (e) return -e;
    Meta *r = meta_find(fs[0], fs[1]);
    u32 bits = r ? r->mode : def_mode(*((u8 *)fs + 16));
    if (((mode & 4) && !(bits & 0444)) || ((mode & 2) && !(bits & 0222)) || ((mode & 1) && !(bits & 0111))) return -FE_ACCES;
    return 0;
}

// WASI dirents {d_next u64, d_ino u64, d_namlen u32, d_type u8, name} -> linux_dirent64
// {d_ino u64, d_off i64, d_reclen u16, d_type u8, name\0, padded to 8}
EXPORT("__syscall_getdents64") i32 sc_getdents64(i32 fd, u8 *dirp, i32 count) {
    if (fd < 0) return -EBADF;
    u64 *ck = ckp(fd);
    i32 cap = count + 512;
    u8 *tmp = (u8 *)malloc((u32)cap);
    if (!tmp) return -ENOMEM;
    i32 used = 0;
    i32 e = w_fd_readdir(fd, tmp, cap, *ck, &used);
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
        *ck = next;
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

WASI("fd_fdstat_set_flags") i32 w_fd_fdstat_set_flags(i32 fd, i32 flags);

// the WASI filetype of an open descriptor (a socket is a stream socket), or -errno (EBADF)
static i32 fd_type(i32 fd) {
    if (is_sock(fd)) return 6;
    u8 st[24] __attribute__((aligned(8)));
    i32 e = w_fd_fdstat_get(fd, st);
    return e ? -e : st[0];
}
// can the descriptor seek? The standard streams, sockets and character devices can not (Pyodide: stream.seekable)
static i32 fd_seekable(i32 fd, i32 ft) { return fd > 2 && ft != 2 && ft != 5 && ft != 6; }

// fcntl: the flags are WASI's fdflags (append, nonblock) and rights; an invalid descriptor is EBADF for every command (as
// Pyodide's getStreamFromFD). The lock commands of this ABI are F_GETLK 12, F_SETLK 13, F_SETLKW 14: there is one process,
// so a lock is always granted and F_GETLK reports F_UNLCK.
EXPORT("__syscall_fcntl64") i32 sc_fcntl64(i32 fd, i32 cmd, i32 va) {
    if (fd_type(fd) < 0) return -FE_BADF;
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
        case 12: {  // F_GETLK: nobody else holds a lock -> l_type = F_UNLCK
            u16 *fl = va ? *(u16 **)va : 0;
            if (fl) *fl = 2;
            return 0;
        }
        case 13:  // F_SETLK
        case 14:  // F_SETLKW
            return 0;
        case 0:     // F_DUPFD (the minimum number is not honoured)
        case 1030:  // F_DUPFD_CLOEXEC
            return sc_dup(fd);
        default:
            return -FE_INVAL;
    }
}

// lseek on a descriptor: a directory keeps its readdir cookie here (rewinddir is SEEK_SET 0, seekdir/telldir use the
// d_off of the entries, getdents64 continues from it); the others go to WASI. Sockets can not seek.
EXPORT("fd_seek") i32 x_fd_seek(i32 fd, i64 off, i32 whence, u64 *newoff) {
    if (is_sock(fd)) return FE_SPIPE;
    u8 st[24] __attribute__((aligned(8)));
    if (!w_fd_fdstat_get(fd, st) && st[0] == 3) {
        u64 *ck = ckp(fd);
        i64 pos = whence == 1 ? (i64)*ck + off : off;  // SEEK_SET, SEEK_END (a directory has no size: as SET), SEEK_CUR
        if (whence < 0 || whence > 2 || pos < 0) return FE_INVAL;
        *ck = (u64)pos;
        *newoff = (u64)pos;
        return 0;
    }
    return w_fd_seek(fd, off, whence, newoff);
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
    // not a library loaded by dlopen: the main module (dlopen(NULL), ctypes.pythonapi) or RTLD_DEFAULT: the main
    // module first, then the libraries, as the glue's global search does
    u32 out[2] = {0, 0}, v = dl_sym(0, sym, slen(sym), out);
    for (i32 k = -1; out[0] == 0 && k < L->n; k++) {
        if (k >= 0) {
            v = dl_sym(L->lib[k].id, sym, slen(sym), out);
            if (out[0] == 1) v += L->lib[k].base;
        }
    }
    if (out[0] == 1) return v;
    if (out[0] == 2) {
        *index = out[1];
        return v;
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
    char dot[2];
    const char *p;
    i32 n, fd = resolve(dirfd, path, &p, &n, dot);
    if (dir_denies(fd, p, n, 1)) return -FE_ACCES;
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
    if (dir_denies(fd, p, n, 0)) return -FE_ACCES;
    i32 e = (flags & 0x200) ? w_rmdir(fd, p, n) : w_unlink(fd, p, n);  // AT_REMOVEDIR
    if (e) return -e;
    if (doomed) meta_del(key[0], key[1]);
    return 0;
}

EXPORT("__syscall_rmdir") i32 sc_rmdir(const char *path) { return sc_unlinkat(AT_FDCWD, path, 0x200); }

static void relink(i32 dirfd, const char *path);
EXPORT("__syscall_renameat") i32 sc_renameat(i32 olddirfd, const char *oldpath, i32 newdirfd, const char *newpath) {
    char d1[2], d2[2];
    const char *p1, *p2;
    i32 n1, n2, f1 = resolve(olddirfd, oldpath, &p1, &n1, d1), f2 = resolve(newdirfd, newpath, &p2, &n2, d2);
    u64 key[2];
    i32 doomed = meta_doomed(f2, p2, n2, key);  // a file or directory that the rename replaces
    if (dir_denies(f1, p1, n1, 0) || dir_denies(f2, p2, n2, 2)) return -FE_ACCES;
    i32 e = w_rename(f1, p1, n1, f2, p2, n2);
    if (e) return -e;
    if (doomed) {
        u64 fs[8];
        if (w_path_filestat_get(f2, 0, p2, n2, fs) || fs[0] != key[0] || fs[1] != key[1]) meta_del(key[0], key[1]);
    }
    if (mt()->ntarget) relink(newdirfd, newpath);
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
    *err = FE_BADF;
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
                i32 k = 0;
                for (i32 i = 0; i < up; i++) r[k++] = '.', r[k++] = '.', r[k++] = '/';
                for (i32 i = 0; i < n2; i++) r[k++] = p2[i];
                if (k > 0 && r[k - 1] == '/') k--;
                r[k] = 0;
                if (k == 0) r[0] = '.', r[1] = 0;
            }
        }
    }
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
    if (dir_denies(fd, p, n, 1)) {
        if (rel) free(rel);
        return -FE_ACCES;
    }
    i32 e = w_symlink(use, slen(use), fd, p, n);
    if (rel) free(rel);
    if (e) return -e;
    if (target[0] == '/') {  // remember what was stored
        u64 fs[8];
        if (!w_path_filestat_get(fd, 0, p, n, fs)) {
            Meta *m = meta_put(fs[0], fs[1], 0777, 0, 0);
            m->target = dupn(target, (u32)slen(target));
            mt()->ntarget++;
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
    u32 mode = r->mode, uid = r->uid, gid = r->gid;
    u64 dev = fs[0], ino = fs[1];
    i32 err;
    char *rel = rel_target(dirfd, path, target, &err);
    if (rel) {
        fd = resolve(dirfd, path, &p, &n, dot);
        if (!w_unlink(fd, p, n) && !w_symlink(rel, slen(rel), fd, p, n)) {
            meta_del(dev, ino);
            if (!w_path_filestat_get(fd, 0, p, n, fs)) {
                Meta *m = meta_put(fs[0], fs[1], mode, uid, gid);
                m->target = target;
                mt()->ntarget++;
                target = 0;
            }
        }
        free(rel);
    }
    if (target) free(target);
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
    meta_for((const u8 *)fs)->mode = (u32)mode & 07777;
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
// chown: any uid and gid is accepted (the process is root of a single-user world) and recorded; -1 leaves one as it is
static i32 set_owner(const u64 *fs, i32 uid, i32 gid) {
    Meta *r = meta_for((const u8 *)fs);
    if (uid != -1) r->uid = (u32)uid;
    if (gid != -1) r->gid = (u32)gid;
    return 0;
}

EXPORT("__syscall_fchownat") i32 sc_fchownat(i32 dirfd, const char *path, i32 uid, i32 gid, i32 flags) {
    u64 fs[8];
    i32 e = fx_lookup(dirfd, path, !(flags & 0x100), fs);  // AT_SYMLINK_NOFOLLOW; it must exist
    return e ? -e : set_owner(fs, uid, gid);
}

EXPORT("__syscall_fchown32") i32 sc_fchown32(i32 fd, i32 uid, i32 gid) {
    u64 fs[8];
    i32 e = w_fd_filestat_get(fd, fs);
    if (e) return -e;
    return is_sock(fd) ? 0 : set_owner(fs, uid, gid);
}

// mknod: a regular file (made like open(O_CREAT|O_EXCL), with the mode and the umask); FIFOs, devices and sockets can not
// be made over WASI (ENOSYS), and a mode with no type is EINVAL, as Pyodide's JavaScript
EXPORT("__syscall_mknodat") i32 sc_mknodat(i32 dirfd, const char *path, i32 mode, i32 dev) {
    (void)dev;
    i32 type = mode & 0170000;
    if (type != 0100000 && type != 020000 && type != 060000 && type != 010000 && type != 0140000) return -FE_INVAL;
    if (type != 0100000) return -FE_NOSYS;
    i32 fd = open_at(dirfd, path, 0100 | 0200 | 1, (u32)mode);  // O_CREAT | O_EXCL | O_WRONLY
    if (fd < 0) return fd;
    x_fd_close(fd);
    return 0;
}

// statfs / fstatfs: the host answers with the numbers of the folder that backs the path (struct statfs of musl, 88 bytes)
static i32 statfs_to(const char *abs, u32 size, u8 *buf) {
    u8 tmp[88] __attribute__((aligned(8)));
    for (i32 i = 0; i < 88; i++) tmp[i] = 0;
    i32 e = fs_statvfs(abs, slen(abs), tmp);
    if (e) return e;
    for (u32 i = 0; i < size && i < 88; i++) buf[i] = tmp[i];
    return 0;
}
EXPORT("__syscall_statfs64") i32 sc_statfs64(const char *path, u32 size, u8 *buf) {
    if (!path[0]) return -FE_NOENT;
    char *a = absdup(AT_FDCWD, path);
    i32 e = statfs_to(a, size, buf);
    free(a);
    return e;
}
EXPORT("__syscall_fstatfs64") i32 sc_fstatfs64(i32 fd, u32 size, u8 *buf) {
    i32 ft = fd_type(fd);
    if (ft < 0) return ft;
    char root[2];
    root[0] = '/', root[1] = 0;
    const char *p = fd_base_path(fd);  // a stream, a socket or a file deleted since: the guest's root
    i32 e = p ? statfs_to(p, size, buf) : -FE_NOENT;
    return e == -FE_NOENT ? statfs_to(root, size, buf) : e;
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
