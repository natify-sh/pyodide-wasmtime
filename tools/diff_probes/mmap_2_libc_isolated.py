# ruff: noqa
# type: ignore
# isolate
# libc mmap/munmap/msync/mprotect/madvise through ctypes, one case per interpreter (Pyodide dies on some).
import ctypes
import os

PAT = bytes(i % 251 for i in range(100000))
F = B + "/f"
with open(F, "wb") as _f:
    _f.write(PAT)


def cmm(length, prot, flags, fd, off, addr=None):
    r = libc.mmap(addr, length, prot, flags, fd, off)
    e = ctypes.get_errno()
    if r == 2**32 - 1 or r is None or r == ctypes.c_void_p(-1).value:
        return "MAP_FAILED errno=%d" % e
    rc = libc.munmap(r, length)
    return "ok munmap=%d" % rc


libc = ctypes.CDLL(None, use_errno=True)
libc.mmap.restype = ctypes.c_void_p
libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_longlong]
libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
FDF = os.open(F, os.O_RDWR)
for ln in (0, 1, 4096, 65536, 2**31, 2**32, 2**40):
    for fl in (1, 2, 0x20 | 2, 0x20 | 1, 0x10 | 2, 0, 3):
        case("c-mmap-len%d-flags%x" % (ln, fl), cmm, ln, 3, fl, FDF if not fl & 0x20 else -1, 0)
for pr in (0, 1, 2, 3, 4, 7):
    case("c-mmap-prot%d" % pr, cmm, 4096, pr, 1, FDF, 0)
for off in (0, 1, 4095, 4096, 65536, -1, 2**40):
    case("c-mmap-off%d" % off, cmm, 4096, 3, 1, FDF, off)
case("c-mmap-fd-bad", cmm, 4096, 3, 1, 9999, 0)
case("c-mmap-fd-neg-nonanon", cmm, 4096, 3, 1, -1, 0)
case("c-mmap-addr-hint", cmm, 4096, 3, 1, FDF, 0, 0x100000)
case("c-mmap-fixed", cmm, 4096, 3, 1 | 0x10, FDF, 0, 0x100000)
case("c-munmap-bad", lambda: libc.munmap(0x1234, 4096))
case("c-munmap-zero-len", lambda: libc.munmap(0, 0))
case("c-munmap-null", lambda: libc.munmap(0, 4096))
case("c-msync-bad", lambda: libc.msync(ctypes.c_void_p(0x1234), 4096, 4))
case("c-mprotect-bad", lambda: libc.mprotect(ctypes.c_void_p(0x1234), 4096, 1))
case("c-madvise-bad", lambda: libc.madvise(ctypes.c_void_p(0x1234), 4096, 0))
case("c-mlock", lambda: libc.mlock(ctypes.c_void_p(0x1234), 4096))
case("c-mremap-sym", lambda: libc.mremap.__class__.__name__)
