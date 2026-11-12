// Owners, nodes, messages, failures. Included only by adapter.c.
#ifndef ADAPTER_OWNERS_H
#define ADAPTER_OWNERS_H

#include "common.h"
#include "state.h"
#include "metadata.h"
#include "openfiles.h"
#include "log.h"
#include "sockets.h"

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
    if (dev_fs(fd, fs)) return set_owner(fs, uid, gid);
    if (is_virt(fd)) return 0;  // (a socket or a pipe has no owner here, and no WASI descriptor to ask)
    i32 e = w_fd_filestat_get(rfd(fd), fs);
    if (e) return -e;
    return set_owner(fs, uid, gid);
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
    w_fd_close(fd);  // (a WASI descriptor of ours, no guest number)
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

#endif
