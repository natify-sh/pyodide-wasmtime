"""The side modules of the loader probes, built on the host with tests/sidemod.py: build() -> {relative path: bytes}."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from sidemod import lib, uleb, with_dylink  # noqa: E402  # pyright: ignore[reportMissingImports]
from wasmtime import wat2wasm  # noqa: E402

HEAD = """(module
  (import "env" "memory" (memory 1))
  (import "env" "__indirect_function_table" (table 0 funcref))
  (import "env" "__memory_base" (global $mb i32))
  (import "env" "__table_base" (global $tb i32))
"""


def raw(extra_imports: str, body: str, **dy: object) -> bytes:
    return with_dylink(bytes(wat2wasm(HEAD + extra_imports + body + ")")), **dy)  # type: ignore[arg-type]


def build() -> dict[str, bytes]:
    s: dict[str, bytes] = {}
    s["ok.so"] = lib(7, data=("dat",))
    s["ok2.so"] = lib(8, fn="val2")
    s["nodata.so"] = lib(9)
    # exported globals of the four types, mutable and not (one module each: the glue adds the memory base to
    # every exported global, which a BigInt (i64) refuses, and a failed load leaves state behind)
    for ty, init in (("i32", "5"), ("i64", "6"), ("f32", "1.5"), ("f64", "2.5")):
        s[f"glob_{ty}.so"] = raw(
            "",
            f"""
  (global (export "g") {ty} ({ty}.const {init}))
  (global (export "m") (mut {ty}) ({ty}.const {init}))
  (func (export "val") (result i32) (i32.const 1))
""",
            memsize=16,
            memalign=4,
            tsize=1,
        )
    s["funcs.so"] = raw(
        "",
        """
  (func (export "f_i64") (param i64) (result i64) (local.get 0))
  (func (export "f_f64") (param f64) (result f64) (f64.mul (local.get 0) (f64.const 2)))
  (func (export "f_add") (param i32 i32) (result i32) (i32.add (local.get 0) (local.get 1)))
  (func (export "f_void"))
  (func (export "f_trap") (result i32) unreachable)
  (func (export "f_div") (param i32) (result i32) (i32.div_s (i32.const 1) (local.get 0)))
  (func (export "f_mem") (param i32) (result i32) (i32.load (local.get 0)))
  (memory (export "mem") 1)
  (table (export "tab") 2 funcref)
""",
        memsize=16,
        memalign=4,
        tsize=1,
    )
    # dylink.0 variations
    base = lib(1)
    plain = bytes(wat2wasm('(module (func (export "val") (result i32) (i32.const 3)))'))
    s["nodylink.so"] = plain
    s["empty.so"] = b""
    s["junk.so"] = b"this is not wasm at all\n" * 10
    s["magic.so"] = b"\0asm"
    s["badver.so"] = b"\0asm\2\0\0\0" + base[8:]
    s["trunc10.so"] = base[:10]
    s["trunc_half.so"] = base[: len(base) // 2]
    s["trunc_minus1.so"] = base[:-1]
    s["trailing.so"] = base + b"\0\0\0"
    simple = bytes(
        wat2wasm(
            HEAD
            + '(func $v (export "val") (result i32) (i32.const 4)) (func (export "fptr") (result i32) (global.get $tb))'
            + " (elem (global.get $tb) func $v))"
        )
    )
    for nm, kw in {
        "mem0": dict(memsize=0, memalign=0, tsize=1),
        "mem_1k": dict(memsize=1024, memalign=4, tsize=1),
        "mem_huge": dict(memsize=2**31, memalign=4, tsize=1),
        "mem_max32": dict(memsize=2**32 - 1, memalign=4, tsize=1),
        "mem_gb": dict(memsize=1 << 30, memalign=4, tsize=1),
        "tab0": dict(memsize=0, memalign=0, tsize=0),
        "tab_big": dict(memsize=0, memalign=0, tsize=100000),
        "tab_huge": dict(memsize=0, memalign=0, tsize=2**31),
        "align_big": dict(memsize=16, memalign=20, tsize=1),
        "align_huge": dict(memsize=16, memalign=40, tsize=1),
        "align_0": dict(memsize=16, memalign=0, tsize=1),
        "align_3": dict(memsize=17, memalign=3, tsize=1),
    }.items():
        s[nm + ".so"] = with_dylink(simple, **kw)  # type: ignore[arg-type]
    # NEEDED
    s["need_ok.so"] = lib(10, fn="vneed", needed=("ok.so",), rpaths=("$ORIGIN",))
    s["need_abs.so"] = lib(11, fn="vabs", needed=("/nonexistent/abs.so",))
    s["need_missing.so"] = lib(12, fn="vmiss", needed=("missing.so",), rpaths=("$ORIGIN",))
    s["need_norpath.so"] = lib(13, fn="vnorp", needed=("ok2.so",))
    s["need_rpathdir.so"] = lib(14, fn="vrp", needed=("ok2.so",), rpaths=("/tmp/dp_rpath_dir",))
    s["rp/need_sub.so"] = lib(15, fn="vsub", needed=("inner.so",), rpaths=("$ORIGIN/lib",))
    s["rp/lib/inner.so"] = lib(16, fn="vinner")
    s["need_dollar.so"] = lib(17, fn="vdollar", needed=("$ORIGIN/ok2.so",))
    s["need_rel.so"] = lib(18, fn="vrel", needed=("so/ok2.so",), rpaths=("$ORIGIN/..",))
    s["cyc_a.so"] = lib(19, fn="va", needed=("cyc_b.so",), rpaths=("$ORIGIN",))
    s["cyc_b.so"] = lib(20, fn="vb", needed=("cyc_a.so",), rpaths=("$ORIGIN",))
    s["self.so"] = lib(21, fn="vself", needed=("self.so",), rpaths=("$ORIGIN",))
    # NEEDED chains: ch<N>/l0.so .. l<N-1>.so, each needing the next
    for n in (2, 3, 5, 10, 25, 50):
        for i in range(n):
            nd = (f"l{i + 1}.so",) if i < n - 1 else ()
            s[f"ch{n}/l{i}.so"] = lib(i, fn=f"v{i}", needed=nd, rpaths=("$ORIGIN",))
    # GOT.func / GOT.mem / env imports
    s["got_main.so"] = lib(30, got_funcs=("strlen", "getpid"), got_mems=("_Py_NoneStruct",))
    s["got_undef_func.so"] = lib(31, got_funcs=("no_such_function_xyz",))
    s["got_undef_mem.so"] = lib(32, got_mems=("no_such_data_xyz",))
    s["got_dyn.so"] = lib(33, got_funcs=("val",), got_mems=("dat",), needed=("ok.so",), rpaths=("$ORIGIN",))
    s["got_bridge.so"] = lib(34, got_funcs=("JsArray_count_js",))
    s["env_unknown.so"] = lib(35, env_calls=("no_such_env_fn_xyz",))
    s["env_getpid.so"] = lib(36, env_calls=("getpid",))
    s["env_bridge.so"] = lib(37, env_calls=("JsArray_count_js",))
    s["env_emlog.so"] = lib(38, env_calls=("emscripten_get_now",))
    # an env import of a main-module function with the wrong signature: strlen is (i32) -> i32
    s["sig_bad.so"] = raw(
        '(import "env" "strlen" (func $f (result i32)))', '(func (export "val") (result i32) (call $f))'
    )
    s["sig_bad2.so"] = raw(
        '(import "env" "strlen" (func $f (param i64) (result i64)))', '(func (export "val") (result i32) (i32.const 0))'
    )
    s["sig_ok.so"] = raw(
        '(import "env" "strlen" (func $f (param i32) (result i32)))',
        '(func (export "val") (param i32) (result i32) (call $f (local.get 0)))',
    )
    s["sig_unk_bad.so"] = raw(
        '(import "env" "unknown_xyz" (func $f (param i64) (result f64)))',
        '(func (export "val") (result i32) (i32.const 1))',
    )
    s["imp_global.so"] = raw(
        '(import "env" "no_such_global_xyz" (global i32))', '(func (export "val") (result i32) (i32.const 1))'
    )
    s["imp_mem_gen.so"] = raw(
        '(import "env" "no_such_table_xyz" (table 0 funcref))', '(func (export "val") (result i32) (i32.const 1))'
    )
    s["imp_module.so"] = raw('(import "nosuchmod" "f" (func))', '(func (export "val") (result i32) (i32.const 1))')
    s["imp_wasi.so"] = lib(39, wasi=True)
    s["start_trap.so"] = raw("", "(func $s unreachable) (start $s)", memsize=0, memalign=0, tsize=0)
    s["ctor.so"] = raw(
        '(import "env" "getpid" (func $g (result i32)))',
        '(func (export "__wasm_call_ctors") (call $g) drop) (func (export "val") (result i32) (i32.const 1))',
    )
    s["ctor_trap.so"] = raw(
        "", '(func (export "__wasm_call_ctors") unreachable) (func (export "val") (result i32) (i32.const 1))'
    )
    s["post_inst.so"] = raw(
        "", '(func (export "__wasm_apply_data_relocs")) (func (export "val") (result i32) (i32.const 2))'
    )
    # a dylink.0 with an unknown subsection, and an old-style "dylink" section
    payload = uleb(len("dylink.0")) + b"dylink.0" + bytes([1, 4, 0, 0, 1, 0, 99, 2, 1, 2])
    s["dy_unknown_sub.so"] = simple[:8] + b"\0" + uleb(len(payload)) + payload + simple[8:]
    payload = uleb(len("dylink")) + b"dylink" + bytes([16, 4, 1, 0])
    s["dy_old.so"] = simple[:8] + b"\0" + uleb(len(payload)) + payload + simple[8:]
    return s
