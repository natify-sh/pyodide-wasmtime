"""pyodide-wasmtime [-c CODE | FILE] [ARGS...]: run Python in Pyodide on wasmtime; with no code, a REPL on a terminal or
the script on stdin."""

from __future__ import annotations

import argparse
import logging
import sys

from . import PYODIDE_ABI, PYODIDE_VERSION, __version__
from ._host import FLAVORS, Pyodide

# The REPL's console lives in the guest (state between lines); the host reads the lines (readline, or prompt_toolkit
# when installed) and pushes each one. The guest tells the host in /_repl whether the line needs more.
SETUP = """\
import ast, code, types


class Console(code.InteractiveConsole):
    def __init__(self, aw):
        super().__init__(__import__("__main__").__dict__)
        self.net = False
        if aw:  # top-level await, as in Pyodide's REPL: on hostnet's loop (no JavaScript, no threads)
            self.compile.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT

    def runcode(self, c):
        try:
            r = types.FunctionType(c, self.locals)()
            if isinstance(r, types.CoroutineType):
                import hostnet  # imported by the preload (the snapshot); install() patches urllib: only now

                if not self.net:
                    self.net = True
                    hostnet.install()
                r = hostnet.run(r)
        except SystemExit:
            raise
        except BaseException:
            self.showtraceback()


_console = Console({aw})
import asyncio, hostnet  # in the snapshot, so that the first `await` is fast
"""
# the banner is the host's: a preload must not print (it would print at snapshot time only)
BANNER = 'import sys; print("Python " + sys.version.split()[0] + " on wasmtime (Pyodide {v})")'
PUSH = """\
import sys
try:
    _more = _console.push({line!r})
except SystemExit:
    open("/_repl", "w").write("exit")
    raise
sys.stdout.flush()
open("/_repl", "w").write("more" if _more else "done")
"""


def _reader():
    """The line reader: prompt_toolkit if installed (extra `repl`), else input() with the host's readline if any."""
    try:
        from prompt_toolkit import PromptSession

        return PromptSession().prompt
    except ImportError:
        try:
            import readline  # noqa: F401  (input() uses it when imported)
        except ImportError:
            pass
        return input


def repl(py: Pyodide) -> int:
    """The REPL on PY, which was made with ``preload=SETUP.format(aw=...)``."""
    py.run(BANNER.format(v=PYODIDE_VERSION))
    assert py.root is not None
    flag = py.root / "_repl"
    read = _reader()
    more = False
    while True:
        try:
            line = read("... " if more else ">>> ")
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print("\nKeyboardInterrupt")
            py.run("_console.resetbuffer()")
            more = False
            continue
        flag.unlink(missing_ok=True)
        rc = py.run(PUSH.format(line=line))
        state = flag.read_text() if flag.exists() else "done"
        if state == "exit":
            return rc
        more = state == "more"


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
    ap.add_argument(
        "--asm-wasm",
        metavar="FILE",
        help="a pyodide.asm.wasm instead of the package's (implies --flavor dynamic; or $PYODIDE_WASMTIME_ASM_WASM)",
    )
    ap.add_argument(
        "--stdlib",
        metavar="FILE",
        help="a python_stdlib.zip instead of the package's (implies --flavor dynamic; or $PYODIDE_WASMTIME_STDLIB)",
    )
    ap.add_argument("--dev", action="store_true", help="give the guest the host's /dev (OpenSSL reads /dev/urandom)")
    ap.add_argument(
        "--allow-top-level-await",
        action="store_true",
        help="in the REPL, accept `await` at the top level (run on the host-fetch event loop, as in Pyodide's REPL)",
    )
    ap.add_argument("-v", "--verbose", action="store_true", help="log the loader and the network to stderr")
    ap.add_argument("--version", action="store_true", help="print the versions and exit")
    ns = ap.parse_args(argv)
    if ns.version:
        print(f"pyodide-wasmtime {__version__} (Pyodide {PYODIDE_VERSION}, {PYODIDE_ABI})")
        return 0
    if ns.verbose:
        logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    if (ns.asm_wasm or ns.stdlib) and ns.flavor == "fused":
        ap.error(
            "--asm-wasm and --stdlib replace files of the dynamic build: the fused module is built for one Pyodide"
        )
    flavor = ns.flavor or ("dynamic" if ns.asm_wasm or ns.stdlib else None)
    mounts = dict(m.split("=", 1) for m in ns.mount)
    argv0: list[str] | None = None
    code: str | None
    if ns.code is not None:
        code = ns.code
        argv0 = ["-c", *([ns.file] if ns.file else []), *ns.args]
    elif ns.file:
        with open(ns.file) as f:
            code = f.read()
        argv0 = [ns.file, *ns.args]
    elif sys.stdin.isatty():
        code = None
    else:
        code = sys.stdin.read()
    preload = SETUP.format(aw=ns.allow_top_level_await) if code is None else None
    with Pyodide(
        flavor,
        site=ns.site,
        mounts=mounts,
        data=ns.data,
        preopen_dev=ns.dev or None,
        preload=preload,
        asm_wasm=ns.asm_wasm,
        stdlib=ns.stdlib,
    ) as py:
        if code is None:
            return repl(py)
        return py.run(code, argv0)  # 0, 1 for an uncaught error, or the code of sys.exit()/os._exit()
