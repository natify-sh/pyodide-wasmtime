"""Offline: libffi's emscripten port (`ffi_call_js`, `ffi_prep_closure_loc_js`, `ffi_closure_alloc_js`/`_free_js`) and
the trampoline's fallback, on both packagings. The .expected files are what the real Pyodide 315.0.0a2 prints for the
same scripts (tests/checks/ffi_*.py, cffi_callbacks.py)."""

from __future__ import annotations

import zipfile
from pathlib import Path

from conftest import Guest, check_file, missing, work_dir


def lines(out: str) -> list[str]:
    return [x for x in out.splitlines() if x]


def test_ctypes_calls_take_any_signature(guest: Guest) -> None:
    """A call tolerates what JavaScript's `wasmTable.get(fn)(...args)` tolerates: a void function with the default
    restype, an extra or a missing argument, more than 8 arguments, doubles with 5 arguments, a long double, a struct
    as argument and as result, variadic calls (nfixedargs)."""
    r = guest.run(check_file("ffi_calls.py"))
    assert r.returncode == 0, r.stderr
    assert lines(r.stdout) == lines(check_file("ffi_calls.expected"))


def test_ctypes_callbacks_of_every_kind(guest: Guest) -> None:
    """int, double, float, int64, pointers, no arguments, void, a struct by value as argument, qsort and bsearch calling
    a comparator, a callback that raises, a callback inside a callback."""
    r = guest.run(check_file("ffi_callbacks.py"))
    assert r.returncode == 0, r.stderr
    assert lines(r.stdout) == lines(check_file("ffi_callbacks.expected"))


def test_freed_closures_give_their_table_slots_back(guest: Guest) -> None:
    """JavaScript's getEmptyTableSlot() takes the slot freed last; the slots do not grow with each created callback."""
    code = """
import ctypes as c, gc
def addr(f): return c.cast(f, c.c_void_p).value
CB = c.CFUNCTYPE(None)
a = CB(lambda: 0); A = addr(a)
b = CB(lambda: 0); B = addr(b)
cc = CB(lambda: 0); C = addr(cc)
print(B - A, C - A)
del a; gc.collect()
d = CB(lambda: 0); print("reuse a", addr(d) - A)
del b, cc; gc.collect()
e = CB(lambda: 0); f = CB(lambda: 0); g = CB(lambda: 0)
print([addr(x) - A for x in (e, f, g)])
x = []
for i in range(1000):
    x.append(CB(lambda: 0))
x.clear(); gc.collect()
h = [CB(lambda: 0) for _ in range(3)]
print([addr(q) - A for q in h])
"""
    r = guest.run(code)
    assert r.returncode == 0, r.stderr
    assert lines(r.stdout) == ["1 2", "reuse a 0", "[2, 1, 3]", "[4, 5, 6]"]


def test_the_trampoline_calls_a_type_it_does_not_know(guest: Guest) -> None:
    """_PyEM_TrampolineCall_JS(f, a, b, c) on a table entry of another type than its ten (a double, a void function, 2
    parameters of f64 and i32): the call is made with the entry's own type, as JavaScript does, not `unreachable`."""
    code = """
import ctypes as c
libc = c.CDLL(None)
tr = libc._PyEM_TrampolineCall_JS
tr.restype = c.c_int
tr.argtypes = [c.c_void_p, c.c_int, c.c_int, c.c_int]
idx = lambda f: c.cast(f, c.c_void_p).value
calls = ((libc.sqrt, 16, 0), (libc.abs, -5, 0), (libc.free, 0, 0), (libc.ldexp, 3, 2))
print(*[tr(idx(f), a, b, 0) for f, a, b in calls])
"""
    r = guest.run(code)
    assert r.returncode == 0, r.stderr
    assert lines(r.stdout) == ["4 5 0 12"]


def test_cffi_callbacks(guest: Guest, tmp_path: Path) -> None:
    """cffi's own wheel, loaded by dlopen: callback() makes a closure (it was SystemError 'bad user_data')."""
    dist = work_dir() / "dl" / "dist"
    wheels = [dist / "cffi-2.0.0-cp315-cp315-pyemscripten_2026_5_wasm32.whl", dist / "pycparser-3.0-py3-none-any.whl"]
    if not all(w.exists() for w in wheels):
        missing(f"the cffi and pycparser wheels are not in {dist}")
    for w in wheels:
        zipfile.ZipFile(w).extractall(tmp_path)
    r = guest.run(check_file("cffi_callbacks.py"), None, "--site", str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert lines(r.stdout) == lines(check_file("cffi_callbacks.expected"))
