"""Small Emscripten-style side modules (dylink.0, GOT imports, a table slot) built from WAT, for the loader's tests.

A side module imports the main module's memory, table and bases, takes its function pointers from `__table_base`,
and says what it needs in a `dylink.0` custom section placed first. `lib()` makes the few shapes the tests use.
"""

from __future__ import annotations

from wasmtime import wat2wasm


def uleb(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def name(s: str) -> bytes:
    raw = s.encode()
    return uleb(len(raw)) + raw


def with_dylink(
    wasm: bytes,
    *,
    memsize: int = 0,
    memalign: int = 0,
    tsize: int = 0,
    needed: tuple[str, ...] = (),
    rpaths: tuple[str, ...] = (),
) -> bytes:
    """`wasm` with a dylink.0 custom section first: memory size/alignment, table size, NEEDED libraries and
    the runtime paths they are searched in."""
    mem = uleb(memsize) + uleb(memalign) + uleb(tsize) + uleb(0)
    sub = bytes([1]) + uleb(len(mem)) + mem
    if needed:
        nd = uleb(len(needed)) + b"".join(name(n) for n in needed)
        sub += bytes([2]) + uleb(len(nd)) + nd
    if rpaths:
        rp = uleb(len(rpaths)) + b"".join(name(n) for n in rpaths)
        sub += bytes([5]) + uleb(len(rp)) + rp
    payload = name("dylink.0") + sub
    return wasm[:8] + bytes([0]) + uleb(len(payload)) + payload + wasm[8:]


def lib(*args: object, needed: tuple[str, ...] = (), rpaths: tuple[str, ...] = (), **kw: object) -> bytes:
    wasm, dy = lib_parts(*args, **kw)  # type: ignore[arg-type]
    return with_dylink(wasm, needed=needed, rpaths=rpaths, **dy)


def lib_parts(
    value: int = 1,
    *,
    fn: str = "val",
    env_calls: tuple[str, ...] = (),
    got_funcs: tuple[str, ...] = (),
    got_mems: tuple[str, ...] = (),
    data: tuple[str, ...] = (),
    callbacks: bool = False,
    wasi: bool = False,
    garbage: int = 0,
) -> tuple[bytes, dict[str, int]]:
    """A side module: exports `fn()` -> value (one table slot, `fptr()` gives its number, the pointer C would take),
    `call_<f>()` for each `env_calls` (an `env` function import f() -> i32), `got_<g>()` for each GOT.func /
    GOT.mem import (the number the loader put in its GOT global), a data symbol for each name in `data` (an exported
    global, an offset into the module's memory), and with `callbacks` `on_ok(ud, handle)`, `on_err(ud)` and
    `peek(i)` for the tests of emscripten_dlopen. `garbage` bytes of memory beyond what is used."""
    w = [
        "(module",
        '  (import "env" "memory" (memory 1))',
        '  (import "env" "__indirect_function_table" (table 0 funcref))',
        '  (import "env" "__memory_base" (global $mb i32))',
        '  (import "env" "__table_base" (global $tb i32))',
    ]
    if wasi:
        w.append('  (import "wasi_snapshot_preview1" "fd_write" (func $fd_write (param i32 i32 i32 i32) (result i32)))')
        w.append('  (import "wasi_snapshot_preview1" "random_get" (func $random_get (param i32 i32) (result i32)))')
    for f in env_calls:
        w.append(f'  (import "env" "{f}" (func $e_{f} (result i32)))')
    for g in got_funcs:
        w.append(f'  (import "GOT.func" "{g}" (global $gf_{g} (mut i32)))')
    for g in got_mems:
        w.append(f'  (import "GOT.mem" "{g}" (global $gm_{g} (mut i32)))')
    for f in env_calls:
        w.append(f'  (func (export "call_{f}") (result i32) (call $e_{f}))')
    for g in got_funcs:
        w.append(f'  (func (export "got_{g}") (result i32) (global.get $gf_{g}))')
    for g in got_mems:
        w.append(f'  (func (export "got_{g}") (result i32) (global.get $gm_{g}))')
    w.append(f'  (func $v (export "{fn}") (result i32) (i32.const {value}))')
    w.append('  (func (export "fptr") (result i32) (global.get $tb))')
    w.append("  (elem (global.get $tb) func $v)")
    for d in data:
        w.append(f'  (global (export "{d}") i32 (i32.const 0))')
    if wasi:  # fd_write of an empty buffer to stdout, and random_get of 8 bytes: 0 is success
        w.append('  (func (export "rnd") (result i32) (call $random_get (global.get $mb) (i32.const 8)))')
        w.append(
            '  (func (export "wr") (result i32) (i32.store (global.get $mb) (i32.add (global.get $mb) (i32.const 16)))'
            " (i32.store offset=4 (global.get $mb) (i32.const 0))"
            " (call $fd_write (i32.const 1) (global.get $mb) (i32.const 1) (i32.add (global.get $mb) (i32.const 8))))"
        )
    if callbacks:
        w.append(
            '  (func (export "on_ok") (param i32 i32) (i32.store (global.get $mb) (local.get 0))'
            " (i32.store offset=4 (global.get $mb) (local.get 1))"
            " (i32.store offset=8 (global.get $mb) (i32.add (i32.load offset=8 (global.get $mb)) (i32.const 1))))"
        )
        w.append(
            '  (func (export "on_err") (param i32) (i32.store offset=16 (global.get $mb) (local.get 0))'
            " (i32.store offset=24 (global.get $mb) (i32.add (i32.load offset=24 (global.get $mb)) (i32.const 1))))"
        )
        w.append(
            '  (func (export "peek") (param i32) (result i32)'
            " (i32.load (i32.add (global.get $mb) (i32.shl (local.get 0) (i32.const 2)))))"
        )
    w.append(")")
    memsize = 64 + garbage if callbacks else (16 if data or got_mems or wasi else 0) + garbage
    return bytes(wat2wasm("\n".join(w))), {"memsize": memsize, "memalign": 4 if memsize else 0, "tsize": 1}


def guest_chain(directory: str, count: int, wasm: bytes, dy: dict[str, int]) -> str:
    """Guest source that writes `count` copies of `wasm` as <directory>/l<i>.so, each NEEDing the next one (the guest
    builds them: 600 modules would not fit on a command line)."""
    import inspect

    src = "".join(inspect.getsource(f) + "\n" for f in (uleb, name, with_dylink))
    return (
        f"import os\n{src}\nos.makedirs({directory!r}, exist_ok=True)\nW = bytes.fromhex({wasm.hex()!r})\n"
        f"for i in range({count}):\n"
        f"    open({directory!r} + '/l%d.so' % i, 'wb').write(with_dylink(W, needed=('l%d.so' % (i + 1),), **{dy!r}))\n"
    )


def guest_files(files: dict[str, bytes]) -> str:
    """Python source for the guest that writes `files` (path -> bytes) before the test code runs."""
    return "import os\n" + "".join(
        f"os.makedirs(os.path.dirname({p!r}), exist_ok=True)\nopen({p!r}, 'wb').write(bytes.fromhex({b.hex()!r}))\n"
        for p, b in files.items()
    )
