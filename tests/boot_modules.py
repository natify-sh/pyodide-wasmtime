"""What Pyodide's own start-up imports, and a plain `Py_Initialize` does not.

Pyodide's JavaScript runs Python code of its own at start: the packages `_pyodide` and `pyodide` (30 files, in the same
`python_stdlib.zip` that this package ships). `pyodide.webloop` imports asyncio, `_pyodide._importhook` imports
importlib.abc, importlib.machinery and importlib.util, and so on: 197 modules are loaded when Pyodide is ready on Node,
82 in a plain start. Some tests of the official suite use these modules without importing them and pass in Pyodide
only because of that, so the suite's guest imports the same packages first (191 of the 197 modules; the rest is
`glob` and the two `pyodide_js*` modules of the JavaScript side). The package itself does not: its start is CPython's.
"""

BOOT_MODULES = [
    "_pyodide",
    "_pyodide._base",
    "_pyodide._importhook",
    "pyodide",
    "pyodide._package_loader",
    "pyodide.code",
    "pyodide.common",
    "pyodide.ffi",
    "pyodide.webloop",
    "glob",
]
