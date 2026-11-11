"""Reading a WebAssembly binary's imports, and the WAT the dynamic build is linked from (WAT text; the engine is only needed by `func_imports`).

`func_imports` gives the function types of a module's imports (from wasmtime's `Module.imports`). `shim_wat` is the module that answers every `env` import of `pyodide.asm.wasm` for the
dynamic build (what the adapter answers calls through a table; the rest are zero/null stubs, the JavaScript bridge),
`TRAMP_WAT` is `_PyEM_TrampolineCall_JS` (what JavaScript's `wasmTable.get(f)(a, b, c)` does: the ten types it knows are
called in wasm, any other through the host's `loader.call_any`).
"""

from __future__ import annotations

LOADER: set = set()  # the loader is in the adapter now
WASI_ROUTED = (
    "fd_read",
    "fd_write",
    "fd_close",
    "fd_fdstat_get",
    "fd_seek",
    "fd_pread",
    "fd_pwrite",
    "fd_sync",
    "clock_time_get",
    "clock_res_get",
)  # the adapter's first: sockets, pipes, duplicated descriptors, directories
TRAMP = "_PyEM_TrampolineCall_JS"


def _ty(t) -> str:
    """wasmtime-py prints every reference type as `anyref`; in this Pyodide build they are all `externref` (checked
    by the instantiation: a wrong type does not link)."""
    s = str(t)
    return "externref" if s == "anyref" else s


def func_imports(module):
    """[(module, name, params, results)] of a compiled module's function imports, from wasmtime's `Module.imports`."""
    from wasmtime import FuncType

    return [
        (i.module, i.name, [_ty(t) for t in i.type.params], [_ty(t) for t in i.type.results])
        for i in module.imports
        if isinstance(i.type, FuncType)
    ]


def leb(b, i):
    """An unsigned LEB128 at b[i]: (value, next index)."""
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if not c & 0x80:
            return r, i


def _section(b, wanted):
    """(start, end) of the first section with id `wanted` in the binary b, or None."""
    i = 8
    while i < len(b):
        size, j = leb(b, i + 1)
        if b[i] == wanted:
            return j, j + size
        i = j + size
    return None


def import_names(b):
    """[(module, name, kind)] of a binary's imports (kind 0 function, 1 table, 2 memory, 3 global, 4 tag), read from
    the bytes: no compile. For the main module only (its global imports are plain, no reference types)."""
    sec = _section(b, 2)
    if not sec:
        return []
    n, i = leb(b, sec[0])
    out = []
    for _ in range(n):
        ml, i = leb(b, i)
        m = bytes(b[i : i + ml]).decode()
        i += ml
        fl, i = leb(b, i)
        f = bytes(b[i : i + fl]).decode()
        i += fl
        kind = b[i]
        i += 1
        if kind == 0:
            _, i = leb(b, i)
        elif kind in (1, 2):
            i += kind == 1  # a table's element type
            flags, i = leb(b, i)
            _, i = leb(b, i)
            if flags & 1:
                _, i = leb(b, i)
        elif kind == 3:
            i += 2
        else:
            i += 1
            _, i = leb(b, i)
        out.append((m, f, kind))
    return out


def export_names(b):
    """The names of a binary's exports, read from the bytes."""
    sec = _section(b, 7)
    if not sec:
        return []
    n, i = leb(b, sec[0])
    out = []
    for _ in range(n):
        nl, i = leb(b, i)
        out.append(bytes(b[i : i + nl]).decode())
        i += nl + 1
        _, i = leb(b, i)
    return out


def with_memory_export(b):
    """The binary with its imported memory 0 also exported as `memory` (wasmtime's WASI reads the memory of the
    instance that calls it from that export); b is returned as it is when there is no export section to add to."""
    sec = _section(b, 7)
    if not sec:
        return b
    n, i = leb(b, sec[0])
    body = bytes(_uleb(n + 1)) + bytes(b[i : sec[1]]) + bytes([6]) + b"memory" + b"\x02\x00"
    return (
        bytes(b[: sec[0] - len(_uleb(sec[1] - sec[0])) - 1]) + bytes([7]) + _uleb(len(body)) + body + bytes(b[sec[1] :])
    )


def _uleb(n):
    out = bytearray()
    while True:
        c = n & 0x7F
        n >>= 7
        out.append(c | (0x80 if n else 0))
        if not n:
            return bytes(out)


def zero(t):
    return {"i32": "(i32.const 0)", "i64": "(i64.const 0)", "f32": "(f32.const 0)", "f64": "(f64.const 0)"}.get(
        t, "(ref.null extern)" if "extern" in t else "(ref.null func)"
    )


def stub_results(name, rs):
    """What an unanswered import returns: zero/null for the JavaScript bridge and the like, but ENOSYS (-52) for a
    system call: 0 would mean "it worked", and the callers (symlink, pipe, dup...) would go on with nothing made."""
    if name.startswith("__syscall_") and list(rs) == ["i32"]:
        return "(i32.const -52)"
    return " ".join(zero(r) for r in rs)


def shim_wat(imports, forwarded, got_names):
    lines, types = ["(module"], {}
    for _m, _n, ps, rs in imports:
        key = (tuple(ps), tuple(rs))
        if key not in types:
            types[key] = f"$t{len(types)}"
            lines.append(
                f"  (type {types[key]} (func (param {' '.join(ps)}) (result {' '.join(rs)})))".replace(
                    "(param )", ""
                ).replace("(result )", "")
            )
    lines.append(f'  (table (export "table") {max(1, len(forwarded))} funcref)')
    for m, n, ps, rs in imports:
        if m == "wasi_snapshot_preview1" and n in WASI_ROUTED and n in forwarded:
            args = " ".join(f"(local.get {k})" for k in range(len(ps)))
            sig = " ".join(f"(param {p})" for p in ps) + " " + " ".join(f"(result {r})" for r in rs)
            lines.append(
                f'  (func (export "wasi:{n}") {sig} (call_indirect (type {types[(tuple(ps), tuple(rs))]}) {args} (i32.const {forwarded[n]})))'
            )
            continue
        if m != "env" or n in LOADER:
            continue
        sig = " ".join(f"(param {p})" for p in ps) + " " + " ".join(f"(result {r})" for r in rs)
        if n in forwarded:
            args = " ".join(f"(local.get {k})" for k in range(len(ps)))
            body = f"(call_indirect (type {types[(tuple(ps), tuple(rs))]}) {args} (i32.const {forwarded[n]}))"
        else:
            body = stub_results(n, rs)
        lines.append(f'  (func (export "{n}") {sig} {body})')
    for g in got_names:
        lines.append(f'  (global (export "got:{g}") (mut i32) (i32.const 0))')
    lines.append(")")
    return "\n".join(lines)


TRAMP_WAT = """(module
  (type $r0 (func (result i32)))
  (type $r1 (func (param i32) (result i32)))
  (type $r2 (func (param i32 i32) (result i32)))
  (type $r3 (func (param i32 i32 i32) (result i32)))
  (type $r4 (func (param i32 i32 i32 i32) (result i32)))
  (type $v0 (func))
  (type $v1 (func (param i32)))
  (type $v2 (func (param i32 i32)))
  (type $v3 (func (param i32 i32 i32)))
  (type $v4 (func (param i32 i32 i32 i32)))
  (import "env" "__indirect_function_table" (table $t 0 funcref))
  ;; a table entry of any other type: the host calls it with its real type, as JavaScript does (loader.call_any)
  (import "loader" "call_any" (func $any (param i32 i32 i32 i32) (result i32)))
  ;; wasmTable.get(f)(a, b, c) of JavaScript: extra arguments dropped, missing ones 0
  (func (export "_PyEM_TrampolineCall_JS") (param $f i32) (param $a i32) (param $b i32) (param $c i32) (result i32)
    (local $r funcref)
    (local.set $r (table.get $t (local.get $f)))
    (if (ref.test (ref $r3) (local.get $r)) (then (return (call_ref $r3 (local.get $a) (local.get $b) (local.get $c) (ref.cast (ref $r3) (local.get $r))))))
    (if (ref.test (ref $r2) (local.get $r)) (then (return (call_ref $r2 (local.get $a) (local.get $b) (ref.cast (ref $r2) (local.get $r))))))
    (if (ref.test (ref $r1) (local.get $r)) (then (return (call_ref $r1 (local.get $a) (ref.cast (ref $r1) (local.get $r))))))
    (if (ref.test (ref $r4) (local.get $r)) (then (return (call_ref $r4 (local.get $a) (local.get $b) (local.get $c) (i32.const 0) (ref.cast (ref $r4) (local.get $r))))))
    (if (ref.test (ref $r0) (local.get $r)) (then (return (call_ref $r0 (ref.cast (ref $r0) (local.get $r))))))
    (if (ref.test (ref $v3) (local.get $r)) (then (call_ref $v3 (local.get $a) (local.get $b) (local.get $c) (ref.cast (ref $v3) (local.get $r))) (return (i32.const 0))))
    (if (ref.test (ref $v2) (local.get $r)) (then (call_ref $v2 (local.get $a) (local.get $b) (ref.cast (ref $v2) (local.get $r))) (return (i32.const 0))))
    (if (ref.test (ref $v1) (local.get $r)) (then (call_ref $v1 (local.get $a) (ref.cast (ref $v1) (local.get $r))) (return (i32.const 0))))
    (if (ref.test (ref $v4) (local.get $r)) (then (call_ref $v4 (local.get $a) (local.get $b) (local.get $c) (i32.const 0) (ref.cast (ref $v4) (local.get $r))) (return (i32.const 0))))
    (if (ref.test (ref $v0) (local.get $r)) (then (call_ref $v0 (ref.cast (ref $v0) (local.get $r))) (return (i32.const 0))))
    (call $any (local.get $f) (local.get $a) (local.get $b) (local.get $c)))
  (func (export "table_grow") (param i32) (result i32) (table.grow $t (ref.null func) (local.get 0))))
"""


def check_sections(b: bytes) -> None:
    """The adapter has no memory, data or data-count section (Wasmtime's adapter rules)."""
    i = 8
    while i < len(b):
        sid = b[i]
        size, i = leb(b, i + 1)
        assert sid not in (5, 11, 12), f"adapter has section {sid} (memory/data)"
        i += size
