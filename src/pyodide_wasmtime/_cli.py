"""pyodide-wasmtime [-c CODE | FILE] [ARGS...]: run Python in Pyodide on wasmtime; with no code, a REPL on a terminal or
the script on stdin."""

from __future__ import annotations

import argparse
import logging
import sys

from . import PYODIDE_ABI, PYODIDE_VERSION, __version__
from ._host import FLAVORS, Pyodide

REPL = (
    "import code, sys; "
    "code.interact(banner='Python ' + sys.version.split()[0] + ' on wasmtime (Pyodide {v})', exitmsg='')"
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pyodide-wasmtime", description=__doc__)
    ap.add_argument("-c", dest="code", help="program text")
    ap.add_argument("file", nargs="?", help="a script (a host file)")
    ap.add_argument("args", nargs=argparse.REMAINDER, help="arguments for the program (sys.argv[1:])")
    ap.add_argument(
        "--flavor", choices=FLAVORS, help="the build: fused (one module) or dynamic (adapter linked at run time)"
    )
    ap.add_argument(
        "--site", action="append", default=[], metavar="DIR", help="a folder copied into site-packages (repeatable)"
    )
    ap.add_argument(
        "--mount",
        action="append",
        default=[],
        metavar="GUEST=HOST",
        help="a host folder visible in the guest (repeatable)",
    )
    ap.add_argument("--data", metavar="DIR", help="the wasm files (default: the package's, or $PYODIDE_WASMTIME_DATA)")
    ap.add_argument("--dev", action="store_true", help="give the guest the host's /dev (OpenSSL reads /dev/urandom)")
    ap.add_argument("-v", "--verbose", action="store_true", help="log the loader and the network to stderr")
    ap.add_argument("--version", action="store_true", help="print the versions and exit")
    ns = ap.parse_args(argv)
    if ns.version:
        print(f"pyodide-wasmtime {__version__} (Pyodide {PYODIDE_VERSION}, {PYODIDE_ABI})")
        return 0
    if ns.verbose:
        logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    mounts = dict(m.split("=", 1) for m in ns.mount)
    argv0: list[str] | None = None
    if ns.code is not None:
        code = ns.code
        argv0 = ["-c", *([ns.file] if ns.file else []), *ns.args]
    elif ns.file:
        with open(ns.file) as f:
            code = f.read()
        argv0 = [ns.file, *ns.args]
    elif sys.stdin.isatty():
        code = REPL.format(v=PYODIDE_VERSION)
    else:
        code = sys.stdin.read()
    with Pyodide(ns.flavor, site=ns.site, mounts=mounts, data=ns.data, preopen_dev=ns.dev or None) as py:
        return py.run(code, argv0)  # 0, 1 for an uncaught error, or the code of sys.exit()/os._exit()
