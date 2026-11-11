"""Offline: the first batch of differences the differential audits found against Pyodide (docs/DIFF_AUDIT_runtime.md
N2-N9, docs/DIFF_AUDIT_files.md N1-N4), on both packagings. Each test fails on the build before the fix."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from conftest import Guest

from pyodide_wasmtime import Pyodide
from pyodide_wasmtime._host import BASE_ENV

# ----------------------------------------------------------------------------------------------------- runtime


def test_callback_with_three_arguments_can_make_a_wasi_call(guest: Guest) -> None:
    """N5: the stack pointer of a closure was not 16-aligned, so `fstat` trapped ("Pointer not aligned to 8")."""
    code = (
        "import os\nfrom ctypes import CFUNCTYPE, c_int, c_double\n"
        "def body(*a):\n    os.fstat(1)\n    return 7\n"
        "print(CFUNCTYPE(c_int, c_int, c_double, c_int)(body)(1, 0.5, 2))\n"
    )
    r = guest.run(code)
    assert (r.returncode, r.stdout.strip()) == (0, "7"), r.stderr


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("import os; os._exit(255)", 255),
        ("import os; os._exit(126)", 126),
        ("import os; os._exit(-1)", 255),
        ("import os, signal; os.kill(os.getpid(), signal.SIGTERM)", 143),
        ("import ctypes; ctypes.CDLL(None).exit(200)", 200),
        ("import sys; sys.exit(True)", 1),
        ("import sys; sys.exit(256 + 5)", 5),
        ("import sys; sys.exit(2**70)", 255),
        ("import sys; sys.exit('text')", 1),
    ],
)
def test_exit_status(guest: Guest, code: str, status: int) -> None:
    """N2, N4: 126 and above was a failure of the host (wasmtime refuses it), `sys.exit(True)` was int('True')."""
    r = guest.run(code)
    assert r.returncode == status, (r.returncode, r.stderr)
    assert "host function failed" not in r.stderr and "Traceback" not in r.stderr


def test_cpu_time_clocks_are_the_hosts(guest: Guest) -> None:
    """N3 (and D12): the CPU-time clocks answer with the host's CPU time, where wasmtime says EBADF."""
    code = """
import time, ctypes, errno
a = time.process_time()
t0 = time.clock_gettime(time.CLOCK_PROCESS_CPUTIME_ID)
t1 = time.clock_gettime(time.CLOCK_THREAD_CPUTIME_ID)
sum(i * i for i in range(300000))
b = time.process_time()
print(b > a, time.clock_gettime(time.CLOCK_PROCESS_CPUTIME_ID) > t0, t1 >= 0)
print(time.clock_getres(time.CLOCK_PROCESS_CPUTIME_ID) > 0, time.clock_getres(time.CLOCK_THREAD_CPUTIME_ID) > 0)
print(ctypes.CDLL(None).clock() > 0)
for cid in (4, 99, -1):
    try:
        time.clock_gettime(cid)
    except OSError as e:
        print(cid, errno.errorcode[e.errno])
"""
    r = guest.run(code)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["True True True", "True True", "True", "4 EINVAL", "99 EINVAL", "-1 EINVAL"]


def test_excepthook_is_called_for_an_uncaught_exception(guest: Guest) -> None:
    """N6: the host printed the traceback itself and never called a custom `sys.excepthook`."""
    r = guest.run("import sys\nsys.excepthook = lambda *a: print('hook', a[0].__name__)\nraise KeyError('k')")
    assert (r.returncode, r.stdout.strip()) == (1, "hook KeyError"), r.stderr
    assert "Traceback" not in r.stderr


def test_stdout_is_line_buffered_on_a_pipe(guest: Guest) -> None:
    """N7: a line printed before `os._exit` or an abort was lost on a pipe (line_buffering was False)."""
    r = guest.run("import os, sys; print('seen', sys.stdout.line_buffering); os._exit(3)")
    assert (r.returncode, r.stdout) == (3, "seen True\n")
    r = guest.run("import ctypes; print('before the trap'); ctypes.CDLL(None).abort()")
    assert r.returncode == 134 and r.stdout == "before the trap\n"


ENV_CODE = """
import os, sys, pathlib, getpass
print(sorted(os.environ))
print(os.path.expanduser('~'), pathlib.Path.home(), getpass.getuser(), os.get_exec_path())
print(sys.path)
print(sorted(os.listdir('/home')), os.getcwd())
"""


def test_guest_environment_is_pyodides_and_isolated(guest: Guest, monkeypatch: pytest.MonkeyPatch) -> None:
    """N8, N9 and D13: Pyodide's minimal environment, no PYTHONHOME/PYTHONPATH in it, stdlib before site-packages,
    /home/pyodide exists, and a variable of the host's process is not seen."""
    monkeypatch.setenv("WASMHOST_TEST_SECRET", "hunter2")
    monkeypatch.setenv("HOME", "/host/home")
    r = guest.run(ENV_CODE)
    assert r.returncode == 0, r.stderr
    keys, home, path, listing = r.stdout.splitlines()
    assert "WASMHOST_TEST_SECRET" not in r.stdout and "hunter2" not in r.stdout and "/host/home" not in r.stdout
    names = eval(keys)  # noqa: S307  (our own output)
    assert {k for k, _ in BASE_ENV} <= set(names)
    assert not {"PYTHONHOME", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONINSPECT"} & set(names)
    assert home == "/home/pyodide /home/pyodide web_user ['/']"
    p = eval(path)  # noqa: S307
    assert p == ["", "/lib/python315.zip", "/lib/python3.15/lib-dynload", "/lib/python3.15/site-packages"]
    assert "pyodide" in eval(listing.rsplit(" ", 1)[0])  # noqa: S307


def test_inherit_env_and_env_flags(guest: Guest, monkeypatch: pytest.MonkeyPatch) -> None:
    """--inherit-env passes the host's variables (not the interpreter's own); --env K=V wins over it."""
    monkeypatch.setenv("WASMHOST_TEST_SECRET", "hunter2")
    monkeypatch.setenv("PYTHONPATH", "/nowhere")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/nowhere")
    code = (
        "import os; e = os.environ; print(*map(e.get, ('WASMHOST_TEST_SECRET', 'K', 'PYTHONPATH', 'LD_LIBRARY_PATH')))"
    )
    r = guest.run(code, None, "--inherit-env", "--env", "K=v", "--env", "WASMHOST_TEST_SECRET=mine")
    assert (r.returncode, r.stdout.strip()) == (0, "mine v None /usr/lib:/lib/python3.15/site-packages"), r.stderr
    r = guest.run(code, None, "--env", "K=v")
    assert r.stdout.split()[:3] == ["None", "v", "None"], r.stderr


def test_mount_cwd(guest: Guest, tmp_path: Path) -> None:
    """--mount-cwd: the host's current folder is the guest's working directory."""
    (tmp_path / "hello.txt").write_text("hi")
    import subprocess

    cmd = [sys.executable, "-m", "pyodide_wasmtime", "--flavor", guest.flavor, "--mount-cwd", "-c"]
    r = subprocess.run(
        [*cmd, "import os; print(os.getcwd(), open('hello.txt').read()); open('new.txt', 'w').write('x')"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
    )
    assert (r.returncode, r.stdout.strip()) == (0, "/host hi"), r.stderr
    assert (tmp_path / "new.txt").read_text() == "x"


def test_inherit_env_is_an_api_option(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WASMHOST_TEST_SECRET", "hunter2")
    isolated = dict(Pyodide(inherit_env=False)._wasi_env())
    inherited = dict(Pyodide(inherit_env=True, env={"HOME": "/h"})._wasi_env())
    assert "WASMHOST_TEST_SECRET" not in isolated and isolated["HOME"] == "/home/pyodide"
    assert inherited["WASMHOST_TEST_SECRET"] == "hunter2" and inherited["HOME"] == "/h"


# ------------------------------------------------------------------------------------------------------- files


def test_lseek_validates_whence_and_offsets(guest: Guest) -> None:
    """Files N1, N4: whence outside 0..2 killed the guest (WASI's enum conversion), an offset beyond 2**53 left errno 0
    and a pending exception (SystemError on every later call)."""
    code = """
import os, errno
fd = os.open('/tmp/f', os.O_RDWR | os.O_CREAT); os.write(fd, b'0123456789')
def c(*a):
    try: return os.lseek(fd, *a)
    except OSError as e: return errno.errorcode[e.errno]
print(c(0, 3), c(0, 4), c(0, 7), c(0, -1))
print(c(2 ** 63 - 1, 0), c(1, 1), c(2 ** 62, 1), c(2 ** 63 - 1, 2), c(-2 ** 62, 0), c(0, 1))
try: os.lseek(99, 0, 7)
except OSError as e: print(errno.errorcode[e.errno])
print(c(0, 0), c(3, 0), c(2, 1), c(-1, 2))
"""
    r = guest.run(code)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "EINVAL EINVAL EINVAL EINVAL",
        "EFBIG 11 EFBIG EFBIG EFBIG 11",
        "EBADF",
        "0 3 5 9",
    ]


def test_read_of_zero_bytes_does_not_wait_for_stdin(guest: Guest) -> None:
    """Files N2: `os.read(0, 0)` hung forever (it is b'' at once in Pyodide)."""
    r = guest.run("import os; print(os.read(0, 0))", timeout=60)
    assert (r.returncode, r.stdout.strip()) == (0, "b''"), r.stderr


def test_preopen_descriptors_are_not_the_guests(guest: Guest) -> None:
    """Files N3: close(3) closed the guest's root, so every later open failed; fstat/dup/read/write/seek on a preopen
    number must be EBADF as for a free number (the numbering itself is a later step)."""
    code = """
import os, errno
def c(n, f):
    try: r = f()
    except OSError as e: r = errno.errorcode[e.errno]
    print(n, r)
for fd in (3, 4):
    c('close', lambda: os.close(fd))
    c('fstat', lambda: os.fstat(fd))
    c('dup', lambda: os.dup(fd))
    c('read', lambda: os.read(fd, 1))
    c('write', lambda: os.write(fd, b'x'))
    c('lseek', lambda: os.lseek(fd, 0, 0))
    c('fsync', lambda: os.fsync(fd))
    c('ftruncate', lambda: os.ftruncate(fd, 0))
    c('fchdir', lambda: os.chdir(fd))
    c('listdir', lambda: os.listdir(fd))
    c('dup2', lambda: os.dup2(0, fd))
    c('openat', lambda: os.open('x', os.O_RDONLY, dir_fd=fd))
    c('fcntl', lambda: __import__('fcntl').fcntl(fd, 1))
print(os.listdir('/') != [], os.path.exists('/lib'), os.close(os.open('/tmp', 0)) is None)
"""
    r = guest.run(code, None, "--dev")
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[-1] == "True True True"
    # descriptor 4 is a preopen only with --dev (the root is 3): the others are as for a free number
    assert all(ln.endswith("EBADF") for ln in lines[:-1]), lines
