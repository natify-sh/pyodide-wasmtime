"""Offline: what the two independent reviews of the descriptor layer and of the first fix batch found, on both
packagings. Each test says which finding it is; the ones that need the new adapter fail on the build before."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import sidemod
from conftest import Guest
from wasmtime import wat2wasm

from pyodide_nojs import Pyodide

POSIX = sys.platform != "win32"

# ---------------------------------------- inherit_env and the snapshot


def test_inherit_env_makes_no_snapshot_and_no_file_holds_the_secret(
    flavor: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    """Batch 1 M1: the snapshot is the guest's whole memory, environment included: with `inherit_env` it would be the
    host's secrets in a file."""
    monkeypatch.setenv("PYODIDE_NOJS_CACHE", str(tmp_path))
    monkeypatch.delenv("PYODIDE_NOJS_SNAPSHOT", raising=False)
    monkeypatch.setenv("WASMHOST_TEST_SECRET", "hunter2-needle")
    for _ in range(2):
        with Pyodide(flavor, preload="import json\nvalue = 41", inherit_env=True) as py:
            assert py.run("import os; print(os.environ['WASMHOST_TEST_SECRET'], value)") == 0
            assert not py.restored
        assert capfd.readouterr().out == "hunter2-needle 41\n"
    for f in tmp_path.rglob("*"):
        if f.is_file():
            assert b"hunter2-needle" not in f.read_bytes(), f
    assert not list(tmp_path.glob("snapshot-*.mem"))


def test_snapshot_restores_on_the_second_start(
    flavor: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    """The bytes of the snapshot and of the compiled-module cache are intact (a Windows file in text mode would turn
    every newline byte into two): the second start restores the first one's memory and runs."""
    monkeypatch.setenv("PYODIDE_NOJS_CACHE", str(tmp_path))
    monkeypatch.delenv("PYODIDE_NOJS_SNAPSHOT", raising=False)
    for restored in (False, True):
        with Pyodide(flavor, preload="import json\nvalue = 41") as py:
            assert py.run("print(value + 1)") == 0
            assert py.restored is restored
        assert capfd.readouterr().out == "42\n"


@pytest.mark.skipif(not POSIX, reason="file modes")
def test_an_existing_cache_folder_keeps_its_mode(flavor: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A folder the user named (or that exists) is not chmod'ed; the files in it are 0600 anyway."""
    cache = tmp_path / "shared"
    cache.mkdir(mode=0o755)
    cache.chmod(0o755)
    monkeypatch.setenv("PYODIDE_NOJS_CACHE", str(cache))
    monkeypatch.delenv("PYODIDE_NOJS_SNAPSHOT", raising=False)
    with Pyodide(flavor, preload="import json") as py:
        py.run("pass")
    assert cache.stat().st_mode & 0o777 == 0o755
    files = list(cache.glob("snapshot-*.mem"))
    assert files and all(f.stat().st_mode & 0o777 == 0o600 for f in files)


@pytest.mark.skipif(not POSIX, reason="file modes")
def test_snapshot_and_cache_are_private(flavor: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setenv("PYODIDE_NOJS_CACHE", str(cache))
    monkeypatch.delenv("PYODIDE_NOJS_SNAPSHOT", raising=False)
    with Pyodide(flavor, preload="import json") as py:
        py.run("pass")
    assert cache.stat().st_mode & 0o777 == 0o700
    files = list(cache.glob("snapshot-*.mem")) + list(cache.glob("*.cwasm"))
    assert files
    assert all(f.stat().st_mode & 0o777 == 0o600 for f in files), [oct(f.stat().st_mode) for f in files]


# ---------------------------------------- exit in a constructor


def ctor_module(body: str) -> bytes:
    wat = f"""(module (import "env" "memory" (memory 0)) (import "env" "exit" (func $exit (param i32))) (tag $t)
      (func (export "__wasm_call_ctors") {body}) (func (export "f") (result i32) i32.const 1))"""
    return sidemod.with_dylink(bytes(wat2wasm(wat)))


@pytest.mark.parametrize("body", ["(call $exit (i32.const 205))", "unreachable", "(throw $t)"])
def test_exit_or_trap_in_a_constructor_is_a_failed_load(guest: Guest, tmp_path: Path, body: str) -> None:
    """Batch 1 M2: the glue's try/catch turns it into `OSError: could not load dynamic lib`; here dlopen succeeded and
    the exit was swallowed with a traceback."""
    (tmp_path / "ctor.so").write_bytes(ctor_module(body))
    code = (
        "import ctypes\n"
        "try:\n    ctypes.CDLL('/s/ctor.so')\n    print('loaded')\n"
        "except OSError as e:\n    print('OSError', str(e).splitlines()[0])\n"
        "print('alive')\n"
    )
    r = guest.run(code, None, "--mount", f"/s={tmp_path}")
    assert (r.returncode, r.stdout.splitlines()) == (0, ["OSError could not load dynamic lib: /s/ctor.so", "alive"])
    assert "Traceback" not in r.stderr, r.stderr


# ---------------------------------------- poll, pread


def test_poll_and_select_of_a_preopen_number_are_invalid(guest: Guest) -> None:
    """Batch 1 L3: the root's descriptor number is no descriptor of the guest: POLLNVAL, and select says EBADF."""
    code = """
import os, select, errno
p = select.poll(); p.register(3, select.POLLIN | select.POLLOUT)
print(p.poll(0))
try: select.select([3], [], [], 0)
except OSError as e: print(errno.errorcode[e.errno])
r, w = os.pipe()
print(select.select([r], [w], [], 0) == ([], [w], []))
"""
    r = guest.run(code)
    assert (r.returncode, r.stdout.splitlines()) == (0, ["[(3, 32)]", "EBADF", "True"]), r.stderr


def test_pread_and_pwrite_check_the_offset(guest: Guest) -> None:
    """Batch 1 L5: an offset above 2**53 is EFBIG (the glue's bigintToI53Checked), as lseek has it."""
    code = """
import os, errno
fd = os.open('/tmp/f', os.O_RDWR | os.O_CREAT); os.write(fd, b'0123456789')
def c(f, *a):
    try: return f(*a)
    except OSError as e: return errno.errorcode[e.errno]
print(c(os.pread, fd, 1, 2**62), c(os.pread, fd, 0, 2**62), c(os.pread, fd, 1, 2**53 + 8), c(os.pread, fd, 2, 3))
print(c(os.pwrite, fd, b'x', 2**62), c(os.pwrite, fd, b'x', 1))
"""
    r = guest.run(code)
    assert (r.returncode, r.stdout.splitlines()) == (0, ["EFBIG EFBIG EFBIG b'34'", "EFBIG 1"]), r.stderr


# ---------------------------------------- the environment and run()


def test_inherit_env_skips_what_is_not_utf8(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Batch 1 L6: a host variable that is not UTF-8 crashed the start with UnicodeEncodeError."""
    if not POSIX:
        pytest.skip("Windows has no undecodable variables")
    monkeypatch.setenv("WASMHOST_BAD", "\udcff")
    monkeypatch.setenv("WASMHOST_GOOD", "ok")
    with caplog.at_level("WARNING", logger="pyodide_nojs"):
        env = dict(Pyodide(inherit_env=True)._wasi_env())
    assert env["WASMHOST_GOOD"] == "ok" and "WASMHOST_BAD" not in env
    assert "WASMHOST_BAD" in caplog.text


@pytest.mark.parametrize("opt", ["--env", "--mount"])
def test_cli_option_without_an_equals_sign_is_a_usage_error(opt: str) -> None:
    r = subprocess.run(
        [sys.executable, "-m", "pyodide_nojs", opt, "NOEQUALS", "-c", "pass"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 2 and "expected" in r.stderr and "Traceback" not in r.stderr, r.stderr


def test_hostile_python_variables_do_not_break_the_host(guest: Guest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Batch 1 L7, L8: PYTHONWARNINGS=error turned the host's own unclosed files into errors, and PYTHONSAFEPATH was
    defeated by the '' that the start put first in sys.path."""
    monkeypatch.setenv("PYTHONWARNINGS", "error")
    monkeypatch.setenv("PYTHONSAFEPATH", "1")
    r = guest.run("import sys; print('' in sys.path, sys.flags.safe_path)", None, "--inherit-env")
    assert (r.returncode, r.stdout.strip()) == (0, "False True"), r.stderr
    assert "Warning" not in r.stderr and "Traceback" not in r.stderr, r.stderr


def test_sys_executable_is_the_web_pyodides(guest: Guest) -> None:
    r = guest.run("import sys; print(sys.executable); print(sys._emscripten_info.runtime)")
    out = r.stdout.splitlines()
    assert r.returncode == 0 and out[0] == "/home/pyodide/this.program", r.stderr
    assert out[1].startswith("pyodide-nojs"), out


STARTUP_STATE = """
import os, sys, zipimport
print(sys.executable, sys._base_executable, sys.orig_argv, sys.argv)
print(sys.path[:3], sys._stdlib_dir, os.getcwd(), os.listdir('/home/pyodide'))
print(zipimport.__file__, zipimport.__spec__.loader_state.filename, os.__file__)
print(sys.dont_write_bytecode, sys.flags.inspect, sys.prefix)
import _pyodide_core
"""
# Pyodide's own values (the real 315.0.0a2 on Node: executable and orig_argv are the script's path there, the web has
# Emscripten's default thisProgram "./this.program"; PYTHONINSPECT=1 of Pyodide's JavaScript is not mirrored)
STARTUP_WANT = [
    "/home/pyodide/this.program /home/pyodide/this.program ['./this.program'] ['']",
    "['', '/lib/python315.zip', '/lib/python3.15/lib-dynload'] /lib/python315.zip /home/pyodide []",
    "/lib/python315.zip/zipimport.py /lib/python315.zip/zipimport.py /lib/python315.zip/os.py",
    "True 0 /",
]


def test_startup_state_is_pyodides(flavor: str, capfd: pytest.CaptureFixture[str]) -> None:
    with Pyodide(flavor) as py:  # not the CLI: it sets sys.argv to what it was given
        assert py.run(STARTUP_STATE) == 0
    assert capfd.readouterr().out.splitlines() == STARTUP_WANT


def test_missing_site_and_mount_folders_are_said_plainly(flavor: str, tmp_path: Path) -> None:
    gone = str(tmp_path / "gone")
    with pytest.raises(FileNotFoundError, match=f"site folder not found: {re.escape(gone)}"):
        Pyodide(flavor, site=gone)
    with pytest.raises(FileNotFoundError, match=f"mount folder not found: {re.escape(gone)}"):
        Pyodide(flavor, mounts={"/m": gone})
    for opt in ("--site", "--mount"):
        arg = gone if opt == "--site" else f"/m={gone}"
        r = subprocess.run(
            [sys.executable, "-m", "pyodide_nojs", "--flavor", flavor, opt, arg, "-c", "pass"],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 2 and f"folder not found: {gone}" in r.stderr and "Traceback" not in r.stderr, r.stderr


def test_run_returns_the_status_as_a_process_exit_would(flavor: str) -> None:
    """Batch 1 L9: `sys.exit(256)` returned 256 and `os._exit(256)` returned 0."""
    codes = ["sys.exit(256)", "sys.exit(256 + 5)", "sys.exit(-1)", "sys.exit(2**70)", "sys.exit(3)", "os._exit(256)"]
    with Pyodide(flavor) as py:
        got = [py.run(f"import sys, os; {c}") for c in codes]
    assert got == [0, 5, 255, 255, 3, 0]


def test_realtime_clock_resolution_is_pyodides(guest: Guest) -> None:
    """Batch 1 L9: `clock_getres(CLOCK_REALTIME)` is 1 ms in the glue (Date.now()), WASI says 1 ns."""
    r = guest.run("import time; print(time.clock_getres(time.CLOCK_REALTIME))")
    assert (r.returncode, r.stdout.strip()) == (0, "0.001"), r.stderr


# ---------------------------------------- descriptors


def test_cloexec_is_kept_for_every_descriptor(guest: Guest) -> None:
    """Descriptor review 3: Python opens everything O_CLOEXEC (PEP 446) and F_SETFD must stick: a bit per number for
    plain descriptors and sockets too (a deliberate difference from Pyodide, whose F_GETFD is always 0).
    os.set_inheritable(fd, True) is a no-op: the libc answers FIONCLEX itself."""
    code = """
import os, fcntl, socket, ctypes
def fd_flag(fd): return fcntl.fcntl(fd, fcntl.F_GETFD)
f = os.open('/tmp', os.O_RDONLY)                      # CPython adds O_CLOEXEC
print(fd_flag(f), os.get_inheritable(f))
fcntl.fcntl(f, fcntl.F_SETFD, 0); print(fd_flag(f), os.get_inheritable(f))
fcntl.fcntl(f, fcntl.F_SETFD, 1); print(fd_flag(f), os.get_inheritable(f))
print(fd_flag(os.open('/tmp', os.O_RDONLY | os.O_CLOEXEC)), fd_flag(os.open('/tmp', os.O_RDONLY)))
s = socket.socket(); print(s.get_inheritable())
fcntl.fcntl(s, fcntl.F_SETFD, 0); print(s.get_inheritable(), fd_flag(s.fileno()))
print(fd_flag(os.dup(f)), fd_flag(ctypes.CDLL(None).dup(f)))  # Python's dup is O_CLOEXEC, libc's dup clears it
print(fd_flag(fcntl.fcntl(f, fcntl.F_DUPFD_CLOEXEC, 0)))
libc = ctypes.CDLL(None)
g = libc.open(b'/tmp', os.O_RDONLY); print(fd_flag(g))   # libc's open without O_CLOEXEC: 0
fcntl.fcntl(g, fcntl.F_SETFD, 1); os.close(g)             # closed with the bit set ...
seen = []
for _ in range(3000):                                     # ... until the number comes again: it starts clear
    h = libc.open(b'/tmp', os.O_RDONLY); seen.append(fd_flag(h))
    if h == g: break
print(h == g, set(seen))
"""
    r = guest.run(code)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "1 False", "0 True", "1 False", "1 1", "False", "True 0", "1 0", "1", "0", "True {0}",
    ]  # fmt: skip


def test_descriptors_work_after_many_files_were_opened_and_closed(guest: Guest) -> None:
    """Descriptor review 1: after 1200 files were opened and closed WASI hands out numbers above 1024, and every dup,
    pipe and socket failed with EMFILE."""
    code = """
import os, socket, time
open('/tmp/g.txt', 'w').close()
t = time.perf_counter()
for _ in range(5): os.close(os.dup(2))
base = time.perf_counter() - t                          # the same machine before the churn
L = [os.open('/tmp/g.txt', os.O_RDONLY) for _ in range(1200)]
for x in L: os.close(x)
t = time.perf_counter()
for _ in range(5): os.close(os.dup(2))
# 0.04-0.09 s after the churn; 18 s when every placeholder held the high numbers again: the bound is far from both
# (and from a stall of a loaded runner: an absolute 3 s failed once on a shared one)
print(time.perf_counter() - t < max(30 * base, 5.0))
print(os.dup(2) > 2, len(os.pipe()), socket.socket().fileno() > 2)
"""
    r = guest.run(code)
    assert (r.returncode, r.stdout.strip()) == (0, "True\nTrue 2 True"), r.stderr


def test_moving_the_holder_of_a_directory_keeps_its_listing(guest: Guest) -> None:
    """Descriptor review 4: the holder of a directory's WASI descriptor moves when its number is closed while a dup
    lives; the readdir cookie follows it (the cookie table may grow in between: a number above 256)."""
    code = """
import os
import re
os.mkdir('/tmp/dd')
for n in 'abc': open('/tmp/dd/' + n, 'w').close()
f = os.open('/tmp/dd', os.O_RDONLY | os.O_DIRECTORY)
want = sorted(os.listdir(f))
os.dup2(f, 600); os.close(f)
print(sorted(os.listdir(600)) == want, sorted(e.name for e in os.scandir(600)) == want)
os.dup2(600, 900); os.close(600)
print(sorted(os.listdir(900)) == want)
"""
    r = guest.run(code)
    assert (r.returncode, r.stdout.splitlines()) == (0, ["True True", "True"]), r.stderr


def test_a_file_opened_on_a_closed_standard_number_is_a_file(guest: Guest) -> None:
    """Descriptor review 7: `fd_std` went by the number: after close(1) the next file opened onto 1 stat'ed as a
    character device and could not seek."""
    code = """
import os, stat, sys
open('/tmp/g.txt', 'w').write('abc')
s = os.dup(1); os.close(1)
fd = os.open('/tmp/g.txt', os.O_RDONLY)
d = os.dup(fd)  # a dup of the reopened number is a file too
res = (fd == 1, stat.S_ISREG(os.fstat(fd).st_mode), os.lseek(fd, 0, 2))
res += (stat.S_ISREG(os.fstat(d).st_mode), os.lseek(d, 0, 0))
os.close(d); os.close(fd); os.dup2(s, 1); os.close(s)
print(*res)
print(stat.S_ISCHR(os.fstat(1).st_mode))
"""
    r = guest.run(code)
    assert (r.returncode, r.stdout.splitlines()) == (0, ["True True 3 True 0", "True"]), r.stderr


# ------------------------------------------------------------------------------------------ sys.path and the stdlib dir


def test_site_folders_come_before_the_stdlib_zip(guest: Guest, tmp_path: Path) -> None:
    """CI of cb1f608: a `site=` folder's real `_ssl` lost to the stub `_ssl.py` of the stdlib zip when site-packages
    was last. With `site=` they come first (as before); without it the order is Pyodide's."""
    (tmp_path / "colorsys.py").write_text("MARK = 'from the site folder'\n")
    code = "import sys, colorsys; print(sys.path[1:3]); print(getattr(colorsys, 'MARK', None))"
    r = guest.run(code, None, "--site", str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["['/lib/python3.15/site-packages', '/lib/python315.zip']", "from the site folder"]
    r = guest.run(code)
    assert r.stdout.splitlines() == ["['/lib/python315.zip', '/lib/python3.15/lib-dynload']", "None"], r.stderr


def test_a_site_folders_own_sitecustomize_runs_beside_ours(guest: Guest, tmp_path: Path) -> None:
    """Our start code is a .pth, so a `site=` folder's sitecustomize.py is not overwritten: both run."""
    (tmp_path / "sitecustomize.py").write_text("MARK = 'user sitecustomize'\n")
    code = "import sitecustomize, socket; print(sitecustomize.MARK, socket.SO_REUSEADDR)"
    r = guest.run(code, None, "--site", str(tmp_path))
    assert (r.returncode, r.stdout.splitlines()) == (0, ["user sitecustomize 2"]), r.stderr


def test_tracebacks_show_only_the_users_frames(guest: Guest) -> None:
    """The run wrapper's own frame is not in a traceback (the old one added just `File "<string>"`)."""
    for code in ("1/0\n", "def f():\n    raise ValueError('x')\nf()\n", "def (:\n"):
        r = guest.run(code)
        assert r.returncode == 1 and "Error" in r.stderr, r.stderr
        assert "pyodide_nojs" not in r.stderr and "exec(code" not in r.stderr, r.stderr
    r = guest.run("1/0\n")
    assert re.findall(r'File "[^"]*", line \d+, in <?\w+>?', r.stderr) == ['File "<string>", line 2, in <module>'], (
        r.stderr
    )


def test_a_site_folders_pyodide_nojs_run_does_not_hijack_the_run(guest: Guest, tmp_path: Path) -> None:
    (tmp_path / "pyodide_nojs_run.py").write_text("x = 1\n")
    r = guest.run("import sys; sys.exit(3)", None, "--site", str(tmp_path))
    assert r.returncode == 3, r.stderr


def test_frozen_modules_follow_the_stdlib_dir(guest: Guest) -> None:
    """CI of cb1f608: `sys._stdlib_dir` is the zip (as Pyodide's), but the frozen modules were laid out under
    /lib/python3.15 at init; a fresh import of importlib (the tests of importlib do it) asserted they agree."""
    code = """
import sys, zipimport
st = zipimport.__spec__.loader_state.filename
print(sys._stdlib_dir, zipimport.__file__ == st == sys._stdlib_dir + '/zipimport.py')
import encodings
print(encodings.__path__, encodings.__spec__.submodule_search_locations)
"""
    r = guest.run(code)
    zipdir = "/lib/python315.zip/encodings"
    want = f"/lib/python315.zip True\n['{zipdir}'] ['{zipdir}']"
    assert (r.returncode, r.stdout.strip()) == (0, want), r.stderr
