"""dlopen, dlsym, dlerror, emscripten_dlopen and emscripten_log, on both builds: what Emscripten's glue does.

The side modules are small ones built from WAT (`sidemod.py`); their expected numbers come from reading the glue
(`loadDynamicLibrary`, `loadWebAssemblyModule`, `updateGOT`, `__dlsym_js`) and were compared with the same scripts
on Pyodide 315.0.0a2 on Node.
"""

from __future__ import annotations

import subprocess
import sys

import conftest
import pytest
import sidemod
from conftest import Guest

PRE = "import ctypes, os\nP = lambda f: ctypes.cast(f, ctypes.c_void_p).value\n"


def run(guest: Guest, files: dict[str, bytes], code: str, site: str | None = None, timeout: int = 600):
    p = guest.run(PRE + sidemod.guest_files(files) + code, site, timeout=timeout)
    return p


def ok(guest: Guest, files: dict[str, bytes], code: str, site: str | None = None) -> list[str]:
    p = run(guest, files, code, site)
    assert p.returncode == 0, p.stderr[-3000:]
    return p.stdout.splitlines()


def test_dlerror_is_the_glues_text(guest: Guest):
    text = b'(module (func (export "f")))\n' + b"\n" * 8  # WAT text, 37 bytes: wasmtime would take it
    head = bytes.fromhex("0061736d01000000")
    nodylink = head + bytes([1, 4, 1, 0x60, 0, 0]) + bytes([0, 12, 1, 0x78]) + bytes(10)  # 28 bytes
    files = {
        "/t/empty.so": b"",
        "/t/junk.so": b"junk-not-wasm",
        "/t/wat.so": text,
        "/t/nodylink.so": nodylink,
        "/t/notdylink.so": head + bytes([0, 17, 8]) + b"dylink.1" + bytes(8),
        "/t/short.so": head + bytes([0, 200, 8]) + b"dylink.0" + bytes(10),
        "/t/needs.so": sidemod.lib(1, needed=("nothere.so",)),
    }
    out = ok(
        guest,
        files,
        r"""
for p in ["/nonexistent.so", "nonexistent.so", "/t/empty.so", "/t/junk.so", "/t/wat.so", "/t/nodylink.so",
          "/t/notdylink.so", "/t/short.so", "/t/needs.so", "/t//../t/./needs.so", "/t"]:
    try:
        ctypes.CDLL(p)
        print("loaded", p)
    except OSError as e:
        print(str(e).replace("\n", "|"))
""",
    )
    assert out == [
        'could not load dynamic lib: /nonexistent.so|Error: Failed to find dynamic library "/nonexistent.so"',
        'could not load dynamic lib: nonexistent.so|Error: Failed to find dynamic library "nonexistent.so"',
        "could not load dynamic lib: /t/empty.so|Error: need to see wasm magic number",
        "could not load dynamic lib: /t/junk.so|RangeError: byte length of Uint32Array should be a multiple of 4",
        "could not load dynamic lib: /t/wat.so|Error: need to see wasm magic number",
        "could not load dynamic lib: /t/nodylink.so|Error: need the dylink section to be first",
        "could not load dynamic lib: /t/notdylink.so|Error",
        "could not load dynamic lib: /t/short.so|CompileError: WebAssembly.Module(): module is truncated or malformed",
        'could not load dynamic lib: /t/needs.so|Error: Failed to find dynamic library "nothere.so"',
        'could not load dynamic lib: /t/needs.so|Error: Failed to find dynamic library "nothere.so"',
        "could not load dynamic lib: /t|[object Object]",
    ]


def test_a_failed_load_prints_nothing_on_stderr(flavor: str):
    from conftest import missing

    from pyodide_wasmtime import available_flavors, data_dir

    if flavor not in available_flavors(data_dir()):
        missing(f"the {flavor} build is not in {data_dir()}")
    code = "import ctypes\ntry:\n    ctypes.CDLL('/nonexistent.so')\nexcept OSError as e:\n    print('failed')\n"
    p = subprocess.run(
        [sys.executable, "-m", "pyodide_wasmtime", "--flavor", flavor, "-c", code], capture_output=True, text=True
    )
    assert p.returncode == 0 and p.stdout.strip() == "failed", p.stderr
    assert "instantiate failed" not in p.stderr and "[loader]" not in p.stderr


def test_engine_errors_are_the_dlerror(guest: Guest):
    # a valid module whose import nobody answers: a link error, with the engine's reason
    wat = '(module (import "env" "memory" (memory 1)) (import "nowhere" "x" (func)))'
    from wasmtime import wat2wasm

    files = {"/t/link.so": sidemod.with_dylink(bytes(wat2wasm(wat)))}
    out = ok(
        guest,
        files,
        """
try:
    ctypes.CDLL("/t/link.so")
except OSError as e:
    print(str(e).replace("\\n", "|"))
""",
    )
    assert out[0].startswith("could not load dynamic lib: /t/link.so|LinkError: WebAssembly.Instance(): ")


def test_dlsym_and_function_pointers(guest: Guest):
    files = {"/m/a.so": sidemod.lib(1, data=("counter",)), "/m/f.so": sidemod.lib(6, fn="f", got_mems=("counter",))}
    out = ok(
        guest,
        files,
        r"""
A = ctypes.CDLL("/m/a.so")
print("a.val", A.val())
print("same slot as the pointer C takes", P(A.val) == A.fptr())      # getFunctionAddress: the slot it already has
print("again", P(A.val) == P(ctypes.CDLL("/m/a.so").val))
F = ctypes.CDLL("/m/f.so")                                              # GOT.mem.counter -> A's data
print("data", F.got_counter() == ctypes.addressof(ctypes.c_int.in_dll(A, "counter")))
try:
    A.nothing
except AttributeError as e:
    print(e)
m = ctypes.CDLL(None)
try:
    m.nonexistent_symbol_xyz
except AttributeError as e:
    print(e)
""",
    )
    assert out[:4] == [
        "a.val 1",
        "same slot as the pointer C takes True",
        "again True",
        "data True",
    ]
    assert out[4] == 'Tried to lookup unknown symbol "nothing" in dynamic lib: /m/a.so'
    assert out[-1] == 'Tried to lookup unknown symbol "nonexistent_symbol_xyz" in dynamic lib: __main__'


def test_a_main_module_function_has_one_address(guest: Guest):
    # object.tp_alloc is PyType_GenericAlloc in the type's slot: the table index C uses; dlsym must give that one
    out = ok(
        guest,
        {},
        r"""
# PyTypeObject.tp_alloc of `object`, found through the C API: PyType_GetSlot(object, Py_tp_alloc = 47)
get_slot = ctypes.pythonapi.PyType_GetSlot
get_slot.restype = ctypes.c_void_p
get_slot.argtypes = [ctypes.py_object, ctypes.c_int]
print(get_slot(object, 47) == P(ctypes.pythonapi.PyType_GenericAlloc))
""",
    )
    assert out[-1] == "True"


NAMES_OF_THE_ADAPTER = (
    "exit getaddrinfo getnameinfo __assert_fail emscripten_get_heap_max _emscripten_system _gmtime_js"
)


def test_the_main_modules_symbols_are_the_same_on_both_builds(guest: Guest):
    out = ok(
        guest,
        {},
        f"""
m = ctypes.CDLL(None)
for n in {NAMES_OF_THE_ADAPTER!r}.split() + ["malloc", "emscripten_log", "emscripten_dlopen", "emscripten_log_impl_js",
                                              "_emscripten_log_formatted", "JsArray_count_js", "JsProxy_Bool_js"]:
    try:
        getattr(m, n)
        print(n, "found")
    except AttributeError:
        print(n, "missing")
""",
    )
    found = dict(line.split() for line in out)
    for n in [*NAMES_OF_THE_ADAPTER.split(), "malloc", "emscripten_log", "emscripten_dlopen", "emscripten_log_impl_js"]:
        assert found[n] == "found", n
    assert found["_emscripten_log_formatted"] == "found"
    # a DIFFERENCE from Pyodide, on purpose: its JavaScript bridge functions are real there (dlsym finds them);
    # here they are zero stubs, and a stub that returns 0 in silence would be a fake: hidden from dlsym and the GOT
    assert found["JsArray_count_js"] == "missing" and found["JsProxy_Bool_js"] == "missing"


FILES_SCOPE = {
    "/m/a.so": sidemod.lib(1, fn="val"),
    "/m/b.so": sidemod.lib(2, fn="val", got_funcs=("val",)),
    "/m/c.so": sidemod.lib(3, fn="c", env_calls=("val",)),
    "/m/e.so": sidemod.lib(5, fn="e", env_calls=("val",), needed=("a.so",)),
    "/m/g.so": sidemod.lib(9, fn="val"),
    "/m/d.so": sidemod.lib(4, fn="d", env_calls=("val",)),
}


def test_the_got_takes_the_first_definition_and_env_functions_see_the_scope(guest: Guest):
    out = ok(
        guest,
        FILES_SCOPE,
        r"""
A = ctypes.CDLL("/m/a.so")                       # RTLD_LOCAL
B = ctypes.CDLL("/m/b.so")                       # exports val too, and imports GOT.func.val
print("got", B.got_val() == A.fptr(), B.got_val() != B.fptr(), B.val(), A.val())
E = ctypes.CDLL("/m/e.so")                       # NEEDED a.so: it is in E's scope
print("needed", E.call_val())
G = ctypes.CDLL("/m/g.so", mode=ctypes.RTLD_GLOBAL)
D = ctypes.CDLL("/m/d.so")                       # env.val: the RTLD_GLOBAL library, not the local ones
print("global", D.call_val())
print("main sees global", ctypes.CDLL(None).val(), P(ctypes.CDLL(None).val) == G.fptr())
""",
    )
    assert out == ["got True True 2 1", "needed 1", "global 9", "main sees global 9 True"]


def test_a_local_library_is_not_visible_to_an_unrelated_one(guest: Guest):
    p = run(
        guest,
        FILES_SCOPE,
        r"""
A = ctypes.CDLL("/m/a.so")
C = ctypes.CDLL("/m/c.so")                       # imports env.val; A is RTLD_LOCAL and not C's NEEDED
print("loaded", flush=True)
C.call_val()
print("unreachable")
""",
    )
    assert "loaded" in p.stdout and "unreachable" not in p.stdout
    assert p.returncode != 0
    assert "cannot resolve symbol val" in p.stderr


def test_there_is_no_limit_of_libraries_or_of_needed_depth(guest: Guest):
    chain = {f"/c/c{i}.so": sidemod.lib(i, fn=f"f{i}", needed=(f"c{i + 1}.so",) if i < 19 else ()) for i in range(20)}
    cyc = {
        "/y/x.so": sidemod.lib(1, fn="x", needed=("y.so",)),
        "/y/y.so": sidemod.lib(2, fn="y", needed=("x.so",)),
    }
    out = ok(
        guest,
        {"/n/l.so": sidemod.lib(1), **chain, **cyc},
        r"""
import shutil
for i in range(300):
    shutil.copy("/n/l.so", f"/n/l{i}.so")
libs = [ctypes.CDLL(f"/n/l{i}.so") for i in range(300)]
print("300 libraries", all(l.val() == 1 for l in libs), len({l._handle for l in libs}))
c0 = ctypes.CDLL("/c/c0.so")
print("chain", c0.f0(), ctypes.CDLL("/c/c19.so").f19(), c0._handle != 0)
x = ctypes.CDLL("/y/x.so")
print("cycle", x.x(), ctypes.CDLL("/y/y.so").y())
""",
    )
    assert out == ["300 libraries True 300", "chain 0 19 True", "cycle 1 2"]
    wasm, dy = sidemod.lib_parts(1)
    out = ok(
        guest,
        {},
        sidemod.guest_chain("/d", 600, wasm, dy)
        + r"""
try:
    ctypes.CDLL("/d/l0.so")
    print("loaded")
except OSError as e:
    print(str(e).replace("\n", "|"))
""",
    )
    assert out == ["could not load dynamic lib: /d/l0.so|Error: too many nested NEEDED libraries"]


def test_a_side_module_may_import_wasi(guest: Guest):
    out = ok(
        guest,
        {"/w/w.so": sidemod.lib(1, wasi=True)},
        """
w = ctypes.CDLL("/w/w.so")
print(w.wr(), w.rnd())
""",
    )
    assert out == ["0 0"]


def test_needed_libraries_are_searched_as_the_glue_does(guest: Guest):
    files = {
        "/r/top.so": sidemod.lib(1, fn="top", needed=("dep.so", "viald.so", "beside.so"), rpaths=("$ORIGIN/sub",)),
        "/r/sub/dep.so": sidemod.lib(2, fn="dep"),
        "/r/ld/viald.so": sidemod.lib(3, fn="viald"),
        "/r/beside.so": sidemod.lib(4, fn="beside"),
    }
    out = ok(
        guest,
        files,
        r"""
os.environ["LD_LIBRARY_PATH"] = "/r/ld"       # the glue looks here too
top = ctypes.CDLL("/r/top.so")
print(top.top(), ctypes.CDLL("/r/sub/dep.so").dep(), ctypes.CDLL("/r/ld/viald.so").viald(),
      ctypes.CDLL("/r/beside.so").beside())
""",
    )
    assert out == ["1 2 3 4"]


def _cuts(lib_bytes: bytes) -> list[int]:
    """Every byte of the first 120, then the section boundaries of the module and one byte either side."""
    cuts = set(range(0, min(120, len(lib_bytes))))
    i = 8
    while i < len(lib_bytes):
        n, j, s = 0, i + 1, 0
        while True:
            c = lib_bytes[j]
            n |= (c & 0x7F) << s
            s += 7
            j += 1
            if not c & 0x80:
                break
        cuts.update({i - 1, i, i + 1, j, j + 1, j + n - 1, j + n, j + n + 1})
        i = j + n
    return sorted(c for c in cuts if 0 <= c < len(lib_bytes))


FUZZ = r"""
import os
res = {"error": 0, "loaded": 0}
def attempt(path, data):
    open(path, "wb").write(data)
    try:
        ctypes.CDLL(path)
        res["loaded"] += 1
    except OSError as e:
        assert "could not load dynamic lib: " + path in str(e), str(e)
        res["error"] += 1
good = open("/f/good.so", "rb").read()
CUTS = %s
for k, cut in enumerate(CUTS):
    attempt(f"/f/cut{k}.so", good[:cut])
for pos in POSITIONS:
    for val in (0xFF, 0x80, 0x00, 0x7F):
        if good[pos] != val:
            attempt(f"/f/m{pos}_{val}.so", good[:pos] + bytes([val]) + good[pos + 1:])
print("attempts", res["error"] + res["loaded"], "errors", res["error"] > 0)
G = ctypes.CDLL("/f/good.so")
print("still loads", G.val())
"""


def test_truncated_and_corrupt_files_fail_cleanly(guest: Guest):
    good = sidemod.lib(
        1, fn="val", got_funcs=("val", "malloc"), got_mems=("counter",), data=("counter",), needed=("/f/needed.so",)
    )
    needed = sidemod.lib(2, fn="n", data=("counter",))
    cuts = _cuts(good)
    positions = list(range(0, min(len(good), 160)))
    code = FUZZ.replace("%s", repr(cuts), 1).replace("POSITIONS", repr(positions))
    out = ok(guest, {"/f/good.so": good, "/f/needed.so": needed}, code)
    assert out[1] == "still loads 1"
    assert out[0].endswith("errors True")


def test_a_real_wheels_library_cut_at_every_section_boundary(guest: Guest):
    site = conftest.testenv() / "site"
    if not site.is_dir():
        pytest.skip(f"{site} is missing (tools/prepare_testenv.sh)")
    code = r"""
import glob, os
sos = sorted(glob.glob("/lib/python3.15/site-packages/numpy/**/*.so", recursive=True), key=os.path.getsize)
so = sos[0]
good = open(so, "rb").read()
def leb(b, i):
    n = s = 0
    while True:
        c = b[i]; i += 1; n |= (c & 0x7F) << s; s += 7
        if not c & 0x80: return n, i
cuts, i = {0, 1, 7, 8, 9, 10, 11, 12, 20, 40}, 8
while i < len(good):
    n, j = leb(good, i + 1)
    cuts.update({i, i + 1, j, j + 1, j + n - 1, j + n, j + n + 1})
    i = j + n
os.makedirs("/f", exist_ok=True)
fails = loaded = 0
for k, cut in enumerate(sorted(c for c in cuts if c < len(good))):
    p = f"/f/{os.path.basename(so)}.{k}.so"
    open(p, "wb").write(good[:cut])
    try:
        ctypes.CDLL(p); loaded += 1
    except OSError as e:
        assert "could not load dynamic lib: " + p in str(e), str(e); fails += 1
print("sections", len(cuts), "failed", fails > len(cuts) // 2, "survived", True)
"""
    p = guest.run(PRE + code, "site")
    assert p.returncode == 0, p.stderr[-3000:]
    assert p.stdout.splitlines()[-1].endswith("failed True survived True")


def test_emscripten_dlopen_calls_back(guest: Guest):
    # The glue calls back from a promise, after the caller returned; here from a pending call of the interpreter, at its
    # next safe point after emscripten_dlopen returned (a loop that polls sees it). A bad file that exists goes to
    # onerror with the glue's text. A missing top-level file is a DELIBERATE difference (owner): Pyodide is fatal there
    # ("Failed to find dynamic library"), here it is onerror as well.
    files = {
        "/m/cb.so": sidemod.lib(1, fn="cb", callbacks=True),
        "/m/a.so": sidemod.lib(1, fn="val"),
        "/m/junk.so": b"junk-not-wasm",
    }
    out = ok(
        guest,
        files,
        r"""
import itertools, operator, time
L = ctypes.CDLL("/m/cb.so")
m = ctypes.CDLL(None)
m.emscripten_dlopen.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
m.emscripten_dlopen.restype = None
m.dlerror.restype = ctypes.c_char_p
def wait(slot, n):
    t = time.time()
    while L.peek(slot) < n and time.time() - t < 10: time.sleep(0.001)
call = (m.emscripten_dlopen, b"/m/a.so", 2, 1234, P(L.on_ok), P(L.on_err))
# two C calls with no bytecode between them (no safe point): not called back inside, nor right after, emscripten_dlopen
print("atomic", list(itertools.starmap(operator.call, [call, (L.peek, 2)]))[1])
wait(2, 1)
print("success", L.peek(0), L.peek(1) != 0, L.peek(2), L.peek(6))
m.emscripten_dlopen(b"/m/junk.so", 2, 7, P(L.on_ok), P(L.on_err))
wait(6, 1)
print("junk", L.peek(4), L.peek(6), L.peek(2))
print(m.dlerror().decode().split("\n")[0])
m.emscripten_dlopen(b"/m/none.so", 2, 99, P(L.on_ok), P(L.on_err))
wait(6, 2)
err = m.dlerror()
print("failure", L.peek(4), L.peek(6), L.peek(2))
print(err.decode().replace("\n", "|"))
""",
    )
    # the C library calls onsuccess(user_data, handle) and onerror(user_data); the glue calls (handle, user_data)
    assert out[0] == "atomic 0"
    assert out[1] == "success 1234 True 1 0"
    assert out[2] == "junk 7 1 1"
    assert out[3] == "'Could not load dynamic lib: /m/junk.so"
    assert out[4] == "failure 99 2 1"
    assert out[5] == '\'Could not load dynamic lib: /m/none.so|Error: Failed to find dynamic library "/m/none.so"'


def test_emscripten_log_goes_to_stdout_or_stderr(guest: Guest):
    out = guest.run(
        PRE
        + r"""
m = ctypes.CDLL(None)
log = m.emscripten_log          # emscripten_log(flags, fmt, varargs)
log.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p]
log.restype = None
for flags, text in ((0, "plain"), (1, "console log"), (1 | 2, "console warn"), (1 | 4, "console error"),
                    (1 | 512, "console info"), (1 | 256, "console debug"), (2, "warn flag only"),
                    (4, "error flag only"),
                    (512, "info flag only"), (8, "with a stack   \n")):
    log(flags, ("LOG %d " % flags).encode() + text.encode(), None)
m._emscripten_log_formatted.argtypes = [ctypes.c_int, ctypes.c_char_p]
m._emscripten_log_formatted.restype = None
m._emscripten_log_formatted(4, b"LOG direct error")
m.emscripten_log_impl_js.argtypes = [ctypes.c_char_p]
m.emscripten_log_impl_js.restype = None
m.emscripten_log_impl_js(b"LOG impl")
"""
    )
    assert out.returncode == 0, out.stderr[-2000:]
    so = [x for x in out.stdout.splitlines() if x.startswith("LOG")]
    se = [x for x in out.stderr.splitlines() if x.startswith("LOG")]
    assert so == [
        "LOG 0 plain",
        "LOG 1 console log",
        "LOG 513 console info",
        "LOG 257 console debug",
        "LOG 512 info flag only",
        "LOG 8 with a stack",
    ]
    assert se == [
        "LOG 3 console warn",
        "LOG 5 console error",
        "LOG 2 warn flag only",
        "LOG 4 error flag only",
        "LOG direct error",
        "LOG impl",
    ]


def test_a_bridge_function_a_side_module_imports_is_an_error_not_a_zero(guest: Guest):
    files = {
        "/b/call.so": sidemod.lib(1, fn="c", env_calls=("JsArray_count_js",)),
        "/b/got.so": sidemod.lib(1, fn="g", got_funcs=("JsArray_count_js",)),
    }
    out = ok(
        guest,
        files,
        """
try:
    ctypes.CDLL("/b/got.so")
except OSError as e:
    print(str(e).replace("\\n", "|"))
ctypes.CDLL("/b/call.so")
print("loaded", flush=True)
""",
    )
    assert (
        out[0]
        == "could not load dynamic lib: /b/got.so|Error: Dynamic linking error: undefined symbol 'JsArray_count_js'"
    )
    p = run(guest, files, 'ctypes.CDLL("/b/call.so").call_JsArray_count_js()')
    assert p.returncode != 0 and "cannot resolve symbol JsArray_count_js" in p.stderr


def test_a_huge_dylink_table_or_memory_is_a_dlerror_not_the_end(guest: Guest):
    wasm, dy = sidemod.lib_parts(1)
    files = {
        "/h/table.so": sidemod.with_dylink(wasm, memsize=dy["memsize"], memalign=dy["memalign"], tsize=0x7FFFFFF0),
        "/h/memory.so": sidemod.with_dylink(wasm, memsize=0x7FFF0000, memalign=dy["memalign"], tsize=dy["tsize"]),
        "/h/ok.so": sidemod.lib(5),
    }
    out = ok(
        guest,
        files,
        r"""
for p in ("/h/table.so", "/h/memory.so"):
    try:
        ctypes.CDLL(p)
        print("loaded", p)
    except OSError as e:
        print(str(e).replace("\n", "|"))
print(ctypes.CDLL("/h/ok.so").val())
""",
    )
    why = "|RangeError: WebAssembly.Memory(): out of memory"
    assert out == [
        f"could not load dynamic lib: /h/table.so{why}",
        f"could not load dynamic lib: /h/memory.so{why}",
        "5",
    ]


HOLD = "held = [bytearray(1100 << 20) for _ in range(3)]\n"


def test_no_memory_for_a_big_file_is_a_dlerror(guest: Guest):
    out = ok(
        guest,
        {},
        HOLD
        + r"""
with open("/big.so", "wb") as f:
    f.truncate(1000 << 20)
try:
    ctypes.CDLL("/big.so")
except OSError as e:
    print(str(e).replace("\n", "|"))
""",
    )
    assert out == ["could not load dynamic lib: /big.so|RangeError: WebAssembly.Memory(): out of memory"]


def test_a_dlerror_without_memory_for_its_text_is_an_attribute_error(guest: Guest):
    out = ok(
        guest,
        {},
        HOLD
        + r"""
m = ctypes.CDLL(None)
try:
    getattr(m, "q" * 3000000)
except AttributeError as e:
    print("AttributeError", len(str(e)) > 0)
""",
    )
    assert out == ["AttributeError True"]


def test_exported_globals_that_are_no_address(guest: Guest):
    out = ok(
        guest,
        {"/o/o.so": sidemod.lib(1, other_globals=True)},
        r"""
o = ctypes.CDLL("/o/o.so")
for n in ("gf64", "gi64"):
    try:
        print(n, "found", isinstance(ctypes.c_int.in_dll(o, n).value, int))
    except (AttributeError, ValueError) as e:
        print(n, type(e).__name__)
print(o.val())
""",
    )
    assert out[0].startswith("gf64 found") and out[1] in ("gi64 AttributeError", "gi64 ValueError") and out[2] == "1"


def test_legacy_exceptions_and_wasi_together(guest: Guest):
    out = ok(guest, {"/l/l.so": sidemod.legacy_try_with_wasi()}, 'print(ctypes.CDLL("/l/l.so").rnd())')
    assert out == ["0"]


def test_wasi_calls_of_a_side_module_that_the_adapter_owns_reach_the_adapter(guest: Guest):
    # fd_write on a socket descriptor is the adapter's (wasmtime's WASI would say EBADF, 8)
    out = ok(
        guest,
        {"/w/w.so": sidemod.lib(1, wasi=True)},
        """
import socket
w = ctypes.CDLL("/w/w.so")
s = socket.socket()
print(w.wrfd(1), w.wrfd(s.fileno()) != 8, w.wrfd(999))
""",
    )
    assert out == ["0 True 8"]


def test_needed_is_the_library_the_glue_finds_not_one_of_that_file_name(guest: Guest):
    files = {
        "/a/libx.so": sidemod.lib(1, fn="x"),
        "/b/libx.so": sidemod.lib(2, fn="x"),
        "/b/m.so": sidemod.lib(3, fn="m", env_calls=("x",), needed=("libx.so",), rpaths=("$ORIGIN",)),
    }
    out = ok(guest, files, 'ctypes.CDLL("/a/libx.so")\nprint(ctypes.CDLL("/b/m.so").call_x())')
    assert out == ["2"]


def test_the_first_library_made_global_wins(guest: Guest):
    files = {
        "/g/a.so": sidemod.lib(1, fn="val"),
        "/g/b.so": sidemod.lib(2, fn="val"),
        "/g/d.so": sidemod.lib(4, fn="d", env_calls=("val",)),
    }
    out = ok(
        guest,
        files,
        """
ctypes.CDLL("/g/a.so")
ctypes.CDLL("/g/b.so", mode=ctypes.RTLD_GLOBAL)
ctypes.CDLL("/g/a.so", mode=ctypes.RTLD_GLOBAL)
print(ctypes.CDLL("/g/d.so").call_val(), ctypes.CDLL(None).val())
""",
    )
    assert out == ["2 2"]
