"""Pyodide's official test suite of CPython (python_tests.yaml and test_core_python.py of 315.0.0a2), on both builds.

One guest process per test module (there is no fork and a crash must not take the rest with it), the same snippet as
Pyodide's `test_cpython_core`: libregrtest with the entry's `skip` globs; an `xfail` entry is not run (reported as
xfail, as Pyodide does; PYODIDE_SUITE_RUN_XFAIL=1 runs them and reports the truth), a module that skips at import or
runs no tests is a skip. Not here: the tests of the JavaScript API and `@run_in_pyodide` (they need a browser or Node).

    uv run pytest -m suite                                    # all, both builds (about an hour on 4 cores)
    uv run pytest -m suite -k "fused and (test_abc or test_json)"
    PYODIDE_SUITE_SHARD=2/8 uv run pytest -m suite            # a part of it (CI runs one job per build with -n auto)
    PYODIDE_SUITE_FLAVORS=fused uv run pytest -m suite
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from textwrap import dedent
from typing import Any

import pytest
from boot_modules import BOOT_MODULES
from conftest import missing, testenv

from pyodide_nojs import FLAVORS

pytestmark = pytest.mark.suite

RUN_XFAIL = bool(os.environ.get("PYODIDE_SUITE_RUN_XFAIL"))
FLAVORS_WANTED = [f for f in os.environ.get("PYODIDE_SUITE_FLAVORS", ",".join(FLAVORS)).split(",") if f]
# Pyodide's timeouts are for a browser around a warm Pyodide; ours include the start of a process
TIMEOUT_FACTOR = float(os.environ.get("PYODIDE_SUITE_TIMEOUT_FACTOR", "4"))

GUEST = """
res = None
import importlib
import platform
import sys
import unittest
from test.libregrtest.main import main
sys.excepthook = sys.__excepthook__

for _name in {boot_modules}:  # what Pyodide's own start-up has imported (tests/boot_modules.py)
    try:
        importlib.import_module(_name)
    except Exception:
        pass
platform.platform(aliased=True)
import _testcapi
if hasattr(_testcapi, "raise_SIGINT_then_send_None"):
    # This uses raise() which doesn't work.
    del _testcapi.raise_SIGINT_then_send_None

try:
    importlib.import_module("test.{name}")
except unittest.SkipTest as e:
    res = f"skip:{{e}}"
finally:
    sys.modules.pop("test.{name}", None)

if res is None:
    match_tests = [[pat, False] for pat in {ignore_tests}]
    try:
        main(["{name}"], match_tests=match_tests, verbose=True, verbose3=True)
    except SystemExit as e:
        if e.code == 4:
            res = e.code
        elif e.code != 0:
            raise RuntimeError(f"Failed with code: {{e.code}}")
print("PW_RESULT:", repr(res))
"""


def load_entries() -> list[tuple[str, dict[str, Any]]]:
    path = testenv() / "python_tests.yaml"
    if not path.exists():
        return []
    import yaml

    out = []
    for entry in yaml.safe_load(path.read_text()):
        if isinstance(entry, str):
            out.append((entry, {}))
        else:
            ((name, info),) = entry.items()
            out.append((name, info or {}))
    return out


ENTRIES = load_entries()


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "module" in metafunc.fixturenames:
        metafunc.parametrize("module", ENTRIES or [("(no python_tests.yaml)", {})], ids=lambda e: e[0])
    if "suite_flavor" in metafunc.fixturenames:
        metafunc.parametrize("suite_flavor", FLAVORS_WANTED)


def test_cpython_core(suite_flavor: str, module: tuple[str, dict[str, Any]]):
    name, info = module
    if not ENTRIES:
        missing(f"{testenv() / 'python_tests.yaml'} is missing")
    if "segfault" in info:
        pytest.skip(f"known segfault: {info['segfault']}")
    xfails = [v for k, v in info.items() if k == "xfail"]
    if xfails and not RUN_XFAIL:
        pytest.xfail(f"known failure: {xfails[0]}")
    ignore_tests = info.get("skip", [])
    if not isinstance(ignore_tests, list):
        raise Exception("Invalid python_tests.yaml entry: 'skip' should be a list")
    timeout = info.get("timeout", 30)

    t = testenv()
    for d in (t / "suite" / "test", t / "suite_ext"):
        if not d.is_dir():
            missing(f"{d} is missing")
    cmd = [
        sys.executable,
        "-m",
        "pyodide_nojs",
        "--flavor",
        suite_flavor,
        "--site",
        str(t / "suite_ext"),
        "--mount",
        f"/lib/python3.15/site-packages/test={t / 'suite' / 'test'}",
        "-c",
        dedent(GUEST).format(name=name, ignore_tests=repr(ignore_tests), boot_modules=repr(BOOT_MODULES)),
    ]
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(timeout * TIMEOUT_FACTOR, 120),
            stdin=subprocess.DEVNULL,  # a test that reads stdin gets EOF, not the terminal of this run
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"")[-1500:]
        pytest.fail(f"timeout after {e.timeout:.0f} s (Pyodide's limit is {timeout} s); output ends: {out!r}")
    m = re.search(r"^PW_RESULT: (.*)$", p.stdout, re.M)
    if p.returncode != 0 or not m:
        pytest.fail(f"exit {p.returncode}\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")
    res = m.group(1)
    if res == "4":
        pytest.skip("No tests ran")
    if res.startswith("'skip:"):
        pytest.skip(res[len("'skip:") :].rstrip("'") or f"{name} skipped")
