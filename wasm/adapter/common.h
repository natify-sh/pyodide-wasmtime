// Types, macros, errno constants, WASI and host imports, forward declarations. Included only by adapter.c.
#ifndef ADAPTER_COMMON_H
#define ADAPTER_COMMON_H

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
WASI("clock_res_get") i32 w_clock_res_get(i32 id, u64 *out);

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
// libffi's emscripten port (calls and closures), the local time zone, signals: host operations
// (_host.py). ffi_call performs the call with the callee's real wasm type, as the JavaScript glue's
// `wasmTable.get(fn)(...args)` does; ffi_prep puts a host function into the closure's table slot.
LOADER("ffi_call") void host_ffi_call(const void *cif, u32 fn, void *rvalue, void **avalue);
LOADER("ffi_prep") i32 host_ffi_prep(void *closure, const void *cif, u32 fun, u32 user_data, u32 codeloc);
LOADER("ffi_slot") u32 host_ffi_slot(void);
LOADER("ffi_free") void host_ffi_free(u32 index);
LOADER("localtime") i32 host_localtime(i64 t, i32 *tm);  // tm_isdst and tm_gmtoff of the host's zone; 1 beyond Date's range
LOADER("mktime") i64 host_mktime(i32 *tm);
LOADER("tzset") void host_tzset(i32 *timezone, i32 *daylight, char *std_name, char *dst_name);
LOADER("depth") i32 host_depth(void);       // how many NEEDED libraries may nest (the wasm stack in force decides)
LOADER("cpuclock") i32 host_cpuclock(i32 id, i32 res, u64 *out);  // the host's CPU time of the process (2) or thread (3), in ns; res: its resolution. -> an errno

#define AT_FDCWD (-100)
#define PREOPEN 3
#define ENOTTY 59
#define ERANGE 68
#define EBADF 8
#define ENOMEM 48
#define MAXFD 4096  // the guest's descriptor numbers are 0..MAXFD-1 (Pyodide's MAX_OPEN_FDS is 4096 too)
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

#endif
