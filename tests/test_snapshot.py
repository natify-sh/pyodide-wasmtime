"""`Pyodide(preload=...)`: a start from a cached memory snapshot gives what a normal start plus run(preload) gives."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pyodide_wasmtime import Pyodide
from pyodide_wasmtime import _engine as engine

PRE = "import json, random\nvalue = 41\ndef f(x):\n    return x + value\n"
CODE = "print(json.dumps(f(1)))\nraise ValueError('boom')"


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PYODIDE_WASMTIME_CACHE", str(tmp_path))
    monkeypatch.delenv("PYODIDE_WASMTIME_SNAPSHOT", raising=False)
    return tmp_path


def snaps(cache: Path) -> list[Path]:
    return sorted(cache.glob("snapshot-*.mem"))


def once(flavor: str, preload: str | None, code: str, capfd: pytest.CaptureFixture[str], **kw):
    with Pyodide(flavor, preload=preload, **kw) as py:
        rc = [py.run(code), py.run("print(f(2), value)")]
        restored = py.restored
    out = capfd.readouterr()
    return rc, out.out, out.err.splitlines()[-1:], restored


def test_same_as_normal_start(flavor, cache, capfd):
    want = once(flavor, None, PRE + CODE + "\n", capfd)  # no preload: the preload text is part of the program
    want_second = once(flavor, None, PRE + "print(f(2), value)", capfd)
    first = once(flavor, PRE, CODE, capfd)  # writes the snapshot
    assert len(snaps(cache)) == 1
    second = once(flavor, PRE, CODE, capfd)  # restores it
    assert (first[3], second[3]) == (False, True)
    assert first[:3] == second[:3]
    assert second[0] == [1, 0] and second[1] == "42\n43 41\n" and second[2] == want[2] == ["ValueError: boom"]
    assert want[0][0] == 1 and want_second[0][0] == 0


def test_restore_does_not_boot_python(flavor, cache, monkeypatch):
    names: list[str] = []
    orig = engine.LazyExports.__getitem__
    monkeypatch.setattr(engine.LazyExports, "__getitem__", lambda self, n: (names.append(n), orig(self, n))[1])
    with Pyodide(flavor, preload=PRE) as py:  # the control: a normal start is seen by the spy
        py.run("pass")
        assert not py.restored
    assert "Py_Initialize" in names and "PyRun_SimpleString" in names
    names.clear()
    with Pyodide(flavor, preload=PRE) as py:
        assert py.run("print(f(0))") == 0
        assert py.restored
    assert "Py_Initialize" not in names and "__wasm_call_ctors" not in names


def test_key_changes_with_preload_and_env(flavor, cache):
    paths = {
        Pyodide(flavor, preload=p, env=e)._snapshot_path()
        for p, e in [(PRE, {}), (PRE + "\n", {}), (PRE, {"A": "1"}), (PRE, {"A": "2"})]
    }
    assert len(paths) == 4


def test_corrupt_snapshot_falls_back_and_is_rewritten(flavor, cache):
    with Pyodide(flavor, preload=PRE) as py:
        py.run("pass")
    (path,) = snaps(cache)
    good = path.read_bytes()
    for bad in (good[: len(good) // 2], b"not json\n" + good, b""):
        path.write_bytes(bad)
        with Pyodide(flavor, preload=PRE) as py:
            assert py.run("print(f(1))") == 0
            assert not py.restored
        new = path.read_bytes()  # rewritten (the memory differs: the hash seed)
        assert new[:100] == good[:100] and len(new) == len(good)
    with Pyodide(flavor, preload=PRE) as py:
        py.run("pass")
        assert py.restored


def test_two_interpreters_restored_and_normal(flavor, cache, capfd):
    with Pyodide(flavor, preload=PRE) as py:
        py.run("pass")
    with Pyodide(flavor, preload=PRE) as a, Pyodide(flavor) as b:
        assert a.run("print(f(1))") == 0
        assert b.run("print('value' in dir())") == 0
        assert a.restored and not b.restored
        assert a.run("value = 1; print(value)") == 0
    assert capfd.readouterr().out == "42\nFalse\n1\n"


def test_snapshot_off(flavor, cache, monkeypatch):
    monkeypatch.setenv("PYODIDE_WASMTIME_SNAPSHOT", "0")
    with Pyodide(flavor, preload=PRE) as py:
        assert py.run("print(f(1))") == 0
        assert not py.restored
    assert snaps(cache) == []


def test_random_differs_between_restores(flavor, cache, capfd):
    with Pyodide(flavor, preload=PRE) as py:
        py.run("pass")
    capfd.readouterr()
    seen = set()
    for _ in range(2):
        with Pyodide(flavor, preload=PRE) as py:
            py.run("print(random.random())")
            assert py.restored
        seen.add(capfd.readouterr().out)
    assert len(seen) == 2


def test_key_changes_with_stdlib_stamp_and_dev(flavor, cache, monkeypatch):
    base = Pyodide(flavor, preload=PRE)._snapshot_path()
    assert Pyodide(flavor, preload=PRE, preopen_dev=True)._snapshot_path() != base
    orig = engine._stamp
    monkeypatch.setattr(engine, "_stamp", lambda p: orig(p) + (b"x" if p.name == "python_stdlib.zip" else b""))
    assert Pyodide(flavor, preload=PRE)._snapshot_path() != base


@pytest.mark.parametrize(
    "pre",
    [
        "import ctypes\nf = ctypes.pythonapi.Py_IsInitialized\n",
        "log = open('/pre.txt', 'w')\nlog.write('x')\n",
        "import os\nos.mkdir('/w')\nos.chdir('/w')\n",
        "import mmap\nopen('/mm', 'wb').write(b'x' * 10)\nf = open('/mm', 'r+b')\n"
        "m = mmap.mmap(f.fileno(), 10)\nf.close()\n",
    ],
    ids=["ctypes-slot", "open-file", "chdir", "mmap-kept"],
)
def test_preload_with_unsnapshotable_state_is_not_saved(flavor, cache, pre):
    for _ in range(2):  # the program works on both starts
        with Pyodide(flavor, preload=pre) as py:
            assert py.run("import os; print(os.getcwd())") == 0
            assert not py.restored
        assert snaps(cache) == []


def test_failing_preload_runs_once_and_is_not_saved(flavor, cache, capfd):
    for _ in range(2):
        with Pyodide(flavor, preload="raise RuntimeError('pre')") as py:
            assert py.run("pass") == 0
        assert capfd.readouterr().err.count("RuntimeError: pre") == 1
    assert snaps(cache) == []


def test_site_means_no_snapshot(flavor, cache, tmp_path):
    (tmp_path / "site").mkdir()
    for _ in range(2):
        with Pyodide(flavor, preload=PRE, site=tmp_path / "site") as py:
            assert py.run("print(f(1))") == 0
            assert not py.restored
    assert snaps(cache) == []


def test_failed_write_leaves_no_tmp_file(flavor, cache, monkeypatch):
    def boom(*a):
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", boom)
    with Pyodide(flavor, preload=PRE) as py:
        assert py.run("print(f(1))") == 0
    assert list(cache.glob("snapshot-*")) == []


def test_no_stdin_does_not_break_the_key(flavor, cache, monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    assert Pyodide(flavor, preload=PRE)._snapshot_path().name.startswith("snapshot-")


def test_a_failed_dlopen_in_the_preload_leaves_the_loader_working(flavor, cache, capfd):
    # the loader's state is wasm globals and host objects, which a snapshot (linear memory only) does not hold
    pre = "import ctypes\ntry:\n    ctypes.CDLL('/nope.so')\nexcept OSError:\n    pass\n"
    code = (
        "import ctypes\n"
        "try:\n    ctypes.CDLL('/nope2.so')\nexcept OSError as e:\n    print(str(e).replace(chr(10), '|'))\n"
        "m = ctypes.CDLL(None)\nprint(ctypes.cast(m.PyType_GenericAlloc, ctypes.c_void_p).value is not None)\n"
    )
    outs = []
    for _ in range(2):
        with Pyodide(flavor, preload=pre) as py:
            assert py.run(code) == 0
            outs.append((py.restored, capfd.readouterr().out))
    assert [r for r, _ in outs] == [False, True]
    assert outs[0][1] == outs[1][1]
    assert outs[1][1].splitlines()[0] == (
        'could not load dynamic lib: /nope2.so|Error: Failed to find dynamic library "/nope2.so"'
    )
