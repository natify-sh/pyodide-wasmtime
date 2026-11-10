# ctypes calls (ffi_call_js): what a JavaScript `wasmTable.get(fn)(...args)` tolerates (the .expected file is what Pyodide prints)
import ctypes as c

libc = c.CDLL(None)
py = c.pythonapi


class div_t(c.Structure):
    _fields_ = [("quot", c.c_int), ("rem", c.c_int)]


class in_addr(c.Structure):
    _fields_ = [("s", c.c_uint32)]


def show(name, fn):
    try:
        print(name, fn())
    except BaseException as e:
        print(name, "EXC", type(e).__name__)


libc.div.restype, libc.div.argtypes = div_t, [c.c_int, c.c_int]
show("struct result", lambda: (lambda r: (r.quot, r.rem))(libc.div(7, 2)))
py.PyOS_double_to_string.restype = c.c_char_p
py.PyOS_double_to_string.argtypes = [c.c_double, c.c_char, c.c_int, c.c_int, c.c_void_p]
show("5 args with a double", lambda: py.PyOS_double_to_string(1.5, b"r", 0, 0, None))
libc.sqrtl.restype, libc.sqrtl.argtypes = c.c_longdouble, [c.c_longdouble]
show("long double", lambda: libc.sqrtl(16.0))
libc.inet_ntoa.restype, libc.inet_ntoa.argtypes = c.c_char_p, [in_addr]
show("struct argument", lambda: libc.inet_ntoa(in_addr(0x0100007F)))
show("void function, default restype", lambda: libc.free(libc.malloc(16)))
show("srand (void), default restype", lambda: libc.srand(1))
libc.labs.restype, libc.labs.argtypes = c.c_long, [c.c_long]
show("labs", lambda: libc.labs(-5))
libc.llabs.restype, libc.llabs.argtypes = c.c_longlong, [c.c_longlong]
show("llabs", lambda: libc.llabs(-(2**40)))
libc.fabs.restype, libc.fabs.argtypes = c.c_double, [c.c_double]
show("fabs", lambda: libc.fabs(-2.5))
libc.fabsf.restype, libc.fabsf.argtypes = c.c_float, [c.c_float]
show("fabsf", lambda: libc.fabsf(-2.5))
libc.ldexp.restype, libc.ldexp.argtypes = c.c_double, [c.c_double, c.c_int]
show("ldexp", lambda: libc.ldexp(1.5, 4))
buf = c.create_string_buffer(64)
show(
    "snprintf, no argtypes",
    lambda: (libc.snprintf(buf, 64, b"%d|%s|%.3f|%ld", 7, b"x", c.c_double(2.5), 2**31), buf.value),
)
libc.snprintf.argtypes = [c.c_char_p, c.c_size_t, c.c_char_p]  # the rest of the arguments are variadic (nfixedargs)
show(
    "snprintf, variadic",
    lambda: (libc.snprintf(buf, 64, b"%d|%s|%.3f|%ld", 7, b"x", c.c_double(2.5), 2**31), buf.value),
)
show(
    "snprintf, variadic with a long double and a char",
    lambda: (libc.snprintf(buf, 64, b"%c|%Lf", c.c_int(65), c.c_longdouble(1.5)), buf.value),
)
f = py.PyLong_FromLong
f.restype = c.py_object
show("an extra argument", lambda: f(5, 6))
show("a missing argument", lambda: f())
show("more than 8 arguments", lambda: (libc.snprintf(buf, 64, b"%d%d%d%d%d%d%d%d%d%d", *range(10)), buf.value))
libc.memset.restype, libc.memset.argtypes = c.c_void_p, [c.c_void_p, c.c_int, c.c_size_t]
m = c.create_string_buffer(4)
show("memset", lambda: (libc.memset(m, 65, 3) is not None, m.raw))
