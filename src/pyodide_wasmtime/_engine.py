"""The wasmtime engine, compiled-module cache and Binaryen's `wasm-opt.wasm`, run in-process.

wasmtime-py is imported here and nowhere in the package's top level: a missing engine is reported when it is needed
(`require_wasmtime`), the way wasmhost does it. The cache holds machine code (`Module.serialize`) keyed by the
wasmtime version and the file's size and mtime, so a second start costs a deserialize, not a compile of 10 MB of wasm.
"""

from __future__ import annotations

import atexit
import ctypes
import hashlib
import os
import sys
from collections.abc import Iterator, Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

_STATE: dict[str, Any] = {}


def shutdown() -> None:
    """Drop the engine and the compiled modules while the interpreter is still whole (wasmtime-py's destructors
    fail noisily during interpreter teardown). Registered with atexit."""
    import gc

    _STATE.clear()
    gc.collect()


atexit.register(shutdown)


def require_wasmtime() -> Any:
    try:
        import wasmtime
    except ImportError as e:  # pragma: no cover - the message is the point
        raise ImportError(
            "pyodide-wasmtime runs on wasmtime-py, an optional dependency: pip install 'pyodide-wasmtime[wasmtime]'"
        ) from e
    return wasmtime


def cache_dir() -> Path:
    base = os.environ.get("PYODIDE_WASMTIME_CACHE")
    if base:
        return Path(base)
    xdg = os.environ.get("XDG_CACHE_HOME")
    return (Path(xdg) if xdg else Path.home() / ".cache") / "pyodide-wasmtime"


def private_dir(path: Path) -> None:
    """Make the cache folder (mode 0700 where the OS has modes): what is cached may hold a guest's memory."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError:
        pass


class LazyExports(Mapping):
    """The exports of an instance, by name, each wrapped when first asked for, in the module's export order.

    wasmtime-py's `Instance.exports` walks all of them with `wasmtime_instance_export_nth`, which costs ~3 s for the
    ~9300 exports of Pyodide (measured: cProfile, `Pyodide("fused").run("pass")`); the host needs a dozen at start.
    """

    def __init__(self, store: Any, instance: Any, module: Any) -> None:
        self._store, self._instance = store, instance
        self._names = [e.name for e in module.exports]
        self._known = frozenset(self._names)
        self._got: dict[str, Any] = {}

    def __getitem__(self, name: str) -> Any:
        if name in self._got:
            return self._got[name]
        if name not in self._known:
            raise KeyError(name)
        from wasmtime import _ffi as ffi
        from wasmtime._extern import wrap_extern

        raw = name.encode()
        item = ffi.wasmtime_extern_t()
        if not ffi.wasmtime_instance_export_get(
            self._store._context(), ctypes.byref(self._instance._instance), raw, len(raw), ctypes.byref(item)
        ):
            raise KeyError(name)
        self._got[name] = ext = wrap_extern(item)
        return ext

    def __iter__(self) -> Iterator[str]:
        return iter(self._names)

    def __len__(self) -> int:
        return len(self._names)


DEFAULT_WASM_STACK = 512 * 1024  # wasmtime's own
BIG_WASM_STACK = 1 << 20


def wasm_stack(platform: str, soft_limit: int | None, main_thread: bool) -> int:
    """The wasm stack to ask wasmtime for. wasm runs on the native thread stack, so more than the default only where
    that is known to be big: not on Windows (a 1 MiB main thread), not off the main thread (macOS gives 512 KiB), and
    only when the soft RLIMIT_STACK (None: unknown; negative: unlimited) is at least 4 times what is asked."""
    if platform == "win32" or not main_thread or soft_limit is None:
        return DEFAULT_WASM_STACK
    return BIG_WASM_STACK if soft_limit < 0 or soft_limit >= 4 * BIG_WASM_STACK else DEFAULT_WASM_STACK


def depth_cap(stack: int) -> int:
    """How many NEEDED libraries may nest below the first, for that wasm stack (measured on Linux, fused and dynamic:
    1 MiB loads 1500 and traps at about 2000; the default 512 KiB loads 1000 and traps at 1200)."""
    return 1500 if stack >= BIG_WASM_STACK else 800


def _wasm_stack() -> int:
    import threading

    try:
        import resource

        soft: int | None = resource.getrlimit(resource.RLIMIT_STACK)[0]
        if soft == resource.RLIM_INFINITY:
            soft = -1
    except (ImportError, ValueError, OSError):
        soft = None
    return wasm_stack(sys.platform, soft, threading.current_thread() is threading.main_thread())


def engine() -> Any:
    """One engine: exceptions (exnref), function references and GC are what Pyodide and the trampoline need."""
    if "engine" not in _STATE:
        wt = require_wasmtime()
        cfg = wt.Config()
        cfg.wasm_exceptions = True
        cfg.wasm_function_references = True
        cfg.wasm_gc = True
        _STATE["wasm_stack"] = cfg.max_wasm_stack = _wasm_stack()  # the loader's NEEDED recursion runs on it
        _STATE["engine"] = wt.Engine(cfg)
    return _STATE["engine"]


def _stamp(path: Path) -> bytes:
    try:
        wt_version = version("wasmtime")
    except PackageNotFoundError:  # pragma: no cover
        wt_version = "?"
    st = path.stat()
    return f"wasmtime-py {wt_version}:{st.st_size}:{st.st_mtime_ns}".encode()


def load_module(
    path: str | os.PathLike[str],
    *,
    cache: bool = True,
    wasm_opt: str | os.PathLike[str] | None = None,
    converted: list[Path] | None = None,
) -> Any:
    """Compile a module from a file, through the machine-code cache. With WASM_OPT, a file refused for its legacy
    exceptions is converted to exnref (and PATH appended to CONVERTED); the cache then holds the converted module,
    keyed by the source file's stamp, so the conversion runs once per file."""
    wt = require_wasmtime()
    path = Path(path).resolve()
    stamp = _stamp(path)
    key = (str(path), stamp)
    modules: dict = _STATE.setdefault("modules", {})
    if key in modules:
        return modules[key]
    eng = engine()
    module = None
    cached = (
        cache_dir() / (path.name + "." + hashlib.sha1(str(path).encode()).hexdigest()[:10] + ".cwasm")
        if cache
        else None
    )
    if cached is not None:
        try:
            with open(cached, "rb") as f:
                if f.readline().rstrip(b"\n") == stamp:
                    module = wt.Module.deserialize(eng, f.read())
        except (OSError, wt.WasmtimeError):
            module = None
    if module is None:
        try:
            module = wt.Module.from_file(eng, str(path))
        except wt.WasmtimeError as exc:
            if wasm_opt is None or "legacy_exceptions" not in str(exc):
                raise
            module = wt.Module(eng, translate_to_exnref(path.read_bytes(), wasm_opt))
            if converted is not None:
                converted.append(path)
        if cached is not None:
            try:
                private_dir(cached.parent)
                tmp = cached.with_suffix(f".tmp{os.getpid()}")
                with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
                    f.write(stamp + b"\n" + module.serialize())
                os.replace(tmp, cached)
            except OSError:
                pass
    modules[key] = module
    return module


def run_tool(tool: str | os.PathLike[str], args: list[str], cwd: str | os.PathLike[str] = ".") -> int:
    """Run a WASI command module (Binaryen's wasm-opt) with ARGS in directory CWD, preopened as "."; its stdout and
    stderr are the host's. Returns the exit code."""
    wt = require_wasmtime()
    tool = Path(tool)
    eng = engine()
    store = wt.Store(eng)
    wasi = wt.WasiConfig()
    wasi.argv = [tool.name.removesuffix(".wasm"), *args]
    wasi.preopen_dir(str(Path(cwd).resolve()), ".")
    wasi.inherit_stdout()
    wasi.inherit_stderr()
    store.set_wasi(wasi)
    linker = wt.Linker(eng)
    linker.define_wasi()
    inst = linker.instantiate(store, load_module(tool))
    try:
        inst.exports(store)["_start"](store)
    except wt.ExitTrap as e:
        return e.code
    return 0


def translate_to_exnref(data: bytes, wasm_opt: str | os.PathLike[str] | None) -> bytes:
    """Legacy wasm exceptions (Emscripten's -fwasm-exceptions, in Pyodide's wheels) -> exnref, which wasmtime runs.
    WASM_OPT is a `wasm-opt.wasm` (run in-process) or, from $WASM_OPT, a command line."""
    import subprocess
    import tempfile

    args = ["in.wasm", "--all-features", "--disable-compact-imports", "--translate-to-exnref", "-o", "out.wasm"]
    with tempfile.TemporaryDirectory() as td:
        Path(td, "in.wasm").write_bytes(data)
        tool = str(wasm_opt)
        if tool.endswith(".wasm"):
            code = run_tool(tool, args, td)
            if code:
                raise RuntimeError(f"wasm-opt.wasm exited with {code}")
        else:
            subprocess.run([*tool.split(), *args], check=True, cwd=td)
        return Path(td, "out.wasm").read_bytes()


if __name__ == "__main__":  # python -m pyodide_wasmtime._engine TOOL.wasm ARGS...: the tool, like on a shell
    sys.exit(run_tool(sys.argv[1], sys.argv[2:]))
