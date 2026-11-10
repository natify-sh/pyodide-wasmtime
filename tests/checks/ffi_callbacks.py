# ctypes callbacks (ffi_prep_closure_loc_js): every kind, libc calling back, a callback that raises, one inside another
# (the .expected file is what Pyodide prints)
import ctypes as c
import sys

libc = c.CDLL(None)
out = []


def t(name, fn):
    try:
        out.append((name, fn()))
    except BaseException as e:
        out.append((name, "EXC " + type(e).__name__))


t("int", lambda: c.CFUNCTYPE(c.c_int, c.c_int, c.c_int)(lambda a, b: a + b)(3, 4))
t("double", lambda: c.CFUNCTYPE(c.c_double, c.c_double, c.c_double)(lambda a, b: a * b)(1.5, 4.0))
t("float", lambda: c.CFUNCTYPE(c.c_float, c.c_float)(lambda a: a / 2)(3.0))
t("int64", lambda: c.CFUNCTYPE(c.c_int64, c.c_int64, c.c_int64)(lambda a, b: a * b)(1 << 33, 3))
t("uint64", lambda: c.CFUNCTYPE(c.c_uint64, c.c_uint64)(lambda a: a + 1)(2**64 - 2))
t("ptr", lambda: c.CFUNCTYPE(c.c_void_p, c.c_void_p)(lambda a: a)(1234))
t("noargs", lambda: c.CFUNCTYPE(c.c_int)(lambda: 42)())
seen = []
c.CFUNCTYPE(None, c.c_int)(lambda a: seen.append(a))(9)
t("void", lambda: seen)
t("char", lambda: c.CFUNCTYPE(c.c_char, c.c_char)(lambda a: b"z")(b"a"))
t("short", lambda: c.CFUNCTYPE(c.c_short, c.c_short)(lambda a: -a)(5))
t("ubyte", lambda: c.CFUNCTYPE(c.c_ubyte, c.c_ubyte)(lambda a: a + 1)(255))


class P(c.Structure):
    _fields_ = [("x", c.c_int), ("y", c.c_int)]


t("structret", lambda: (lambda r: (r.x, r.y))(c.CFUNCTYPE(P, c.c_int)(lambda a: P(a, a * 2))(7)))


class Big(c.Structure):
    _fields_ = [("a", c.c_int), ("b", c.c_double), ("c", c.c_int)]


t("bigstruct arg", lambda: c.CFUNCTYPE(c.c_double, Big)(lambda s: s.a + s.b + s.c)(Big(1, 2.5, 3)))
t("bigstruct ret", lambda: (lambda r: (r.a, r.b, r.c))(c.CFUNCTYPE(Big, c.c_int)(lambda a: Big(a, a + 0.5, a + 1))(4)))
t("longdouble", lambda: c.CFUNCTYPE(c.c_longdouble, c.c_longdouble)(lambda a: a * 2)(1.5))
t("many", lambda: c.CFUNCTYPE(c.c_double, *[c.c_int, c.c_double] * 5)(lambda *a: sum(a))(*[1, 0.5] * 5))


def bad():
    raise ValueError("x")


import io

e = io.StringIO()
sys.stderr, old = e, sys.stderr
t("raises", lambda: c.CFUNCTYPE(c.c_int)(bad)() is not None)
sys.stderr = old
t("raises-stderr", lambda: "Exception ignored" in e.getvalue() or e.getvalue()[:60])
inner = c.CFUNCTYPE(c.c_int, c.c_int)(lambda a: a + 1)
outer = c.CFUNCTYPE(c.c_int, c.c_int)(lambda a: inner(a) * 2)
t("nested", lambda: outer(5))
cmp = c.CFUNCTYPE(c.c_int, c.POINTER(c.c_int), c.POINTER(c.c_int))
arr = (c.c_int * 6)(5, 3, 9, 1, 4, 0)
libc.qsort(arr, 6, 4, cmp(lambda a, b: a[0] - b[0]))
t("qsort", lambda: list(arr))
key = c.c_int(4)
libc.bsearch.restype = c.c_void_p
r = libc.bsearch(c.byref(key), arr, 6, 4, cmp(lambda a, b: a[0] - b[0]))
t("bsearch", lambda: (r - c.addressof(arr)) // 4)
for n, v in out:
    print(n, v)
