# ruff: noqa
# type: ignore
# FFI calls that crash the guest: one program each (the result is the output and EXIT-STATUS).
# --- NULL pointer deref
from ctypes import *

print(POINTER(c_int)()[0])
# --- string_at NULL
from ctypes import *

print(string_at(None, 4))
# --- string_at 0
from ctypes import *

print(string_at(0, 4))
# --- string_at 1
from ctypes import *

print(string_at(1, 4))
# --- string_at 0xFFFFFFF0
from ctypes import *

print(string_at(0xFFFFFFF0, 4))
# --- string_at 0x7FFFFFFF
from ctypes import *

print(string_at(0x7FFFFFFF, 4))
# --- c_char_p(-1).value
from ctypes import *

print(c_char_p(-1).value)
# --- c_wchar_p(1).value
from ctypes import *

print(repr(c_wchar_p(1).value))
# --- memmove to NULL
from ctypes import *

memmove(0, b"abcd", 4)
print("survived")
# --- memset 0 address
from ctypes import *

memset(0, 65, 4)
print("survived")
# --- call table index 0
from ctypes import *

print(CFUNCTYPE(c_int)(0)())
# --- call table index 99999999
from ctypes import *

print(CFUNCTYPE(c_int)(99999999)())
# --- call data address as function
from ctypes import *

b = create_string_buffer(16)
print(CFUNCTYPE(c_int)(addressof(b))())
# --- call function with wrong signature (abs as void(void))
from ctypes import *

L = CDLL(None)
print(CFUNCTYPE(None)(cast(L.abs, c_void_p).value)())
# --- call function with wrong signature (abs as double(double))
from ctypes import *

L = CDLL(None)
print(CFUNCTYPE(c_double, c_double)(cast(L.abs, c_void_p).value)(1.5))
# --- call function with wrong signature (abs as 3 args)
from ctypes import *

L = CDLL(None)
print(CFUNCTYPE(c_int, c_int, c_int, c_int)(cast(L.abs, c_void_p).value)(1, 2, 3))
# --- call function with wrong signature (abs as int64)
from ctypes import *

L = CDLL(None)
print(CFUNCTYPE(c_int64, c_int64)(cast(L.abs, c_void_p).value)(-5))
# --- call function with wrong signature (fabs as int)
from ctypes import *

L = CDLL(None)
print(CFUNCTYPE(c_int, c_int)(cast(L.fabs, c_void_p).value)(-5))
# --- call with mismatched struct return
from ctypes import *


class S(Structure):
    _fields_ = [("a", c_int), ("b", c_int)]


L = CDLL(None)
print(CFUNCTYPE(S, c_int)(cast(L.abs, c_void_p).value)(-5).a)
# --- free of garbage pointer
from ctypes import *

L = CDLL(None)
L.free(12345)
print("survived")
# --- double free
from ctypes import *

L = CDLL(None)
L.malloc.restype = c_void_p
p = L.malloc(16)
L.free(p)
L.free(p)
print("survived")
# --- strcpy overflow
from ctypes import *

L = CDLL(None)
b = create_string_buffer(2)
L.strcpy(b, b"x" * 100)
print("survived")
# --- memcpy huge
from ctypes import *

L = CDLL(None)
b = create_string_buffer(2)
L.memcpy(b, b, 2**31)
print("survived")
# --- 2**31 stack array
from ctypes import *

print(len((c_char * (2**31))()))
# --- recursion via callbacks 20000 deep
from ctypes import *
import sys

sys.setrecursionlimit(100000)


def f(n):
    return 0 if n == 0 else CFUNCTYPE(c_int)(lambda: f(n - 1) + 1)()


try:
    print(f(20000))
except RecursionError:
    print("RecursionError")
# --- recursion via callbacks 2000 deep
from ctypes import *
import sys

sys.setrecursionlimit(100000)


def f(n):
    return 0 if n == 0 else CFUNCTYPE(c_int)(lambda: f(n - 1) + 1)()


try:
    print(f(2000))
except RecursionError:
    print("RecursionError")
# --- BigInt mismatch int64 arg to double func
from ctypes import *

L = CDLL(None)
print(CFUNCTYPE(c_double, c_int64)(cast(L.sqrt, c_void_p).value)(16))
# --- cb with 1001 args
from ctypes import *

print(CFUNCTYPE(c_int, *([c_int] * 1001))(lambda *a: len(a))(*range(1001)))
# --- struct nested 100 deep
from ctypes import *

T = c_int
for _ in range(100):

    class T(Structure):
        _fields_ = [("a", T)]


print(sizeof(T))
print(CFUNCTYPE(c_int, T)(lambda x: 1)(T()))
# --- cffi missing
try:
    import cffi

    print("cffi", cffi.__version__)
except ImportError as e:
    print("ImportError", e)
# --- llabs default argtypes (int to an i64 parameter)
from ctypes import *

print(CDLL(None).llabs(-5))
# --- llabs c_int arg
from ctypes import *

f = CDLL(None).llabs
f.restype = c_longlong
print(f(c_int(-5)))
# --- llabs restype c_int8 (an i64 result read as 8 bits)
from ctypes import *

f = CDLL(None).llabs
f.argtypes = [c_longlong]
f.restype = c_int8
print(f(-5))
# --- abs restype c_int64 (an i32 result read as 64 bits)
from ctypes import *

f = CDLL(None).abs
f.argtypes = [c_int]
f.restype = c_int64
print(f(-5))
# --- sqrt restype c_float (a double result read as float)
from ctypes import *

f = CDLL(None).sqrt
f.argtypes = [c_double]
f.restype = c_float
print(f(16.0))
# --- sqrtf argtypes c_double
from ctypes import *

f = CDLL(None).sqrtf
f.argtypes = [c_double]
f.restype = c_float
print(f(16.0))
# --- snprintf %u 2**32-1 (a Python int above 2**31 as a variadic argument)
from ctypes import *

buf = create_string_buffer(64)
print(CDLL(None).snprintf(buf, 64, b"%u", 2**32 - 1), buf.value)
