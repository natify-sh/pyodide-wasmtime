"""mmap of a file (`_mmap_js`, `_munmap_js`, `_msync_js`), on both builds.

CPython skips its own test_mmap on Emscripten, so the official suite runs none of it (`test_cpython_core[test_mmap]`
is a skip); `test_cpythons_test_mmap` here runs it with that skip taken off. The expected values are what Pyodide
315.0.0a2 on Node prints for the same scripts.
"""

from __future__ import annotations

import ast
import re

import conftest
import pytest
from conftest import Guest, missing

PRE = """
import mmap, os
os.makedirs("/mm", exist_ok=True)
def disk(p): return open(p, "rb").read()
def err(fn):
    try: return repr(fn())
    except BaseException as e: return type(e).__name__ + " " + str(e)
DATA = b"HELLO-MMAP" + bytes(range(256)) * 10
"""


def run(guest: Guest, code: str) -> list[str]:
    p = guest.run(PRE + code)
    assert p.returncode == 0, p.stderr[-3000:]
    return p.stdout.splitlines()


def test_a_file_is_read_through_the_mapping(guest: Guest):
    out = run(
        guest,
        r"""
p = "/mm/f.bin"
open(p, "wb").write(DATA)
with open(p, "rb") as f:
    m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    print(len(m), m[:10], m.find(b"MMAP"), m[-3:], m[300:304] == DATA[300:304], m.read(5), m.tell())
    m.seek(0); print(m.readline()[:12], m.rfind(b"\xff") == DATA.rfind(b"\xff"))
    print(mmap.mmap(f.fileno(), 20, offset=0, access=mmap.ACCESS_READ)[:20] == DATA[:20])
    print(err(lambda: mmap.mmap(f.fileno(), 10, offset=4096, access=mmap.ACCESS_READ)[:4]))
""",
    )
    assert out == [
        "2570 b'HELLO-MMAP' 6 b'\\xfd\\xfe\\xff' True b'HELLO' 5",
        "b'HELLO-MMAP\\x00\\x01' True",
        "True",
        "ValueError mmap length is greater than file size",
    ]


def test_writes_reach_the_file_on_flush_and_close(guest: Guest):
    out = run(
        guest,
        r"""
p = "/mm/w.bin"
open(p, "wb").write(DATA)
with open(p, "r+b") as f:
    m = mmap.mmap(f.fileno(), 0)
    m[0:5] = b"howdy"
    m.flush()
    print(disk(p)[:10])
    m[6:10] = b"mmap"
    m.close()
    print(disk(p)[:10], len(disk(p)))
with open(p, "r+b") as f:
    m = mmap.mmap(f.fileno(), 20, offset=0)
    m[0:2] = b"DD"
    m.close()                  # no flush: munmap writes back
print(disk(p)[:10])
""",
    )
    assert out == ["b'howdy-MMAP'", "b'howdy-mmap' 2570", "b'DDwdy-mmap'"]


def test_a_mapping_outlives_the_descriptor_it_was_made_from(guest: Guest):
    # POSIX: the mapping stays valid after close(fd); CPython's test_basic closes the file before m.flush()
    out = run(
        guest,
        r"""
p = "/mm/o.bin"
open(p, "wb").write(DATA)
f = open(p, "r+b")
m = mmap.mmap(f.fileno(), 0)
f.close()
m[0:4] = b"BYE!"
m.flush()
print(disk(p)[:8])
m[4:6] = b"ok"
m.close()
print(disk(p)[:8])
""",
    )
    assert out == ["b'BYE!O-MM'", "b'BYE!okMM'"]


def test_private_mappings_never_write_back(guest: Guest):
    out = run(
        guest,
        r"""
p = "/mm/p.bin"
open(p, "wb").write(DATA)
with open(p, "r+b") as f:
    m = mmap.mmap(f.fileno(), 20, flags=mmap.MAP_PRIVATE)
    m[0:3] = b"XXX"
    print(m[:10]); m.flush(); m.close()
    c = mmap.mmap(f.fileno(), 20, access=mmap.ACCESS_COPY)
    c[0:3] = b"YYY"
    print(c[:10]); c.close()
print(disk(p)[:10])
""",
    )
    assert out == ["b'XXXLO-MMAP'", "b'YYYLO-MMAP'", "b'HELLO-MMAP'"]


def test_errors_are_the_ones_pyodide_gives(guest: Guest):
    out = run(
        guest,
        r"""
p = "/mm/e.bin"
open(p, "wb").write(DATA)
open("/mm/empty", "wb").close()
with open(p, "rb") as f:
    m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    def w(): m[0:1] = b"z"
    print(err(w))
    print(err(lambda: mmap.mmap(f.fileno(), 0, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE)))
    print(err(lambda: mmap.mmap(f.fileno(), 10, offset=5)))
    print(err(lambda: mmap.mmap(f.fileno(), 100000, access=mmap.ACCESS_READ)))
with open("/mm/empty", "r+b") as f:
    print(err(lambda: mmap.mmap(f.fileno(), 0)))
print(err(lambda: mmap.mmap(os.open("/mm", os.O_RDONLY), 10, access=mmap.ACCESS_READ)))
fd = os.open(p, os.O_WRONLY)
print(err(lambda: mmap.mmap(fd, 10)))
print(err(lambda: (lambda a: (a.write(b"abc"), a[:3])[1])(mmap.mmap(-1, 100))))
with open(p, "r+b") as f:
    m = mmap.mmap(f.fileno(), 100)
    print(err(lambda: m.resize(200)), len(m))   # mremap does not exist in Emscripten
""",
    )
    assert out == [
        "TypeError mmap can't modify a readonly memory map.",
        "PermissionError [Errno 2] Permission denied",
        "OSError [Errno 28] Invalid argument",
        "ValueError mmap length is greater than file size",
        "ValueError cannot mmap an empty file",
        "OSError [Errno 43] No such device",
        "PermissionError [Errno 2] Permission denied",
        "b'abc'",
        "OSError [Errno 48] Out of memory 100",
    ]


def test_a_big_mapping_and_an_offset_past_4_gib(guest: Guest):
    out = run(
        guest,
        r"""
p = "/mm/big.bin"
n = 100 << 20
with open(p, "wb") as f:
    f.seek(0x140000000 + n + 5); f.write(b" ")
with open(p, "r+b") as f:
    m = mmap.mmap(f.fileno(), n, offset=0x140000000)       # 100 MiB: read in several pieces
    print(len(m), m[:4], m[-1:])
    m[-5:] = b"tail!"
    m.close()
with open(p, "rb") as f:
    f.seek(0x140000000 + n - 5)
    print(f.read(5))
""",
    )
    assert out == ["104857600 b'\\x00\\x00\\x00\\x00' b'\\x00'", "b'tail!'"]


@pytest.mark.suite
def test_cpythons_test_mmap(flavor: str):
    """CPython's own test_mmap, which it skips on Emscripten, with the skip taken off. What still fails is what
    Emscripten's libc lacks, not the imports: mremap (`resize`) and msync with an address inside a mapping."""
    suite = conftest.testenv() / "suite" / "test"
    ext = conftest.testenv() / "suite_ext"
    if not (suite.is_dir() and ext.is_dir()):
        missing(f"{suite} is missing")
    code = """
import test.support as s
s.is_emscripten = False
import unittest
from test import test_mmap
r = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_mmap))
print("PW_FAILED:", sorted(t.id().split(".")[-1] for t, _ in r.failures + r.errors))
"""
    p = Guest(flavor).run(
        code, None, "--site", str(ext), "--mount", f"/lib/python3.15/site-packages/test={suite}", timeout=1800
    )
    m = re.search(r"^PW_FAILED: (.*)$", p.stdout, re.M)
    assert m, p.stdout[-2000:] + p.stderr[-2000:]
    failed = ast.literal_eval(m.group(1))
    mremap = {
        "test_offset",
        "test_resize",
        "test_resize_down_anonymous_mapping",
        "test_resize_past_pos",
        "test_resize_up_anonymous_mapping",
        "test_resize_up_private_anonymous_mapping",
    }
    assert set(failed) <= mremap | {"test_flush_parameters"}, failed
