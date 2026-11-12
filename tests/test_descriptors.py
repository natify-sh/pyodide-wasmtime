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
    """mmap holds a reference to the open file (not a number, not a re-opening by name; Pyodide: EBADF at flush)."""
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
    dead stream again (it printed `OSError: [Errno 8]` and exited 255; Pyodide has no such end). The next open() is
    descriptor 1 again, as in Pyodide (and in a kernel)."""
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
msg += [r(lambda: print("x")), r(lambda: os.fsync(1)), os.open("/", os.O_RDONLY)]
os.write(2, repr(msg).encode() + b"\\n")
"""
    p = guest.run(code)
    assert p.returncode == 0 and p.stdout == "", p
    assert "[8, 8, 8, 8, 8, 8, 1]" in p.stderr and "Traceback" not in p.stderr
    p = guest.run("import os\nos.close(2)\nraise ValueError('boom')")
    assert p.returncode == 1 and p.stdout == "" and "boom" not in p.stderr, p


def test_the_end_of_a_run_reports_a_failed_flush_as_cpython_does(guest: Guest) -> None:
    """A closed descriptor (EBADF) is skipped at the end of a run; any other error of the final flush is a message on
    stderr and status 120 (CPython's shutdown), and a non-zero status of the program itself is kept."""
    code = """
import sys, errno
class S:
    def write(self, s): return len(s)
    def flush(self): raise OSError(%s, 'x')
sys.stdout = S()
%s
"""
    p = guest.run(code % ("errno.EIO", ""))
    assert p.returncode == 120 and "Exception ignored in" in p.stderr and "] x" in p.stderr, p
    p = guest.run(code % ("errno.EIO", "sys.exit(3)"))
    assert p.returncode == 3 and "Exception ignored in" in p.stderr and "] x" in p.stderr, p
    p = guest.run(code % ("errno.EBADF", ""))
    assert p.returncode == 0 and "Exception ignored" not in p.stderr, p


def test_a_directory_number_above_1024_keeps_its_nonblocking_flag(guest: Guest) -> None:
    """The table has 4096 numbers (it had 1024, and WASI's numbers above that were accepted and not kept): a directory
    held as number 1102 keeps O_NONBLOCK like any other, and the numbers beside it are untouched."""
    out = run(
        guest,
        """
held = [os.open(base, os.O_RDONLY | os.O_DIRECTORY) for _ in range(1100)]
x = held[-1]
print(x == 1102)
before = [fcntl.fcntl(n, fcntl.F_GETFD) for n in (0, 1, 2, 4)]
os.set_blocking(x, False)
print(os.get_blocking(x), os.get_blocking(held[0]), os.get_blocking(held[-2]))
fcntl.ioctl(x, termios.FIONBIO, b"\\0\\0\\0\\0")
print(os.get_blocking(x), before == [fcntl.fcntl(n, fcntl.F_GETFD) for n in (0, 1, 2, 4)])
""",
    )
    assert out == ["True", "False True True", "True True"]


# ---- the numbers: a kernel's (BACKLOG B5), whatever WASI's allocator hands out. The expected values are the real
# Pyodide 315.0.0-alpha.2 on Node's, except where a test says it differs.


def test_numbers_start_at_3_and_every_new_one_is_the_lowest_free(guest: Guest) -> None:
    out = run(
        guest,
        """
import socket
log = []
a = os.open(base + "/f", os.O_RDONLY); b = os.open(base + "/f", os.O_RDONLY)
log.append(("first, second", a, b))
os.close(a); x = os.open(base + "/f", os.O_RDONLY)
log.append(("the freed one again", x == a))
sv = os.dup(1)                 # the standard output is kept to print at the end
log.append(("dup", sv))
os.close(1); log.append(("open after close(1)", os.open(base + "/f", os.O_RDONLY)))
os.close(0); log.append(("open after close(0)", os.open(base + "/f", os.O_RDONLY)))
os.close(2); log.append(("dup after close(2)", os.dup(x)))
log.append(("dup", os.dup(x)))
log.append(("pipe", os.pipe()))
s = socket.socket(); log.append(("socket", s.fileno()))
log.append(("F_DUPFD 10", fcntl.fcntl(x, fcntl.F_DUPFD, 10), fcntl.fcntl(x, fcntl.F_DUPFD, 10)))
os.dup2(sv, 1)
for entry in log: print(*entry)
""",
    )
    assert out == [
        "first, second 3 4",
        "the freed one again True",
        "dup 5",
        "open after close(1) 1",
        "open after close(0) 0",
        "dup after close(2) 2",
        "dup 6",
        "pipe (7, 8)",
        "socket 9",
        "F_DUPFD 10 10 11",
    ]


def test_dup2_takes_any_number_below_the_limit_and_later_calls_stay_fast(guest: Guest) -> None:
    """Pyodide: dup2 to 4000 and 4095 work, to 4096, 5000, 2**31-1 and -1 are EBADF, dup2 onto itself returns the number
    (dup3: EINVAL), F_DUPFD 4095 is 4095. It also gives 4096 and 5000 for F_DUPFD, and 4096 when 4095 is taken: EINVAL
    and EMFILE here (as in Linux: the limit is the size of the table). The old numbering opened a placeholder for every
    number below the wanted one: 200 dup + close took 3 s after a dup2 to 1000."""
    out = run(
        guest,
        """
import time
a = os.open(base + "/f", os.O_RDONLY)
def t(name, fn):
    try: r = fn()
    except OSError as e: r = "OSError " + errno.errorcode.get(e.errno, str(e.errno))
    print(name, r)
for n in (4000, 4095, 4096, 5000, 2**31 - 1, -1): t("dup2 to %d" % n, lambda: os.dup2(a, n))
t("dup2 onto itself", lambda: os.dup2(a, a))
t("dup3 onto itself", lambda: os.dup2(a, a, inheritable=False))
t("dup2 of a free number", lambda: os.dup2(777, 777))
t("F_DUPFD 4094", lambda: fcntl.fcntl(a, fcntl.F_DUPFD, 4094))
t("F_DUPFD 4095 (taken by the dup2)", lambda: fcntl.fcntl(a, fcntl.F_DUPFD, 4095))
t("F_DUPFD 4096", lambda: fcntl.fcntl(a, fcntl.F_DUPFD, 4096))
t("F_DUPFD 2**31-1", lambda: fcntl.fcntl(a, fcntl.F_DUPFD, 2**31 - 1))
print("the data of 4000", os.read(4000, 3), os.lseek(a, 0, 1))
s = time.perf_counter()
for _ in range(300):
    os.close(os.dup(a)); os.close(os.open(base + "/f", os.O_RDONLY))
print("fast", time.perf_counter() - s < 2)
print("lowest", os.dup(a), os.open(base + "/f", os.O_RDONLY))
""",
    )
    assert out == [
        "dup2 to 4000 4000",
        "dup2 to 4095 4095",
        "dup2 to 4096 OSError EBADF",
        "dup2 to 5000 OSError EBADF",
        "dup2 to 2147483647 OSError EBADF",
        "dup2 to -1 OSError EBADF",
        "dup2 onto itself 3",
        "dup3 onto itself OSError EINVAL",
        "dup2 of a free number OSError EBADF",
        "F_DUPFD 4094 4094",
        "F_DUPFD 4095 (taken by the dup2) OSError EMFILE",
        "F_DUPFD 4096 OSError EINVAL",
        "F_DUPFD 2**31-1 OSError EINVAL",
        "the data of 4000 b'012' 3",
        "fast True",
        "lowest 4 5",
    ]


def _need_host_fds(n: int) -> None:
    """Each guest file is a host descriptor too: raise the soft limit or skip (else the host says EIO, not EMFILE)."""
    try:
        import resource
    except ImportError:  # Windows
        return
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft != resource.RLIM_INFINITY and soft < n:
        if hard != resource.RLIM_INFINITY and hard < n:
            pytest.skip(f"the host's open-file limit is {hard}, the test needs {n}")
        resource.setrlimit(resource.RLIMIT_NOFILE, (n, hard))


def test_the_table_is_full_at_4096_numbers_and_a_failed_call_leaves_nothing_behind(guest: Guest) -> None:
    _need_host_fds(4300)
    """Pyodide: opens give 3..4096 (4094 files), then EMFILE; os.pipe() with one number left is EMFILE and leaks that
    number (the next open is EMFILE too); 5000 open + close pairs are fine. Here the numbers are 0..4095 (4093 files),
    a pipe or a socket that finds no room takes nothing, and the churn is no problem (it ended in EMFILE after about
    1200 files before)."""
    out = run(
        guest,
        """
import socket
files = []
try:
    while True: files.append(os.open(base + "/f", os.O_RDONLY))
except OSError as e:
    print("full", files[0], files[-1], len(files), errno.errorcode[e.errno])
print(files == list(range(3, 4096)))
os.close(files.pop())
try: os.pipe()
except OSError as e: print("pipe", errno.errorcode[e.errno])
print("the free number is still free", os.open(base + "/f", os.O_RDONLY) == 4095)
try: socket.socket()
except OSError as e: print("socket", errno.errorcode[e.errno])
try: os.dup(0)
except OSError as e: print("dup", errno.errorcode[e.errno])
for f in files: os.close(f)
for _ in range(5000): os.close(os.open(base + "/f", os.O_RDONLY))
print("churn", os.open(base + "/f", os.O_RDONLY))
""",
    )
    assert out == [
        "full 3 4095 4093 EMFILE",
        "True",
        "pipe EMFILE",
        "the free number is still free True",
        "socket EMFILE",
        "dup EMFILE",
        "churn 3",
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot rename a file that a mapping keeps open")
def test_a_mapping_uses_no_number_and_survives_the_guest_closing_all_of_them(guest: Guest) -> None:
    """Pyodide: open 3, mmap (CPython dups it: 4), dup gives 5, and the next open after closing 3 and 5 is 3 again. The
    mapping's own hold on the file (it outlives the descriptor: a difference from Pyodide) is no number: the guest can
    close every number it has and reuse them, and the mapping still writes the file it was made from."""
    out = run(
        guest,
        """
import mmap
f = os.open(base + "/f", os.O_RDWR)
m = mmap.mmap(f, 10)
n = os.dup(f)
print(f, n)
os.close(f); os.close(n)
print(os.open(base + "/d/a", os.O_RDWR))
for k in range(3, 100):
    try: os.close(k)
    except OSError: pass
others = [os.open(base + "/d/b", os.O_RDWR) for _ in range(10)]  # the numbers it had are reused
m[0:2] = b"QQ"
m.flush()
try: m.close()
except OSError: pass
print(open(base + "/f").read(), open(base + "/d/a").read(), open(base + "/d/b").read())
""",
    )
    assert out == ["3 5", "3", "QQ23456789 a b"]


def test_numbers_that_are_no_descriptor_are_ebadf_whatever_the_value(guest: Guest) -> None:
    """The numbers a guest controls (negative, past the table, 2**31-1, a number nothing was opened on, and the numbers
    the preopens have in WASI) are EBADF in every call that takes a descriptor, as in Pyodide; the few other answers are
    Python's own (a negative number to fsync, fcntl, ioctl and poll is a ValueError, isatty says False, poll says
    POLLNVAL)."""
    out = run(
        guest,
        """
import mmap
bad = 0
def t(name, n, fn):
    global bad
    try: r = fn()
    except OSError as e: r = "OSError " + errno.errorcode.get(e.errno, str(e.errno))
    except (ValueError, OverflowError) as e: r = type(e).__name__
    want = "OSError EBADF"
    if name in ("fsync", "fcntl", "ioctl", "poll") and n < 0: want = "ValueError"
    if name == "isatty": want = False
    if name == "poll" and n >= 0: want = [(n, 32)]
    if r != want:
        bad += 1; print("DIFFERENT", name, n, r)
for n in (3, 4, -1, 99, 1100, 4095, 4096, 5000, 2**31 - 1, -2**31):
    t("fstat", n, lambda: os.fstat(n))
    t("read", n, lambda: os.read(n, 1))
    t("write", n, lambda: os.write(n, b"x"))
    t("lseek", n, lambda: os.lseek(n, 0, 0))
    t("close", n, lambda: os.close(n))
    t("dup", n, lambda: os.dup(n))
    t("fsync", n, lambda: os.fsync(n))
    t("ftruncate", n, lambda: os.ftruncate(n, 0))
    t("fcntl", n, lambda: fcntl.fcntl(n, fcntl.F_GETFD))
    t("ioctl", n, lambda: fcntl.ioctl(n, termios.FIONREAD, b"\\0\\0\\0\\0"))
    t("listdir", n, lambda: os.listdir(n))
    t("fchdir", n, lambda: os.chdir(n))
    t("fchmod", n, lambda: os.fchmod(n, 0o600))
    t("fchown", n, lambda: os.fchown(n, 0, 0))
    t("pread", n, lambda: os.pread(n, 1, 0))
    t("isatty", n, lambda: os.isatty(n))
    t("get_blocking", n, lambda: os.get_blocking(n))
    t("utime", n, lambda: os.utime(n, None))
    t("open dir_fd", n, lambda: os.open("x", os.O_RDONLY, dir_fd=n))
    t("dup2 from", n, lambda: os.dup2(n, 20))
    t("poll", n, lambda: (lambda p: (p.register(n, select.POLLIN), p.poll(0)))(select.poll())[1])
    if n >= 0: t("mmap", n, lambda: mmap.mmap(n, 4))
print("different:", bad)
""",
    )
    assert out == ["different: 0"]


def test_a_standard_number_closed_and_opened_again_is_a_file_and_dup2_puts_the_stream_back(guest: Guest) -> None:
    """Pyodide: after close(1) an open is 1 and it is a regular file (not a character device, no tty), writes to 1 go
    into it; dup2(saved, 1) makes 1 the stream again. dup2 onto a number of the same object keeps it, and the object
    lives while one number is left."""
    out = run(
        guest,
        """
sv = os.dup(1)
os.close(1)
fd = os.open(base + "/f", os.O_RDWR)
st = os.fstat(1)
res = [fd, stat.S_ISREG(st.st_mode), stat.S_ISCHR(st.st_mode), os.isatty(1), os.get_blocking(1)]
os.write(1, b"AB"); os.lseek(1, 0, 0); res.append(os.read(1, 4))
os.close(1)
res.append(os.dup(sv))   # the lowest free number is 1 again
os.dup2(sv, 1)           # onto the number just made: the same object stays
res.append(stat.S_ISCHR(os.fstat(1).st_mode))
a = os.open(base + "/f", os.O_RDONLY); b = os.dup(a)
res += [os.dup2(a, b) == b, os.lseek(a, 0, 1), os.read(b, 2), os.read(a, 2)]
os.close(a)
res.append(os.read(b, 2))
print(res)
""",
    )
    assert out == ["[1, True, False, False, True, b'AB23', 1, True, True, 0, b'AB', b'23', b'45']"]
