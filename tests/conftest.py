"""Fixtures: the built wasm (tools/build_data.sh), the test environment (tools/prepare_testenv.sh), both flavors."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from pyodide_nojs import FLAVORS, _engine, available_flavors, data_dir

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def work_dir() -> Path:
    return Path(os.environ.get("PYODIDE_NOJS_BUILD") or ROOT / "pyo-build")


def testenv() -> Path:
    return work_dir() / "testenv"


def missing(what: str) -> None:
    """On CI a missing build is a failure; on a checkout without one, a skip that says what to run."""
    msg = f"{what} (run tools/build_data.sh / tools/prepare_testenv.sh WORKDIR)"
    if os.environ.get("CI"):
        pytest.fail(msg)
    pytest.skip(msg)


@pytest.fixture(params=FLAVORS)
def flavor(request: pytest.FixtureRequest) -> str:
    name = request.param
    if name == "fused" and (_engine.env("PYODIDE_NOJS_ASM_WASM") or _engine.env("PYODIDE_NOJS_STDLIB")):
        pytest.skip("PYODIDE_NOJS_ASM_WASM/STDLIB replace files of the dynamic build; the fused module cannot follow")
    if name not in available_flavors(data_dir()):
        missing(f"the {name} build is not in {data_dir()}")
    return name


class Guest:
    """Runs code in Pyodide on wasmtime in a fresh process, the way a user's program would."""

    def __init__(self, flavor: str) -> None:
        self.flavor = flavor

    def run(
        self, code: str, site: str | None = None, *args: str, timeout: int = 1800
    ) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, "-m", "pyodide_nojs", "--flavor", self.flavor, "-v"]
        if site:
            path = testenv() / site
            if not path.is_dir():
                missing(f"{path} is missing")
            cmd += ["--site", str(path)]
        cmd += [*args, "-c", code]
        # stdin is /dev/null: a guest that reads it gets EOF, not a wait for the terminal of the test run
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


@pytest.fixture
def guest(flavor: str) -> Guest:
    return Guest(flavor)


def check_file(name: str) -> str:
    return (HERE / "checks" / name).read_text()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """PYODIDE_SUITE_SHARD=I/N: the suite's items are dealt out to N CI jobs, I from 1 (stable: by collection order)."""
    spec = os.environ.get("PYODIDE_SUITE_SHARD")
    if not spec:
        return
    i, n = (int(x) for x in spec.split("/"))
    suite = [it for it in items if "suite" in it.keywords]
    mine = {it.nodeid for k, it in enumerate(suite) if k % n == i - 1}
    drop = [it for it in suite if it.nodeid not in mine]
    config.hook.pytest_deselected(items=drop)
    items[:] = [it for it in items if it.nodeid not in {d.nodeid for d in drop}]
