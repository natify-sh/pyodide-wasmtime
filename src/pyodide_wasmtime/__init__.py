"""Pyodide's CPython run by wasmtime, with no JavaScript (alpha).

    from pyodide_wasmtime import Pyodide
    with Pyodide() as py:
        py.run("import sys; print(sys.version)")

Compatible with exactly one Pyodide build, the one the wasm in `data/` comes from (`PYODIDE_VERSION`, Emscripten ABI
`PYODIDE_ABI`): the adapter answers that build's `env` imports. wasmtime-py is an optional dependency (`[wasmtime]`).
"""

try:
    from ._version import __version__
except ImportError:  # not built from a checkout with setuptools-scm
    __version__ = "0.0.0"

PYODIDE_VERSION = "315.0.0-alpha.2"  # npm / GitHub tag 315.0.0a2: Python 3.15.0rc1, Emscripten 6.0.5
PYODIDE_ABI = "pyemscripten_2026_5_wasm32"  # the platform tag of the wheels this build loads

from ._host import FLAVORS, PYVER, Pyodide, available_flavors, data_dir  # noqa: E402

__all__ = [
    "FLAVORS",
    "PYODIDE_ABI",
    "PYODIDE_VERSION",
    "PYVER",
    "Pyodide",
    "__version__",
    "available_flavors",
    "data_dir",
]
