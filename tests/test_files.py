"""Offline, both builds: files and their metadata (stat, modes, owners, umask, times, links, directories, statfs).

WASI has no chmod, chown or umask: the adapter keeps them for the interpreter's lifetime (a table keyed by the device
and inode); everything else is WASI's. Each test runs a small program in the guest that asserts what Pyodide (and Linux)
answer; a failed assertion is a traceback and exit status 1.
"""

from __future__ import annotations

from conftest import Guest

HEAD = """\
import os, stat, errno, shutil, ctypes, fcntl, sys
libc = ctypes.CDLL(None, use_errno=True)
B = '/tmp/fx'
shutil.rmtree(B, ignore_errors=True)
os.makedirs(B)

def err(f, *a, **k):
    try:
        f(*a, **k)
    except OSError as e:
        return errno.errorcode[e.errno]
    return None
"""


def check(guest: Guest, code: str, **kw: str) -> None:
    p = guest.run(HEAD + code + "\nprint('ok')", None, *[x for k, v in kw.items() for x in (k, v)])
    assert p.returncode == 0, p.stderr[-3000:]
    assert p.stdout.split() == ["ok"], p.stdout + p.stderr[-2000:]


def test_umask_is_stored_and_applied_to_new_files(guest: Guest):
    check(
        guest,
        """
assert (os.umask(0o77), os.umask(0o22), os.umask(0o22)) == (0o22, 0o77, 0o22)
fd = os.open(B + '/m', os.O_CREAT | os.O_RDWR, 0o600)
assert stat.S_IMODE(os.fstat(fd).st_mode) == 0o600
os.umask(0o27)
os.close(os.open(B + '/m2', os.O_CREAT | os.O_RDWR, 0o666))
os.mkdir(B + '/d', 0o777)
assert libc.mknod((B + '/n').encode(), 0o100666, 0) == 0
assert [oct(os.stat(B + p).st_mode) for p in ('/m2', '/d', '/n')] == ['0o100640', '0o40750', '0o100640']
os.umask(0o22)
os.close(os.open(B + '/m2', os.O_CREAT | os.O_RDWR, 0o777))  # it exists: its mode is not touched
assert oct(os.stat(B + '/m2').st_mode) == '0o100640'
assert oct(os.stat(B).st_mode) == '0o40755'  # a folder the guest did not make: the default
""",
    )


def test_chmod_fchmod_access_and_open_follow_the_recorded_mode(guest: Guest):
    check(
        guest,
        """
open(B + '/f', 'w').close()
os.chmod(B + '/f', 0o751)
assert oct(os.stat(B + '/f').st_mode) == '0o100751'
fd = os.open(B + '/f', os.O_RDONLY)
os.fchmod(fd, 0o640)
assert oct(os.fstat(fd).st_mode) == '0o100640'
os.chmod('f', 0o444, dir_fd=os.open(B, os.O_RDONLY))
assert oct(os.stat(B + '/f').st_mode) == '0o100444'
assert err(os.chmod, B + '/nope', 0o600) == 'ENOENT'
assert err(os.fchmod, 5000, 0o600) == 'EBADF'
os.chmod(B + '/f', 0)
assert [os.access(B + '/f', m) for m in (os.R_OK, os.W_OK, os.X_OK, os.F_OK)] == [False, False, False, True]
libc.faccessat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
assert libc.faccessat(-100, (B + '/f').encode(), 8, 0) == -1 and ctypes.get_errno() == errno.EINVAL
assert err(open, B + '/f') == 'EACCES'
os.chmod(B + '/f', 0o444)
assert err(os.open, B + '/f', os.O_WRONLY | os.O_TRUNC) == 'EACCES'
assert err(os.open, B + '/f', os.O_RDWR) == 'EACCES'
assert err(os.close, os.open(B + '/f', os.O_RDONLY)) is None
assert os.access(B + '/f', os.R_OK) and not os.access(B + '/f', os.W_OK)
os.mkdir(B + '/nox', 0o600)
assert err(os.chdir, B + '/nox') == 'EACCES'
""",
    )


def test_a_directory_without_write_or_search_permission_refuses_changes(guest: Guest):
    check(
        guest,
        """
os.mkdir(B + '/d')
open(B + '/d/f', 'w').close()
os.mkdir(B + '/d/sub')
os.mkdir(B + '/other')
os.chmod(B + '/d', 0o555)
assert err(os.mkdir, B + '/d/new') == 'EACCES'
assert err(os.open, B + '/d/new', os.O_CREAT | os.O_WRONLY) == 'EACCES'
assert err(os.unlink, B + '/d/f') == 'EACCES'
assert err(os.rmdir, B + '/d/sub') == 'EACCES'
assert err(os.rename, B + '/d/f', B + '/other/f') == 'EACCES'
assert err(os.rename, B + '/other', B + '/d/other') == 'EACCES'
assert err(os.symlink, 'f', B + '/d/l') == 'EACCES'
assert err(os.symlink, B + '/f', B + '/d/l') == 'EACCES'
# the existing name or the missing one is reported first, as the system call does
assert err(os.mkdir, B + '/d/sub') == 'EEXIST' and err(os.unlink, B + '/d/nope') == 'ENOENT'
assert err(os.open, B + '/d/f', os.O_RDONLY) is None  # reading a file in it is allowed
os.chmod(B + '/d', 0o755)
os.mkdir(B + '/d/new')
os.chmod(B + '/d', 0o700 & ~0o100)  # no search permission either
assert err(os.mkdir, B + '/d/new2') == 'EACCES'
os.chmod(B + '/d', 0o755)
os.unlink(B + '/d/f')
os.rmdir(B + '/d/sub')
shutil.rmtree(B + '/d')
""",
    )


def test_chown_is_recorded_and_stat_shows_it(guest: Guest):
    check(
        guest,
        """
open(B + '/f', 'w').close()
os.chown(B + '/f', 1000, 1001)
st = os.stat(B + '/f')
assert (st.st_uid, st.st_gid) == (1000, 1001)
os.chown(B + '/f', -1, 5)
st = os.stat(B + '/f')
assert (st.st_uid, st.st_gid) == (1000, 5)
fd = os.open(B + '/f', os.O_RDONLY)
os.fchown(fd, 7, 8)
st = os.fstat(fd)
assert (st.st_uid, st.st_gid) == (7, 8)
assert err(os.chown, B + '/nope', 0, 0) == 'ENOENT'
assert err(os.fchown, 5000, 0, 0) == 'EBADF'
""",
    )


def test_stat_types_and_empty_and_dotdot_paths(guest: Guest):
    check(
        guest,
        """
assert [oct(os.fstat(i).st_mode) for i in (0, 1, 2)] == ['0o20666'] * 3
assert stat.S_ISCHR(os.fstat(1).st_mode)
assert err(os.stat, '') == 'ENOENT' and err(os.lstat, '') == 'ENOENT'
assert err(os.stat, '', dir_fd=os.open(B, os.O_RDONLY)) == 'ENOENT'
os.chdir('/')
assert os.stat('/..').st_ino == os.stat('/').st_ino == os.stat('..').st_ino
assert os.stat('/../../tmp').st_ino == os.stat('/tmp').st_ino
assert os.stat(B + '/../../../../../../../../../tmp').st_ino == os.stat('/tmp').st_ino
os.chdir(B)
assert os.stat('../../../..').st_ino == os.stat('/').st_ino
d = os.open(B, os.O_RDONLY)
assert os.stat('../../../../../tmp', dir_fd=d).st_ino == os.stat('/tmp').st_ino
os.chdir('/..')
assert os.getcwd() == '/'
s = os.stat(B)
assert s.st_ino > 0 and s.st_dev > 0 and os.fstat(d).st_dev == s.st_dev and os.fstat(d).st_ino == s.st_ino
os.symlink('f', B + '/l')
assert stat.S_ISLNK(os.lstat(B + '/l').st_mode) and oct(os.lstat(B + '/l').st_mode) == '0o120777'
""",
    )


def test_long_paths_have_no_wrong_answer(guest: Guest):
    check(
        guest,
        """
deep = B + '/' + 'q/' * 400  # 800 bytes beyond the old 1024-byte buffers once the cwd is added
os.makedirs(deep)
os.chdir(deep)
assert len(os.getcwd()) > 800
open('f', 'w').write('hi')
for _ in range(2):
    os.chdir('..')
os.chdir(B)
for _ in range(400):
    os.chdir('q')
assert open('f').read() == 'hi' and os.path.exists(deep + 'f')
assert not os.path.exists('x')  # not the root's: the cwd + the name, not the name alone
assert os.read(os.dup(os.open(deep + 'f', os.O_RDONLY)), 2) == b'hi'  # dup() keeps a path of any length
os.chdir('/')
assert err(os.chdir, '/' + 'a/' * 600) == 'ENOENT'
assert err(os.stat, '/' + 'a/' * 3000) == 'ENAMETOOLONG'
""",
    )


def test_chdir_is_physical(guest: Guest):
    check(
        guest,
        """
os.makedirs(B + '/real/sub')
os.symlink('real/sub', B + '/ln')
os.chdir(B + '/ln')
assert os.getcwd() == B + '/real/sub'
os.chdir('..')
assert os.getcwd() == B + '/real'
os.chdir('/')
os.symlink(B + '/real/sub', B + '/abs')
os.chdir(B + '/abs')
assert os.getcwd() == B + '/real/sub'
os.chdir('/')
fd = os.open(B + '/real', os.O_RDONLY)
os.fchdir(fd)
assert os.getcwd() == B + '/real'
os.chdir('/')
assert err(os.fchdir, os.open(B + '/real/..', os.O_RDONLY)) is None
os.chdir('/')
open(B + '/file', 'w').close()
assert err(os.chdir, B + '/file') == 'ENOTDIR' and err(os.chdir, B + '/nope') == 'ENOENT'
assert err(os.chdir, '') == 'ENOENT'
assert err(os.fchdir, os.open(B + '/file', os.O_RDONLY)) == 'ENOTDIR'
assert err(os.fchdir, 1) == 'ENOTDIR' and err(os.fchdir, 5000) == 'EBADF'
os.symlink('l2', B + '/l1')
os.symlink('l1', B + '/l2')
assert err(os.chdir, B + '/l1') == 'ELOOP'
assert os.getcwd() == '/'
""",
    )


def test_absolute_symlinks_work_and_read_back_as_stored(guest: Guest):
    check(
        guest,
        """
os.makedirs(B + '/a/b/c')
open(B + '/x', 'w').write('X')
os.symlink(B + '/a/b', B + '/lab')
assert os.readlink(B + '/lab') == B + '/a/b' and os.path.isdir(B + '/lab') and os.listdir(B + '/lab') == ['c']
assert os.lstat(B + '/lab').st_size == len(B + '/a/b')
os.symlink(B + '/x', B + '/a/b/lx')  # from another depth
assert os.readlink(B + '/a/b/lx') == B + '/x' and open(B + '/lab/lx').read() == 'X'
os.symlink('/', B + '/root')
assert os.readlink(B + '/root') == '/' and os.path.isdir(B + '/root/tmp')
os.symlink('/nope/x', B + '/dang')
assert os.readlink(B + '/dang') == '/nope/x' and not os.path.exists(B + '/dang') and os.path.lexists(B + '/dang')
os.chdir(B)
os.symlink(B + '/x', 'rel')  # a relative link name, with an absolute target
assert open('rel').read() == 'X' and os.readlink('rel') == B + '/x'
os.chdir('/')
libc.symlinkat.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p]
assert libc.symlinkat((B + '/x').encode(), os.open(B + '/a', os.O_RDONLY), b'ld') == 0  # os.symlink has no dir_fd here
assert open(B + '/a/ld').read() == 'X' and os.readlink(B + '/a/ld') == B + '/x'
os.mkdir(B + '/other')
os.rename(B + '/lab', B + '/other/lab')  # the link is made again for its new place
assert os.readlink(B + '/other/lab') == B + '/a/b' and sorted(os.listdir(B + '/other/lab')) == ['c', 'lx']
shutil.copytree(B + '/other', B + '/copy', symlinks=True)
assert os.readlink(B + '/copy/lab') == B + '/a/b' and os.path.isdir(B + '/copy/lab')
os.unlink(B + '/other/lab')
assert not os.path.lexists(B + '/other/lab')
""",
    )


def test_directory_descriptors_seek_and_list_past_1024(guest: Guest):
    check(
        guest,
        """
os.mkdir(B + '/d')
for i in range(5):
    open(B + '/d/e%d' % i, 'w').close()
libc.opendir.restype = libc.readdir.restype = libc.fdopendir.restype = ctypes.c_void_p
libc.opendir.argtypes = [ctypes.c_char_p]
libc.readdir.argtypes = [ctypes.c_void_p]
libc.fdopendir.argtypes = [ctypes.c_int]
libc.telldir.argtypes = [ctypes.c_void_p]
libc.telldir.restype = ctypes.c_long

def count(d):
    n = 0
    while libc.readdir(d):
        n += 1
    return n

def seekdir(d, off):  # musl's seekdir/rewinddir: lseek the descriptor and drop the buffer
    os.lseek(ctypes.c_int.from_address(d + 8).value, off, 0)
    ctypes.c_int.from_address(d + 12).value = 0
    ctypes.c_int.from_address(d + 16).value = 0

d = libc.opendir((B + '/d').encode())
n = count(d)
assert n == 7  # five names, "." and ".."
seekdir(d, 0)
assert count(d) == n  # rewinddir
seekdir(d, 0)
for _ in range(3):
    libc.readdir(d)
t = libc.telldir(d)
rest = count(d)
assert rest == n - 3
seekdir(d, t)
assert count(d) == rest  # seekdir(telldir)
fd = os.open(B + '/d', os.O_RDONLY)
assert (os.lseek(fd, 0, 0), os.lseek(fd, 7, 0), os.lseek(fd, 2, 1)) == (0, 7, 9)
assert err(os.lseek, fd, -1, 0) == 'EINVAL'
# a descriptor above 1024 lists its directory (the cookie table has no fixed size)
fds = [os.open(B + '/d', os.O_RDONLY) for _ in range(1100)]
big = fds[-1]
assert big > 1023 and count(libc.fdopendir(big)) == n
for f in fds[:-1]:
    os.close(f)
""",
    )


def test_dup2_onto_a_directory_resets_its_listing(guest: Guest):
    check(
        guest,
        """
os.mkdir(B + '/d')
for i in range(3):
    open(B + '/d/e%d' % i, 'w').close()
libc.fdopendir.restype = libc.readdir.restype = ctypes.c_void_p
libc.fdopendir.argtypes = [ctypes.c_int]
libc.readdir.argtypes = [ctypes.c_void_p]

def count(d):
    n = 0
    while libc.readdir(d):
        n += 1
    return n

a = os.open(B + '/d', os.O_RDONLY)
b = os.open(B + '/d', os.O_RDONLY)
assert count(libc.fdopendir(b)) == 5  # b is at its end now
os.dup2(a, b)
assert count(libc.fdopendir(b)) == 5
""",
    )


def test_utimensat_sets_the_times(guest: Guest):
    check(
        guest,
        """
import time
open(B + '/f', 'w').close()
os.utime(B + '/f', (1_000_000_000, 1_500_000_000))
s = os.stat(B + '/f')
assert (s.st_atime, s.st_mtime) == (1e9, 1.5e9)
os.utime(B + '/f', ns=(1000000001, 2000000002))
s = os.stat(B + '/f')
assert (s.st_atime_ns, s.st_mtime_ns) in ((1000000001, 2000000002), (1000000000, 2000000000))
assert err(os.utime, B + '/nope', (1, 1)) == 'ENOENT'
fd = os.open(B + '/f', os.O_RDONLY)
os.utime(fd, (5, 6))
assert (os.fstat(fd).st_atime, os.fstat(fd).st_mtime) == (5.0, 6.0)
os.utime(B + '/f', None)
assert abs(os.stat(B + '/f').st_mtime - time.time()) < 100
os.utime(B, (100, 200))
assert os.stat(B).st_mtime == 200
class TS(ctypes.Structure):
    _fields_ = [('s', ctypes.c_longlong), ('n', ctypes.c_long)]
libc.utimensat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int]
os.utime(B + '/f', (11, 22))
omit = (TS * 2)(TS(0, 0x3FFFFFFE), TS(33, 0))  # UTIME_OMIT, then a time
assert libc.utimensat(-100, (B + '/f').encode(), omit, 0) == 0
s = os.stat(B + '/f')
assert (s.st_atime, s.st_mtime) == (11.0, 33.0)
now = (TS * 2)(TS(0, 0x3FFFFFFF), TS(44, 0))  # UTIME_NOW, then a time
assert libc.utimensat(-100, (B + '/f').encode(), now, 0) == 0
s = os.stat(B + '/f')
assert abs(s.st_atime - time.time()) < 100 and s.st_mtime == 44.0
os.symlink('f', B + '/l')
assert libc.utimensat(-100, (B + '/l').encode(), (TS * 2)(TS(7, 0), TS(8, 0)), 0x100) == 0  # AT_SYMLINK_NOFOLLOW
assert os.lstat(B + '/l').st_mtime == 8.0 and os.stat(B + '/f').st_mtime == 44.0
""",
    )


def test_statvfs_and_fstatvfs_come_from_the_host(guest: Guest, tmp_path):
    host = tmp_path / "h"
    host.mkdir()
    (host / "f").write_text("x")
    import os

    if hasattr(os, "statvfs"):
        want = os.statvfs(host)
        same = (
            f"assert m.f_bsize == {want.f_bsize} and m.f_blocks == {want.f_blocks}"
            f" and m.f_namemax == {want.f_namemax}, m"
        )
    else:  # Windows: the numbers come from shutil.disk_usage
        same = "assert m.f_bsize > 0 and m.f_blocks > 0, m"
    code = f"""
import os, errno
r, m = os.statvfs('/'), os.statvfs('/mnt/h')
{same}
assert r.f_bsize > 0 and r.f_blocks >= r.f_bfree >= r.f_bavail, r
assert os.statvfs('/mnt/h/f').f_blocks == m.f_blocks == os.fstatvfs(os.open('/mnt/h/f', os.O_RDONLY)).f_blocks
assert os.fstatvfs(os.open('/lib', os.O_RDONLY)).f_blocks == r.f_blocks
assert os.fstatvfs(1).f_bsize > 0
import shutil
assert shutil.disk_usage('/').total > 0
for f, a, e in (
    (os.statvfs, '/mnt/h/nope', errno.ENOENT),
    (os.fstatvfs, 5000, errno.EBADF),
    (os.statvfs, '', errno.ENOENT),
):
    try:
        f(a)
    except OSError as x:
        assert x.errno == e, (a, x)
    else:
        raise AssertionError(a)
print('ok')
"""
    p = guest.run(code, None, "--mount", f"/mnt/h={host}")
    assert p.returncode == 0, p.stderr[-3000:]
    assert p.stdout.split() == ["ok"], p.stdout


def test_fcntl_locks_and_invalid_descriptors(guest: Guest):
    check(
        guest,
        """
import struct
open(B + '/f', 'w').close()
fd = os.open(B + '/f', os.O_RDWR)
g = os.open(B + '/f', os.O_RDWR)
fcntl.lockf(fd, fcntl.LOCK_EX)
fcntl.lockf(fd, fcntl.LOCK_UN)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
fcntl.lockf(g, fcntl.LOCK_EX | fcntl.LOCK_NB)  # one process: always granted
fcntl.lockf(fd, fcntl.LOCK_SH, 10, 5, 0)
assert fcntl.fcntl(fd, fcntl.F_GETLK, struct.pack('hhqqi', fcntl.F_WRLCK, 0, 0, 0, 0))[:2] == b'\\x02\\x00'  # F_UNLCK
for call in (
    lambda: fcntl.fcntl(5000, fcntl.F_GETFD),
    lambda: fcntl.fcntl(5000, fcntl.F_SETFD, 1),
    lambda: fcntl.fcntl(5000, fcntl.F_GETFL),
    lambda: fcntl.fcntl(5000, 9999),
    lambda: fcntl.lockf(5000, fcntl.LOCK_EX),
):
    assert err(call) == 'EBADF', call
assert err(fcntl.fcntl, fd, 9999) == 'EINVAL'
assert fcntl.fcntl(fd, fcntl.F_GETFD) == 0
""",
    )


def test_fadvise_fallocate_fdatasync_unlinkat_linkat(guest: Guest):
    check(
        guest,
        """
fd = os.open(B + '/f', os.O_CREAT | os.O_RDWR, 0o644)
assert err(os.posix_fadvise, 5000, 0, 0, 0) == 'EBADF'
assert err(os.posix_fadvise, 1, 0, 0, 0) == 'ESPIPE'
assert err(os.posix_fadvise, fd, 0, 0, os.POSIX_FADV_NORMAL) is None
assert err(os.posix_fadvise, os.open(B, os.O_RDONLY), 0, 0, 0) is None
libc.posix_fallocate.argtypes = [ctypes.c_int, ctypes.c_longlong, ctypes.c_longlong]
assert libc.posix_fallocate(fd, 0, 100) == 0 and os.fstat(fd).st_size == 100
assert libc.posix_fallocate(fd, 0, 10) == 0 and os.fstat(fd).st_size == 100  # never shrinks
assert libc.posix_fallocate(fd, 90, 30) == 0 and os.fstat(fd).st_size == 120
assert libc.posix_fallocate(5000, 0, 10) == errno.EBADF
assert libc.posix_fallocate(1, 0, 10) == errno.ESPIPE
assert libc.posix_fallocate(fd, -1, 10) == errno.EINVAL
os.chmod(B + '/f', 0o444)
assert libc.posix_fallocate(fd, 0, 500) == errno.EACCES  # growing is a write
os.fdatasync(1)  # a stream succeeds, as in Pyodide
os.fdatasync(fd)
os.fdatasync(os.open(B, os.O_RDONLY))
assert err(os.fdatasync, 5000) == 'EBADF'
libc.unlinkat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
assert libc.unlinkat(-100, (B + '/f').encode(), 1) == -1 and ctypes.get_errno() == errno.EINVAL
assert os.path.exists(B + '/f')  # kept
assert libc.unlinkat(-100, (B + '/f').encode(), 0x200) == -1 and ctypes.get_errno() == errno.ENOTDIR
os.mkdir(B + '/d')
assert libc.unlinkat(-100, (B + '/d').encode(), 0x200) == 0 and not os.path.exists(B + '/d')
libc.linkat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
os.symlink('f', B + '/l')
assert libc.linkat(-100, (B + '/l').encode(), -100, (B + '/h1').encode(), 0x400) == 0  # AT_SYMLINK_FOLLOW
assert not os.path.islink(B + '/h1') and os.stat(B + '/h1').st_ino == os.stat(B + '/f').st_ino
assert os.stat(B + '/f').st_nlink == 2
assert libc.linkat(-100, (B + '/l').encode(), -100, (B + '/h2').encode(), 0) == 0  # the link itself
assert os.path.islink(B + '/h2')
os.symlink(B + '/f', B + '/labs')  # a link to a link, with an absolute target
assert libc.linkat(-100, (B + '/labs').encode(), -100, (B + '/h3').encode(), 0x400) == 0
assert os.stat(B + '/h3').st_ino == os.stat(B + '/f').st_ino and not os.path.islink(B + '/h3')
""",
    )


def test_mknod_makes_regular_files_only(guest: Guest):
    check(
        guest,
        """
libc.mknod.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_ulong]
assert libc.mknod((B + '/n').encode(), 0o100640, 0) == 0 and oct(os.stat(B + '/n').st_mode) == '0o100640'
assert libc.mknod((B + '/n').encode(), 0o100640, 0) == -1 and ctypes.get_errno() == errno.EEXIST
assert libc.mknod((B + '/z').encode(), 0o640, 0) == -1 and ctypes.get_errno() == errno.EINVAL  # no type: EINVAL
assert libc.mkfifo((B + '/p').encode(), 0o644) == -1 and ctypes.get_errno() == errno.ENOSYS  # not over WASI
assert not os.path.exists(B + '/p') and not os.path.exists(B + '/z')
""",
    )


def test_replacing_or_removing_a_file_drops_its_record(guest: Guest):
    check(
        guest,
        """
fd = os.open(B + '/a', os.O_CREAT | os.O_WRONLY, 0o600)
os.close(fd)
os.unlink(B + '/a')
os.close(os.open(B + '/a', os.O_CREAT | os.O_WRONLY, 0o640))
assert oct(os.stat(B + '/a').st_mode) == '0o100640'
open(B + '/r1', 'w').close()
os.chmod(B + '/r1', 0o600)
open(B + '/r2', 'w').close()
os.chmod(B + '/r2', 0o700)
os.rename(B + '/r1', B + '/r2')
assert oct(os.stat(B + '/r2').st_mode) == '0o100600'
os.chmod(B + '/r2', 0o640)
os.rename(B + '/r2', B + '/r2')
assert oct(os.stat(B + '/r2').st_mode) == '0o100640'
os.mkdir(B + '/dd', 0o700)
os.rmdir(B + '/dd')
os.mkdir(B + '/dd')
assert oct(os.stat(B + '/dd').st_mode) == '0o40755'
for i in range(3000):
    os.close(os.open(B + '/m%d' % i, os.O_CREAT | os.O_WRONLY, 0o600 + i % 8))
assert oct(os.stat(B + '/m0').st_mode) == '0o100600' and oct(os.stat(B + '/m2999').st_mode) == '0o100605'  # & ~umask
""",
    )


def test_statvfs_never_gives_the_host_a_path_from_the_guest(guest: Guest, tmp_path):
    host = tmp_path / "h"
    host.mkdir()
    (host / "f").write_text("x")
    # links that leave the sandbox: os.stat and os.statvfs must fail alike, never answer with the host's numbers
    code = """
import os
os.symlink('../../../../../../../../../../../../proc', '/pr')
os.symlink('../../../../../../../../../../../../etc', '/esc')
os.symlink('../../../../../../../../../../../../proc', '/mnt/h/pr')
for p in ('/pr', '/esc/passwd', '/esc/nonexist', '/esc', '/mnt/h/pr', '/mnt/h/pr/self'):
    errs = []
    for f in (os.stat, os.statvfs):
        try:
            f(p)
        except OSError as e:
            errs.append(e.errno)
        else:
            errs.append(None)
    assert errs[0] is not None and errs[0] == errs[1], (p, errs)
assert os.statvfs('/mnt/h/f').f_bsize > 0
print('ok')
"""
    p = guest.run(code, None, "--mount", f"/mnt/h={host}")
    assert p.returncode == 0, p.stderr[-3000:]
    assert p.stdout.split() == ["ok"], p.stdout


def test_the_preopen_of_a_path_picks_the_host_folder(flavor: str, tmp_path, monkeypatch):
    """The adapter names the preopen that a guest path belongs to (the longest mount that matches) and the host maps it
    to its folder: asked through a recording os.statvfs, the folders must be the right ones even when they are all on
    one filesystem (so the numbers could not tell)."""
    import os

    import pytest

    from pyodide_wasmtime import Pyodide

    if not hasattr(os, "statvfs"):
        pytest.skip("no os.statvfs (Windows): the numbers come from shutil.disk_usage")
    a, b, c = (tmp_path / n for n in "abc")
    for d in (a, b, c):
        d.mkdir()
        (d / "f").write_text("x")
    mounts = {"/m1": a, "/m2": b, "/m1/inner": c}
    py = Pyodide(flavor, mounts=mounts)
    py._setup_root()
    assert [py._preopen_dir(n) for n in (3, 4, 5, 6, 7)] == [str(py.root), str(a), str(b), str(c), None]
    py.close()

    seen: list[str] = []
    real = os.statvfs

    def recording(path):
        seen.append(str(path))
        return real(path)

    monkeypatch.setattr(os, "statvfs", recording)
    code = (
        "import os\n"
        "for p in ('/', '/lib', '/m1', '/m1/f', '/m2', '/m2/f', '/m1/inner', '/m1/inner/f'):\n"
        "    os.statvfs(p)\n"
        "os.fstatvfs(os.open('/m1/inner/f', os.O_RDONLY))\n"
        "os.fstatvfs(os.open('/m2', os.O_RDONLY))\n"
        "os.fstatvfs(1)\n"
    )
    with Pyodide(flavor, mounts=mounts) as py:
        assert py.run(code) == 0
        root = str(py.root)
    A, B, C = str(a), str(b), str(c)
    assert seen == [root, root, A, A, B, B, C, C, C, B, root]


def test_the_host_operation_has_no_trap_without_statvfs_or_on_any_error(flavor: str, monkeypatch):
    import collections
    import os
    import shutil

    from pyodide_wasmtime import Pyodide

    usage = collections.namedtuple("usage", "total used free")
    with Pyodide(flavor) as py:
        monkeypatch.delattr(os, "statvfs", raising=False)  # as on Windows
        monkeypatch.setattr(shutil, "disk_usage", lambda p: usage(4096 * 100, 0, 4096 * 40))
        code = (
            "import os\nr = os.statvfs('/')\n"
            "assert (r.f_bsize, r.f_blocks, r.f_bavail, r.f_files) == (4096, 100, 40, 0), r"
        )
        assert py.run(code) == 0
        monkeypatch.setattr(shutil, "disk_usage", lambda p: 1 / 0)  # an error of any kind: an errno, not a trap
        code = (
            "import os\ntry:\n    os.statvfs('/')\nexcept OSError as e:\n    assert e.errno > 0\n"
            "else:\n    raise AssertionError"
        )
        assert py.run(code) == 0


def test_dotdot_after_a_symlink_is_physical(guest: Guest):
    check(
        guest,
        """
os.makedirs('/a/b')
open('/top', 'w').write('top')
open('/a/top', 'w').write('a')
os.symlink('a/b', '/l')
assert open('/l/../../top').read() == 'top'  # l -> a/b: /l/.. is /a, and /a/.. is /
assert open('/l/../top').read() == 'a'
assert open('/l/../../../../top').read() == 'top'  # above the root is the root
os.chdir('/l')
assert os.getcwd() == '/a/b' and open('../../top').read() == 'top' and open('../top').read() == 'a'
os.chdir('/')
os.makedirs('/p/q/d/sub')
open('/p/q/d/sub/f', 'w').write('in')
open('/p/q/marker', 'w').write('real')
d = os.open('/p/q/d', os.O_RDONLY)
assert os.read(os.open('sub/../sub/f', os.O_RDONLY, dir_fd=d), 2) == b'in'
assert os.read(os.open('../marker', os.O_RDONLY, dir_fd=d), 4) == b'real'  # out of the descriptor: walked from its path
os.rename('/p/q', '/p/r')
assert os.read(os.open('sub/../sub/f', os.O_RDONLY, dir_fd=d), 2) == b'in'  # WASI resolves it from the descriptor
os.makedirs('/p/q/d')  # a decoy where the descriptor used to be
open('/p/q/marker', 'w').write('DECOY')
try:
    got = os.read(os.open('../marker', os.O_RDONLY, dir_fd=d), 5)
except OSError:
    got = None  # refused, as WASI does
assert got in (None, b'real'), got
""",
    )


def test_a_renamed_directory_keeps_its_absolute_symlinks_pointing_at_the_same_file(guest: Guest):
    check(
        guest,
        """
os.makedirs('/w/d/deep/er')
open('/w/t', 'w').write('T')
os.symlink('/w/t', '/w/d/abs')
os.symlink('/w/t', '/w/d/deep/er/abs2')
os.makedirs('/w/x/y')
os.makedirs('/w/x/w')
open('/w/x/w/t', 'w').write('WRONG FILE')
os.rename('/w/d', '/w/x/y/d')
assert os.readlink('/w/x/y/d/abs') == '/w/t' and open('/w/x/y/d/abs').read() == 'T'
assert os.readlink('/w/x/y/d/deep/er/abs2') == '/w/t' and open('/w/x/y/d/deep/er/abs2').read() == 'T'
""",
    )


def test_dup_does_not_check_permissions(guest: Guest):
    check(
        guest,
        """
fd = os.open(B + '/f', os.O_CREAT | os.O_RDWR, 0o644)
os.chmod(B + '/f', 0)
d = os.dup(fd)
os.write(d, b'x')
t = os.open(B + '/other', os.O_CREAT | os.O_RDWR)
assert os.dup2(fd, t) == t
assert fcntl.fcntl(fd, fcntl.F_DUPFD, 50) > 2  # (the minimum number is the descriptor layer's)
assert fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 60) > 2
assert err(os.open, B + '/f', os.O_RDWR) == 'EACCES'  # opening anew is still checked
""",
    )


def test_an_unlinked_open_file_keeps_its_mode_until_the_last_close(guest: Guest):
    check(
        guest,
        """
fd = os.open(B + '/g', os.O_CREAT | os.O_RDWR, 0o600)
d = os.dup(fd)
os.unlink(B + '/g')
assert oct(os.fstat(fd).st_mode) == '0o100600'
os.close(fd)
assert oct(os.fstat(d).st_mode) == '0o100600'
os.close(d)
# the record is gone with the last close: a new file, maybe on the same inode, has its own mode
for i in range(200):
    p = B + '/c%d' % (i % 3)
    fd = os.open(p, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(p, 0o400 if i % 2 else 0o640)
    if i % 4 < 2:
        os.unlink(p)
        os.close(fd)
    else:
        os.close(fd)
        os.unlink(p)
    open(B + '/n%d' % (i % 3), 'w').close()
    assert oct(os.stat(B + '/n%d' % (i % 3)).st_mode) == '0o100644', i
    os.unlink(B + '/n%d' % (i % 3))
""",
    )


def test_the_guest_root_is_0777(guest: Guest):
    check(
        guest,
        """
assert oct(os.stat('/').st_mode) == '0o40777' and oct(os.stat('/..').st_mode) == '0o40777'
assert oct(os.stat(B).st_mode) == '0o40755'
""",
    )


def test_tmp_is_in_the_root_with_mode_777_and_tempfile_works(guest: Guest):
    # Pyodide: stat('/tmp') is 0o40777, tempfile.gettempdir() is '/tmp'
    p = guest.run(
        "import os, tempfile\n"
        "print(oct(os.stat('/tmp').st_mode), tempfile.gettempdir())\n"
        "with tempfile.NamedTemporaryFile() as f:\n"
        "    f.write(b'x'); f.flush()\n"
        "    n = os.path.basename(f.name)\n"
        "    print(os.path.dirname(f.name), os.path.getsize(f.name), os.listdir('/tmp') == [n])\n"
        "print(os.listdir('/tmp'))\n"
    )
    assert p.returncode == 0, p.stderr[-3000:]
    assert p.stdout.splitlines() == ["0o40777 /tmp", "/tmp 1 True", "[]"]
