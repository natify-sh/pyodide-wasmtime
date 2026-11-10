"""Offline: the runtime imports of Emscripten's glue (`__assert_fail`, `_abort_js`, `exit`, `_emscripten_system`,
`_emscripten_get_progname`, `emscripten_get_heap_max`, `emscripten_resize_heap`, `emscripten_date_now`), on both
packagings.
The expected values are what Pyodide 315.0.0a2 prints for the same calls."""

from __future__ import annotations

from conftest import Guest

ASSERT = """
import ctypes as c
libc = c.CDLL(None)
libc.__assert_fail.restype = None
libc.__assert_fail(b"x == 1", b"file.c", 42, b"func")
"""


def test_a_failed_assert_says_what_javascript_says_and_aborts(guest: Guest) -> None:
    r = guest.run(ASSERT)
    assert r.returncode == 134  # the guest trapped
    assert "Aborted(Assertion failed: x == 1, at: file.c,42,func)\n" in r.stderr


def test_an_assert_without_names(guest: Guest) -> None:
    r = guest.run(ASSERT.replace('b"x == 1", b"file.c", 42, b"func"', "None, None, -7, None"))
    assert r.returncode == 134
    assert "Aborted(Assertion failed: , at: unknown filename,-7,unknown function)\n" in r.stderr


def test_abort_says_aborted(guest: Guest) -> None:
    r = guest.run("import os; os.abort()")
    assert r.returncode == 134
    assert "Aborted()\n" in r.stderr


EXIT = """
import ctypes as c, os
libc = c.CDLL(None)
handler = c.CFUNCTYPE(None)(lambda: os.write(1, b"ATEXIT-HANDLER-RAN\\n"))
print("atexit", libc.atexit(handler), flush=True)
libc.printf(b"unflushed-stdio")
libc.exit.restype = None
libc.exit(3)
"""


def test_c_exit_ends_the_process_without_atexit_handlers_or_a_flush(guest: Guest) -> None:
    """Pyodide's `exit` import runs no C atexit handler (the runtime stays alive) and flushes no stdio."""
    r = guest.run(EXIT)
    assert r.returncode == 3
    assert r.stdout == "atexit 0\n"


def test_system_is_enosys(guest: Guest) -> None:
    """No processes: system(NULL) says there is no shell; a command is ENOSYS (Node would run a shell)."""
    code = """
import ctypes as c
libc = c.CDLL(None, use_errno=True)
libc.system.argtypes = [c.c_char_p]
print(libc.system(None), libc.system(b"true"), c.get_errno())
import os
print(os.system("true"))
"""
    r = guest.run(code)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["0 -1 52", "-1"]


def test_progname_is_cut_and_ended(guest: Guest) -> None:
    code = """
import ctypes as c
libc = c.CDLL(None)
for n in (4, 1, 0, 20):
    buf = c.create_string_buffer(b"x" * 20)
    libc._emscripten_get_progname(buf, n)
    print(n, buf.raw[:16])
"""
    r = guest.run(code)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "4 b'./t\\x00xxxxxxxxxxxx'",
        "1 b'\\x00xxxxxxxxxxxxxxx'",
        "0 b'xxxxxxxxxxxxxxxx'",
        "20 b'./this.program\\x00x'",
    ]


def test_heap_max_and_resize_follow_getheapmax(guest: Guest) -> None:
    """getHeapMax() is 4294901760; a request above it fails, one below it that the memory can grow to succeeds."""
    code = """
import ctypes as c
libc = c.CDLL(None)
libc.emscripten_get_heap_max.restype = c.c_uint32
libc.emscripten_resize_heap.argtypes = [c.c_uint32]
print(libc.emscripten_get_heap_max(), *[libc.emscripten_resize_heap(n) for n in (0xFFFF0000, 0xFFFF0001, 0xFFFFFFFF)])
"""
    r = guest.run(code)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["4294901760 1 0 0"]


def test_date_now_is_whole_milliseconds(guest: Guest) -> None:
    code = """
import ctypes as c
libc = c.CDLL(None)
libc.emscripten_date_now.restype = c.c_double
a = libc.emscripten_date_now(); b = libc.emscripten_date_now()
import time
print(a == int(a), abs(a / 1000 - time.time()) < 5, b >= a)
"""
    r = guest.run(code)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["True True True"]


def test_the_adapters_functions_are_found_by_dlsym(guest: Guest) -> None:
    """dlsym(RTLD_DEFAULT, ...) finds what the glue answers, in the dynamic packaging as in the fused one."""
    code = """
import ctypes as c
libc = c.CDLL(None)
print([hasattr(libc, n) for n in ("exit", "__assert_fail", "emscripten_get_heap_max", "_PyEM_TrampolineCall_JS")])
"""
    r = guest.run(code)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["[True, True, True, True]"]
