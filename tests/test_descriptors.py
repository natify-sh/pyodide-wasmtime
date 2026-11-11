"""Offline: pipes, dup, dup2/dup3 and F_DUPFD on every kind of descriptor (files, directories, the standard streams,
sockets, pipes), on both packagings. The expected values are what the real Pyodide 315.0.0-alpha.2 on Node printed for
the same script (its PIPEFS and FS.dupStream), except where a test says it differs."""

from __future__ import annotations

import sys

import pytest
from conftest import Guest

HEAD = """
import os, fcntl, stat, errno, select, struct, termios, sys, shutil, ctypes

def t(name, fn):
    try:
        r = fn()
    except OSError as e:
        r = "OSError " + errno.errorcode.get(e.errno, str(e.errno))
    print(name, repr(r))

def fionread(fd):
    return struct.unpack("i", fcntl.ioctl(fd, termios.FIONREAD, b"\\0\\0\\0\\0"))[0]

def poll(fd, ev):
    p = select.poll(); p.register(fd, ev)
    return [e[1] for e in p.poll(0)]

WIN = {WIN}  # the HOST is Windows: it cannot rename or delete a file that is open
base = "/tmp/t_desc"
shutil.rmtree(base, ignore_errors=True)
os.makedirs(base + "/d/sub")
open(base + "/f", "wb").write(b"0123456789")
open(base + "/d/a", "wb").write(b"a")
open(base + "/d/b", "wb").write(b"b")
"""


def run(guest: Guest, body: str) -> list[str]:
    r = guest.run(HEAD.replace("{WIN}", str(sys.platform == "win32")) + body)
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


def test_a_pipe_carries_bytes_as_pyodides_does(guest: Guest) -> None:
    out = run(
        guest,
        """
r, w = os.pipe()
print(r + 1 == w, fcntl.fcntl(r, fcntl.F_GETFL), fcntl.fcntl(w, fcntl.F_GETFL))
t("empty", lambda: os.read(r, 10))
t("size0", lambda: os.read(r, 0))
t("write empty", lambda: os.write(w, b""))
for n in (1, 8191, 8192, 8193, 100000):
    data = bytes(i % 251 for i in range(n))
    a = os.write(w, data); fi = fionread(r); got = b""
    while True:
        try: got += os.read(r, 5000)
        except BlockingIOError: break
    print(n, a, fi, got == data)
t("partial", lambda: (os.write(w, b"abcdef"), os.read(r, 2), os.read(r, 2), os.read(r, 100)))
st = os.fstat(r)
print(oct(st.st_mode), st.st_nlink, stat.S_ISFIFO(st.st_mode), st.st_uid, st.st_size, st.st_blksize)
print(os.fstat(w).st_ino != st.st_ino)
t("lseek", lambda: os.lseek(r, 0, 0))
t("read write end", lambda: os.read(w, 1))
t("write read end", lambda: os.write(r, b"x"))
t("fsync", lambda: os.fsync(w))
t("pread", lambda: os.pread(r, 1, 0))
t("ftruncate", lambda: os.ftruncate(w, 0))
t("isatty", lambda: os.isatty(r))
t("setfl", lambda: (fcntl.fcntl(r, fcntl.F_SETFL, os.O_NONBLOCK), fcntl.fcntl(r, fcntl.F_GETFL), os.get_blocking(r)))
os.close(r)
t("write after close of the reader", lambda: os.write(w, b"hello"))
t("closed", lambda: os.read(r, 1))
""",
    )
    assert out == [
        "True 0 1",
        "empty 'OSError EAGAIN'",
        "size0 b''",
        "write empty 0",
        "1 1 1 True",
        "8191 8191 8191 True",
        "8192 8192 8192 True",
        "8193 8193 8193 True",
        "100000 100000 100000 True",
        "partial (6, b'ab', b'cd', b'ef')",
        "0o10600 1 True 0 0 4096",
        "True",
        "lseek 'OSError ESPIPE'",
        "read write end 'OSError EBADF'",
        "write read end 'OSError EBADF'",
        "fsync 'OSError EINVAL'",
        "pread 'OSError ESPIPE'",
        "ftruncate 'OSError EINVAL'",
        "isatty False",
        "setfl (0, 2048, False)",
        "write after close of the reader 5",
        "closed 'OSError EBADF'",
    ]


def test_end_of_file_is_zero_bytes_unlike_pyodide(guest: Guest) -> None:
    """The one deliberate difference (the owner's decision): Pyodide's PIPEFS gives EAGAIN for an empty pipe whose
    writers are all closed, here it is end of file, as POSIX."""
    out = run(
        guest,
        """
r, w = os.pipe(); w2 = os.dup(w)
os.write(w, b"x"); os.close(w)
print(os.read(r, 5), end=" ")
t("one writer left", lambda: os.read(r, 5))
os.close(w2)
t("no writer", lambda: os.read(r, 5))
t("no writer again", lambda: os.read(r, 5))
""",
    )
    assert out == ["b'x' one writer left 'OSError EAGAIN'", "no writer b''", "no writer again b''"]


def test_poll_and_select_on_pipes(guest: Guest) -> None:
    out = run(
        guest,
        """
r, w = os.pipe()
print(poll(r, select.POLLIN), poll(w, select.POLLOUT), poll(w, select.POLLIN))
print(select.select([r], [w], [], 0) == ([], [w], []), select.select([r], [], [], 0.05))
os.write(w, b"d")
print(poll(r, select.POLLIN | select.POLLOUT | select.POLLPRI), select.select([r], [w], [], 0) == ([r], [w], []))
os.read(r, 5)
os.close(w)
print(poll(r, select.POLLIN), poll(r, 0), select.select([r], [], [], 0) == ([r], [], []))
r, w = os.pipe()
os.close(r)
print(poll(w, select.POLLOUT))
p = select.poll(); p.register(w, select.POLLOUT); p.register(0, select.POLLIN); p.register(999, select.POLLIN)
print(sorted(e[1] for e in p.poll(0)))
""",
    )
    assert out == [
        "[] [4] []",
        "True ([], [], [])",
        "[1] True",
        "[17] [16] True",
        "[12]",
        "[1, 12, 32]",
    ]


def test_pipe2_flags(guest: Guest) -> None:
    """pipe2 takes O_CLOEXEC and O_NONBLOCK only (EOPNOTSUPP for the rest, EFAULT for no array), as PIPEFS. FD_CLOEXEC
    is kept per number here (Pyodide's F_GETFD is always 0)."""
    out = run(
        guest,
        """
libc = ctypes.CDLL(None, use_errno=True)
def p2(flags):
    arr = (ctypes.c_int * 2)()
    ctypes.set_errno(0)
    if libc.pipe2(arr, flags):
        return ctypes.get_errno()
    a, b = arr
    g = fcntl.fcntl
    res = (g(a, fcntl.F_GETFL), g(b, fcntl.F_GETFL), g(a, fcntl.F_GETFD), g(b, fcntl.F_GETFD))
    os.close(a); os.close(b)
    return res
print(p2(0), p2(os.O_NONBLOCK), p2(os.O_CLOEXEC), p2(os.O_NONBLOCK | os.O_CLOEXEC))
print(p2(os.O_DIRECT), p2(os.O_APPEND), p2(1 << 30))
ctypes.set_errno(0)
print(libc.pipe2(None, 0), ctypes.get_errno())
""",
    )
    assert out == [
        "(0, 1, 0, 0) (2048, 2049, 0, 0) (0, 1, 1, 1) (2048, 2049, 1, 1)",
        "138 138 138",
        "-1 21",
    ]


def test_pipes_and_their_descriptors_are_freed(guest: Guest) -> None:
    out = run(
        guest,
        """
for i in range(300):
    a, b = os.pipe(); c = os.dup(a); d = os.dup(b); os.dup2(a, 500)
    os.write(d, b"x" * 100)
    for x in (a, b, c, d, 500): os.close(x)
a, b = os.pipe()
print(a, b, a == b - 1)
os.close(a); os.close(b)
fds = []
try:
    while True: fds += os.pipe()
except OSError as e:
    print(errno.errorcode[e.errno], len(fds) > 100)
for f in fds: os.close(f)
a, b = os.pipe()
print(b == a + 1)
""",
    )
    assert out[1:] == ["EMFILE True", "True"]
    assert out[0].endswith("True")


def test_dup_shares_the_offset_and_does_not_depend_on_the_name(guest: Guest) -> None:
    out = run(
        guest,
        """
F = os.open(base + "/f", os.O_RDWR)
D = os.dup(F)
print(D > F, os.get_inheritable(D))
t("read", lambda: (os.read(F, 2), os.read(D, 2), os.lseek(F, 0, 1), os.lseek(D, 0, 1)))
t("write", lambda: (os.write(D, b"XY"), os.lseek(F, 0, 1), os.pread(F, 10, 0)))
t("close orig", lambda: (os.close(F), os.read(D, 3), os.lseek(D, 0, 1)))
t("orig closed", lambda: os.read(F, 1))
if not WIN:
    os.rename(base + "/f", base + "/g")
    t("renamed", lambda: (os.lseek(D, 0, 0), os.read(os.dup(D), 4)))
    os.unlink(base + "/g")
    t("unlinked", lambda: (os.read(os.dup(D), 4), os.fstat(D).st_size))
os.close(D)
A = os.open(base + "/d/a", os.O_RDONLY); B = os.open(base + "/d/b", os.O_RDONLY)
t("dup2 onto an open one", lambda: (os.dup2(A, B) == B, os.read(B, 5), os.read(A, 5)))
t("dup2 same", lambda: os.dup2(A, A) == A)
t("dup2 non-inheritable", lambda: (os.dup2(A, B, inheritable=False) == B, os.get_inheritable(B)))
N = max(A, B) + 20
t("dup2 onto an unused one", lambda: (os.dup2(A, N) == N, os.fstat(N).st_size, os.lseek(N, 0, 1) == os.lseek(A, 0, 1)))
t("negative", lambda: os.dup2(A, -1))
t("huge", lambda: os.dup2(A, 100000))
t("bad old", lambda: os.dup2(999, 50))
t("dup bad", lambda: os.dup(999))
t("dup negative", lambda: os.dup(-1))
t("dup huge", lambda: os.dup(1 << 30))
os.close(N)
A2 = os.dup(A)
t("setfl shared", lambda: (fcntl.fcntl(A, fcntl.F_SETFL, os.O_NONBLOCK), fcntl.fcntl(A2, fcntl.F_GETFL) & 2048))
n = []
for i in range(300):
    x = os.open(base + "/d/a", os.O_RDONLY); n.append(os.dup(x)); os.close(x)
for x in n: os.close(x)
print(os.dup(0) < 20)  # the lowest free number: nothing is left open
""",
    )
    assert out == [
        "True False",
        "read (b'01', b'23', 4, 4)",
        "write (2, 6, b'0123XY6789')",
        "close orig (None, b'678', 9)",
        "orig closed 'OSError EBADF'",
        *([] if sys.platform == "win32" else ["renamed (0, b'0123')", "unlinked (b'XY67', 10)"]),
        "dup2 onto an open one (True, b'a', b'')",
        "dup2 same True",
        "dup2 non-inheritable (True, False)",
        "dup2 onto an unused one (True, 1, True)",
        "negative 'OSError EBADF'",
        "huge 'OSError EBADF'",
        "bad old 'OSError EBADF'",
        "dup bad 'OSError EBADF'",
        "dup negative 'OSError EBADF'",
        "dup huge 'OSError EBADF'",
        "setfl shared (0, 2048)",
        "True",
    ]


def test_f_dupfd_takes_the_lowest_free_number_from_the_argument(guest: Guest) -> None:
    out = run(
        guest,
        """
A = os.open(base + "/d/a", os.O_RDONLY)
r = fcntl.fcntl(A, fcntl.F_DUPFD, 40)
print(r, fcntl.fcntl(A, fcntl.F_DUPFD, 40), fcntl.fcntl(r, fcntl.F_GETFD))
c = fcntl.fcntl(A, fcntl.F_DUPFD_CLOEXEC, 10)
print(c >= 10, fcntl.fcntl(c, fcntl.F_GETFD), os.get_inheritable(c))
os.close(41); os.close(40)
print(fcntl.fcntl(A, fcntl.F_DUPFD, 40), fcntl.fcntl(A, fcntl.F_DUPFD, 40))
t("negative", lambda: fcntl.fcntl(A, fcntl.F_DUPFD, -1))
t("bad fd", lambda: fcntl.fcntl(999, fcntl.F_DUPFD, 10))
g = fcntl.fcntl
print(g(A, fcntl.F_SETFD, 1), g(A, fcntl.F_GETFD), g(A, fcntl.F_SETFD, 0), g(A, fcntl.F_GETFD))
""",
    )
    assert out == [
        "40 41 0",
        "True 1 False",
        "40 41",
        "negative 'OSError EINVAL'",
        "bad fd 'OSError EBADF'",
        "0 1 0 0",
    ]


def test_dup_of_directories(guest: Guest) -> None:
    out = run(
        guest,
        """
dfd = os.open(base + "/d", os.O_RDONLY | os.O_DIRECTORY)
e = os.dup(dfd)
print(sorted(os.listdir(e)), os.fstat(e).st_ino == os.fstat(dfd).st_ino, stat.S_ISDIR(os.fstat(e).st_mode))
os.close(dfd)
f2 = os.open("a", os.O_RDONLY, dir_fd=e)
print(sorted(os.listdir(e)), oct(os.stat("sub", dir_fd=e).st_mode & 0o170000), os.read(f2, 1))
os.close(f2); os.close(e)
sfd = os.open(base + "/d", os.O_RDONLY)
print(sorted(x.name for x in os.scandir(sfd)))
os.close(sfd)  # an open directory cannot be removed on Windows
print([(r, sorted(d), sorted(f)) for r, d, f, fd in os.fwalk(base)])
shutil.rmtree(base + "/d")
print(os.path.exists(base + "/d"))
""",
    )
    assert out == [
        "['a', 'b', 'sub'] True True",
        "['a', 'b', 'sub'] 0o40000 b'a'",
        "['a', 'b', 'sub']",
        "[('/tmp/t_desc', ['d'], ['f']), ('/tmp/t_desc/d', ['sub'], ['a', 'b']), ('/tmp/t_desc/d/sub', [], [])]",
        "False",
    ]


def test_dup_of_the_standard_streams(guest: Guest) -> None:
    """os.dup(0/1/2) (it was ENOSYS), and the redirection idiom: save, dup2 a file onto 1 or 2, restore."""
    out = run(
        guest,
        """
for n in (0, 1, 2):
    x = os.dup(n)
    print(n, x > 2, os.fstat(x).st_mode == os.fstat(n).st_mode, os.isatty(x) == os.isatty(n))
    os.close(x)
sys.stdout.flush()
save = os.dup(1)
f = os.open(base + "/out", os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
os.dup2(f, 1); os.close(f)
os.write(1, b"captured\\n"); print("printed", flush=True)
os.dup2(save, 1); os.close(save)
print(open(base + "/out").read().split())
save = os.dup(2)
f = os.open(base + "/err", os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
os.dup2(f, 2); os.close(f)
os.write(2, b"to err\\n")
os.dup2(save, 2); os.close(save)
print(open(base + "/err").read().split())
s = os.dup(0)
g = os.fdopen(s)
print(g.fileno() == s, g.read())
g.close()
s = os.dup(1)
os.close(1)
os.dup2(s, 1)
os.close(s)
print("stdout again")
""",
    )
    assert out == [
        "0 True True True",
        "1 True True True",
        "2 True True True",
        "['captured', 'printed']",
        "['to', 'err']",
        "True ",
        "stdout again",
    ]


def test_dup_of_pipe_ends(guest: Guest) -> None:
    out = run(
        guest,
        """
r, w = os.pipe()
w2 = os.dup(w)
os.write(w2, b"hi"); os.close(w)
print(os.read(r, 10), end=" ")
os.write(w2, b"yo")
print(os.read(r, 10), poll(r, select.POLLIN))
os.close(w2)
print(poll(r, select.POLLIN))
os.close(r)
r, w = os.pipe()
r2 = os.dup(r)
os.write(w, b"abc")
print(os.read(r2, 1), os.read(r, 10), end=" ")
os.close(r)
print(poll(w, select.POLLOUT), end=" ")
os.close(r2)
print(poll(w, select.POLLOUT))
os.close(w)
r, w = os.pipe()
N = w + 20
os.dup2(w, N); os.dup2(r, w)
print(os.write(N, b"1"), os.read(w, 5), os.fstat(w).st_mode == os.fstat(r).st_mode)
r2 = os.dup(r)
fcntl.fcntl(r, fcntl.F_SETFL, os.O_NONBLOCK)
print(fcntl.fcntl(r2, fcntl.F_GETFL), fcntl.fcntl(fcntl.fcntl(r, fcntl.F_DUPFD, 30), fcntl.F_GETFL))
""",
    )
    assert out == [
        "b'hi' b'yo' []",
        "[17]",
        "b'a' b'bc' [4] [12]",
        "1 b'1' True",
        "2048 2048",
    ]


def test_dup_of_a_socket(guest: Guest) -> None:
    out = run(
        guest,
        """
import socket
s = socket.socket()
s2 = s.dup()
print(s2.fileno() != s.fileno(), s2.type == s.type)
s.bind(("127.0.0.1", 0)); s.listen()
print(s2.getsockname() == s.getsockname())
c = socket.create_connection(s.getsockname())
conn, _ = s2.accept()
dc = conn.dup()
conn.close()
c.sendall(b"ping")
print(dc.recv(4), end=" ")
dc.setblocking(False)
print(conn.fileno() == -1, os.get_blocking(dc.fileno()), end=" ")
s.close(); print(s2.getsockname()[0], end=" ")
s2.close(); dc.close(); c.close()
print("closed")
""",
    )
    assert out == ["True True", "True", "b'ping' True False 127.0.0.1 closed"]


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot rename a file that a mapping keeps open")
def test_mmap_keeps_working_after_the_descriptor_is_closed(guest: Guest) -> None:
    """mmap holds a duplicate of the descriptor: the same file, not a re-opening by name (Pyodide: EBADF at flush)."""
    out = run(
        guest,
        """
import mmap
f = os.open(base + "/f", os.O_RDWR)
m = mmap.mmap(f, 4)
os.close(f)
os.rename(base + "/f", base + "/moved")
m[0:2] = b"QQ"
m.flush(); m.close()
print(open(base + "/moved").read())
""",
    )
    assert out == ["QQ23456789"]


def test_standard_streams_and_directories_sync_truncate_and_set_nonblocking(guest: Guest) -> None:
    """The real Pyodide: fsync of 0-2 and of a directory is None, FIONBIO / F_SETFL O_NONBLOCK / os.set_blocking succeed
    on them, ftruncate is EINVAL. The read side stays POSIX's (get_blocking(0..2) True, F_GETFL 0/1/1), but a flag that
    was set is read back, and shared by dup (Pyodide's own F_GETFL values 2048/2049 are not copied)."""
    out = run(
        guest,
        """
def r(fn):
    try:
        x = fn()
        return "ok" if x is None or isinstance(x, bytes) else x
    except OSError as e:
        return errno.errorcode.get(e.errno, e.errno)

d = os.open(base + "/d", os.O_RDONLY | os.O_DIRECTORY)
for n, fd in (("0", 0), ("1", 1), ("2", 2), ("dir", d)):
    a = [r(lambda: os.fsync(fd)), r(lambda: os.ftruncate(fd, 0)), os.get_blocking(fd)]
    a += [r(lambda: fcntl.ioctl(fd, termios.FIONBIO, b"\\1\\0\\0\\0")), os.get_blocking(fd)]
    a += [r(lambda: os.set_blocking(fd, True)), os.get_blocking(fd)]
    a += [r(lambda: os.set_blocking(fd, False)), os.get_blocking(fd)]
    d2 = os.dup(fd)
    a += [os.get_blocking(d2), bool(fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_NONBLOCK)]
    os.close(d2)
    a += [r(lambda: fcntl.fcntl(fd, fcntl.F_SETFL, 0)), os.get_blocking(fd)]
    a += [r(lambda: fcntl.fcntl(fd, fcntl.F_SETFL, os.O_NONBLOCK)), os.get_blocking(fd)]
    a += [r(lambda: fcntl.ioctl(fd, termios.FIONBIO, b"\\0\\0\\0\\0")), os.get_blocking(fd)]
    print(n, *a)
print([fcntl.fcntl(n, fcntl.F_GETFL) for n in (0, 1, 2)])
print(r(lambda: os.fsync(99)), r(lambda: os.ftruncate(99, 0)), r(lambda: os.set_blocking(99, False)))
""",
    )
    line = "ok EINVAL True ok False ok True ok False False True 0 True 0 False ok True"
    assert out == [f"{n} {line}" for n in ("0", "1", "2", "dir")] + ["[0, 1, 1]", "EBADF EBADF EBADF"]


def test_a_program_that_closes_1_or_2_ends_without_a_shutdown_error(guest: Guest) -> None:
    """os.close(1): write/read/fstat/fsync on it are EBADF, print() raises it, and the end of the run does not flush the
    dead stream again (it printed `OSError: [Errno 8]` and exited 255; Pyodide has no such end). The number of the next
    open() differs from Pyodide's (BACKLOG W5), so it is not asserted."""
    code = """
import os
def r(fn):
    try:
        fn()
        return "ok"
    except OSError as e:
        return e.errno
os.close(1)
msg = [r(lambda: os.write(1, b"x")), r(lambda: os.read(1, 1)), r(lambda: os.fstat(1)), r(lambda: os.fsync(1))]
msg += [r(lambda: print("x")), r(lambda: os.fsync(1))]
os.write(2, repr(msg).encode() + b"\\n")
"""
    p = guest.run(code)
    assert p.returncode == 0 and p.stdout == "", p
    assert "[8, 8, 8, 8, 8, 8]" in p.stderr and "Traceback" not in p.stderr
    p = guest.run("import os\nos.close(2)\nraise ValueError('boom')")
    assert p.returncode == 1 and p.stdout == "" and "boom" not in p.stderr, p
