# ruff: noqa
# type: ignore
# cffi (the wheel's own _cffi_backend, libffi closures): run with --site <testenv>/site_cffi
import errno
import sys

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


import cffi

ffi = cffi.FFI()
c("version", lambda: cffi.__version__)
lib = ffi.dlopen(None)
ffi.cdef("""
int abs(int); long labs(long); long long llabs(long long); double sqrt(double); float sqrtf(float);
long double sqrtl(long double);
int snprintf(char *, size_t, const char *, ...);
void qsort(void*, size_t, size_t, int(*)(const void*, const void*));
void *bsearch(const void *, const void *, size_t, size_t, int(*)(const void*, const void*));
size_t strlen(const char *);
void *malloc(size_t); void free(void *);
int atoi(const char *);
double atof(const char *);
unsigned char toupper(unsigned char);
double ldexp(double, int);
double fmod(double, double);
""")
for v in [0, 1, -1, 127, 128, 2**31 - 1, -(2**31), 2**31, 2**32, 2**63 - 1, -(2**63)]:
    c("abs %d" % v, lambda: lib.abs(v))
    c("labs %d" % v, lambda: lib.labs(v))
    c("llabs %d" % v, lambda: lib.llabs(v))
for v in [0.0, 1.5, -1.5, 1e300, float("inf"), float("nan"), 2.0, 16.0]:
    c("sqrt %r" % v, lambda: lib.sqrt(v))
    c("sqrtf %r" % v, lambda: lib.sqrtf(v))
    c("sqrtl %r" % v, lambda: float(lib.sqrtl(v)))
c("strlen", lambda: [lib.strlen(x) for x in (b"", b"abc", b"\xff" * 300)])
c("strlen str", lambda: lib.strlen("x"))
c("atoi", lambda: [lib.atoi(x) for x in (b"12", b"-5", b"x", b"99999999999")])
c("atof", lambda: [lib.atof(x) for x in (b"1.5", b"inf", b"1e999")])
c("toupper", lambda: [lib.toupper(x) for x in (97, 0, 255, 256, -1)])
c("ldexp", lambda: [lib.ldexp(1.0, e) for e in (0, 10, 1024, -1075)])
c("fmod", lambda: [lib.fmod(a, b) for a, b in ((5.5, 2.0), (1.0, 0.0), (-5.5, 2.0))])
buf = ffi.new("char[64]")
c("snprintf int", lambda: (lib.snprintf(buf, 64, b"%d %s", ffi.cast("int", 5), b"x"), ffi.string(buf)))
c("snprintf double", lambda: (lib.snprintf(buf, 64, b"%f", ffi.cast("double", 1.5)), ffi.string(buf)))
c(
    "snprintf 10 ints",
    lambda: (lib.snprintf(buf, 64, b"%d" * 10, *[ffi.cast("int", i) for i in range(10)]), ffi.string(buf)),
)
c("snprintf long long", lambda: (lib.snprintf(buf, 64, b"%lld", ffi.cast("long long", 2**40)), ffi.string(buf)))
c(
    "snprintf mixed",
    lambda: (
        lib.snprintf(
            buf, 64, b"%d %f %lld %s", ffi.cast("int", 1), ffi.cast("double", 2.5), ffi.cast("long long", 3), b"s"
        ),
        ffi.string(buf),
    ),
)
c("snprintf python int variadic", lambda: lib.snprintf(buf, 64, b"%d", 5))
c("snprintf python float variadic", lambda: lib.snprintf(buf, 64, b"%f", 1.5))
for sig, f, args in [
    ("int(int,int)", lambda a, b: a + b, (3, 4)),
    ("double(double)", lambda x: x * 2, (1.25,)),
    ("float(float)", lambda x: x / 2, (3.0,)),
    ("long long(long long,long long)", lambda a, b: a * b, (1 << 33, 3)),
    ("unsigned long long(unsigned long long)", lambda a: a, (2**64 - 1,)),
    ("signed char(signed char)", lambda a: a, (-128,)),
    ("unsigned char(unsigned char)", lambda a: a, (255,)),
    ("short(short)", lambda a: a, (-32768,)),
    ("void()", lambda: None, ()),
    ("int()", lambda: 7, ()),
    ("char*(char*)", lambda p: p, (b"hi",)),
    ("void*(void*)", lambda p: p, (ffi.NULL,)),
    ("long double(long double)", lambda x: x, (1.5,)),
    ("_Bool(_Bool)", lambda x: x, (True,)),
    ("size_t(size_t)", lambda x: x, (2**32,)),
    ("int(int,int,int,int,int,int,int,int,int,int)", lambda *a: sum(a), tuple(range(10))),
    (
        "double(double,double,double,double,double,double,double,double,double,double)",
        lambda *a: sum(a),
        tuple(float(i) for i in range(10)),
    ),
    ("int(int,double,int,double,int,double,int,double,int)", lambda *a: sum(a), (1, 2.5, 3, 4.5, 5, 6.5, 7, 8.5, 9)),
    ("int(char*,int)", lambda s, n: len(ffi.string(s)) + n, (b"abc", 1)),
]:
    cb = ffi.callback(sig, f)
    c("callback %s" % sig, lambda: cb(*args))
    c(
        "callback via fnptr %s" % sig,
        lambda: (
            ffi.cast(
                sig.replace("(", "(*)(", 1) if False else sig.split("(")[0] + "(*)(" + sig.split("(", 1)[1],
                ffi.cast("void*", cb),
            )(*args)
            if True
            else 0
        ),
    )
ffi.cdef(
    "struct P { int a; int b; }; struct Q { double x; char c; }; struct R { char s[40]; }; struct U { int a; float f; double d; };"
)
c("callback struct arg", lambda: ffi.callback("int(struct P)", lambda p: p.a + p.b)(ffi.new("struct P *", [3, 4])[0]))
c(
    "callback struct arg double",
    lambda: ffi.callback("double(struct Q)", lambda q: q.x)(ffi.new("struct Q *", [2.5, b"x"])[0]),
)
c("callback struct return", lambda: (lambda r: (r.a, r.b))(ffi.callback("struct P(int)", lambda a: [a, a * 2])(5)))
c("callback big struct return", lambda: ffi.string(ffi.callback("struct R(int)", lambda a: [b"x" * 30])(1).s))
c(
    "callback big struct arg",
    lambda: ffi.callback("int(struct R)", lambda r: len(ffi.string(r.s)))(ffi.new("struct R *", [b"y" * 30])[0]),
)
c("callback struct ptr arg", lambda: ffi.callback("int(struct P *)", lambda p: p.a)(ffi.new("struct P *", [9, 0])))
arr = ffi.new("int[]", [5, 3, 9, 1, 4, 8, 2, 7, 6, 0])
c(
    "qsort",
    lambda: (
        lib.qsort(
            arr,
            10,
            4,
            ffi.callback("int(const void*, const void*)", lambda a, b: ffi.cast("int*", a)[0] - ffi.cast("int*", b)[0]),
        ),
        list(arr),
    )[1],
)
c(
    "bsearch",
    lambda: (
        lambda k: ffi.cast(
            "int*",
            lib.bsearch(
                k,
                arr,
                10,
                4,
                ffi.callback(
                    "int(const void*, const void*)", lambda a, b: ffi.cast("int*", a)[0] - ffi.cast("int*", b)[0]
                ),
            ),
        )[0]
    )(ffi.new("int *", 7)),
)
c(
    "qsort raising callback",
    lambda: (lib.qsort(arr, 10, 4, ffi.callback("int(const void*, const void*)", lambda a, b: 1 / 0)), "returned")[1],
)
c(
    "callback with onerror",
    lambda: ffi.callback("int(int)", lambda a: 1 / 0, onerror=lambda e, v, tb: print("onerror", e.__name__) or 5)(1),
)
c("callback error return", lambda: ffi.callback("int(int)", lambda a: 1 / 0, error=-9)(1))
c("callback returns wrong type", lambda: ffi.callback("int(int)", lambda a: "x")(1))
c("callback returns out of range", lambda: ffi.callback("int(int)", lambda a: 2**40)(1))
c("callback returns out of range char", lambda: ffi.callback("signed char(int)", lambda a: 300)(1))
c("callback keeps alive", lambda: [ffi.callback("int(int)", lambda a, i=i: a + i)(1) for i in range(2000)][-1])
c(
    "1000 callbacks alive",
    lambda: (lambda keep: [k(1) for k in keep][-1])(
        [ffi.callback("int(int)", lambda a, i=i: a + i) for i in range(1000)]
    ),
)
c("def_extern missing", lambda: ffi.def_extern)
c("new/cast", lambda: [int(ffi.cast("unsigned char", x)) for x in (-1, 255, 256, 2**32 + 5)])
c("cast int8", lambda: [int(ffi.cast("int8_t", x)) for x in (-1, 127, 128, -129)])
c("cast uint64", lambda: [int(ffi.cast("uint64_t", x)) for x in (-1, 2**64, 2**63)])
c("cast float", lambda: [float(ffi.cast("float", x)) for x in (0.1, 1e39)])
c("cast long double", lambda: float(ffi.cast("long double", 1.5)))
c(
    "sizeof",
    lambda: [
        ffi.sizeof(t)
        for t in (
            "char",
            "short",
            "int",
            "long",
            "long long",
            "float",
            "double",
            "long double",
            "void*",
            "size_t",
            "wchar_t",
            "struct P",
            "struct Q",
            "struct R",
            "struct U",
            "_Bool",
            "int[5]",
        )
    ],
)
c(
    "alignof",
    lambda: [
        ffi.alignof(t)
        for t in ("char", "short", "int", "long", "long long", "double", "long double", "void*", "struct P", "struct Q")
    ],
)
c("offsetof", lambda: [ffi.offsetof("struct Q", f) for f in ("x", "c")])
c("new struct", lambda: (lambda p: (p.a, p.b))(ffi.new("struct P *", {"a": 1, "b": 2})))
c("new array", lambda: list(ffi.new("int[]", 5)))
c("new huge", lambda: ffi.new("char[]", 2**31))
c("buffer", lambda: bytes(ffi.buffer(ffi.new("char[]", b"abc"), 3)))
c("from_buffer", lambda: bytes(ffi.from_buffer(bytearray(b"xyz"))))
c("string", lambda: ffi.string(ffi.new("char[]", b"hello")))
c("unpack", lambda: ffi.unpack(ffi.new("int[]", [1, 2, 3]), 3))
c("memmove", lambda: (lambda b: (ffi.memmove(b, b"abcd", 4), bytes(ffi.buffer(b, 4)))[1])(ffi.new("char[8]")))
c("NULL", lambda: (ffi.NULL, bool(ffi.NULL)))
c("NULL deref", lambda: ffi.cast("int *", 0)[0])
c("gc", lambda: ffi.gc(ffi.new("int *", 3), lambda p: None)[0])
c("addressof", lambda: ffi.addressof(ffi.new("struct P *", [1, 2])[0], "b") is not None)
c("typeof", lambda: str(ffi.typeof("struct P")))
c("getctype", lambda: ffi.getctype("int *"))
c("dlopen missing", lambda: ffi.dlopen("libnotthere.so"))
c("lib missing func", lambda: lib.no_such_fn_xyz)
c("errno", lambda: (ffi.errno, ffi.errno))
c("cdef bad", lambda: ffi.cdef("int ((("))
c("wchar", lambda: ffi.string(ffi.new("wchar_t[]", "wide中")))
c("char16", lambda: ffi.string(ffi.new("char16_t[]", "ab")))
c("bitfield", lambda: (ffi.cdef("struct BF { int a:3; unsigned b:5; };"), ffi.sizeof("struct BF"))[1])
c("union", lambda: (ffi.cdef("union UU { int i; double d; };"), ffi.sizeof("union UU"))[1])
c("enum", lambda: (ffi.cdef("enum EE { A, B = 5 };"), ffi.string(ffi.cast("enum EE", 5)))[1])
c("set_source verify unavailable", lambda: hasattr(ffi, "verify"))
c("abi mode only", lambda: cffi.FFI().dlopen(None).__class__.__name__)
