"""The wasmtime engine, compiled-module cache and Binaryen's `wasm-opt.wasm`, run in-process.

wasmtime-py is imported here and nowhere in the package's top level: a missing engine is reported when it is needed
(`require_wasmtime`), the way wasmhost does it. The cache holds machine code (`Module.serialize`) keyed by the
wasmtime version and the file's size and mtime, so a second start costs a deserialize, not a compile of 10 MB of wasm.
"""

from __future__ import annotations

import atexit
import hashlib
import os
import sys
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


def engine() -> Any:
    """One engine: exceptions (exnref), function references and GC are what Pyodide and the trampoline need."""
    if "engine" not in _STATE:
        wt = require_wasmtime()
        cfg = wt.Config()
        cfg.wasm_exceptions = True
        cfg.wasm_function_references = True
        cfg.wasm_gc = True
        _STATE["engine"] = wt.Engine(cfg)
    return _STATE["engine"]


def _stamp(path: Path) -> bytes:
    try:
        wt_version = version("wasmtime")
    except PackageNotFoundError:  # pragma: no cover
        wt_version = "?"
    st = path.stat()
    return f"wasmtime-py {wt_version}:{st.st_size}:{st.st_mtime_ns}".encode()


def load_module(path: str | os.PathLike[str], *, cache: bool = True) -> Any:
    """Compile a module from a file, through the machine-code cache."""
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
        module = wt.Module.from_file(eng, str(path))
        if cached is not None:
            try:
                cached.parent.mkdir(parents=True, exist_ok=True)
                tmp = cached.with_suffix(f".tmp{os.getpid()}")
                with open(tmp, "wb") as f:
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
