"""Fuse pyodide.asm.wasm with the adapter into one core module (Binaryen's wasm-merge).

    python fuse.py PYODIDE_WASM ADAPTER_WASM OUT_WASM        # WASM_MERGE="node .../wasm-merge" (default: on PATH)

The result imports only `wasi_snapshot_preview1.*`, `loader.*` (instantiate, got_set, sym, call), `fs.*` (statvfs) and `net.*`
(the host's sockets): the
shim's job (the `env` imports, the 280 `GOT.func` globals) is done by merging, so no table of forwarders and
no fixup at run time. Steps:
  1. adapter.wasm with its imports of the main module's memory, table, stack pointer and allocator renamed
     from `env` to `pyodide`, and `__memory_base`/`__table_base` to `base`;
  2. generated WAT: `tramp` (the trampoline and table_grow, over pyodide's table), `stubs` (every `env`
     import the adapter and the trampoline do not answer: zero or null), `got` (the GOT.func globals),
     `base` (the two bases, 0: the adapter has no data);
  3. wasm-merge adapter + tramp (as `aux`) + stubs -> the `env` module;
  4. wasm-merge pyodide + env + got (as `GOT.func`) + base, pyodide first, so its exports win.
"""

import os
import shutil
import subprocess
import sys
import tempfile

from wasmtime import FuncType, Module, wat2wasm

from pyodide_wasmtime import _engine  # noqa: E402
from pyodide_wasmtime import _wasm as R  # noqa: E402, N812  (the WAT generators and the import list)

VT = {0x7F: "i32", 0x7E: "i64", 0x7D: "f32", 0x7C: "f64", 0x7B: "v128", 0x70: "funcref", 0x6F: "externref"}


def valtype(b, i):
    """Skip a value type in a global import (rename_imports walks the import section byte by byte)."""
    c = b[i]
    if c in VT:
        return VT[c], i + 1
    if c in (0x63, 0x64):  # (ref null? ht)
        _, j = R.leb(b, i + 1)
        return "ref", j
    raise ValueError(f"value type 0x{c:02x}")


FLAGS = ["--all-features", "--disable-compact-imports"]


def leb(n):
    out = bytearray()
    while True:
        c = n & 0x7F
        n >>= 7
        out.append(c | (0x80 if n else 0))
        if not n:
            return bytes(out)


def rename_imports(b, renames):
    """Rewrite the module names of imports: renames maps (module, name) -> new module."""
    b = bytearray(b)
    i = 8
    while i < len(b):
        sid = b[i]
        size, j = R.leb(b, i + 1)
        if sid != 2:
            i = j + size
            continue
        end = j + size
        cnt, k = R.leb(b, j)
        out = bytearray(leb(cnt))
        for _ in range(cnt):
            ml, k = R.leb(b, k)
            m = bytes(b[k : k + ml])
            k += ml
            nl, k2 = R.leb(b, k)
            n = bytes(b[k2 : k2 + nl])
            rest_start = k
            k = k2 + nl
            kind = b[k]
            k += 1
            if kind == 0:
                _, k = R.leb(b, k)
            elif kind in (1, 2):
                if kind == 1:
                    k += 1
                fl, k = R.leb(b, k)
                _, k = R.leb(b, k)
                if fl & 1:
                    _, k = R.leb(b, k)
            elif kind == 3:
                _, k = valtype(b, k)
                k += 1
            elif kind == 4:
                k += 1
                _, k = R.leb(b, k)
            new_m = renames.get((m.decode(), n.decode()), m.decode()).encode()
            out += leb(len(new_m)) + new_m + bytes(b[rest_start:k])
        assert k == end
        b[i:end] = bytes([2]) + leb(len(out)) + out
        return bytes(b)
    return bytes(b)


def run_merge(args, cwd):
    cmd = os.environ.get("WASM_MERGE", "wasm-merge").split() + args + FLAGS
    subprocess.run(cmd, check=True, cwd=cwd)


def main(pyodide_wasm, adapter_wasm, out):
    main_bytes = open(pyodide_wasm, "rb").read()
    # the main module's WASI calls that the adapter takes first (socket descriptors) come from `env` in the merge
    main_renamed = rename_imports(main_bytes, {("wasi_snapshot_preview1", n): "env" for n in R.WASI_ROUTED})
    adapter = open(adapter_wasm, "rb").read()
    eng = _engine.engine()
    am = Module(eng, adapter)
    imports = R.func_imports(Module(eng, main_bytes))
    answered = {e.name for e in am.exports if isinstance(e.type, FuncType)} | {R.TRAMP}
    got = [i.name for i in Module(eng, main_bytes).imports if i.module == "GOT.func"]
    renames = {
        ("env", n): "pyodide"
        for n in (
            "memory",
            "__indirect_function_table",
            "__stack_pointer",
            "malloc",
            "calloc",
            "free",
            "emscripten_builtin_memalign",
            "_emscripten_find_dylib",
        )
    }
    renames.update({("env", "__memory_base"): "base", ("env", "__table_base"): "base"})
    with tempfile.TemporaryDirectory() as td:
        open(f"{td}/adapter.wasm", "wb").write(rename_imports(adapter, renames))
        open(f"{td}/tramp.wasm", "wb").write(
            wat2wasm(
                R.TRAMP_WAT.replace(
                    '(import "env" "__indirect_function_table"', '(import "pyodide" "__indirect_function_table"'
                )
            )
        )
        stub_lines = ["(module"]
        for m, n, ps, rs in imports:
            if m == "env" and n not in answered:
                sig = " ".join(f"(param {p})" for p in ps) + " " + " ".join(f"(result {r})" for r in rs)
                stub_lines.append(f'  (func (export "{n}") {sig} {R.stub_results(n, rs)})')
        open(f"{td}/stubs.wasm", "wb").write(wat2wasm("\n".join(stub_lines + [")"])))
        open(f"{td}/got.wasm", "wb").write(
            wat2wasm("(module\n" + "\n".join(f'  (global (export "{g}") (mut i32) (i32.const 0))' for g in got) + ")")
        )
        open(f"{td}/base.wasm", "wb").write(
            wat2wasm(
                '(module (global (export "__memory_base") i32 (i32.const 0)) (global (export "__table_base") i32 (i32.const 0)))'
            )
        )
        run_merge(["adapter.wasm", "adapter", "tramp.wasm", "aux", "stubs.wasm", "stubs", "-o", "env.wasm"], td)
        open(f"{td}/main.wasm", "wb").write(main_renamed)
        run_merge(
            [
                "main.wasm",
                "pyodide",
                "env.wasm",
                "env",
                "got.wasm",
                "GOT.func",
                "base.wasm",
                "base",
                "--skip-export-conflicts",
                "-o",
                "fused.wasm",
            ],
            td,
        )
        shutil.move(f"{td}/fused.wasm", out)
    m = Module(eng, open(out, "rb").read())
    mods = {}
    for i in m.imports:
        mods.setdefault(i.module, []).append(i.name)
    print(f"{out}: {os.path.getsize(out)} bytes; imports: " + ", ".join(f"{k} ({len(v)})" for k, v in mods.items()))


if __name__ == "__main__":
    main(*sys.argv[1:4])
