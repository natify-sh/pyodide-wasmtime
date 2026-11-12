"""Offline: the virtual /dev and /proc of the adapter (wasm/adapter/dev.h), on both packagings and on every OS (the host
has no part in them: they work where there is no /dev, and a folder mounted at /dev does not show through). The expected
values are what the real Pyodide 315.0.0-alpha.2 on Node printed for the same scripts, except where a comment says it
differs (Pyodide's answers that are defects of its own are Linux's here)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import Guest

from pyodide_nojs import Pyodide

HEAD = """
import os, stat, errno, fcntl, termios, select, socket, shutil, re, mmap

def err(f, *a, **k):
    try:
        f(*a, **k)
    except OSError as e:
        return errno.errorcode[e.errno]
    return None

def devfd(p, flags=os.O_RDONLY):
    return os.open(p, flags)

def listing():
    return sorted(int(n) for n in os.listdir('/proc/self/fd'))
"""


def run(guest: Guest, body: str, *args: str) -> str:
    r = guest.run(HEAD + body + "\nprint('ok')", None, *args)
    assert r.returncode == 0 and r.stdout.rstrip().endswith("ok"), (r.stdout[-1500:], r.stderr[-2500:])
    return r.stdout


def test_the_tree_and_the_stat_of_every_node(guest: Guest):
    run(
        guest,
        """
assert sorted(os.listdir('/dev')) == ['null', 'random', 'shm', 'stderr', 'stdin', 'stdout', 'tty', 'tty1', 'urandom']
assert os.listdir('/proc') == ['self'] and os.listdir('/proc/self') == ['fd']
assert os.listdir('/dev/shm') == []  # Pyodide's holds an empty `tmp`
want = {  # mode, rdev, ino: Pyodide's numbers
    '/dev/null': (0o20666, 259, 6), '/dev/tty': (0o20666, 1280, 7), '/dev/tty1': (0o20666, 1536, 8),
    '/dev/random': (0o20555, 16384, 9), '/dev/urandom': (0o20555, 16640, 10),
    '/dev/stdin': (0o20666, 17152, 29), '/dev/stdout': (0o20666, 17153, 30), '/dev/stderr': (0o20666, 17154, 31),
    '/dev': (0o40777, 0, 5), '/dev/shm': (0o40777, 0, 11), '/proc': (0o40777, 0, 13), '/proc/self': (0o40777, 0, 14),
    '/proc/self/fd': (0o40777, 0, 15),  # (Pyodide: EPERM)
}
for p, (mode, rdev, ino) in want.items():
    for f in (os.stat, os.lstat):
        s = f(p)
        assert (s.st_mode, s.st_rdev, s.st_ino, s.st_nlink, s.st_uid) == (mode, rdev, ino, 1, 0), (p, s)
        assert s.st_size == (4096 if stat.S_ISDIR(mode) else 0) and s.st_mtime > 1e9
    assert err(os.readlink, p) == 'EINVAL', p
    assert os.path.realpath(p) == p
    assert os.path.exists(p) and os.path.lexists(p) and not os.path.islink(p)
    assert os.path.isdir(p) == stat.S_ISDIR(mode) and not os.path.isfile(p)
assert os.stat('/dev/null').st_dev == 6 and os.stat('/dev').st_dev == 1
assert os.path.samefile('/dev/null', '/dev/null') and not os.path.samefile('/dev/null', '/dev/tty')
assert [os.access('/dev/null', m) for m in (os.R_OK, os.W_OK, os.X_OK, os.F_OK)] == [True, True, False, True]
assert [os.access('/dev/urandom', m) for m in (os.R_OK, os.W_OK, os.X_OK)] == [True, False, True]
for p in ('/dev/zero', '/dev/full', '/dev/fd', '/dev/nonexistent', '/proc/meminfo', '/proc/self/cwd', '/dev/shm/tmp'):
    assert err(os.stat, p) == 'ENOENT' and not os.path.lexists(p), p
assert err(os.listdir, '/dev/null') == 'ENOTDIR' and err(os.stat, '/dev/null/x') == 'ENOTDIR'
assert err(os.stat, '/dev/null/') == 'ENOTDIR'  # (Pyodide accepts it; Linux does not)
os.chmod('/dev/null', 0o600)  # kept for the session, as Pyodide's
assert os.stat('/dev/null').st_mode == 0o20600 and not os.access('/dev/null', os.X_OK)
os.chmod('/dev/null', 0o666)
assert os.stat('/dev/null').st_mode == 0o20666
""",
    )


def test_paths_that_reach_the_nodes(guest: Guest):
    run(
        guest,
        """
os.chdir('/')
for p in ('//dev//null', '/dev/./null', '/tmp/../dev/null', '/../dev/null', 'dev/null', 'dev/../dev/null'):
    assert os.stat(p).st_rdev == 259, p
os.chdir('/tmp')
assert os.stat('../dev/null').st_rdev == 259 and os.stat('../proc/self/fd').st_ino == 15
os.chdir('/')
d = devfd('/dev', os.O_RDONLY | os.O_DIRECTORY)
assert os.stat('null', dir_fd=d).st_rdev == 259 and os.stat('./null', dir_fd=d).st_rdev == 259
assert os.stat('../dev/urandom', dir_fd=d).st_rdev == 16640
assert err(os.stat, 'zero', dir_fd=d) == 'ENOENT' and err(os.open, 'zero', os.O_RDONLY, dir_fd=d) == 'ENOENT'
n = os.open('null', os.O_RDWR, dir_fd=d)
assert os.write(n, b'abc') == 3
r = os.open('/', os.O_RDONLY)
assert os.stat('dev/null', dir_fd=r).st_rdev == 259 and os.stat('proc/self', dir_fd=r).st_ino == 14
assert err(os.stat, 'null', dir_fd=n) == 'ENOTDIR'  # a device is no directory
p = os.open('/proc/self', os.O_RDONLY)
assert os.listdir(os.open('fd', os.O_RDONLY, dir_fd=p)) is not None
assert os.stat('fd', dir_fd=p).st_ino == 15
for f in (n, d, r, p):
    os.close(f)
""",
    )


@pytest.mark.parametrize("at", ["/dev", "/proc", "/dev/shm", "/proc/self", "dev/x", "/dev/", "//proc"])
def test_a_mount_at_or_below_dev_or_proc_is_refused(flavor, tmp_path: Path, at: str):
    with pytest.raises(ValueError, match="adapter's own"):
        Pyodide(flavor, mounts={at: tmp_path})
    p = subprocess.run(
        [sys.executable, "-m", "pyodide_nojs", "--flavor", flavor, "--mount", f"{at}={tmp_path}", "-c", "pass"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert p.returncode != 0 and "adapter's own" in p.stderr


def test_utime_truncate_and_chmod_by_path_on_virtual_nodes(guest: Guest):
    run(
        guest,
        """
open('/tmp/src', 'w').write('hello')
os.utime('/dev/null')
os.utime('/dev/null', (1, 2))
os.utime('/dev/urandom', ns=(5, 6))
assert shutil.copy2('/tmp/src', '/dev/null') == '/dev/null'
shutil.copystat('/tmp/src', '/dev/null')
import pathlib
pathlib.Path('/dev/null').touch()
assert err(os.utime, '/dev/zero') == 'ENOENT' and err(os.utime, '/dev/null/x') == 'ENOTDIR'
assert err(os.truncate, '/dev/null', 0) == 'EINVAL' and err(os.truncate, '/dev', 0) == 'EISDIR'
assert err(os.truncate, '/dev/zero', 0) == 'ENOENT'
os.chmod('/dev/null', 0o640)
os.chown('/dev/null', 0, 0)
assert os.stat('/dev/null').st_mode == 0o20640
os.chmod('/dev/null', 0o666)
""",
    )


def test_mutating_calls_never_reach_the_host(guest: Guest):
    run(
        guest,
        """
import ctypes
libc = ctypes.CDLL(None, use_errno=True)


def link(a, b):  # (Pyodide's os has no link)
    assert libc.link(a.encode(), b.encode()) == -1
    return errno.errorcode[ctypes.get_errno()]


open('/tmp/src', 'w').write('x')
for p in ('/dev', '/proc', '/dev/shm'):
    assert err(os.mkdir, p) == 'EEXIST'
for p in ('/dev/x', '/proc/x', '/dev/shm/x', '/proc/self/fd/x'):
    assert err(os.mkdir, p) == 'EACCES', p
    assert err(os.symlink, '/tmp', p) == 'EACCES' and err(os.rename, '/tmp/src', p) == 'EACCES'
    assert link('/tmp/src', p) == 'EACCES' and err(os.unlink, p) == 'ENOENT' and err(os.rmdir, p) == 'ENOENT'
for p in ('/dev', '/dev/null', '/dev/shm', '/proc', '/proc/self/fd'):
    assert err(os.rmdir, p) == 'EACCES' and err(os.unlink, p) == 'EACCES', p
    assert err(os.rename, p, '/tmp/moved') == 'EACCES' and link(p, '/tmp/lk') == 'EACCES'
assert err(os.mkdir, '/dev/null/x') == 'ENOTDIR'
assert os.listdir('/dev') == os.listdir('/dev') and os.path.exists('/dev/null') and not os.path.exists('/tmp/moved')
""",
    )


def test_append_and_directory_open_flags_of_virtual_nodes(guest: Guest):
    run(
        guest,
        """
n = devfd('/dev/null', os.O_WRONLY | os.O_APPEND)
assert fcntl.fcntl(n, fcntl.F_GETFL) & (3 | os.O_APPEND) == 1 | os.O_APPEND
fcntl.fcntl(n, fcntl.F_SETFL, 0)
assert fcntl.fcntl(n, fcntl.F_GETFL) & (3 | os.O_APPEND) == 1
fcntl.fcntl(n, fcntl.F_SETFL, os.O_APPEND | os.O_NONBLOCK)
assert fcntl.fcntl(n, fcntl.F_GETFL) & (3 | os.O_APPEND | os.O_NONBLOCK) == 1 | os.O_APPEND | os.O_NONBLOCK
d = os.dup(n)
assert fcntl.fcntl(d, fcntl.F_GETFL) & os.O_APPEND  # one description
assert err(os.open, '/dev/shm', os.O_RDONLY | os.O_CREAT) == 'EISDIR'
assert err(os.open, '/dev', os.O_CREAT | os.O_WRONLY) == 'EISDIR' and err(os.open, '/dev', os.O_RDWR) == 'EISDIR'
assert err(os.open, '/dev', os.O_CREAT | os.O_EXCL) == 'EEXIST'
os.close(os.open('/dev', os.O_RDONLY))
""",
    )


def test_readlink_buffer_sizes_and_trailing_slashes(guest: Guest):
    run(
        guest,
        """
import ctypes
libc = ctypes.CDLL(None)
nul = devfd('/dev/null')
p = ('/proc/self/fd/%d' % nul).encode()
buf = ctypes.create_string_buffer(64)
for size in (2**31, 2**32 - 1, 64, 5):
    n = libc.readlink(p, buf, ctypes.c_size_t(size))
    assert n == min(len('/dev/null'), size if size < 2**31 else 64), (size, n)
assert buf.raw[:9] == b'/dev/null'
for q in ('/dev/null/.', '/dev/null/', '/dev/tty/', '/proc/self/fd/1/', '/proc/self/fd/%d/' % nul):
    assert err(os.stat, q) == 'ENOTDIR' and err(os.lstat, q) == 'ENOTDIR', q
    assert err(os.open, q, os.O_RDONLY) == 'ENOTDIR', q
d = devfd('/dev')
assert stat.S_ISDIR(os.stat('/proc/self/fd/%d/' % d).st_mode)
assert stat.S_ISDIR(os.lstat('/proc/self/fd/%d/' % d).st_mode)
assert stat.S_ISLNK(os.lstat('/proc/self/fd/%d' % d).st_mode)
t = os.open('/tmp', os.O_RDONLY)
assert stat.S_ISDIR(os.stat('/proc/self/fd/%d/' % t).st_mode)
assert stat.S_ISDIR(os.stat('/dev/.').st_mode) and stat.S_ISDIR(os.stat('/proc/self/').st_mode)
""",
    )


def test_dev_null_and_os_devnull(guest: Guest):
    run(
        guest,
        """
assert os.devnull == '/dev/null'
assert open(os.devnull, 'w').write('abc') == 3 and open(os.devnull, 'rb').read() == b''
f = open('/dev/null', 'r+b', buffering=0)
assert (f.write(b'xyz'), f.read(), f.tell(), f.seekable()) == (3, b'', 0, True)
assert open('/dev/null', 'ab', buffering=0).write(b'abc') == 3
assert err(open, '/dev/null', 'x') == 'EEXIST'
assert err(os.open, '/dev/null', os.O_DIRECTORY) == 'ENOTDIR'
assert err(os.open, '/dev/null', os.O_CREAT | os.O_EXCL | os.O_WRONLY) == 'EEXIST'
os.close(os.open('/dev/null', os.O_TRUNC | os.O_WRONLY))
assert err(open, '/dev/nonexistent') == 'ENOENT'
assert err(os.open, '/dev/newfile', os.O_CREAT | os.O_WRONLY) == 'EACCES'  # (Pyodide makes it; /dev is read-only here)
assert err(os.open, '/dev', os.O_WRONLY) == 'EISDIR' and err(os.open, '/dev/shm', os.O_RDWR) == 'EISDIR'
n = devfd('/dev/null', os.O_RDWR)
assert os.read(n, 100000) == b'' and os.write(n, bytes(100000)) == 100000
assert os.writev(n, [b'ab', b'cde']) == 5 and os.readv(n, [bytearray(4)]) == 0
assert os.pread(n, 4, 7) == b'' and os.pwrite(n, b'abc', 7) == 3
assert (os.lseek(n, 100, 0), os.lseek(n, 0, 2), os.lseek(n, 0, 1)) == (0, 0, 0)
assert os.fsync(n) is None and err(os.ftruncate, n, 0) == 'EINVAL'
assert not os.isatty(n) and os.get_blocking(n)
os.set_blocking(n, False)
assert not os.get_blocking(n) and fcntl.fcntl(n, fcntl.F_GETFL) & 3 == 2
assert err(fcntl.ioctl, n, termios.TIOCGWINSZ, bytes(8)) == 'ENOTTY'
assert err(fcntl.ioctl, n, termios.FIONREAD, bytes(4)) == 'ENOTTY'
os.fchmod(n, 0o600)
assert os.fstat(n).st_mode == 0o20600 and os.stat('/dev/null').st_mode == 0o20600
os.fchmod(n, 0o666)
assert select.select([n], [n], [], 0) == ([n], [n], [])
p = select.poll()
p.register(n, select.POLLIN | select.POLLOUT)
assert p.poll(0) == [(n, 5)]
assert err(mmap.mmap, n, 4096) == 'ENODEV'
os.close(n)
# what shutil and the standard library do with it
open('/tmp/x', 'w').write('hello')
assert shutil.copyfile('/tmp/x', '/dev/null') == '/dev/null' and shutil.copy('/tmp/x', '/dev/null') == '/dev/null'
assert shutil.copyfile('/dev/null', '/tmp/empty') == '/tmp/empty' and os.path.getsize('/tmp/empty') == 0
print('to null', file=open(os.devnull, 'w'))
""",
    )


def test_random_and_urandom(guest: Guest):
    run(
        guest,
        """
for p in ('/dev/random', '/dev/urandom'):
    fd = devfd(p)
    a, b = os.read(fd, 16), os.read(fd, 16)
    assert len(a) == len(b) == 16 and a != b
    assert len(os.read(fd, 100000)) == 100000 and len(os.read(fd, 0)) == 0
    assert len(set(os.read(fd, 1000))) > 100
    assert err(os.pread, fd, 4, 0) == 'ESPIPE' and err(os.lseek, fd, 0, 0) == 'ESPIPE'
    assert err(os.write, fd, b'x') == 'EBADF'  # read-only
    assert fcntl.fcntl(fd, fcntl.F_GETFL) & 3 == 0
    os.close(fd)
    assert err(os.open, p, os.O_WRONLY) == 'EACCES' and err(os.open, p, os.O_RDWR) == 'EACCES'  # mode 0555 (Pyodide's)
    assert open(p, 'rb').read(5).__len__() == 5
    assert len({open(p, 'rb').read(8) for _ in range(3)}) == 3
assert len(os.urandom(16)) == 16 and os.urandom(16) != os.urandom(16) and len(os.urandom(1000000)) == 1000000
assert len(os.getrandom(16)) == 16 if hasattr(os, 'getrandom') else True
""",
    )


def test_terminals_and_the_standard_streams(guest: Guest):
    out = run(
        guest,
        """
tt = devfd('/dev/tty', os.O_RDWR)
assert os.read(tt, 10) == b'' and os.isatty(tt) and err(os.lseek, tt, 0, 0) == 'ESPIPE'  # (stdin is /dev/null)
assert fcntl.ioctl(tt, termios.TIOCGWINSZ, bytes(8)) == b'\\x18\\x00P\\x00\\x00\\x00\\x00\\x00'
assert termios.tcgetattr(tt)[:4] == [25856, 5, 191, 35387]
assert fcntl.ioctl(tt, termios.TIOCSWINSZ, bytes(8)) == bytes(8)
assert err(fcntl.ioctl, tt, termios.FIONREAD, bytes(4)) == 'ENOTTY'
assert os.write(tt, b'to-tty\\n') == 7 and os.fstat(tt).st_rdev == 1280
t1 = devfd('/dev/tty1', os.O_RDWR)
assert err(os.read, t1, 10) == 'ENXIO' and os.write(t1, b'to-tty1\\n') == 8 and os.isatty(t1)
for name, fd_ in (('stdin', 0), ('stdout', 1), ('stderr', 2)):
    f = devfd('/dev/' + name, os.O_RDWR)
    assert not os.isatty(f) and os.fstat(f).st_rdev == 17152 + fd_ and err(os.lseek, f, 0, 0) == 'ESPIPE'
    assert err(fcntl.ioctl, f, termios.TCGETS, bytes(64)) == 'ENOTTY'
    os.close(f)
assert os.read(devfd('/dev/stdin'), 10) == b'' and err(os.write, devfd('/dev/stdin', os.O_RDWR), b'x') == 'EIO'
for name in ('stdout', 'stderr'):
    assert err(os.read, devfd('/dev/' + name, os.O_RDWR), 1) == 'EIO'
assert open('/dev/stdout', 'w').write('via-stdout\\n') == 11
os.write(devfd('/dev/stderr', os.O_WRONLY), b'via-stderr\\n')
# closing the device never closes the stream behind it
print('still-printing')
assert os.isatty(0) is False
""",
    )
    assert "to-tty\n" in out and "via-stdout\n" in out and "still-printing\n" in out


def test_proc_self_fd_follows_the_table(guest: Guest):
    run(
        guest,
        """
assert listing() == [0, 1, 2, 3]  # 3: the descriptor that listing the directory opens
f = open('/tmp/x1', 'w')
n = f.fileno()
assert n == 3 and listing() == [0, 1, 2, 3, 4]
f.close()
assert listing() == [0, 1, 2, 3]
r, w = os.pipe()
s = socket.socket()
d = os.open('/tmp', os.O_RDONLY)
g = open('/tmp/x2', 'w')
nul = devfd('/dev/null', os.O_RDWR)
tt = devfd('/dev/tty')
dd = devfd('/dev')
for fd in (r, w, s.fileno(), d, g.fileno(), nul, tt, dd):
    assert os.path.exists('/proc/self/fd/%d' % fd) and os.path.islink('/proc/self/fd/%d' % fd)
link = lambda fd: os.readlink('/proc/self/fd/%d' % fd)
assert [link(0), link(1), link(2)] == ['/dev/stdin', '/dev/stdout', '/dev/stderr']
assert [link(f_) for f_ in (d, g.fileno(), nul, tt, dd)] == ['/tmp', '/tmp/x2', '/dev/null', '/dev/tty', '/dev']
assert re.fullmatch(r'pipe:\\[\\d+\\]', link(r)) and re.fullmatch(r'pipe:\\[\\d+\\]', link(w)) and link(r) != link(w)
assert re.fullmatch(r'socket:\\[\\d+\\]', link(s.fileno()))
assert os.path.realpath('/proc/self/fd/%d' % nul) == '/dev/null'
# stat follows the link, lstat is the link (Pyodide: EPERM for both)
assert os.stat('/proc/self/fd/%d' % nul).st_rdev == 259 and os.stat('/proc/self/fd/%d' % g.fileno()).st_size == 0
assert stat.S_ISLNK(os.lstat('/proc/self/fd/%d' % nul).st_mode)
assert stat.S_ISDIR(os.stat('/proc/self/fd/%d' % d).st_mode)
assert os.access('/proc/self/fd/%d' % nul, os.W_OK)
ents = {e.name: e for e in os.scandir('/proc/self/fd')}
assert all(e.is_symlink() for e in ents.values()) and str(nul) in ents
dd2 = os.open('/proc/self/fd', os.O_RDONLY)
assert str(dd2) in os.listdir(dd2) and str(nul) in os.listdir(dd2)
assert os.listdir(dd2) == os.listdir(dd2)  # the listing is read again after rewinddir
os.close(dd2)
os.close(nul)
assert err(os.readlink, '/proc/self/fd/%d' % nul) == 'ENOENT' and err(os.stat, '/proc/self/fd/%d' % nul) == 'ENOENT'
for bad in ('/proc/self/fd/99', '/proc/self/fd/01', '/proc/self/fd/x', '/proc/self/fd/4096', '/proc/self/fd/-1'):
    assert err(os.readlink, bad) == 'ENOENT', bad
assert err(os.open, '/proc/self/fd/0', os.O_RDONLY) == 'EACCES'  # (as Pyodide's; Linux reopens the file)
""",
    )


def test_descriptors_of_virtual_nodes(guest: Guest):
    run(
        guest,
        """
nul = devfd('/dev/null', os.O_RDWR)
assert nul == 3
d = os.dup(nul)
assert d == 4 and os.fstat(d).st_rdev == 259
os.close(nul)
assert os.write(d, b'x') == 1 and os.fstat(d).st_rdev == 259  # the object lives while a number holds it
assert err(os.fstat, nul) == 'EBADF' and err(os.write, nul, b'x') == 'EBADF'
os.dup2(d, 50)
assert os.write(50, b'x') == 1
os.close(d)
assert os.write(50, b'x') == 1
assert fcntl.fcntl(50, fcntl.F_DUPFD, 60) == 60 and os.read(60, 5) == b''
os.set_blocking(60, False)
assert not os.get_blocking(50)  # one description, shared by the numbers
os.close(50)
assert os.write(60, b'x') == 1
os.close(60)
assert err(os.close, 60) == 'EBADF' and err(os.close, 50) == 'EBADF'
# a directory and a device on the same number space as everything else
a = devfd('/dev', os.O_RDONLY)
assert err(os.read, a, 1) == 'EISDIR' and err(os.write, a, b'x') == 'EBADF' and err(os.ftruncate, a, 0) == 'EINVAL'
assert os.lseek(a, 0, 1) == 0 and sorted(os.listdir(a)) == sorted(os.listdir('/dev'))
assert os.dup(a) == a + 1 and sorted(os.listdir(a + 1)) == sorted(os.listdir('/dev'))
os.close(a + 1)
os.close(a)
# the table is the same size: every number from 3 on, EMFILE after the last
fds = []
try:
    while True:
        fds.append(devfd('/dev/null'))
except OSError as e:
    assert e.errno == errno.EMFILE
assert fds == list(range(3, 4096)), (fds[:3], len(fds))
assert err(os.pipe) == 'EMFILE' and err(os.open, '/tmp', os.O_RDONLY) == 'EMFILE' and err(os.dup, fds[0]) == 'EMFILE'
for f in fds:
    os.close(f)
assert devfd('/dev/urandom') == 3 and listing()[:4] == [0, 1, 2, 3]
""",
    )


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PYODIDE_NOJS_CACHE", str(tmp_path))
    monkeypatch.delenv("PYODIDE_NOJS_SNAPSHOT", raising=False)
    return tmp_path


CHECK = """
import os
n = os.open('/dev/null', os.O_RDWR)
assert os.write(n, b'abc') == 3 and sorted(os.listdir('/dev'))[0] == 'null'
assert sorted(int(x) for x in os.listdir('/proc/self/fd')) == [0, 1, 2, 3, 4], os.listdir('/proc/self/fd')
assert os.readlink('/proc/self/fd/%d' % n) == '/dev/null' and len(os.urandom(8)) == 8
os.close(n)
print('dev ok')
"""


def test_a_restored_snapshot_has_the_nodes(flavor, cache, capfd):
    """The descriptor table is not in a snapshot (like every descriptor): a preload that used /dev/null leaves nothing
    behind, and the restored interpreter has all of /dev and /proc."""
    pre = "import os\nos.close(os.open('/dev/null', os.O_RDWR))\nx = os.urandom(4)\n"
    with Pyodide(flavor, preload=pre) as py:
        assert py.run(CHECK) == 0
    with Pyodide(flavor, preload=pre) as py:
        assert py.run(CHECK) == 0
        assert py.restored
    assert capfd.readouterr().out == "dev ok\ndev ok\n"


def test_two_interpreters_have_their_own_tables(flavor, capfd):
    with Pyodide(flavor) as a, Pyodide(flavor) as b:
        assert (
            a.run("import os\nn = os.open('/dev/null', os.O_RDWR)\nprint(n, sorted(os.listdir('/proc/self/fd')))") == 0
        )
        assert b.run("import os\nprint(sorted(os.listdir('/proc/self/fd')), os.open('/dev/urandom', 0))") == 0
        assert a.run("import os\nprint(os.write(n, b'x'), os.readlink('/proc/self/fd/3'))") == 0
    assert capfd.readouterr().out.splitlines() == [
        "3 ['0', '1', '2', '3', '4']",  # (4: the descriptor that the listing opens)
        "['0', '1', '2', '3'] 3",
        "1 /dev/null",
    ]
