"""Offline: the shape of the built wasm (Wasmtime's adapter rules) and of the package's data."""

from __future__ import annotations

import pytest
from wasmtime import FuncType, Module

from pyodide_wasmtime import _engine, _wasm, available_flavors, data_dir

ALLOWED_ENV = {
    "memory",
    "__indirect_function_table",
    "__stack_pointer",
    "__memory_base",
    "__table_base",
    "malloc",
    "calloc",
    "free",
}


def need(name: str):
    path = data_dir() / name
    if not path.exists():
        pytest.skip(f"{path} is not built (tools/build_data.sh)")
    return path


def test_adapter_has_no_data_and_no_stack():
    b = need("adapter.wasm").read_bytes()
    _wasm.check_sections(b)  # no memory, data or data-count section
    m = Module(_engine.engine(), b)
    for i in m.imports:
        ok = i.module in ("wasi_snapshot_preview1", "loader", "aux", "net")
        assert ok or (i.module == "env" and i.name in ALLOWED_ENV), (i.module, i.name)


def test_fused_imports_only_wasi_loader_net():
    m = Module(_engine.engine(), need("pyodide_fused.wasm").read_bytes())
    assert sorted({i.module for i in m.imports}) == ["loader", "net", "wasi_snapshot_preview1"]
    counts = {mod: sum(i.module == mod for i in m.imports) for mod in ("wasi_snapshot_preview1", "loader", "net")}
    # 36 WASI imports (the main module's own and the adapter's: files, links, dup, fcntl, exit), the loader's 4
    # operations and the 10 of the host's sockets
    assert counts == {"wasi_snapshot_preview1": 36, "loader": 4, "net": 10}


def test_the_package_carries_what_the_run_time_needs():
    d = data_dir()
    for name in ("pyodide.asm.wasm", "python_stdlib.zip", "adapter.wasm", "pyodide_fused.wasm", "wasm-opt.wasm"):
        if not (d / name).exists():
            pytest.skip(f"{d / name} is not built (tools/build_data.sh)")
    assert available_flavors(d) == ["fused", "dynamic"]


def test_func_imports_come_from_the_module():
    m = Module(_engine.engine(), need("pyodide.asm.wasm").read_bytes())
    imports = _wasm.func_imports(m)
    assert len(imports) == sum(isinstance(i.type, FuncType) for i in m.imports)
    assert {t for _, _, ps, rs in imports for t in ps + rs} <= {"i32", "i64", "f32", "f64", "externref"}
