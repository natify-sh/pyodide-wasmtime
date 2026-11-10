"""Offline, no site folders: the interpreter itself, on both builds."""

from __future__ import annotations

from conftest import Guest

import pyodide_wasmtime as pw


def test_versions():
    assert pw.PYODIDE_VERSION == "315.0.0-alpha.2"
    assert pw.PYODIDE_ABI == "pyemscripten_2026_5_wasm32"
    assert pw.PYVER == "3.15"


def test_hello(guest: Guest):
    p = guest.run("import sys; print(sys.platform, sys.version_info[:2], sum(range(10)))")
    assert p.returncode == 0, p.stderr
    assert p.stdout.split() == ["emscripten", "(3,", "15)", "45"]


def test_stdlib_from_the_zip(guest: Guest):
    p = guest.run(
        "import json, collections, platform, hashlib, zlib, decimal, fractions, zipfile\n"
        "print(hashlib.sha256(b'a').hexdigest()[:8], zlib.crc32(b'a'), decimal.Decimal(1) / 3, json.dumps([1, 2]))"
    )
    assert p.returncode == 0, p.stderr
    assert p.stdout.split()[:2] == ["ca978112", "3904355907"]


def test_big_list_grows_the_memory(guest: Guest):
    p = guest.run("x = [i * i for i in range(2_000_000)]; print(len(x), x[-1])")
    assert p.returncode == 0, p.stderr
    assert p.stdout.split() == ["2000000", "3999996000001"]


def test_a_raised_error_is_exit_1_with_a_traceback(guest: Guest):
    p = guest.run("1 / 0")
    assert p.returncode == 1
    assert "ZeroDivisionError" in p.stderr


def test_a_caught_error(guest: Guest):
    p = guest.run("try:\n    1 / 0\nexcept ZeroDivisionError as e:\n    print('caught', e)")
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip() == "caught division by zero"


def test_files_in_the_guest(guest: Guest):
    p = guest.run(
        "import os, tempfile\n"
        "os.makedirs('/work', exist_ok=True)\n"
        "open('/work/a.txt', 'w').write('hi')\n"
        "print(open('/work/a.txt').read(), sorted(os.listdir('/work')), os.path.exists('/nope'))"
    )
    assert p.returncode == 0, p.stderr
    assert p.stdout.split() == ["hi", "['a.txt']", "False"]


def test_a_mounted_host_folder(guest: Guest, tmp_path):
    (tmp_path / "in.txt").write_text("from the host")
    p = guest.run(
        "print(open('/mnt/in.txt').read()); open('/mnt/out.txt', 'w').write('from the guest')",
        None,
        "--mount",
        f"/mnt={tmp_path}",
    )
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip() == "from the host"
    assert (tmp_path / "out.txt").read_text() == "from the guest"


def test_argv_and_a_script(guest: Guest, tmp_path):
    script = tmp_path / "s.py"
    script.write_text("import sys; print(sys.argv)")
    p = guest.run("pass", None, str(script), "a", "b")
    # `-c` wins over the script: the file is its argument
    assert p.returncode == 0, p.stderr


def test_two_interpreters_in_one_process(flavor: str):
    with pw.Pyodide(flavor) as a, pw.Pyodide(flavor) as b:
        assert a.run("x = 1") == 0
        assert b.run("assert 'x' not in dir()") == 0
        assert a.run("assert x == 1") == 0
        assert a.run("raise SystemExit(3)") != 0
