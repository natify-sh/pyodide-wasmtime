# ruff: noqa
# type: ignore
# FFI matrix: ctypes calls through ffi_call_js, callbacks through closures; every class of argument and result.
import ctypes
import errno
import sys
from ctypes import *


N = 0


def c(cid, f):
    global N
    N += 1
    if N <= globals().get("SKIP", 0):
        return
    print(">> " + cid, flush=True)
    try:
        r = f()
        print(cid, "|", r, flush=True)
    except OSError as e:
        print(cid, "| ERR", errno.errorcode.get(e.errno, e.errno), flush=True)
    except BaseException as e:
        print(cid, "| EXC", type(e).__name__, str(e)[:100], flush=True)


L = CDLL(None)
INTS = [
    0,
    1,
    -1,
    127,
    128,
    -128,
    -129,
    255,
    256,
    32767,
    32768,
    -32768,
    65535,
    65536,
    2**31 - 1,
    2**31,
    -(2**31),
    -(2**31) - 1,
    2**32 - 1,
    2**32,
    2**32 + 1,
    2**53,
    2**53 + 1,
    2**63 - 1,
    2**63,
    -(2**63),
    -(2**63) - 1,
    2**64 - 1,
    2**64,
    2**100,
]
# roundtrip through memory: the type's own wrap/convert, and through a function (labs/llabs/abs)
for T in [
    c_int8,
    c_uint8,
    c_int16,
    c_uint16,
    c_int32,
    c_uint32,
    c_int64,
    c_uint64,
    c_long,
    c_ulong,
    c_longlong,
    c_ulonglong,
    c_size_t,
    c_ssize_t,
    c_bool,
    c_char,
    c_wchar,
    c_float,
    c_double,
    c_longdouble,
    c_void_p,
    c_char_p,
    c_wchar_p,
    c_byte,
    c_ubyte,
    c_short,
    c_ushort,
    c_int,
    c_uint,
]:
    for v in INTS[::2]:
        if T in (c_char_p, c_wchar_p) and v != 0:
            continue
        c("%s(%r).value" % (T.__name__, v), lambda: T(v).value)
for v in INTS:
    L.labs.restype = c_long
    L.labs.argtypes = [c_long]
    c("labs %r" % v, lambda: L.labs(v))
    L.llabs.restype = c_longlong
    L.llabs.argtypes = [c_longlong]
    c("llabs %r" % v, lambda: L.llabs(v))
    L.abs.restype = c_int
    L.abs.argtypes = [c_int]
    c("abs %r" % v, lambda: L.abs(v))
    f = L.llabs
    f.restype = c_longlong
    f.argtypes = None
    c("llabs argtypes None restype ll %r" % v, lambda: f(c_longlong(v)))
    c("llabs c_uint64 arg %r" % v, lambda: f(c_uint64(v & (2**64 - 1))))
    L.atoi.restype = c_int
    L.atoi.argtypes = [c_char_p]
    c("atoi %r" % v, lambda: L.atoi(str(v).encode()))
    L.atol.restype = c_long
    L.atol.argtypes = [c_char_p]
    c("atol %r" % v, lambda: L.atol(str(v).encode()))
    L.strtoull.restype = c_ulonglong
    L.strtoull.argtypes = [c_char_p, c_void_p, c_int]
    c("strtoull %r" % v, lambda: L.strtoull(str(v).encode(), None, 10))
    L.strtoll.restype = c_longlong
    L.strtoll.argtypes = [c_char_p, c_void_p, c_int]
    c("strtoll %r" % v, lambda: L.strtoll(str(v).encode(), None, 10))
    for rt in (c_int64, c_uint64):

        def conv(rt=rt):
            f = L.llabs
            f.argtypes = [c_longlong]
            f.restype = rt
            return f(v)

        c("llabs restype %s %r" % (rt.__name__, v), conv)
FLOATS = [
    0.0,
    -0.0,
    1.5,
    -1.5,
    1e-300,
    1e300,
    1e38,
    1e39,
    -1e39,
    3.4028235e38,
    1.17549435e-38,
    1e-45,
    5e-324,
    float("inf"),
    -float("inf"),
    float("nan"),
    2**24 + 1,
    0.1,
    1 / 3,
    123456789.123456789,
    2**53 + 0.0,
    -(2**63) + 0.0,
    2**63 + 0.0,
    2**64 + 0.0,
]
for fn in [
    "sqrt",
    "fabs",
    "floor",
    "ceil",
    "trunc",
    "round",
    "exp",
    "log",
    "sin",
    "cos",
    "tan",
    "atan",
    "cbrt",
    "log2",
    "log10",
    "expm1",
    "log1p",
    "sinh",
    "cosh",
    "tanh",
    "asinh",
    "erf",
    "tgamma",
    "lgamma",
    "nearbyint",
    "rint",
]:
    f = getattr(L, fn)
    f.restype = c_double
    f.argtypes = [c_double]
    for v in FLOATS:
        c("%s(%r)" % (fn, v), lambda: f(v))
for fn in ["sqrtf", "fabsf", "floorf", "ceilf", "truncf", "roundf", "expf", "logf", "sinf", "cosf", "cbrtf"]:
    f = getattr(L, fn)
    f.restype = c_float
    f.argtypes = [c_float]
    for v in FLOATS[::2]:
        c("%s(%r)" % (fn, v), lambda: f(v))
for fn in ["sqrtl", "fabsl", "floorl", "ceill", "expl", "logl", "sinl"]:
    f = getattr(L, fn)
    f.restype = c_longdouble
    f.argtypes = [c_longdouble]
    for v in FLOATS[::3]:
        c("%s(%r)" % (fn, v), lambda: f(v))
for fn in ["pow", "fmod", "atan2", "hypot", "fmax", "fmin", "copysign", "remainder", "nextafter", "fdim"]:
    f = getattr(L, fn)
    f.restype = c_double
    f.argtypes = [c_double, c_double]
    for a, b in [
        (2.0, 10.0),
        (-2.0, 0.5),
        (0.0, 0.0),
        (1e300, 1e300),
        (float("nan"), 1.0),
        (float("inf"), -1.0),
        (1.0, float("inf")),
        (-0.0, 1.0),
        (5.5, 2.0),
    ]:
        c("%s(%r,%r)" % (fn, a, b), lambda: f(a, b))
f = L.ldexp
f.restype = c_double
f.argtypes = [c_double, c_int]
for a, b in [(3.0, 2), (1.0, 1024), (1.0, -1075), (1.0, 2**31 - 1), (1.0, -(2**31)), (0.5, 2**31)]:
    c("ldexp(%r,%r)" % (a, b), lambda: f(a, b))
f = L.frexp
f.restype = c_double
f.argtypes = [c_double, POINTER(c_int)]
for a in [0.0, 1.0, 1e300, float("inf"), float("nan"), 5e-324]:
    e = c_int(77)
    c("frexp(%r)" % a, lambda: (f(a, byref(e)), e.value))
f = L.modf
f.restype = c_double
f.argtypes = [c_double, POINTER(c_double)]
for a in [0.0, 1.5, -1.5, float("inf"), float("nan")]:
    e = c_double(7)
    c("modf(%r)" % a, lambda: (f(a, byref(e)), e.value))
# default restype/argtypes (int), wrong types
c("sqrt default types", lambda: L.sqrt(16))
c("sqrt default types float arg", lambda: L.sqrt(c_double(16.0)))
c("sqrt float python arg", lambda: L.sqrt(16.0))
c("sqrt str arg", lambda: L.sqrt("x"))
c("sqrt None arg", lambda: L.sqrt(None))
c("abs default float", lambda: L.abs(1.5))
c("abs default str", lambda: L.abs("1"))
c("abs default bytes", lambda: L.abs(b"1"))
c("abs default big", lambda: L.abs(2**100))
c("abs default bool", lambda: L.abs(True))
c("abs default list", lambda: L.abs([1]))
c("abs c_char_p", lambda: L.abs(c_char_p(b"x")))
L.abs.argtypes = [c_int]
c("abs argtypes str", lambda: L.abs("x"))
c("abs argtypes float", lambda: L.abs(1.5))
c("abs argtypes None", lambda: L.abs(None))
c("abs argtypes 2 args", lambda: L.abs(1, 2))
c("abs argtypes 0 args", lambda: L.abs())
c("abs argtypes big", lambda: L.abs(2**40))
c("abs argtypes c_long", lambda: L.abs(c_long(-5)))
L.abs.argtypes = None
c("free default restype", lambda: L.free(L.malloc(10)))
c("malloc default restype", lambda: type(L.malloc(10)).__name__)
L.malloc.restype = c_void_p
c("malloc restype void_p", lambda: type(L.malloc(10)).__name__)
c("malloc 0", lambda: L.malloc(0) is not None)
c("malloc huge", lambda: L.malloc(2**31) is not None)
c("malloc 2**32", lambda: L.malloc(2**32))
c("malloc -1", lambda: L.malloc(-1))
c("calloc huge", lambda: (setattr(L.calloc, "restype", c_void_p), L.calloc(2**20, 2**20))[1])
c("realloc NULL", lambda: (setattr(L.realloc, "restype", c_void_p), L.realloc(None, 8) is not None)[1])
c("free NULL", lambda: L.free(None))
c("free(0)", lambda: L.free(0))
c("memset/memcpy", lambda: (lambda b: (L.memset(b, 65, 4), b.raw[:6])[1])(create_string_buffer(8)))
c("memcpy 0 len", lambda: L.memcpy(create_string_buffer(2), create_string_buffer(2), 0) is not None)
c(
    "memcmp",
    lambda: [L.memcmp(a, b, 3) for a, b in ((b"abc", b"abd"), (b"abd", b"abc"), (b"abc", b"abc"), (b"\xff", b"\x01"))],
)
c("strlen", lambda: [L.strlen(x) for x in (b"", b"abc", "x".encode("utf-16"), b"\xff" * 300)])
c("strlen None", lambda: L.strlen(None))
c("strcmp", lambda: [L.strcmp(a, b) for a, b in ((b"a", b"b"), (b"b", b"a"), (b"", b""))])
c("strchr", lambda: (setattr(L.strchr, "restype", c_char_p), L.strchr(b"hello", ord("l")))[1])
c("strstr", lambda: (setattr(L.strstr, "restype", c_char_p), L.strstr(b"hello", b"ll"), L.strstr(b"hello", b"zz"))[1:])
c("getenv missing", lambda: (setattr(L.getenv, "restype", c_char_p), L.getenv(b"DP_NOPE_X"))[1])
c(
    "strerror",
    lambda: (
        setattr(L.strerror, "restype", c_char_p),
        [L.strerror(i) for i in (0, 1, 2, 13, 22, 34, 75, 95, 110, 140, 99999, -1)],
    )[1],
)
c(
    "strtod",
    lambda: (
        setattr(L.strtod, "restype", c_double),
        [L.strtod(s, None) for s in (b"1.5", b"inf", b"nan", b"0x1p3", b"1e999", b"-0", b"abc")],
    )[1],
)
c(
    "strtod argtypes",
    lambda: (setattr(L.strtod, "argtypes", [c_char_p, c_void_p]), [L.strtod(s, None) for s in (b"1.5", b"1e-400")])[1],
)
c("atof", lambda: (setattr(L.atof, "restype", c_double), L.atof(b"3.25"))[1])
# printf-family, variadic
buf = create_string_buffer(256)
for fmt, args in [
    (b"%d", (5,)),
    (b"%d %d", (1, 2)),
    (b"%ld", (2**40,)),
    (b"%lld", (-(2**62),)),
    (b"%x", (255,)),
    (b"%c", (65,)),
    (b"%s", (b"str",)),
    (b"%5.2f", (c_double(3.14159),)),
    (b"%e", (c_double(12345.678),)),
    (b"%g", (c_double(1e-5),)),
    (b"%a", (c_double(1.0),)),
    (b"%f %f", (c_double(1.5), c_double(2.5))),
    (b"%d %f %s %lld", (1, c_double(2.5), b"s", 2**40)),
    (b"%p", (0,)),
    (b"%%", ()),
    (b"%d%d%d%d%d%d%d%d%d%d", tuple(range(10))),
    (b"%Lf", (c_longdouble(2.5),)),
    (b"%.40f", (c_double(1 / 3),)),
    (b"%s %s %s %s", (b"a", b"b", b"c", b"d")),
    (b"%hhd", (300,)),
    (b"%hd", (70000,)),
    (b"%zu", (2**33,)),
    (b"%jd", (2**40,)),
    (b"%f %d %f", (c_double(1.5), 7, c_double(2.5))),
    (b"%n", ()),
    (b"%.3s", (b"abcdef",)),
    (b"%*d", (5, 42)),
    (b"%-5d|", (42,)),
    (b"%+d", (42,)),
    (b"%05d", (42,)),
    (b"%#x", (255,)),
    (b"%o", (8,)),
    (b"%i", (-3,)),
    (b"%lu", (2**31,)),
    (b"%F", (c_double(1e10),)),
]:

    def sp(fmt=fmt, args=args):
        ctypes.memset(buf, 0, 256)
        n = L.snprintf(buf, 256, fmt, *args)
        return (n, buf.value)

    c("snprintf %r %r" % (fmt, args), sp)
c("snprintf truncation", lambda: (L.snprintf(buf, 4, b"%s", b"abcdefgh"), buf.raw[:5]))
c("snprintf size 0", lambda: L.snprintf(None, 0, b"%s", b"abcdefgh"))
c("snprintf float via python float (wrong)", lambda: L.snprintf(buf, 256, b"%f", 1.5))
c("snprintf float via python float 2", lambda: (L.snprintf(buf, 256, b"%f %d", c_double(1.5), 3), buf.value))
c("sprintf", lambda: (L.sprintf(buf, b"%s-%d", b"a", 3), buf.value))
c(
    "sscanf",
    lambda: (lambda a, b: (L.sscanf(b"12 3.5", b"%d %lf", byref(a), byref(b)), a.value, b.value))(c_int(), c_double()),
)
c("sscanf float", lambda: (lambda a: (L.sscanf(b"3.5", b"%f", byref(a)), a.value))(c_float()))
c("sscanf str", lambda: (lambda a: (L.sscanf(b"hello world", b"%15s", a), a.value))(create_string_buffer(16)))
c("sscanf long long", lambda: (lambda a: (L.sscanf(b"9223372036854775807", b"%lld", byref(a)), a.value))(c_longlong()))
c("sscanf fail", lambda: (lambda a: (L.sscanf(b"abc", b"%d", byref(a)), a.value))(c_int(5)))
c("asprintf", lambda: (lambda p: (L.asprintf(byref(p), b"%d-%s", 7, b"x"), string_at(p)))(c_void_p()))
c("vsnprintf exists", lambda: hasattr(L, "vsnprintf"))
c("puts/printf stdout", lambda: (L.printf(b"printf %d\n", 5), L.fflush(None))[0])
c("putchar", lambda: (L.putchar(65), L.putchar(10), L.fflush(None))[0])
c("write(1)", lambda: L.write(1, b"raw-write\n", 10))
c("write bad fd", lambda: (L.write(99, b"x", 1), get_errno())[0])
c("puts", lambda: (L.puts(b"puts-line"), L.fflush(None))[0])
c(
    "fputs stderr",
    lambda: (
        (L.fputs(b"fputs-err\n", c_void_p.in_dll(L, "stderr")), L.fflush(None))[0]
        if hasattr(L, "stderr")
        else "no stderr symbol"
    ),
)
c("fprintf stderr symbol", lambda: [hasattr(L, "stderr"), hasattr(L, "stdout")])
# char/short/signed returns through function pointers; arguments widths
for sig, vals in [
    ((c_int8,), [-1, 127, 200]),
    ((c_uint8,), [255, 256, -1]),
    ((c_int16,), [-1, 32768]),
    ((c_uint16,), [65535, 65536]),
]:
    c("ident %s" % sig[0].__name__, lambda: [sig[0](v).value for v in vals])
# structs by value (passed to a C function that takes them? none in libc). use callbacks: CFUNCTYPE structs back to C is covered below.
for rt, at, vals in [
    (c_int, c_int, (7, -7)),
    (c_double, c_double, (1.5, -2.5)),
    (c_float, c_float, (1.5,)),
    (c_int64, c_int64, (2**40, -(2**40))),
    (c_uint64, c_uint64, (2**63,)),
    (c_void_p, c_void_p, (0, 1234, 2**31, 2**32 - 1)),
    (c_char_p, c_char_p, (None, b"x")),
    (c_int8, c_int8, (-3,)),
    (c_uint8, c_uint8, (250,)),
    (c_int16, c_int16, (-300,)),
    (c_uint16, c_uint16, (60000,)),
    (c_bool, c_bool, (True, False)),
    (c_longdouble, c_longdouble, (1.5, -2.5)),
    (c_char, c_char, (b"x",)),
    (c_wchar, c_wchar, ("x", "中")),
    (c_ulong, c_ulong, (2**32 - 1,)),
    (c_long, c_long, (-(2**31),)),
    (c_size_t, c_size_t, (2**32 - 1,)),
    (c_ssize_t, c_ssize_t, (-1,)),
    (c_wchar_p, c_wchar_p, (None, "wide中")),
]:
    CB = CFUNCTYPE(rt, at)
    for v in vals:
        cb = CB(lambda x: x)
        c("callback ident %s %r (python-side call)" % (at.__name__, v), lambda: cb(v))
CBX = CFUNCTYPE(c_int, c_int)
CPYTYPES = {}
# qsort / bsearch comparators called by libc
for n in (0, 1, 2, 3, 10, 100, 1000):
    arr = (c_int * max(n, 1))(*[(i * 7919) % 1009 - 500 for i in range(n)])
    calls = []

    def cmp(a, b, calls=calls):
        calls.append(1)
        return (a[0] > b[0]) - (a[0] < b[0])

    C = CFUNCTYPE(c_int, POINTER(c_int), POINTER(c_int))
    cmpf = C(cmp)
    c(
        "qsort n=%d" % n,
        lambda: (L.qsort(arr, n, sizeof(c_int), cmpf), list(arr[:n]) == sorted(arr[:n]), len(calls) > 0 or n < 2)[1:],
    )
arr = (c_int * 10)(*range(0, 100, 10))
key = c_int(0)
C = CFUNCTYPE(c_int, POINTER(c_int), POINTER(c_int))
L.bsearch.restype = c_void_p
for k in (0, 10, 50, 90, 95, -5, 100):
    key = c_int(k)
    c(
        "bsearch %d" % k,
        lambda: (lambda r: None if r is None else (r - addressof(arr)) // 4)(
            L.bsearch(byref(key), arr, 10, 4, C(lambda a, b: (a[0] > b[0]) - (a[0] < b[0])))
        ),
    )
dcmp = CFUNCTYPE(c_int, POINTER(c_double), POINTER(c_double))
darr = (c_double * 5)(3.5, -1.5, 2.25, 0.0, 9.75)
c("qsort doubles", lambda: (L.qsort(darr, 5, 8, dcmp(lambda a, b: (a[0] > b[0]) - (a[0] < b[0]))), list(darr))[1])
c("qsort comparator raises", lambda: (L.qsort((c_int * 3)(3, 2, 1), 3, 4, C(lambda a, b: 1 / 0)), "returned")[1])
c("qsort comparator returns None", lambda: (L.qsort((c_int * 3)(3, 2, 1), 3, 4, C(lambda a, b: None)), "returned")[1])
c(
    "qsort comparator returns big",
    lambda: (lambda a: (L.qsort(a, 3, 4, C(lambda x, y: 2**40 if x[0] > y[0] else -(2**40))), list(a))[1])(
        (c_int * 3)(3, 2, 1)
    ),
)
c(
    "qsort comparator returns float",
    lambda: (lambda a: (L.qsort(a, 3, 4, C(lambda x, y: 1.5 if x[0] > y[0] else -1.5)), list(a))[1])(
        (c_int * 3)(3, 2, 1)
    ),
)
c("qsort comparator returns str", lambda: (L.qsort((c_int * 3)(3, 2, 1), 3, 4, C(lambda a, b: "x")), "returned")[1])
c("qsort comparator wrong arity", lambda: (L.qsort((c_int * 3)(3, 2, 1), 3, 4, C(lambda a: 0)), "returned")[1])
c("qsort NULL comparator", lambda: (L.qsort((c_int * 3)(3, 2, 1), 3, 4, None), "returned")[1])
# callbacks of every class called by C through a function pointer: use qsort_r? use a tiny trampoline via ctypes: call callback pointers from C via bsearch with different value types.
# Calling a CFUNCTYPE object from Python goes through ffi_call too:
for rt, at, v in [
    (c_int, c_int, 5),
    (c_double, c_double, 2.5),
    (c_float, c_float, 0.5),
    (c_int64, c_int64, -(2**50)),
    (c_uint8, c_uint8, 255),
    (c_int8, c_int8, -128),
    (c_int16, c_int16, -2),
    (c_uint16, c_uint16, 9),
    (c_void_p, c_void_p, 12345),
    (c_char_p, c_char_p, b"hi"),
    (c_longdouble, c_longdouble, 1.25),
]:
    CB = CFUNCTYPE(rt, at, at)
    cb = CB(lambda a, b: a)
    c("cfunc 2-arg %s" % at.__name__, lambda: cb(v, v))
    ptr = cast(cb, c_void_p).value
    c("cast fnptr %s" % at.__name__, lambda: (ptr > 0, CB(ptr)(v, v)))
cb = CFUNCTYPE(None)(lambda: None)
c("void cb", lambda: cb())
c("void cb via ptr", lambda: CFUNCTYPE(None)(cast(cb, c_void_p).value)())
cb = CFUNCTYPE(c_int, *([c_int] * 12))(lambda *a: sum(a))
c("12-arg cb", lambda: cb(*range(12)))
cb = CFUNCTYPE(c_double, *([c_double] * 12))(lambda *a: sum(a))
c("12 double-arg cb", lambda: cb(*[0.5 * i for i in range(12)]))
cb = CFUNCTYPE(c_int64, c_int, c_int64, c_double, c_float, c_int8, c_uint16, c_void_p, c_char_p, c_int64)(
    lambda *a: int(sum(x if isinstance(x, (int, float)) else 0 for x in a[:6])) + len(a)
)
c("mixed cb", lambda: cb(1, 2, 3.5, 4.5, 5, 6, 7, b"x", 9))
cb = CFUNCTYPE(c_int, c_int)(lambda a: a + 1)
c("cb too many args", lambda: cb(1, 2))
c("cb too few args", lambda: cb())
c("cb wrong type arg", lambda: cb("x"))
c("cb float for int", lambda: cb(1.5))
c("cb None", lambda: cb(None))
c("cb big int", lambda: cb(2**40))
c("cb neg", lambda: cb(-(2**31)))
c("cb 2**31", lambda: cb(2**31))
cb = CFUNCTYPE(c_int, c_int)(lambda a: 1 / 0)
c("cb raises (python call)", lambda: cb(1))
cb = CFUNCTYPE(c_int, c_int)(lambda a: "x")
c("cb returns str", lambda: cb(1))
cb = CFUNCTYPE(c_int, c_int)(lambda a: 2**40)
c("cb returns 2**40", lambda: cb(1))
cb = CFUNCTYPE(c_int, c_int)(lambda a: -1)
c("cb returns -1", lambda: cb(1))
cb = CFUNCTYPE(c_uint, c_int)(lambda a: -1)
c("cb returns -1 as uint", lambda: cb(1))
cb = CFUNCTYPE(c_int8, c_int)(lambda a: 300)
c("cb returns 300 as int8", lambda: cb(1))
cb = CFUNCTYPE(c_bool, c_int)(lambda a: 5)
c("cb returns 5 as bool", lambda: cb(1))
cb = CFUNCTYPE(c_char, c_int)(lambda a: b"z")
c("cb returns char", lambda: cb(1))
cb = CFUNCTYPE(c_double, c_int)(lambda a: 1)
c("cb returns int as double", lambda: cb(1))
cb = CFUNCTYPE(c_float, c_int)(lambda a: 0.1)
c("cb returns 0.1 as float", lambda: cb(1))
cb = CFUNCTYPE(c_void_p, c_int)(lambda a: None)
c("cb returns None void_p", lambda: cb(1))
cb = CFUNCTYPE(c_char_p, c_int)(lambda a: b"keep")
c("cb returns bytes char_p (freed?)", lambda: cb(1))
cb = CFUNCTYPE(c_int)(lambda: 5)
c("nested callback", lambda: CFUNCTYPE(c_int)(lambda: cb() + 1)())
c(
    "deeply nested callbacks",
    lambda: (lambda f: f(f, 50))(lambda f, n: 0 if n == 0 else CFUNCTYPE(c_int)(lambda: f(f, n - 1) + 1)()),
)


# structs
class S1(Structure):
    _fields_ = [("a", c_int)]


class S2(Structure):
    _fields_ = [("a", c_int), ("b", c_int)]


class S3(Structure):
    _fields_ = [("a", c_char), ("b", c_double)]


class S4(Structure):
    _fields_ = [("a", c_int), ("b", c_int), ("c", c_int), ("d", c_int)]


class S5(Structure):
    _fields_ = [("a", c_int64), ("b", c_int64), ("c", c_int64), ("d", c_int64), ("e", c_int64)]


class SF(Structure):
    _fields_ = [("x", c_float), ("y", c_float)]


class SD(Structure):
    _fields_ = [("x", c_double), ("y", c_double)]


class SN(Structure):
    _fields_ = [("s", S2), ("t", S1), ("d", c_double)]


class SA(Structure):
    _fields_ = [("arr", c_int * 3), ("c", c_char)]


class SP(Structure):
    _pack_ = 1
    _fields_ = [("c", c_char), ("i", c_int), ("d", c_double)]


class SB(Structure):
    _fields_ = [("a", c_int, 3), ("b", c_int, 5), ("c", c_uint, 24)]


class SLD(Structure):
    _fields_ = [("x", c_longdouble)]


class SE(Structure):
    _fields_ = []


class U1(Union):
    _fields_ = [("i", c_int), ("f", c_float), ("d", c_double), ("b", c_char * 8)]


class SU(Structure):
    _fields_ = [("u", U1), ("t", c_int)]


for S, vals in [
    (S1, (5,)),
    (S2, (1, 2)),
    (S3, (b"x", 2.5)),
    (S4, (1, 2, 3, 4)),
    (S5, (1, 2, 3, 4, 5)),
    (SF, (1.5, 2.5)),
    (SD, (1.5, 2.5)),
    (SN, (S2(1, 2), S1(3), 4.5)),
    (SA, ((c_int * 3)(1, 2, 3), b"z")),
    (SP, (b"p", 7, 8.5)),
    (SB, (3, 7, 100)),
    (SLD, (1.25,)),
    (SU, (U1(i=7), 9)),
    (SE, ()),
]:
    s = S(*vals)
    c("sizeof/alignment %s" % S.__name__, lambda: (sizeof(S), alignment(S)))
    CB = CFUNCTYPE(S, S)
    cb = CB(lambda x: x)
    c(
        "struct cb ident %s" % S.__name__,
        lambda: (
            [
                getattr(cb(s), f[0])
                if not isinstance(getattr(cb(s), f[0]), (Structure, Union, Array))
                else bytes(cb(s))
                for f in S._fields_
            ][:6]
            if S._fields_
            else "empty"
        ),
    )
    CB2 = CFUNCTYPE(c_int, S, c_int)
    cb2 = CB2(lambda x, k: k + 1)
    c("struct arg + int %s" % S.__name__, lambda: cb2(s, 5))
    CB3 = CFUNCTYPE(None, S, S, S)
    got = []
    cb3 = CB3(lambda a, b, c_: got.append(bytes(a) == bytes(s) and bytes(c_) == bytes(s)))
    c("struct x3 cb %s" % S.__name__, lambda: (cb3(s, s, s), got)[1])
    c(
        "struct byref roundtrip %s" % S.__name__,
        lambda: (lambda d: (memmove(byref(d), byref(s), sizeof(S)), bytes(d) == bytes(s))[1])(S()),
    )
    c("struct from_buffer_copy %s" % S.__name__, lambda: bytes(S.from_buffer_copy(bytes(s))) == bytes(s))
    c("struct ptr cb %s" % S.__name__, lambda: CFUNCTYPE(c_int, POINTER(S))(lambda p: sizeof(p.contents))(pointer(s)))
    c("struct cb returning other struct %s" % S.__name__, lambda: bytes(CFUNCTYPE(S)(lambda: s)()) == bytes(s))
    c(
        "struct 3-arg order %s" % S.__name__,
        lambda: CFUNCTYPE(c_int, c_int, S, c_double, S, c_char)(lambda a, b, c_, d, e: a + int(c_))(1, s, 2.5, s, b"x"),
    )
for n in [1, 2, 3, 4, 7, 8, 9, 15, 16, 17, 31, 32, 33, 64, 100, 1000, 4096, 65536]:

    class SBig(Structure):
        _fields_ = [("a", c_char * n)]

    sb = SBig(b"q" * n)
    cb = CFUNCTYPE(SBig, SBig)(lambda x: x)
    c("struct char[%d] cb ident" % n, lambda: cb(sb).a == sb.a)
    cb = CFUNCTYPE(c_int, SBig, c_int)(lambda x, k: len(x.a) + k)
    c("struct char[%d] by value arg" % n, lambda: cb(sb, 1))
for n in [1, 2, 3, 4, 5, 8, 16, 33]:

    class SDn(Structure):
        _fields_ = [("a", c_double * n)]

    sd = SDn(*[i + 0.5 for i in range(n)])
    cb = CFUNCTYPE(SDn, SDn)(lambda x: x)
    c("struct double[%d] cb ident" % n, lambda: list(cb(sd).a))

    class SIn(Structure):
        _fields_ = [("a", c_int * n), ("f", c_float)]

    si = SIn((c_int * n)(*range(n)), 1.5)
    cb = CFUNCTYPE(SIn, SIn)(lambda x: x)
    c("struct int[%d]+float cb ident" % n, lambda: (list(cb(si).a), cb(si).f))
# arrays, pointers, strings
c("string_at", lambda: (string_at(b"hello", 3), string_at(b"hello"), string_at(b"", 0)))
c("wstring_at", lambda: (wstring_at("hello中", 6), wstring_at("hi")))
c("memmove", lambda: (lambda a, b: (memmove(a, b"1234", 4), a.raw[:4])[1])(create_string_buffer(8), None))
c("memset", lambda: (lambda a: (memset(a, 0x41, 3), a.raw[:4])[1])(create_string_buffer(8)))
c("addressof/cast", lambda: (lambda a: cast(a, c_void_p).value == addressof(a))(create_string_buffer(8)))
c("pointer arith", lambda: (lambda a: cast(addressof(a) + 4, POINTER(c_int))[0])((c_int * 4)(1, 2, 3, 4)))
c("POINTER(None)", lambda: POINTER(c_int)().contents)
c("c_char_p.value NULL", lambda: c_char_p(None).value)
c("c_void_p NULL", lambda: c_void_p(None).value)
c("c_void_p -1", lambda: c_void_p(-1).value)
c("c_void_p 2**32", lambda: c_void_p(2**32).value)
c("c_void_p 2**64", lambda: c_void_p(2**64).value)
c("c_void_p str", lambda: c_void_p("x"))
c("c_char_p int", lambda: c_char_p(5))
c("c_char_p str", lambda: c_char_p("x"))
c("c_wchar_p bytes", lambda: c_wchar_p(b"x"))
c("create_string_buffer neg", lambda: create_string_buffer(-1))
c("create_string_buffer huge", lambda: len(create_string_buffer(2**20).raw))
c("(c_int * -1)", lambda: c_int * -1)
c("(c_int * 2**40)", lambda: (c_int * 2**40)())
c("(c_int * 2**31)", lambda: (c_int * 2**31)())
c("(c_char * 2**30)", lambda: len((c_char * 2**30)()))
c("(c_char * 2**32)", lambda: len((c_char * 2**32)()))
c("array index oob", lambda: (c_int * 3)()[3])
c("array neg index", lambda: (c_int * 3)(1, 2, 3)[-1])
c("array slice", lambda: (c_int * 5)(1, 2, 3, 4, 5)[1:4])
c("array too many init", lambda: (c_int * 2)(1, 2, 3))
c("array init wrong type", lambda: (c_int * 2)("a"))
c("c_int init float", lambda: c_int(1.5))
c("c_int init str", lambda: c_int("1"))
c("c_float init str", lambda: c_float("x"))
c("c_double init int", lambda: c_double(3))
c("c_bool init", lambda: [c_bool(x).value for x in (0, 1, 2, -1, 0.0, "", "a", None, [], [0])])
c("c_char init", lambda: [c_char(x).value for x in (b"a", 97)] if True else 0)
c("c_char init long", lambda: c_char(b"ab"))
c("c_wchar init", lambda: c_wchar("ab"))
c(
    "sizeof table",
    lambda: [
        (T.__name__, sizeof(T), alignment(T))
        for T in (
            c_bool,
            c_char,
            c_wchar,
            c_byte,
            c_ubyte,
            c_short,
            c_ushort,
            c_int,
            c_uint,
            c_long,
            c_ulong,
            c_longlong,
            c_ulonglong,
            c_float,
            c_double,
            c_longdouble,
            c_size_t,
            c_ssize_t,
            c_void_p,
            c_char_p,
            c_wchar_p,
            c_int8,
            c_int16,
            c_int32,
            c_int64,
            c_time_t if hasattr(ctypes, "c_time_t") else c_long,
        )
    ],
)
c("c_longdouble value", lambda: [c_longdouble(x).value for x in (1.5, 1e300, float("inf"), -0.0, 1e-300, 0.1)])
c(
    "c_longdouble arith through sqrtl",
    lambda: (setattr(L.sqrtl, "restype", c_longdouble), setattr(L.sqrtl, "argtypes", [c_longdouble]), L.sqrtl(2.0))[2],
)
c("c_longdouble ptr bytes", lambda: bytes(c_longdouble(1.5)).hex())
c("c_float rounding", lambda: [c_float(x).value for x in (0.1, 16777217, 1e39, -1e39, 1e-46, float("nan"))])
c("c_double nan bytes", lambda: bytes(c_double(float("nan"))).hex())
c(
    "byteorder ints",
    lambda: [
        bytes(T(1)).hex()
        for T in (c_int16.__ctype_be__, c_int32.__ctype_be__, c_int64.__ctype_be__, c_int16.__ctype_le__)
    ],
)
c(
    "BigEndianStructure",
    lambda: bytes(type("B", (BigEndianStructure,), {"_fields_": [("a", c_int32), ("b", c_int16)]})(1, 2)).hex(),
)
c(
    "LittleEndianUnion",
    lambda: (
        type("LU", (LittleEndianUnion,), {"_fields_": [("a", c_int32), ("b", c_int16)]}).__name__
        if hasattr(ctypes, "LittleEndianUnion")
        else "n/a"
    ),
)
c("in_dll int", lambda: c_int.in_dll(L, "errno") if False else "skip")
c("get_errno/set_errno", lambda: (set_errno(5), get_errno(), set_errno(0))[1])
c("errno from libc", lambda: (L.close(9999), get_errno())[1])
c("use_errno CDLL", lambda: (lambda l: (l.close(9999), get_errno(), ctypes.get_errno()))(CDLL(None, use_errno=True)))
c("use_errno CDLL set", lambda: (lambda l: (set_errno(7), l.close(9999), get_errno())[2])(CDLL(None, use_errno=True)))
c("CDLL names", lambda: [CDLL(None)._name, CDLL(None)._handle > 0])
c("CDLL missing", lambda: CDLL("libdoesnotexist.so"))
c("CDLL missing func", lambda: L.no_such_function_xyz)
c("CDLL getitem missing", lambda: L["no_such_function_xyz"])
c("CDLL libc.so.6", lambda: CDLL("libc.so.6"))
c("CDLL libm", lambda: CDLL("libm.so.6"))
c("util.find_library c", lambda: __import__("ctypes.util").util.find_library("c"))
c("util.find_library m", lambda: __import__("ctypes.util").util.find_library("m"))
c("pythonapi", lambda: (pythonapi.Py_GetVersion.restype, pythonapi._name))
c(
    "pythonapi Py_GetVersion",
    lambda: (setattr(pythonapi.Py_GetVersion, "restype", c_char_p), pythonapi.Py_GetVersion()[:4])[1],
)
c(
    "pythonapi PyLong_FromLong",
    lambda: (
        setattr(pythonapi.PyLong_FromLong, "restype", py_object),
        pythonapi.PyLong_FromLong(5),
        pythonapi.PyLong_FromLong(5, 6),
        pythonapi.PyLong_FromLong(),
    )[1:],
)
c(
    "py_object roundtrip",
    lambda: (
        lambda o: (
            setattr(pythonapi.Py_IncRef, "argtypes", [py_object]),
            pythonapi.Py_IncRef(o),
            py_object(o).value is o,
        )[2]
    )([1]),
)
c(
    "PyOS_double_to_string",
    lambda: (
        lambda f: (
            setattr(f, "restype", c_char_p),
            setattr(f, "argtypes", [c_double, c_char, c_int, c_int, c_void_p]),
            f(1.5, b"r", 0, 0, None),
        )[2]
    )(pythonapi.PyOS_double_to_string),
)
c(
    "PyOS_snprintf",
    lambda: (lambda b: (pythonapi.PyOS_snprintf(b, 64, b"%d %s", 5, b"x"), b.value)[1])(create_string_buffer(64)),
)
c("Py_AtExit", lambda: pythonapi.Py_AtExit(CFUNCTYPE(None)(lambda: None)))
c("CFUNCTYPE flags", lambda: [CFUNCTYPE(c_int, c_int, use_errno=True) is not None, PYFUNCTYPE(c_int)(lambda: 3)()])
c("WINFUNCTYPE", lambda: hasattr(ctypes, "WINFUNCTYPE"))
c("CFUNCTYPE too many types", lambda: CFUNCTYPE(c_int, *([c_int] * 100))(lambda *a: len(a))(*range(100)))
c("CFUNCTYPE 1000 args", lambda: CFUNCTYPE(c_int, *([c_int] * 1000))(lambda *a: len(a))(*range(1000)))
c("CFUNCTYPE 20 double args", lambda: CFUNCTYPE(c_double, *([c_double] * 20))(lambda *a: sum(a))(*[1.5] * 20))
c("CFUNCTYPE 20 int64 args", lambda: CFUNCTYPE(c_int64, *([c_int64] * 20))(lambda *a: sum(a))(*[2**40] * 20))
c(
    "CFUNCTYPE 9 args mixed",
    lambda: CFUNCTYPE(c_double, c_int, c_double, c_int, c_double, c_int, c_double, c_int, c_double, c_int)(
        lambda *a: sum(a)
    )(1, 2.5, 3, 4.5, 5, 6.5, 7, 8.5, 9),
)
c(
    "CFUNCTYPE struct+float",
    lambda: CFUNCTYPE(c_double, S2, c_float, c_double)(lambda s, f, d: s.a + s.b + f + d)(S2(1, 2), 1.5, 2.5),
)
c(
    "CFUNCTYPE returns struct of 2 doubles",
    lambda: (lambda r: (r.x, r.y))(CFUNCTYPE(SD, c_double)(lambda v: SD(v, -v))(2.5)),
)
c(
    "CFUNCTYPE returns large struct",
    lambda: list(
        CFUNCTYPE(S5)(lambda: S5(1, 2, 3, 4, 5))().__class__.__dict__ and [CFUNCTYPE(S5)(lambda: S5(1, 2, 3, 4, 5))().e]
    ),
)


# many closures
def many(n):
    keep = []
    for i in range(n):
        cb = CFUNCTYPE(c_int, c_int)(lambda a, i=i: a + i)
        keep.append(cb)
    r = [keep[0](1), keep[-1](1), len({cast(k, c_void_p).value for k in keep})]
    del keep, cb
    return r


c("1000 closures", lambda: many(1000))
c("10000 closures", lambda: many(10000))
c("10000 closures create/free", lambda: [CFUNCTYPE(c_int, c_int)(lambda a: a)(1) for _ in range(10000)][-1])
c(
    "closure ptr reuse",
    lambda: (lambda a: (a, [cast(CFUNCTYPE(None)(lambda: None), c_void_p).value for _ in range(3)]))(1)[0],
)


def slots():
    out = []
    for _ in range(3):
        k = [CFUNCTYPE(None)(lambda: None) for _ in range(5)]
        out.append(sorted(cast(x, c_void_p).value for x in k)[0] - sorted(cast(x, c_void_p).value for x in k)[0])
        del k
    return out


c("closure alloc/free cycle", slots)
c(
    "callback after del",
    lambda: (lambda cb: (lambda p: (del_ := None, CFUNCTYPE(c_int)(p) is not None)[1])(cast(cb, c_void_p).value))(
        CFUNCTYPE(c_int)(lambda: 1)
    ),
)
c("callback keeps arg alive", lambda: CFUNCTYPE(c_int, py_object)(lambda o: len(o))(py_object([1, 2, 3])))
c("py_object arg", lambda: CFUNCTYPE(py_object, py_object)(lambda o: o + [4])(py_object([1, 2, 3])))
c("py_object NULL", lambda: py_object().value)
c("callback c_char_p arg", lambda: CFUNCTYPE(c_int, c_char_p)(lambda s: len(s))(b"hello"))
c("callback c_char_p NULL arg", lambda: CFUNCTYPE(c_int, c_char_p)(lambda s: -1 if s is None else 0)(None))
c("callback c_wchar_p arg", lambda: CFUNCTYPE(c_int, c_wchar_p)(lambda s: len(s))("he中"))
c("callback POINTER(c_int) arg", lambda: CFUNCTYPE(c_int, POINTER(c_int))(lambda p: p[0] + p[1])((c_int * 2)(3, 4)))
c(
    "callback POINTER(POINTER)",
    lambda: CFUNCTYPE(c_int, POINTER(POINTER(c_int)))(lambda pp: pp[0][0])(pointer(pointer(c_int(9)))),
)
c("callback void_p arg", lambda: CFUNCTYPE(c_int, c_void_p)(lambda p: 0 if p is None else 1)(None))
c("callback ARRAY arg", lambda: CFUNCTYPE(c_int, c_int * 3)(lambda a: 1) if False else "n/a")
c("callback callback arg", lambda: CFUNCTYPE(c_int, CFUNCTYPE(c_int))(lambda f: f() + 1)(CFUNCTYPE(c_int)(lambda: 41)))
c("exception in callback prints & returns", lambda: CFUNCTYPE(c_int)(lambda: int("x"))())
c(
    "sys.unraisablehook in callback",
    lambda: (
        lambda hits: (
            setattr(sys, "unraisablehook", lambda u: hits.append(type(u.exc_value).__name__)),
            CFUNCTYPE(c_int)(lambda: 1 / 0)(),
            hits,
        )
    )([])[2],
)
sys.unraisablehook = sys.__unraisablehook__
c("callback returning wrong type exception", lambda: CFUNCTYPE(c_int, c_int)(lambda a: (a,))(1))
c(
    "KeyboardInterrupt in callback",
    lambda: (lambda: CFUNCTYPE(c_int)(lambda: (_ for _ in ()).throw(KeyboardInterrupt()))())(),
)
c("SystemExit in callback", lambda: CFUNCTYPE(c_int)(lambda: (_ for _ in ()).throw(SystemExit(3)))())
c(
    "errcheck",
    lambda: (
        lambda f: (
            setattr(f, "errcheck", lambda r, fn, a: r * 2),
            setattr(f, "restype", c_int),
            setattr(f, "argtypes", [c_int]),
            f(-4),
        )[3]
    )(CDLL(None).abs),
)
c("paramflags", lambda: (lambda proto: proto(("abs", CDLL(None)), ((1, "x", 0),))(x=-3))(CFUNCTYPE(c_int, c_int)))
c(
    "from_param custom",
    lambda: (
        lambda f: (
            setattr(f, "argtypes", [type("P", (), {"from_param": staticmethod(lambda v: c_int(v * 2))})]),
            setattr(f, "restype", c_int),
            f(5),
        )[2]
    )(CDLL(None).abs),
)
c(
    "argtypes subclass int",
    lambda: (lambda f: (setattr(f, "argtypes", [c_int]), setattr(f, "restype", c_int), f(True))[2])(CDLL(None).abs),
)
c(
    "restype subclass",
    lambda: (lambda f: (setattr(f, "restype", type("MyInt", (c_int,), {})), f(-5))[1])(CDLL(None).abs),
)
c("restype callable", lambda: (lambda f: (setattr(f, "restype", lambda x: x * 3), f(-5))[1])(CDLL(None).abs))
c(
    "restype c_char_p",
    lambda: (lambda f: (setattr(f, "restype", c_char_p), f(b"x") if False else "n/a")[1])(CDLL(None).abs),
)
c("sizeof(c_int * 3)", lambda: sizeof(c_int * 3))
c("ctypes.wintypes", lambda: __import__("ctypes.wintypes").wintypes.DWORD)
c("ctypes.util", lambda: __import__("ctypes.util").util.__name__)
c(
    "call with 8 int args via snprintf",
    lambda: (L.snprintf(buf, 256, b"%d%d%d%d%d%d%d", 1, 2, 3, 4, 5, 6, 7), buf.value),
)
c("call with 20 int args via snprintf", lambda: (L.snprintf(buf, 256, b"%d" * 20, *range(20)), buf.value))
c("call with 40 args", lambda: (L.snprintf(buf, 256, b"%d" * 40, *range(40)), buf.value))
c("call with 300 args", lambda: (L.snprintf(buf, 1024, b"%d" * 300, *range(300)), len(buf.value) if False else "ok"))
c(
    "call with 20 double args",
    lambda: (L.snprintf(buf, 256, b"%.0f" * 20, *[c_double(i) for i in range(20)]), buf.value),
)
c(
    "call with mixed 20",
    lambda: (L.snprintf(buf, 256, b"%d%.0f" * 10, *[x for i in range(10) for x in (i, c_double(i))]), buf.value),
)
c("call with int64 args", lambda: (L.snprintf(buf, 256, b"%lld %lld", c_int64(2**62), c_int64(-(2**62))), buf.value))
c("call with c_int8 arg", lambda: (L.snprintf(buf, 256, b"%d", c_int8(-5)), buf.value))
c("call with c_uint8 arg", lambda: (L.snprintf(buf, 256, b"%d", c_uint8(250)), buf.value))
c("call with c_float arg (variadic)", lambda: (L.snprintf(buf, 256, b"%f", c_float(1.5)), buf.value))
c("call with c_bool arg", lambda: (L.snprintf(buf, 256, b"%d", c_bool(True)), buf.value))
c("call with c_char arg", lambda: (L.snprintf(buf, 256, b"%c", c_char(b"q")), buf.value))
c("call with c_wchar_p", lambda: (L.snprintf(buf, 256, b"%ls", c_wchar_p("w中")), buf.value))
c("call with structs by value (snprintf)", lambda: (L.snprintf(buf, 256, b"%d", S1(5)), buf.value))
c("call with byref", lambda: L.snprintf(buf, 256, b"%d", byref(c_int(5))) > 0)
c("call with array", lambda: (L.snprintf(buf, 256, b"%s", (c_char * 4)(b"a", b"b", b"c", b"\0")), buf.value))
c("call with pointer(c_int)", lambda: L.snprintf(buf, 256, b"%d", pointer(c_int(5))) > 0)
c("call with py_object", lambda: L.snprintf(buf, 256, b"%d", py_object(5)) > 0)
c("call with None", lambda: (L.snprintf(buf, 256, b"%s", None), buf.value))
c("call with str (utf-16?)", lambda: (L.snprintf(buf, 256, b"%ls", "wide"), buf.value))
c("call with list", lambda: L.snprintf(buf, 256, b"%d", [1]))
c("call with dict", lambda: L.snprintf(buf, 256, b"%d", {}))
c("call with complex", lambda: L.snprintf(buf, 256, b"%d", 1j))
c("call with big int 2**64", lambda: L.snprintf(buf, 256, b"%d", 2**64))
c("call with float 1e300", lambda: L.snprintf(buf, 256, b"%d", 1e300))
c("call lstat-like struct out", lambda: (lambda st: (L.stat(b"/", st), get_errno())[0])(create_string_buffer(256)))
c("call with kwargs", lambda: L.abs(x=1))
c("call by ordinal", lambda: L[1])
c("attribute names", lambda: [L.abs.__name__, repr(L.abs)[:20]])
c("func pointer equality", lambda: L.abs is L.abs)
c("CFUNCTYPE from address of C func", lambda: CFUNCTYPE(c_int, c_int)(cast(L.abs, c_void_p).value)(-3))
c(
    "CFUNCTYPE from addr of C func varargs",
    lambda: CFUNCTYPE(c_int, c_char_p, c_size_t, c_char_p, c_int)(cast(L.snprintf, c_void_p).value)(buf, 256, b"%d", 3),
)
c("function pointer from qsort via cast", lambda: cast(L.qsort, c_void_p).value > 0)
