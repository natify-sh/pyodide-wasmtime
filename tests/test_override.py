"""A different pyodide.asm.wasm / python_stdlib.zip for the dynamic build: API, environment, CLI, snapshot, warnings.
The real different-version case needs another Pyodide's files (not offline): the copies here are the pinned bytes under
another name or mtime, and the warnings are checked on small modules built here."""

from __future__ import annotations

import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pytest
from conftest import Guest, missing

from pyodide_nojs import Pyodide, _engine, available_flavors, data_dir
from pyodide_nojs._cli import main
from pyodide_nojs._host import override_warnings


@pytest.fixture(autouse=True)
def dynamic(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("PYODIDE_NOJS_ASM_WASM", "PYODIDE_NOJS_STDLIB", "PYODIDE_NOJS_FLAVOR"):
        monkeypatch.delenv(var, raising=False)  # these tests set their own
    if "dynamic" not in available_flavors(data_dir()):
        missing(f"the dynamic build is not in {data_dir()}")


@pytest.fixture
def asm(tmp_path: Path) -> Path:
    """A copy of the pinned pyodide.asm.wasm."""
    p = tmp_path / "other.asm.wasm"
    shutil.copyfile(data_dir() / "pyodide.asm.wasm", p)
    return p


def touch(p: Path, seconds: int) -> Path:
    os.utime(p, ns=(10**9 * seconds, 10**9 * seconds))
    return p


def tiny_wasm(env_imports: list[str], text: bytes) -> bytes:
    """A module with only a type and an import section (env functions) and a custom section holding TEXT."""

    def sec(i: int, body: bytes) -> bytes:
        return (
            bytes([i, len(body)]) + body
            if len(body) < 128
            else bytes([i, 0x80 | len(body) & 127, len(body) >> 7]) + body
        )

    imps = b"".join(bytes([3]) + b"env" + bytes([len(n)]) + n.encode() + b"\0\0" for n in env_imports)
    return b"\0asm\1\0\0\0" + sec(1, b"\1\x60\0\0") + sec(2, bytes([len(env_imports)]) + imps) + sec(0, b"\1x" + text)


def test_api_and_env(asm: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    py = Pyodide(asm_wasm=asm)  # an override and no flavor: dynamic
    assert (py.flavor, py.asm_wasm, py.stdlib) == ("dynamic", asm, None)
    monkeypatch.setenv("PYODIDE_NOJS_ASM_WASM", str(asm))
    monkeypatch.setenv("PYODIDE_NOJS_STDLIB", str(data_dir() / "python_stdlib.zip"))
    py = Pyodide()
    assert (py.flavor, py.asm_wasm, py.stdlib) == ("dynamic", asm, data_dir() / "python_stdlib.zip")
    other = tmp_path / "x.wasm"
    other.write_bytes(b"")
    assert Pyodide(asm_wasm=other).asm_wasm == other  # the argument wins
    with pytest.raises(ValueError, match="fused module is built for one Pyodide"):
        Pyodide("fused")
    monkeypatch.delenv("PYODIDE_NOJS_ASM_WASM")
    monkeypatch.delenv("PYODIDE_NOJS_STDLIB")
    with pytest.raises(ValueError, match="use dynamic"):
        Pyodide("fused", stdlib=data_dir() / "python_stdlib.zip")
    with pytest.raises(FileNotFoundError, match="nope.wasm"):
        Pyodide(asm_wasm=tmp_path / "nope.wasm")
    monkeypatch.setenv("PYODIDE_NOJS_STDLIB", str(tmp_path / "nope.zip"))
    with pytest.raises(FileNotFoundError, match=r"nope.zip.*PYODIDE_NOJS_STDLIB"):
        Pyodide()


def test_old_env_names_are_still_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The PYODIDE_WASMTIME_* names of before the rename are read when the PYODIDE_NOJS_* one is not set."""
    monkeypatch.delenv("PYODIDE_NOJS_CACHE", raising=False)
    monkeypatch.setenv("PYODIDE_WASMTIME_CACHE", str(tmp_path / "old"))
    assert _engine.cache_dir() == tmp_path / "old"
    monkeypatch.setenv("PYODIDE_NOJS_CACHE", str(tmp_path / "new"))
    assert _engine.cache_dir() == tmp_path / "new"


def test_stdlib_override_is_the_one_used(tmp_path: Path) -> None:
    z = tmp_path / "std.zip"
    shutil.copyfile(data_dir() / "python_stdlib.zip", z)
    with zipfile.ZipFile(z, "a") as f:
        f.writestr("zz_override_marker.py", "VALUE = 42\n")
    with Pyodide("dynamic", stdlib=z) as py:
        assert py.run("import zz_override_marker; print(zz_override_marker.VALUE)") == 0
    with Pyodide("dynamic") as py:
        assert py.run("import zz_override_marker") == 1


def test_snapshot_key_follows_the_files_loaded(
    asm: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd
) -> None:
    monkeypatch.setenv("PYODIDE_NOJS_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv("PYODIDE_NOJS_SNAPSHOT", raising=False)
    b = tmp_path / "b.asm.wasm"
    shutil.copyfile(asm, b)
    touch(asm, 1_000_000_000)
    touch(b, 1_100_000_000)

    def key(**kw: Any) -> Path:
        return Pyodide("dynamic", preload="x = 1\n", **kw)._snapshot_path()

    assert key(asm_wasm=asm) == key(asm_wasm=asm)
    assert len({key(asm_wasm=asm), key(asm_wasm=b), key()}) == 3
    z = tmp_path / "std.zip"
    shutil.copyfile(data_dir() / "python_stdlib.zip", z)
    touch(z, 1_000_000_000)
    assert key(stdlib=z) != key()

    def snaps() -> list[Path]:
        return sorted((tmp_path / "cache").glob("snapshot-*.mem"))

    def start(**kw: Any) -> bool:
        with Pyodide("dynamic", preload="x = 1\n", **kw) as py:
            assert py.run("print(x)") == 0
            return py.restored

    assert [start(asm_wasm=asm), start(asm_wasm=asm)] == [False, True]
    (override_snap,) = snaps()
    assert start() is False  # a normal start does not reuse the override's snapshot
    (normal_snap,) = snaps()  # one snapshot per packaging is kept: the new key replaced the old
    assert normal_snap != override_snap


def test_cli(asm: Path, capfd) -> None:
    with pytest.raises(SystemExit) as e:
        main(["--flavor", "fused", "--asm-wasm", str(asm), "-c", "pass"])
    assert e.value.code == 2 and "fused module is built for one Pyodide" in capfd.readouterr().err
    r = Guest("dynamic").run(
        "print(6 * 7)", None, "--asm-wasm", str(asm), "--stdlib", str(data_dir() / "python_stdlib.zip")
    )
    assert r.returncode == 0 and r.stdout == "42\n"
    assert "lacks the setsockopt patch" not in r.stderr  # the pinned bytes warn of nothing


def test_warnings_on_a_foreign_module(tmp_path: Path) -> None:
    names = [f"js_thing_{i}" for i in range(12)]
    foreign = tmp_path / "foreign.wasm"
    foreign.write_bytes(tiny_wasm(["__syscall_openat", *names], b"\0" + b"3.14.1" + b"\0"))
    warn, detail = override_warnings(foreign, None, data_dir())
    text = "\n".join(warn)
    assert "does not carry CPython 3.15.0rc1" in text and "3.14.1" in text  # (a)
    assert "imports 12 env functions that the adapter does not know" in text  # (b)
    assert detail == ["unknown env imports: " + ", ".join(sorted(names)[:10]) + " ..."]
    assert "lacks the setsockopt patch" in text  # (c)
    assert len(warn) == 3
    clean = tiny_wasm(["__syscall_setsockopt_host"], b"\0" + b"3.15.0rc1" + b"\0")
    foreign.write_bytes(clean)
    assert override_warnings(foreign, None, data_dir()) == ([], [])


def test_stdlib_of_another_python_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    z = tmp_path / "std.zip"
    with zipfile.ZipFile(data_dir() / "python_stdlib.zip") as src, zipfile.ZipFile(z, "w") as dst:
        for item in src.infolist():
            blob = src.read(item.filename)
            if item.filename.startswith("_sysconfigdata_"):
                blob = blob.replace(b"'VERSION': '3.15'", b"'VERSION': '3.14'")
            dst.writestr(item, blob)
    assert override_warnings(None, data_dir() / "python_stdlib.zip", data_dir()) == ([], [])
    with caplog.at_level(logging.WARNING, logger="pyodide_nojs"), Pyodide("dynamic", stdlib=z) as py:
        assert py.run("pass") == 0
        assert py.run("pass") == 0
    assert [r.getMessage() for r in caplog.records if "is for Python 3.14" in r.getMessage()] != []
    assert len([r for r in caplog.records if "is for Python" in r.getMessage()]) == 1  # once per start


def test_legacy_exceptions_are_converted_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pyodide_nojs import _engine

    def sec(i: int, body: bytes) -> bytes:
        return bytes([i, len(body)]) + body

    body = bytes([0, 0x06, 0x40, 0x01, 0x19, 0x01, 0x0B, 0x0B])  # try nop catch_all nop end
    legacy = tmp_path / "legacy.wasm"
    legacy.write_bytes(
        b"\0asm\1\0\0\0"
        + sec(1, b"\1\x60\0\0")
        + sec(3, b"\1\0")
        + sec(7, b"\1\1f\0\0")
        + sec(10, bytes([1, len(body)]) + body)
    )
    monkeypatch.setenv("PYODIDE_NOJS_CACHE", str(tmp_path / "cache"))
    calls: list[int] = []
    real = _engine.translate_to_exnref
    monkeypatch.setattr(_engine, "translate_to_exnref", lambda d, w: (calls.append(1), real(d, w))[1])
    opt = data_dir() / "wasm-opt.wasm"
    with pytest.raises(Exception, match="legacy_exceptions"):
        _engine.load_module(legacy)  # without wasm_opt: refused, as before
    done: list[Path] = []
    _engine.load_module(legacy, wasm_opt=opt, converted=done)
    assert (calls, done) == ([1], [legacy.resolve()])
    _engine.STATE.clear()  # a new process: only the machine-code cache is left
    done.clear()
    _engine.load_module(legacy, wasm_opt=opt, converted=done)
    assert (calls, done) == ([1], [])
