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
// libffi's emscripten port (calls and closures), the local time zone, signals and the runtime's name: host operations
// (_host.py). ffi_call performs the call with the callee's real wasm type, as the JavaScript glue's
// `wasmTable.get(fn)(...args)` does; ffi_prep puts a host function into the closure's table slot.
LOADER("ffi_call") void host_ffi_call(const void *cif, u32 fn, void *rvalue, void **avalue);
LOADER("ffi_prep") i32 host_ffi_prep(void *closure, const void *cif, u32 fun, u32 user_data, u32 codeloc);
LOADER("ffi_slot") u32 host_ffi_slot(void);
LOADER("ffi_free") void host_ffi_free(u32 index);
LOADER("localtime") i32 host_localtime(i64 t, i32 *tm);  // tm_isdst and tm_gmtoff of the host's zone; 1 beyond Date's range
LOADER("mktime") i64 host_mktime(i32 *tm);
LOADER("tzset") void host_tzset(i32 *timezone, i32 *daylight, char *std_name, char *dst_name);
LOADER("sigcell") u32 *host_sigcell(void);  // the word where the host posts a signal for Python
LOADER("runtime") u32 host_runtime(void);   // a malloc'd string naming the runtime

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
#define FE_PERM 63
#define FE_NOSYS 52
#define FE_NOTDIR 54
#define FE_SPIPE 70
#define FE_XDEV 75
#define FE_OPNOTSUPP 138
// the host's view of the files: statvfs of the host folder of a preopen (named by its WASI descriptor) -> 0, or -errno;
// writes Emscripten's statfs64 (88 bytes). The host is never given a path of the guest.
#define FS(n) __attribute__((import_module("fs"), import_name(n)))
FS("statvfs") i32 fs_statvfs(i32 preopen_fd, u8 *buf);

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

// ---- what WASI has no place for: permission bits, owners, the umask and the original target of a symlink are
// session metadata kept here (like Pyodide's in-memory file system keeps them in its nodes), keyed by the file's
// (st_dev, st_ino): a hash table in one malloc'd block, its address in a wasm global. They live for the interpreter's
// lifetime and are not written to the host's file. A file with no record (it was there before the guest) gets the
// defaults of Pyodide (regular 0644, directory 0755, symlink 0777, the guest's root 0777).
// nrestrict counts the records whose mode forbids something (a file without read or write, a directory without read,
// write or search): while it is 0 no permission check is needed and the calls do not look at the modes at all.
typedef struct {
    u64 dev, ino;
    u32 mode, uid, gid;
    u8 used;    // 0 free, 1 live, 2 deleted
    u8 orphan;  // the file was unlinked while a descriptor of it is open: the record stays until the last close
    u8 isdir, restr;
    char *target;  // a symlink made with an absolute target: what the program stored (the link holds a relative one)
} Meta;
typedef struct {
    u32 cap, fill, live, umask, ntarget, nrestrict, norphan;
    u32 hasroot;
    u64 rdev, rino;  // the guest's root directory
    Meta *e;
} MetaT;
__asm__(".globaltype meta_state, i32\nmeta_state:\n");
static MetaT *mt(void) {
    MetaT *r;
    __asm__ volatile("global.get meta_state\n\tlocal.set %0" : "=r"(r));
    if (!r) {
        r = (MetaT *)calloc(1, sizeof(MetaT));
        r->umask = 022;
        u64 fs[8];
        if (!w_fd_filestat_get(PREOPEN, fs)) r->hasroot = 1, r->rdev = fs[0], r->rino = fs[1];
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
static i32 meta_grow(MetaT *t) {  // rebuild without the deleted ones, at a size that keeps the load under a half; 0, or ENOMEM
    u32 nc = t->cap ? t->cap : 256;
    while (t->live * 2 >= nc) nc *= 2;
    Meta *ne = (Meta *)calloc(nc, sizeof(Meta));
    if (!ne) return ENOMEM;
    for (u32 j = 0; j < t->cap; j++) {
        Meta *o = &t->e[j];
        if (o->used != 1) continue;
        u32 i = mhash(o->dev, o->ino) & (nc - 1);
        while (ne[i].used) i = (i + 1) & (nc - 1);
        ne[i].dev = o->dev, ne[i].ino = o->ino, ne[i].mode = o->mode, ne[i].uid = o->uid, ne[i].gid = o->gid;
        ne[i].used = 1, ne[i].orphan = o->orphan, ne[i].isdir = o->isdir, ne[i].restr = o->restr, ne[i].target = o->target;
    }
    if (t->e) free(t->e);
    t->e = ne;
    t->cap = nc;
    t->fill = t->live;
    return 0;
}
static void meta_notarget(MetaT *t, Meta *e) {
    if (e->target) {
        free(e->target);
        e->target = 0;
        t->ntarget--;
    }
}
static void meta_setmode(MetaT *t, Meta *e, u32 mode) {
    e->mode = mode;
    u8 r = e->isdir ? (!(mode & 0444) || !(mode & 0222) || !(mode & 0111)) : (!(mode & 0444) || !(mode & 0222));
    t->nrestrict += (u32)r - (u32)e->restr;
    e->restr = r;
}
// a new or replaced record (no symlink target); 0 when out of memory
static Meta *meta_put(u64 dev, u64 ino, u32 mode, u32 uid, u32 gid, u8 ft) {
    MetaT *t = mt();
    Meta *e = meta_find(dev, ino);
    if (!e) {
        if ((t->fill + 1) * 2 > t->cap && meta_grow(t)) return 0;
        u32 m = t->cap - 1, i = mhash(dev, ino) & m;
        while (t->e[i].used == 1) i = (i + 1) & m;
        e = &t->e[i];
        if (e->used == 0) t->fill++;
        t->live++;
        e->used = 1;
        e->dev = dev;
        e->ino = ino;
        e->target = 0;
        e->restr = 0;
        e->orphan = 0;
    }
    if (e->orphan) e->orphan = 0, t->norphan--;
    meta_notarget(t, e);
    e->isdir = ft == 3;
    e->uid = uid, e->gid = gid;
    meta_setmode(t, e, mode);
    return e;
}
static void meta_del(u64 dev, u64 ino) {
    MetaT *t = mt();
    Meta *e = meta_find(dev, ino);
    if (!e) return;
    meta_notarget(t, e);
    if (e->orphan) t->norphan--;
    t->nrestrict -= e->restr;
    e->used = 2;
    t->live--;
}
static u32 def_mode(u8 ft) { return ft == 3 ? 0755 : ft == 7 || ft == 5 || ft == 6 ? 0777 : ft == 2 || ft == 1 ? 0666 : 0644; }
static u32 def_for(const u8 *fs) {  // the mode of a file with no record: Pyodide's defaults (its root directory is 0777)
    MetaT *t = mt();
    if (fs[16] == 3 && t->hasroot && *(const u64 *)fs == t->rdev && *(const u64 *)(fs + 8) == t->rino) return 0777;
    return def_mode(fs[16]);
}
static u32 type_bits(u8 ft) {  // S_IF* of a WASI filetype
    return ft == 3 ? 0040000 : ft == 7 ? 0120000 : ft == 2 ? 0020000 : ft == 1 ? 0060000 : ft == 5 || ft == 6 ? 0140000 : 0100000;
}
static Meta *meta_for(const u8 *fs) {  // the record of the file whose WASI filestat is fs, made from the defaults; 0: no memory
    u64 dev = *(const u64 *)fs, ino = *(const u64 *)(fs + 8);
    Meta *e = meta_find(dev, ino);
    return e ? e : meta_put(dev, ino, def_for(fs), 0, 0, fs[16]);
}
// a file made now: its record is the mode asked, without the umask (if there is no memory for it the file has the defaults)
static void meta_created(const u8 *fs, u32 mode, u32 keep) {
    meta_put(*(const u64 *)fs, *(const u64 *)(fs + 8), mode & ~mt()->umask & keep, 0, 0, fs[16]);
}
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
    if (!mt()->nrestrict) return 0;
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
    if (st && !par) return ENOMEM;
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
// is a descriptor (other than `skip`) that this adapter opened still open on the file (dev, ino)?
static i32 fd_open_inode(u64 dev, u64 ino, i32 skip) {
    Fds *F = fds();
    for (i32 k = 0; k < MAXFD; k++) {
        u64 fs[8];
        if (k != skip && F->path[k] && !w_fd_filestat_get(k, fs) && fs[0] == dev && fs[1] == ino) return 1;
    }
    return 0;
}
// the last name of a file is gone: its record goes too, unless a descriptor still holds the file (an unlinked file keeps
// its mode until the last close; its inode can not be reused before)
static void meta_release(u64 dev, u64 ino) {
    Meta *e = meta_find(dev, ino);
    if (!e) return;
    if (fd_open_inode(dev, ino, -1)) {
        if (!e->orphan) e->orphan = 1, mt()->norphan++;
    } else {
        meta_del(dev, ino);
    }
}
// a descriptor is about to be closed: if it held an unlinked file, drop the record when it was the last one
static void meta_closing(i32 fd) {
    u64 fs[8];
    if (w_fd_filestat_get(fd, fs)) return;
    Meta *e = meta_find(fs[0], fs[1]);
    if (e && e->orphan && !fd_open_inode(fs[0], fs[1], fd)) meta_del(fs[0], fs[1]);
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
// The path to resolve (the path itself when it needs nothing, else a buffer of ours):
//  * a path relative to the cwd is made absolute (the cwd is kept here, WASI has none);
//  * ".." is resolved by WASI physically, and that is right except where WASI refuses it: above the root (Linux: "/.." is "/")
//    and out of a directory descriptor (WASI's sandbox is the descriptor). A chain of ".." that opens the path, from the
//    cwd (a physical path) or the root, is a plain lexical pop and is clamped here; a ".." after a name may follow a symlink,
//    so such a path is walked physically (phys(): readlink of every name) and the result is clamped at the real root;
//  * a relative path with ".." to a directory descriptor is left to WASI, and walked physically from the path the
//    descriptor was opened with only if WASI refuses it, and only if that path still names the same directory (a
//    renamed directory is not guessed at: the refusal stands).
static i32 phys(const char *base, const char *path, i32 follow, char **res);
static i32 resolve(i32 dirfd, const char *path, const char **out, i32 *len, char *dot);
static i32 lead_dots_only(const char *s) {  // every ".." comes before the first name
    i32 seen = 0;
    for (i32 i = 0; s[i];) {
        while (s[i] == '/') i++;
        i32 st = i;
        while (s[i] && s[i] != '/') i++;
        i32 l = i - st;
        if (l == 2 && s[st] == '.' && s[st + 1] == '.') {
            if (seen) return 0;
        } else if (l && !(l == 1 && s[st] == '.')) {
            seen = 1;
        }
    }
    return 1;
}
static const char *fixpath(i32 dirfd, const char *path) {
    Cwd *C = cwdst();
    i32 rel = path[0] != '/';
    i32 dd = has_dotdot(path);
    const char *base = 0;
    i32 byfd = rel && dirfd != AT_FDCWD;
    if (byfd) {
        u64 fs[8], gs[8];
        if (!dd || w_path_filestat_get(dirfd, 0, path, slen(path), fs) != FE_PERM) return path;
        base = fd_base_path(dirfd);
        char dot[2];
        const char *bp;
        i32 bn, bfd;
        if (!base) return path;
        bfd = resolve(AT_FDCWD, base, &bp, &bn, dot);
        if (w_fd_filestat_get(dirfd, fs) || w_path_filestat_get(bfd, 1, bp, bn, gs) || fs[0] != gs[0] || fs[1] != gs[1]) return path;
    } else if (rel) {
        base = C->cwd;
    }
    i32 compose = rel && !byfd && !(C->cwd[0] == '/' && C->cwd[1] == 0);
    if (!compose && !dd) return path;
    if (dd && (byfd || !lead_dots_only(path))) {
        char *r;
        if (!phys(base, path, 0, &r)) {
            u32 n = (u32)slen(r);
            char *o = slot(C->flip, n + 1);
            if (o) {
                C->flip ^= 1;
                for (u32 i = 0; i <= n; i++) o[i] = r[i];
                free(r);
                return o;
            }
            free(r);
        }
        if (byfd) return path;
    }
    i32 depth = base ? ncomp(base) : 0;
    u32 bl = compose ? (u32)slen(base) : 0;
    char *o = slot(C->flip, bl + (u32)slen(path) + 2);
    if (!o) return path;
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
// an absolute path (malloc'd, ".." resolved as above), or 0: the directory descriptor has no known path, or no memory
static char *absdup(i32 dirfd, const char *path) {
    if (path[0] == '/') {
        const char *f = fixpath(dirfd, path);
        return dupn(f, (u32)slen(f));
    }
    const char *base = dirfd == AT_FDCWD ? cwdst()->cwd : fd_base_path(dirfd);
    if (!base) return 0;
    u32 bl = (u32)slen(base), pl = (u32)slen(path);
    char *t = (char *)malloc(bl + pl + 2);
    if (!t) return 0;
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
    u32 mode = type_bits(ft) | (r ? r->mode : def_for(fs));
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
    if (!cur || !rest) {
        if (cur) free(cur);
        if (rest) free(rest);
        return ENOMEM;
    }
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
        if (!cand) {
            err = ENOMEM;
            break;
        }
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
            if (!tb) {
                e = ENOMEM;
                break;
            }
            e = w_path_readlink(fd, p, n, tb, (i32)cap, &used);
            if (e || used < (i32)cap) break;
            free(tb);
            cap *= 2;
        }
        if (e == ENOMEM) {
            free(cand);
            err = e;
            break;
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
        if (!nr) {
            free(tb);
            err = ENOMEM;
            break;
        }
        for (i32 j = 0; j < used; j++) nr[j] = tb[j];
        nr[used] = '/';
        for (u32 j = 0; j <= rl; j++) nr[used + 1 + (i32)j] = rest[i + (i32)j];
        if (tb[0] == '/') {
            free(cur);
            cur = dupn(sl, 1);
            if (!cur) {
                free(tb);
                free(nr);
                free(rest);
                return ENOMEM;
            }
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

// nocheck: dup() opens the same file again, which no permission can forbid
static i32 open_at(i32 dirfd, const char *path, i32 flags, u32 mode, i32 nocheck) {
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
    if (!nocheck && ((flags & 0100) || mt()->nrestrict)) {  // is it made now? if it exists, may it be opened (its recorded mode)?
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
    if (created) {
        i32 de = dir_denies(fd, p, n, 1);
        if (de) return -de;
    }
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
        u64 *ck = ckp(out);
        if (ck) *ck = 0;  // a new descriptor lists its directory from the start
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
    return open_at(dirfd, path, flags, va ? *(const u32 *)va : 0, 0);
}

// dup(): the same file opened again, at the same position (a copy of it: WASI 0.1 can not share the offset)
EXPORT("__syscall_dup") i32 sc_dup(i32 fd) {
    if (fd < 0 || fd >= MAXFD) return -EBADF;
    if (!fds()->path[fd]) {  // no path: a stream, a socket or a pipe (ENOSYS), unless it is no descriptor at all
        u8 st[24] __attribute__((aligned(8)));
        return !is_sock(fd) && w_fd_fdstat_get(fd, st) ? -EBADF : -52;
    }
    i32 flags = fds()->flags[fd] & ~(0100 | 0200 | 01000);       // not O_CREAT, O_EXCL, O_TRUNC again
    i32 nfd = open_at(AT_FDCWD, fds()->path[fd], flags, 0, 1);  // (the new descriptor's record is another one)
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
    if (newfd >= 0 && ckp(newfd)) *ckp(newfd) = 0;  // the cookie of the descriptor that was there is stale
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
    u32 bits = r ? r->mode : def_for((const u8 *)fs);
    if (((mode & 4) && !(bits & 0444)) || ((mode & 2) && !(bits & 0222)) || ((mode & 1) && !(bits & 0111))) return -FE_ACCES;
    return 0;
}

// WASI dirents {d_next u64, d_ino u64, d_namlen u32, d_type u8, name} -> linux_dirent64
// {d_ino u64, d_off i64, d_reclen u16, d_type u8, name\0, padded to 8}
EXPORT("__syscall_getdents64") i32 sc_getdents64(i32 fd, u8 *dirp, i32 count) {
    if (fd < 0) return -EBADF;
    u64 *ck = ckp(fd);
    if (!ck) return -ENOMEM;
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

static i32 is_sock(i32 fd);
WASI("fd_fdstat_get") i32 w_fd_fdstat_get(i32 fd, void *buf);
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
    i32 e = w_fd_seek(fd, off, whence, newoff);
    if (e != FE_BADF) return e;  // WASI refuses a directory descriptor (EBADF): that one is ours
    u8 st[24] __attribute__((aligned(8)));
    if (w_fd_fdstat_get(fd, st) || st[0] != 3) return e;
    u64 *ck = ckp(fd);
    if (!ck) return ENOMEM;
    i64 pos = whence == 1 ? (i64)*ck + off : off;  // SEEK_SET, SEEK_END (a directory has no size: as SET), SEEK_CUR
    if (whence < 0 || whence > 2 || pos < 0) return FE_INVAL;
    *ck = (u64)pos;
    *newoff = (u64)pos;
    return 0;
}

EXPORT("_emscripten_get_progname") void get_progname(char *buf, i32 len) {  // thisProgram, cut to len-1, always ended
    u64 w[2] = {0, 0};  // "./this.program" from integer constants (no data section)
    w[0] = 0x702e736968742f2eull, w[1] = 0x6d6172676f72ull;
    const char *name = (const char *)w;
    if (len <= 0) return;
    i32 i = 0;
    for (; i < len - 1 && name[i]; i++) buf[i] = name[i];
    buf[i] = 0;
}

static double now_ms(i32 clock) {
    u64 t = 0;
    w_clock_time_get(clock, 1000, &t);
    return (double)t / 1e6;
}
EXPORT("emscripten_date_now") double date_now(void) {  // Date.now(): whole milliseconds
    u64 t = 0;
    w_clock_time_get(0, 1000, &t);
    return (double)(t / 1000000ull);
}
EXPORT("emscripten_get_now") double get_now(void) { return now_ms(1); }
EXPORT("emscripten_get_heap_max") u32 heap_max(void) { return 0xFFFF0000u; }  // getHeapMax(): 4 GiB less a page

EXPORT("emscripten_resize_heap") i32 resize_heap(u32 n) {
    if (n > 0xFFFF0000u) return 0;  // beyond getHeapMax()
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
#define MAXDEPTH 1500
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

// emscripten_dlopen: the glue loads asynchronously and calls back from a promise; here the load is done at once
// and the callback follows (a callback is a table index: onsuccess(handle, user_data) or onerror(handle, user_data))
EXPORT("_emscripten_dlopen_js") void emscripten_dlopen_js(u8 *handle, u32 onsuccess, u32 onerror, u32 user_data) {
    u32 cb = dl_open(handle, 1) ? onsuccess : onerror;
    if (cb) ((void (*)(u32, u32))cb)((u32)handle, user_data);
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
        Vec *M = maps();
        if (m) m->addr = (u32)ptr, m->fd = sc_dup(fd);
        if (!m || !M || !vec_push(M, m)) {
            if (m && m->fd >= 0) x_fd_close(m->fd);
            free(m);
            free(ptr);
            return -48;  // ENOMEM
        }
        if (m->fd < 0) m->fd = -1;
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

// A closure is a block from malloc whose first word is its table slot; the host reuses freed slots (getEmptyTableSlot)
EXPORT("ffi_closure_alloc_js") u32 ffi_closure_alloc_js(u32 size, u32 *code) {
    u32 *closure = (u32 *)malloc(size);
    if (!closure) {
        *code = 0;
        return 0;
    }
    u32 slot = host_ffi_slot();
    *code = slot;
    *closure = slot;
    return (u32)closure;
}

EXPORT("ffi_closure_free_js") void ffi_closure_free_js(u32 *closure) {
    host_ffi_free(*closure);
    free(closure);
}

EXPORT("ffi_prep_closure_loc_js") i32 ffi_prep_closure_loc_js(void *closure, const void *cif, u32 fun, u32 user_data, u32 codeloc) {
    return host_ffi_prep(closure, cif, fun, user_data, codeloc);
}

// ================================================================== writing files (what installing a wheel needs)

EXPORT("__syscall_mkdirat") i32 sc_mkdirat(i32 dirfd, const char *path, i32 mode) {
    char dot[2];
    const char *p;
    i32 n, fd = resolve(dirfd, path, &p, &n, dot);
    i32 de = dir_denies(fd, p, n, 1);
    if (de) return -de;
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
    i32 de = dir_denies(fd, p, n, 0);
    if (de) return -de;
    i32 e = (flags & 0x200) ? w_rmdir(fd, p, n) : w_unlink(fd, p, n);  // AT_REMOVEDIR
    if (e) return -e;
    if (doomed) meta_release(key[0], key[1]);
    return 0;
}

EXPORT("__syscall_rmdir") i32 sc_rmdir(const char *path) { return sc_unlinkat(AT_FDCWD, path, 0x200); }

static void relink(i32 dirfd, const char *path);
static void relink_tree(const char *abs, i32 depth);
EXPORT("__syscall_renameat") i32 sc_renameat(i32 olddirfd, const char *oldpath, i32 newdirfd, const char *newpath) {
    char d1[2], d2[2];
    const char *p1, *p2;
    i32 n1, n2, f1 = resolve(olddirfd, oldpath, &p1, &n1, d1), f2 = resolve(newdirfd, newpath, &p2, &n2, d2);
    u64 key[2];
    i32 doomed = meta_doomed(f2, p2, n2, key);  // a file or directory that the rename replaces
    i32 de = dir_denies(f1, p1, n1, 0);
    if (!de) de = dir_denies(f2, p2, n2, 2);
    if (de) return -de;
    i32 e = w_rename(f1, p1, n1, f2, p2, n2);
    if (e) return -e;
    if (doomed) {
        u64 fs[8];
        if (w_path_filestat_get(f2, 0, p2, n2, fs) || fs[0] != key[0] || fs[1] != key[1]) meta_release(key[0], key[1]);
    }
    if (mt()->ntarget) {
        relink(newdirfd, newpath);  // a symlink with a stored absolute target is made again for its new place
        u64 ns[8];
        if (!w_path_filestat_get(f2, 0, p2, n2, ns) && *((u8 *)ns + 16) == 3) {  // a directory: every such link inside it too
            char *abs = absdup(newdirfd, newpath);
            if (abs) {
                relink_tree(abs, 0);
                free(abs);
            }
        }
    }
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
    *err = !ta || (!la && linkpath[0] == '/') ? ENOMEM : FE_BADF;
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
                if (!r) {
                    *err = ENOMEM;
                    goto done;
                }
                i32 k = 0;
                for (i32 i = 0; i < up; i++) r[k++] = '.', r[k++] = '.', r[k++] = '/';
                for (i32 i = 0; i < n2; i++) r[k++] = p2[i];
                if (k > 0 && r[k - 1] == '/') k--;
                r[k] = 0;
                if (k == 0) r[0] = '.', r[1] = 0;
            }
        }
    }
done:
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
    i32 de = dir_denies(fd, p, n, 1);
    if (de) {
        if (rel) free(rel);
        return -de;
    }
    i32 e = w_symlink(use, slen(use), fd, p, n);
    if (rel) free(rel);
    if (e) return -e;
    if (target[0] == '/') {  // remember what was stored
        u64 fs[8];
        if (!w_path_filestat_get(fd, 0, p, n, fs)) {
            Meta *m = meta_put(fs[0], fs[1], 0777, 0, 0, 7);
            char *tcopy = m ? dupn(target, (u32)slen(target)) : 0;
            if (tcopy) m->target = tcopy, mt()->ntarget++;
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
    if (!target) return;
    u32 mode = r->mode, uid = r->uid, gid = r->gid;
    u64 dev = fs[0], ino = fs[1];
    i32 err;
    char *rel = rel_target(dirfd, path, target, &err);
    if (rel) {
        fd = resolve(dirfd, path, &p, &n, dot);
        if (!w_unlink(fd, p, n) && !w_symlink(rel, slen(rel), fd, p, n)) {
            meta_del(dev, ino);
            if (!w_path_filestat_get(fd, 0, p, n, fs)) {
                Meta *m = meta_put(fs[0], fs[1], mode, uid, gid, 7);
                if (m) {
                    m->target = target;
                    mt()->ntarget++;
                    target = 0;
                }
            }
        }
        free(rel);
    }
    if (target) free(target);
}

// every symlink under the directory `abs` that has a stored absolute target is made again (symlinks are not followed)
static void relink_tree(const char *abs, i32 depth) {
    if (depth > 200) return;
    char dot[2];
    const char *p;
    i32 n, fd = resolve(AT_FDCWD, abs, &p, &n, dot), dfd = -1;
    u64 all = (1ull << 30) - 1;
    if (w_path_open(fd, 0, p, n, 2 /* O_DIRECTORY */, all & ~((1ull << 6) | (1ull << 22)), 0, 0, &dfd)) return;
    u32 cap = 4096;
    u8 *buf = (u8 *)malloc(cap);
    u64 cookie = 0;
    while (buf) {
        i32 used = 0;
        if (w_fd_readdir(dfd, buf, (i32)cap, cookie, &used) || used == 0) break;
        i32 in = 0;
        while (in + 24 <= used) {
            u64 next = *(u64 *)(buf + in);
            u32 nl = *(u32 *)(buf + in + 16);
            u8 ft = buf[in + 20];
            if (in + 24 + (i32)nl > used) break;
            char *name = dupn((const char *)buf + in + 24, nl);
            in += 24 + (i32)nl;
            cookie = next;
            if (!name) continue;
            if (!(nl == 1 && name[0] == '.') && !(nl == 2 && name[0] == '.' && name[1] == '.') && (ft == 7 || ft == 3)) {
                u32 al = (u32)slen(abs);
                char *child = (char *)malloc(al + nl + 2);
                if (child) {
                    for (u32 i = 0; i < al; i++) child[i] = abs[i];
                    u32 k = al;
                    if (k == 0 || child[k - 1] != '/') child[k++] = '/';
                    for (u32 i = 0; i <= nl; i++) child[k + i] = name[i];
                    if (ft == 7) relink(AT_FDCWD, child);
                    else relink_tree(child, depth + 1);
                    free(child);
                }
            }
            free(name);
        }
        if (in == 0) {  // one entry does not fit the buffer: a bigger one
            free(buf);
            cap *= 2;
            buf = (u8 *)malloc(cap);
        }
    }
    if (buf) free(buf);
    w_fd_close(dfd);
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
    Meta *r = meta_for((const u8 *)fs);
    if (!r) return -ENOMEM;
    meta_setmode(mt(), r, (u32)mode & 07777);
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

// ================================================================== ffi_call_js: ctypes calls
// libffi's emscripten port calls through JavaScript (`wasmTable.get(fn)(...args)`), which takes any callee type. The host
// does the same (loader.ffi_call: any arity, 64-bit, floats, structs, variadic calls).
EXPORT("ffi_call_js") void ffi_call_js(const void *cif, u32 fn, void *rvalue, void **avalue) { host_ffi_call(cif, fn, rvalue, avalue); }

// ================================================================== sockets: Emscripten's socket calls over the host's
// WASI preview1 cannot create or connect a socket, so the host gives a few operations; a socket is a guest
// descriptor (see the table below). The main module's fd_read / fd_write / fd_close / fd_fdstat_get come here first
// (OpenSSL reads and writes its socket with read() and write()); other descriptors pass on to WASI.
#define NET(n) __attribute__((import_module("net"), import_name(n)))
// The host reads and writes the guest's structures (sockaddr, msghdr, option values, addrinfo) itself: these take pointers.
NET("socket") i32 net_socket(i32 domain, i32 type, i32 proto);  // -> handle, or -errno
NET("bind") i32 net_bind(i32 h, const u8 *sa, i32 len);
NET("listen") i32 net_listen(i32 h, i32 backlog);
NET("accept") i32 net_accept(i32 h, u8 *sa, u32 *lenp, i32 nb);  // -> the new handle; the peer's address into sa, *lenp
NET("connect") i32 net_connect(i32 h, const u8 *sa, i32 len, i32 nb);  // nb: EINPROGRESS, the connection goes on
// flags are musl's MSG_*; the adapter adds MSG_DONTWAIT for a non-blocking socket, and the host then never waits
NET("sendto") i32 net_sendto(i32 h, const u8 *p, i32 n, i32 flags, const u8 *sa, i32 salen);
NET("recvfrom") i32 net_recvfrom(i32 h, u8 *p, i32 n, i32 flags, u8 *sa, u32 *lenp);
NET("sendmsg") i32 net_sendmsg(i32 h, const u32 *msg, i32 flags);
NET("recvmsg") i32 net_recvmsg(i32 h, u32 *msg, i32 flags);
NET("poll") i32 net_poll(i32 h, i32 events, i32 timeout_ms);  // -> revents
NET("pollv") i32 net_pollv(i32 n, const i32 *hs, const i32 *events, i32 timeout_ms, i32 *revents);  // several sockets at once
NET("close") i32 net_close(i32 h);
NET("shutdown") i32 net_shutdown(i32 h, i32 how);
NET("name") i32 net_name(i32 h, i32 peer, u8 *sa, u32 *lenp);  // the local or peer address
NET("getopt") i32 net_getopt(i32 h, i32 level, i32 opt, u8 *val, u32 *lenp);
NET("setopt") i32 net_setopt(i32 h, i32 level, i32 opt, const u8 *val, u32 len);
NET("ioctl") i32 net_ioctl(i32 h, i32 op, i32 *argp);  // FIONREAD
NET("resolve") i32 net_resolve(const char *name, i32 n, u8 *addr4);  // -> 0, or -errno
NET("getaddrinfo") i32 net_getaddrinfo(const char *node, const char *service, const i32 *hint, u32 *out);
NET("getnameinfo") i32 net_getnameinfo(const u8 *sa, i32 salen, char *node, i32 nodelen, char *serv, i32 servlen, i32 flags);
NET("protobyname") u32 net_protobyname(const char *name);

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
#define EFAULT_ 21
#define EINVAL_ 28
#define MSG_DONTWAIT 0x40
// a descriptor that is not a socket: EBADF if it is not open at all, else ENOTSOCK
static i32 notsock(i32 fd) {
    u8 st[24] __attribute__((aligned(8)));
    return w_fd_fdstat_get(fd, st) ? -EBADF : -ENOTSOCK_;
}
static i32 nbflag(i32 fd) { return sock_nb(fd) ? MSG_DONTWAIT : 0; }
// does the socket have what is asked (events: 1 read, 4 write)? An error or a hang-up is an answer too. EAGAIN if not
static i32 would_block(i32 fd, i32 flags, i32 events) {
    if (!sock_nb(fd) && !(flags & MSG_DONTWAIT)) return 0;
    return !(net_poll(hof(fd), events, 0) & (events | 8 | 16));
}

// a placeholder descriptor for a new socket: a directory opened, so the number is a real WASI one. -errno
static i32 sock_fd(void) {
    u64 all = (1ull << 30) - 1, writes = (1ull << 6) | (1ull << 0) | (1ull << 8) | (1ull << 22);
    i32 fd = -1;
    char dot[2];  // "." built on the stack: a string literal would be a data section
    dot[0] = '.', dot[1] = 0;
    i32 e = w_path_open(PREOPEN, 1, dot, 1, 2 /* O_DIRECTORY */, all & ~writes, 0, 0, &fd);
    if (e) return -33;  // EMFILE
    if (fd < 0 || fd >= MAXFD) {
        w_fd_close(fd);
        return -33;
    }
    return fd;
}

EXPORT("__syscall_socket") i32 sc_socket(i32 domain, i32 type, i32 proto, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    i32 fd = sock_fd();
    if (fd < 0) return fd;
    i32 h = net_socket(domain, type & ~(04000 | 02000000), proto);  // without SOCK_NONBLOCK, SOCK_CLOEXEC
    if (h < 0) {
        w_fd_close(fd);
        return h;
    }
    socks()->h[fd] = h + 1;
    socks()->nb[fd] = (type & 04000) != 0;  // SOCK_NONBLOCK
    return fd;
}

EXPORT("__syscall_bind") i32 sc_bind(i32 fd, const u8 *sa, i32 len, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    if (!is_sock(fd)) return notsock(fd);
    return net_bind(hof(fd), sa, len);
}

EXPORT("__syscall_listen") i32 sc_listen(i32 fd, i32 backlog, i32 a, i32 b, i32 c, i32 d) {
    (void)a, (void)b, (void)c, (void)d;
    if (!is_sock(fd)) return notsock(fd);
    return net_listen(hof(fd), backlog);
}

EXPORT("__syscall_accept4") i32 sc_accept4(i32 fd, u8 *sa, u32 *lenp, i32 flags, i32 a, i32 b) {
    (void)a, (void)b;
    if (!is_sock(fd)) return notsock(fd);
    if (flags & ~(04000 | 02000000)) return -EINVAL_;  // SOCK_NONBLOCK, SOCK_CLOEXEC
    if (would_block(fd, 0, 1)) return -EAGAIN_;
    i32 nfd = sock_fd();  // before the accept: no descriptor, the connection stays queued
    if (nfd < 0) return nfd;
    i32 h = net_accept(hof(fd), sa, lenp, sock_nb(fd));
    if (h < 0) {
        w_fd_close(nfd);
        return h;
    }
    socks()->h[nfd] = h + 1;
    socks()->nb[nfd] = (flags & 04000) != 0;
    return nfd;
}

EXPORT("__syscall_connect") i32 sc_connect(i32 fd, const u8 *sa, i32 len, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    if (!is_sock(fd)) return notsock(fd);
    return net_connect(hof(fd), sa, len, sock_nb(fd));
}

EXPORT("__syscall_sendto") i32 sc_sendto(i32 fd, const u8 *p, i32 n, i32 flags, const u8 *addr, i32 alen) {
    if (!is_sock(fd)) return notsock(fd);
    if (would_block(fd, flags, 4)) return -EAGAIN_;
    return net_sendto(hof(fd), p, n, flags | nbflag(fd), addr, alen);
}

EXPORT("__syscall_recvfrom") i32 sc_recvfrom(i32 fd, u8 *p, i32 n, i32 flags, u8 *addr, u32 *alen) {
    if (!is_sock(fd)) return notsock(fd);
    if (would_block(fd, flags, 1)) return -EAGAIN_;
    return net_recvfrom(hof(fd), p, n, flags | nbflag(fd), addr, alen);
}

// sendmsg / recvmsg: the iovecs and msg_name are the host's to read and write; no control data (msg_controllen stays 0,
// and a message that carries some is EOPNOTSUPP)
EXPORT("__syscall_sendmsg") i32 sc_sendmsg(i32 fd, const u32 *msg, i32 flags, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    if (!is_sock(fd)) return notsock(fd);
    if (would_block(fd, flags, 4)) return -EAGAIN_;
    return net_sendmsg(hof(fd), msg, flags | nbflag(fd));
}

EXPORT("__syscall_recvmsg") i32 sc_recvmsg(i32 fd, u32 *msg, i32 flags, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    if (!is_sock(fd)) return notsock(fd);
    if (would_block(fd, flags, 1)) return -EAGAIN_;
    return net_recvmsg(hof(fd), msg, flags | nbflag(fd));
}

EXPORT("__syscall_shutdown") i32 sc_shutdown(i32 fd, i32 how, i32 a, i32 b, i32 c, i32 d) {
    (void)a, (void)b, (void)c, (void)d;
    if (!is_sock(fd)) return notsock(fd);
    return net_shutdown(hof(fd), how);
}

EXPORT("__syscall_getpeername") i32 sc_getpeername(i32 fd, u8 *sa, u32 *lenp, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    if (!is_sock(fd)) return notsock(fd);
    if (!sa || !lenp) return -EFAULT_;
    return net_name(hof(fd), 1, sa, lenp);
}
EXPORT("__syscall_getsockname") i32 sc_getsockname(i32 fd, u8 *sa, u32 *lenp, i32 a, i32 b, i32 c) {
    (void)a, (void)b, (void)c;
    if (!is_sock(fd)) return notsock(fd);
    if (!sa || !lenp) return -EFAULT_;
    return net_name(hof(fd), 0, sa, lenp);
}

EXPORT("__syscall_getsockopt") i32 sc_getsockopt(i32 fd, i32 level, i32 opt, u8 *val, u32 *lenp, i32 a) {
    (void)a;
    if (!is_sock(fd)) return notsock(fd);
    if (!val || !lenp) return -EFAULT_;
    return net_getopt(hof(fd), level, opt, val, lenp);  // the host's real value; ENOPROTOOPT for an option it has not
}

// setsockopt is a stub INSIDE pyodide.asm.wasm (it returns 0); the build (tools/patch_main.mjs) turns it into this import
EXPORT("__syscall_setsockopt_host") i32 sc_setsockopt(i32 fd, i32 level, i32 opt, const u8 *val, u32 len, i32 a) {
    (void)a;
    if (!is_sock(fd)) return notsock(fd);
    return net_setopt(hof(fd), level, opt, val, len);
}

// struct pollfd {int fd; short events, revents;}. Sockets are polled by the host, all in one call, with the timeout;
// a file is always ready for what it is asked (POLLIN, POLLOUT); a descriptor that is not open is POLLNVAL; a negative
// one is ignored. A file that is ready, or an invalid descriptor, makes the sockets answer at once (nothing to wait for).
#define POLLNVAL 32
static i32 do_poll(u8 *fds, i32 n, i32 timeout) {
    if ((u32)n > MAXFD) return -EINVAL_;  // more entries than descriptors (RLIMIT_NOFILE)
    i32 ready = 0, nsock = 0, immediate = 0;
    i32 *buf = n > 0 ? (i32 *)malloc((u32)n * 3 * 4) : 0;  // handles, events, revents of the sockets
    i32 *hs = buf, *evs = buf + n, *revs = buf + 2 * n;
    for (i32 k = 0; k < n; k++) {
        i32 fd = *(i32 *)(fds + 8 * k);
        i16 ev = *(i16 *)(fds + 8 * k + 4), rev = 0;
        if (fd >= 0 && is_sock(fd)) {
            hs[nsock] = hof(fd), evs[nsock] = ev & 7, revs[nsock] = 0;  // POLLIN, POLLPRI, POLLOUT
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

// DNS, by the host. libc's gethostbyname has no way to fail through this call (Pyodide's JavaScript never fails: it
// makes up an address): a name the host cannot resolve gives INADDR_NONE (255.255.255.255), which no connection reaches.
EXPORT("_emscripten_lookup_name") u32 lookup_name(const char *name) {
    u8 a[4];
    if (net_resolve(name, slen(name), a)) return 0xffffffffu;
    return (u32)a[0] | ((u32)a[1] << 8) | ((u32)a[2] << 16) | ((u32)a[3] << 24);
}

// the whole list is one malloc'd block that freeaddrinfo (it frees the first node and its ai_addr) releases
EXPORT("getaddrinfo") i32 getaddrinfo_(const char *node, const char *service, const i32 *hint, u32 *out) {
    return net_getaddrinfo(node, service, hint, out);
}

EXPORT("getnameinfo") i32 getnameinfo_(const u8 *sa, i32 salen, char *node, i32 nodelen, char *serv, i32 servlen, i32 flags) {
    return net_getnameinfo(sa, salen, node, nodelen, serv, servlen, flags);
}

EXPORT("getprotobyname") u32 getprotobyname_(const char *name) { return net_protobyname(name); }

// ioctl as Pyodide's JavaScript answers: a descriptor that is not open is EBADF; FIONREAD and FIONBIO belong to
// sockets (a file has no ioctl: ENOTTY); the terminal requests are ENOTTY (no descriptor here is a terminal for
// them); anything else is EINVAL.
EXPORT("__syscall_ioctl") i32 sc_ioctl(i32 fd, i32 op, i32 va) {
    u8 st[24] __attribute__((aligned(8)));
    if (!is_sock(fd) && w_fd_fdstat_get(fd, st)) return -EBADF;
    i32 *argp = va ? *(i32 **)va : 0;  // va points at the variable arguments; the first is the argument's address
    if (op == 0x5421 || op == 0x541B) {  // FIONBIO, FIONREAD
        if (!is_sock(fd)) return -ENOTTY;
        if (!argp) return -21;  // EFAULT
        if (op == 0x541B) return net_ioctl(hof(fd), op, argp);
        sock_set_nb(fd, *argp != 0);
        return 0;
    }
    if ((op >= 0x5401 && op <= 0x5408) || op == 0x540B || op == 0x540F || op == 0x5410 || op == 0x5413 || op == 0x5414)
        return -ENOTTY;
    return -28;  // EINVAL
}

// the main module's WASI calls, for socket descriptors
EXPORT("fd_read") i32 x_fd_read(i32 fd, const u32 *iov, i32 n, i32 *nread) {
    if (!is_sock(fd)) return w_fd_read(fd, iov, n, nread);
    if (would_block(fd, 0, 1)) return EAGAIN_;
    i32 tot = 0;
    for (i32 k = 0; k < n; k++) {
        i32 r = net_recvfrom(hof(fd), (u8 *)iov[2 * k], (i32)iov[2 * k + 1], nbflag(fd), 0, 0);
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
        i32 r = net_sendto(hof(fd), (const u8 *)iov[2 * k], (i32)iov[2 * k + 1], nbflag(fd), 0, 0);
        if (r < 0) {
            if (tot) break;
            return -r;
        }
        tot += r;
        if (r < (i32)iov[2 * k + 1]) break;
    }
    *nw = tot;
    return 0;
}

EXPORT("fd_close") i32 x_fd_close(i32 fd) {
    if (!is_sock(fd)) {
        if (mt()->norphan) meta_closing(fd);
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

// ================================================================== time: Emscripten's JavaScript date helpers
// gmtime and timegm are integer arithmetic with what JavaScript's Date does to them: nothing beyond +-8.64e12 s (an error),
// V8's limits for the year and the month, and a year 0..99 read as 19xx by Date.UTC (so the day of the year, which JavaScript
// counts from Jan 1 of that 19xx, is wrong for the years 1..99: the same wrong number). localtime, mktime and tzset ask
// the host, which knows the time zone (_host.py, `_t_localtime`).
// struct tm: sec, min, hour, mday, mon, year, wday, yday, isdst (i32 each), gmtoff (long), zone.
#define DATE_LIMIT 8640000000000LL
static i64 days_from_civil(i64 y, i64 m, i64 d) {  // proleptic Gregorian, H. Hinnant's algorithm
    y -= m <= 2;
    i64 era = (y >= 0 ? y : y - 399) / 400;
    i64 yoe = y - era * 400;
    i64 doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
    i64 doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097 + doe - 719468;
}

static void fill_tm(i64 t, i32 *tm, i32 js_yday) {
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
    if (js_yday && y == -271821)  // Date.UTC(y, 0, 1) is NaN, and NaN | 0 is 0
        tm[7] = 0;
    else if (js_yday && y >= 0 && y <= 99)  // (date - Date.UTC(1900 + y, 0, 1)) / 864e5 | 0
        tm[7] = (i32)((t - days_from_civil(1900 + y, 1, 1) * 86400) / 86400);
    else
        tm[7] = (i32)(days - days_from_civil(y, 1, 1));
}

EXPORT("_gmtime_js") i32 gmtime_js(i64 t, i32 *tm) {
    if (t > DATE_LIMIT || t < -DATE_LIMIT) return 1;
    fill_tm(t, tm, 1);
    return 0;
}

EXPORT("_localtime_js") i32 localtime_js(i64 t, i32 *tm) {
    i32 off = host_localtime(t, tm);  // tm_isdst and tm_gmtoff; the exact offset east for the fields, INT_MIN: out of Date's range
    if (off == (i32)0x80000000) return 1;
    fill_tm(t + off, tm, 0);
    return 0;
}

// Date.UTC(...): -1 for NaN; only tm_wday and tm_yday are written
EXPORT("_timegm_js") i64 timegm_js(i32 *tm) {
    i64 y = (i64)tm[5] + 1900, mon = tm[4];
    if (y >= 0 && y <= 99) y += 1900;
    if (y < -1000000 || y > 1000000 || mon < -10000000 || mon > 10000000) return -1;
    y += mon >= 0 ? mon / 12 : -((11 - mon) / 12);
    mon = ((mon % 12) + 12) % 12;
    i64 t = (days_from_civil(y, mon + 1, 1) + tm[3] - 1) * 86400 + (i64)tm[2] * 3600 + (i64)tm[1] * 60 + tm[0];
    if (t > DATE_LIMIT || t < -DATE_LIMIT) return -1;
    i32 f[10];
    fill_tm(t, f, 1);
    tm[6] = f[6], tm[7] = f[7];
    return t;
}

EXPORT("_mktime_js") i64 mktime_js(i32 *tm) { return host_mktime(tm); }

EXPORT("_tzset_js") void tzset_js(i32 *timezone, i32 *daylight, char *std_name, char *dst_name) {
    host_tzset(timezone, daylight, std_name, dst_name);
}

// ================================================================== owners, nodes, messages, failures
// chown: any uid and gid is accepted (the process is root of a single-user world) and recorded; -1 leaves one as it is
static i32 set_owner(const u64 *fs, i32 uid, i32 gid) {
    Meta *r = meta_for((const u8 *)fs);
    if (!r) return -ENOMEM;
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
    i32 fd = open_at(dirfd, path, 0100 | 0200 | 1, (u32)mode, 0);  // O_CREAT | O_EXCL | O_WRONLY
    if (fd < 0) return fd;
    x_fd_close(fd);
    return 0;
}

// statfs / fstatfs: the host answers with the numbers of the folder that backs the path (struct statfs of musl, 88 bytes)
static i32 statfs_to(i32 preopen, u32 size, u8 *buf) {
    u8 tmp[88] __attribute__((aligned(8)));
    for (i32 i = 0; i < 88; i++) tmp[i] = 0;
    i32 e = fs_statvfs(preopen, tmp);
    if (e) return e;
    for (u32 i = 0; i < size && i < 88; i++) buf[i] = tmp[i];
    return 0;
}
EXPORT("__syscall_statfs64") i32 sc_statfs64(const char *path, u32 size, u8 *buf) {
    u64 fs[8];
    i32 e = fx_lookup(AT_FDCWD, path, 1, fs);  // the path exists, as WASI (sandboxed) sees it, or this is its error
    if (e) return -e;
    char dot[2];
    const char *p;
    i32 n, pre = resolve(AT_FDCWD, path, &p, &n, dot);  // the preopen the path belongs to
    return statfs_to(pre, size, buf);
}
EXPORT("__syscall_fstatfs64") i32 sc_fstatfs64(i32 fd, u32 size, u8 *buf) {
    i32 ft = fd_type(fd);
    if (ft < 0) return ft;
    const char *bp = fd_base_path(fd);  // a stream, a socket, or no path known: the guest's root
    char dot[2];
    const char *p;
    i32 n, pre = PREOPEN;
    if (bp) pre = resolve(AT_FDCWD, bp, &p, &n, dot);
    return statfs_to(pre, size, buf);
}

// system(): there are no processes. Outside Node the JavaScript glue answers system(NULL) 0 (no shell) and ENOSYS to a
// command; Pyodide on Node runs the command with a shell, which here would be a way out of the guest.
EXPORT("_emscripten_system") i32 sc_system(const char *cmd) { return cmd ? -52 : 0; }

// abort() and a failed assert() end the program with the message of the JavaScript glue (Aborted(...)) on stderr and a
// trap. The text is built from integer constants (no data section).
static void err_n(const void *s, i32 n) {
    u32 iov[2];
    iov[0] = (u32)s, iov[1] = (u32)n;
    i32 w;
    w_fd_write(2, iov, 1, &w);
}
static void err_lit(i32 n, u64 a, u64 b, u64 c, u64 d) {  // the first n bytes of a, b, c, d (little-endian)
    u64 m[4];
    m[0] = a, m[1] = b, m[2] = c, m[3] = d;
    err_n(m, n);
}
EXPORT("__assert_fail") void sc_assert_fail(const char *cond, const char *file, i32 line, const char *func) {
    err_lit(26, 0x28646574726f6241ull, 0x6f69747265737341ull, 0x64656c696166206eull, 0x203aull);  // "Aborted(Assertion failed: "
    if (cond) err_n(cond, slen(cond));
    err_lit(6, 0x203a7461202cull, 0, 0, 0);  // ", at: "
    if (file) err_n(file, slen(file));
    else err_lit(16, 0x206e776f6e6b6e75ull, 0x656d616e656c6966ull, 0, 0);  // "unknown filename"
    err_lit(1, 0x2cull, 0, 0, 0);  // ","
    char num[12];
    i32 k = 12;
    u32 v = line < 0 ? (u32)-line : (u32)line;
    do num[--k] = (char)('0' + v % 10), v /= 10;
    while (v);
    if (line < 0) num[--k] = '-';
    err_n(num + k, 12 - k);
    err_lit(1, 0x2cull, 0, 0, 0);
    if (func) err_n(func, slen(func));
    else err_lit(16, 0x206e776f6e6b6e75ull, 0x6e6f6974636e7566ull, 0, 0);  // "unknown function"
    err_lit(2, 0xa29ull, 0, 0, 0);                                         // ")\n"
    __builtin_trap();
}
EXPORT("_abort_js") void sc_abort_js(void) {
    err_lit(10, 0x28646574726f6241ull, 0xa29ull, 0, 0);  // "Aborted()\n"
    __builtin_trap();
}

// ================================================================== signals and timers
// raise() and kill(getpid()) call the handler the program set (Python's, which notes the signal); the host can post one
// for Python too (Pyodide.interrupt: JavaScript's Py_EmscriptenSignalBuffer), and a timer the program armed
// (setitimer, alarm) is checked when Python looks for signals, since there is no event loop here to fire it.
EXPORT("__call_sighandler") void call_sighandler(u32 fp, i32 sig) { ((void (*)(i32))fp)(sig); }

typedef struct {
    u32 *cell;          // where the host posts a signal number
    double deadline[3];  // ITIMER_REAL, VIRTUAL, PROF: when it fires (get_now's clock), 0: not armed
} Sig;
__asm__(".globaltype sig_state, i32\nsig_state:\n");
static Sig *sigst(void) {
    Sig *r;
    __asm__ volatile("global.get sig_state\n\tlocal.set %0" : "=r"(r));
    if (!r) {
        r = (Sig *)calloc(1, sizeof(Sig));
        r->cell = host_sigcell();
        __asm__ volatile("local.get %0\n\tglobal.set sig_state" : : "r"(r));
    }
    return r;
}

EXPORT("_setitimer_js") i32 setitimer_js(i32 which, double timeout_ms) {
    if ((u32)which > 2) return 0;
    sigst()->deadline[which] = timeout_ms != 0 ? now_ms(1) + timeout_ms : 0;
    if (timeout_ms != 0) {  // Python looks for signals only when the main module's byte says so (what setInterruptBuffer sets)
        u64 nm[4];
        nm[0] = 0x5243534d455f7950ull, nm[1] = 0x49535f4e45545049ull, nm[2] = 0x4e41485f4c414e47ull, nm[3] = 0x474e494c44ull;  // "Py_EMSCRIPTEN_SIGNAL_HANDLING"
        u32 out[2], addr = dl_sym(0, (const char *)nm, 29, out);
        if (out[0] == 1) *(u8 *)addr = 1;
    }
    return 0;
}

EXPORT("_Py_CheckEmscriptenSignals_Helper") i32 check_signals(void) {
    Sig *s = sigst();
    for (i32 which = 0; which < 3; which++) {
        if (s->deadline[which] == 0) continue;
        double now = now_ms(1);
        if (now < s->deadline[which]) continue;
        s->deadline[which] = 0;
        u64 nm[3];
        nm[0] = 0x70697263736d655full, nm[1] = 0x656d69745f6e6574ull, nm[2] = 0x74756full;  // "_emscripten_timeout" (libc's, re-arms an interval)
        u32 out[2], slot = dl_sym(0, (const char *)nm, 19, out);
        if (out[0] == 2 || out[0] == 3) ((void (*)(i32, double))slot)(which, now);  // 3: a slot made by this lookup
    }
    i32 v = (i32)*s->cell;
    *s->cell = 0;
    return v;
}

// sys._emscripten_info.runtime
EXPORT("_Py_emscripten_runtime") u32 runtime_name(void) { return host_runtime(); }
