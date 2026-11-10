"""Offline: libffi's emscripten port (`ffi_call_js`, `ffi_prep_closure_loc_js`, `ffi_closure_alloc_js`/`_free_js`) and
the trampoline's fallback, on both packagings. The .expected files are what the real Pyodide 315.0.0a2 prints for the
same scripts (tests/checks/ffi_*.py, cffi_callbacks.py)."""

from __future__ import annotations

import struct
from typing import Any

import pytest
from conftest import Guest, check_file, missing, testenv

from pyodide_wasmtime import Pyodide


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


def test_cffi_callbacks(guest: Guest) -> None:
    """cffi's own wheel, loaded by dlopen: callback() makes a closure (it was SystemError 'bad user_data')."""
    site = testenv() / "site_cffi"
    if not (site / "cffi").is_dir() or not (site / "pycparser").is_dir():
        missing(f"the unpacked cffi and pycparser wheels are not in {site}")
    r = guest.run(check_file("cffi_callbacks.py"), None, "--site", str(site))
    assert r.returncode == 0, r.stderr
    assert lines(r.stdout) == lines(check_file("cffi_callbacks.expected"))


class FakeMemory:
    """A guest memory of 4 KiB for the operations that read a cif: the host reads it as the guest left it."""

    def __init__(self) -> None:
        self.data = bytearray(4096)

    def data_len(self, _store: object) -> int:
        return len(self.data)

    def read(self, _store: object, start: int, stop: int) -> bytes:
        return bytes(self.data[start:stop])

    def write(self, _store: object, data: bytes, start: int) -> None:
        self.data[start : start + len(data)] = data


def fake_host() -> Any:
    from pyodide_wasmtime._host import Pyodide

    py = Pyodide.__new__(Pyodide)
    py.cur, py.memory = [None], FakeMemory()
    py._wt = object()

    class Stack:
        def value(self, _ctx: object) -> int:
            return 4000

    py.ex = {"__stack_pointer": Stack()}
    return py


def test_pointers_of_the_operations_are_unsigned_and_checked() -> None:
    """wasmtime passes an i32 as a signed number: a pointer above 2 GiB is negative. It is read as the address it is
    (outside this memory: a GuestFault), never as an offset from the end of the memory."""
    from pyodide_wasmtime._host import GuestFault

    py = fake_host()
    for call in (
        lambda: py._ffi_call(-8, 0, 0, 0),
        lambda: py._ffi_prep(0, -8, 0, 0, 0),
        lambda: py._t_mktime(-40),
        lambda: py._t_localtime(0, -40),
        lambda: py._t_tzset(-4, 0, 0, 0),
    ):
        with pytest.raises(GuestFault):
            call()


def test_a_cif_from_the_guest_cannot_make_the_host_loop_or_copy_without_end() -> None:
    from pyodide_wasmtime._host import GuestFault

    py = fake_host()
    mem = py.memory.data
    mem[16 + 6 : 16 + 8] = (13).to_bytes(2, "little")  # an ffi_type (at 16) that is a struct ...
    mem[16 + 8 : 16 + 12] = (32).to_bytes(4, "little")  # ... whose elements (at 32) are [itself, NULL]
    mem[32:36] = (16).to_bytes(4, "little")
    with pytest.raises(RuntimeError, match="too deep"):
        py._unbox(16)
    # a cif (abi, nargs, arg_types, rtype, bytes, flags, nfixedargs) whose argument types lie outside the memory
    mem[64:92] = struct.pack("<7I", 0, 100, 2**31, 0, 0, 0, 100)
    with pytest.raises(GuestFault):
        py._ffi_call(64, 0, 0, 0)
    mem[64:92] = struct.pack("<7I", 0, 5000, 0, 0, 0, 0, 5000)  # more arguments than a wasm function can have
    with pytest.raises(RuntimeError, match="5000 arguments"):
        py._ffi_call(64, 0, 0, 0)


def test_a_failing_host_function_ends_the_interpreter_like_a_trap(flavor: str, capfd: Any) -> None:
    """A BigInt where the callee wants a Number is a TypeError in JavaScript (fatal in Pyodide); here run() says so once
    on stderr, returns 134 as for a trap, and the next run() starts a new interpreter."""
    code = """
import ctypes as c
libc = c.CDLL(None)
libc.llabs.argtypes = [c.c_int]
libc.llabs.restype = c.c_longlong
libc.llabs(-3)
"""
    with Pyodide(flavor) as py:
        assert py.run(code) == 134
        err = capfd.readouterr().err
        assert "a host function failed, the guest is dead: TypeError: Cannot convert 4294967293 to a BigInt" in err
        assert py.run("print('alive')") == 0
    assert capfd.readouterr().out == "alive\n"


def test_closures_reuse_their_wasmtime_functions(flavor: str) -> None:
    """A wasmtime Func is never freed before its store: 20000 created and freed callbacks must not make 20000."""
    import resource

    code = """
import ctypes as c
CB = c.CFUNCTYPE(c.c_int, c.c_int)
for i in range(20000):
    f = CB(lambda x: x + 1)
    assert f(i) == i + 1
    del f
"""
    with Pyodide(flavor) as py:
        assert py.run("pass") == 0
        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        assert py.run(code) == 0
        grown_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before
        assert sum(len(v) for v in py.func_pool.values()) <= 2 and not py.live_funcs
    assert grown_kb < 40_000  # it was 150 MB
