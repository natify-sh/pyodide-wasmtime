# ruff: noqa
# type: ignore
# EXIT/ABORT/ASSERT: every program a fresh interpreter; compares output and EXIT-STATUS (see the harness header for how each side reports it).
# --- sys.exit(0)
import sys

print("before", flush=True)
sys.exit(0)
# --- sys.exit(1)
import sys

print("before", flush=True)
sys.exit(1)
# --- sys.exit(255)
import sys

print("before", flush=True)
sys.exit(255)
# --- sys.exit(256)
import sys

print("before", flush=True)
sys.exit(256)
# --- sys.exit(257)
import sys

print("before", flush=True)
sys.exit(257)
# --- sys.exit(-1)
import sys

print("before", flush=True)
sys.exit(-1)
# --- sys.exit(-255)
import sys

print("before", flush=True)
sys.exit(-255)
# --- sys.exit(2**31)
import sys

print("before", flush=True)
sys.exit(2**31)
# --- sys.exit(2**32)
import sys

print("before", flush=True)
sys.exit(2**32)
# --- sys.exit(2**63)
import sys

print("before", flush=True)
sys.exit(2**63)
# --- sys.exit(None)
import sys

print("before", flush=True)
sys.exit(None)
# --- sys.exit('msg')
import sys

print("before", flush=True)
sys.exit("msg")
# --- sys.exit('')
import sys

print("before", flush=True)
sys.exit("")
# --- sys.exit(3.5)
import sys

print("before", flush=True)
sys.exit(3.5)
# --- sys.exit(True)
import sys

print("before", flush=True)
sys.exit(True)
# --- sys.exit([1])
import sys

print("before", flush=True)
sys.exit([1])
# --- sys.exit((1,2))
import sys

print("before", flush=True)
sys.exit((1, 2))
# --- sys.exit(b'x')
import sys

print("before", flush=True)
sys.exit(b"x")
# --- sys.exit(object())
import sys

print("before", flush=True)
sys.exit(object())
# --- os._exit(0)
import os

print("before", flush=True)
os._exit(0)
# --- os._exit(1)
import os

print("before", flush=True)
os._exit(1)
# --- os._exit(255)
import os

print("before", flush=True)
os._exit(255)
# --- os._exit(256)
import os

print("before", flush=True)
os._exit(256)
# --- os._exit(-1)
import os

print("before", flush=True)
os._exit(-1)
# --- os._exit(2**31)
import os

print("before", flush=True)
os._exit(2**31)
# --- os._exit('x')
import os

print("before", flush=True)
os._exit("x")
# --- os._exit(None)
import os

print("before", flush=True)
os._exit(None)
# --- os._exit(3.5)
import os

print("before", flush=True)
os._exit(3.5)
# --- os.abort
import os

print("b", flush=True)
os.abort()
# --- raise SystemExit
raise SystemExit(7)
# --- uncaught ValueError
print("b", flush=True)
raise ValueError("x")
# --- uncaught KeyboardInterrupt
raise KeyboardInterrupt
# --- uncaught in thread-less atexit
import atexit

atexit.register(lambda: print("atexit ran", flush=True))
print("end")
# --- atexit + sys.exit(3)
import atexit, sys

atexit.register(lambda: print("atexit ran", flush=True))
sys.exit(3)
# --- atexit raises SystemExit
import atexit, sys


def f():
    raise SystemExit(9)


atexit.register(f)
sys.exit(3)
# --- atexit + os._exit
import atexit, os

atexit.register(lambda: print("atexit ran", flush=True))
os._exit(4)
# --- print no newline then sys.exit
import sys

sys.stdout.write("partial")
sys.exit(2)
# --- print no newline then os._exit
import os, sys

sys.stdout.write("partial")
os._exit(2)
# --- print no newline then ctypes exit
import ctypes, sys

sys.stdout.write("partial")
ctypes.CDLL(None).exit(2)
# --- stderr no newline then os._exit
import os, sys

sys.stderr.write("partial-err")
os._exit(2)
# --- buffered stdout.buffer then os._exit
import os, sys

sys.stdout.buffer.write(b"bin")
os._exit(2)
# --- os.write(1) then os._exit
import os

os.write(1, b"raw\n")
os._exit(2)
# --- open file unflushed then os._exit
import os

f = open("/tmp/dp_x.txt", "w")
f.write("data")
os._exit(2)
# --- C exit(0) atexit not run
import ctypes

libc = ctypes.CDLL(None)
print("b", flush=True)
libc.exit(0)
# --- C exit(0)
import ctypes

ctypes.CDLL(None).exit(0)
# --- C exit(1)
import ctypes

ctypes.CDLL(None).exit(1)
# --- C exit(255)
import ctypes

ctypes.CDLL(None).exit(255)
# --- C exit(256)
import ctypes

ctypes.CDLL(None).exit(256)
# --- C exit(-1)
import ctypes

ctypes.CDLL(None).exit(-1)
# --- C exit(2147483648)
import ctypes

ctypes.CDLL(None).exit(2147483648)
# --- C _exit(5)
import ctypes

ctypes.CDLL(None)._exit(5)
# --- C _Exit(6)
import ctypes

ctypes.CDLL(None)._Exit(6)
# --- C abort
import ctypes

print("b", flush=True)
ctypes.CDLL(None).abort()
# --- C atexit handler then exit
import ctypes

l = ctypes.CDLL(None)
CB = ctypes.CFUNCTYPE(None)
cb = CB(lambda: print("c atexit", flush=True))
l.atexit(cb)
l.exit(3)
# --- C raise SIGABRT
import ctypes

ctypes.CDLL(None)["raise"](6)
# --- C raise SIGSEGV default
import ctypes

ctypes.CDLL(None)["raise"](11)
print("survived")
# --- C raise SIGTERM default
import ctypes

ctypes.CDLL(None)["raise"](15)
print("survived")
# --- os.kill SIGTERM default
import os, signal

os.kill(os.getpid(), signal.SIGTERM)
print("survived")
# --- os.kill SIGKILL
import os, signal

os.kill(os.getpid(), signal.SIGKILL)
print("survived")
# --- os.kill SIGABRT
import os, signal

os.kill(os.getpid(), signal.SIGABRT)
print("survived")
# --- os.kill SIGUSR1 default
import os, signal

os.kill(os.getpid(), signal.SIGUSR1)
print("survived")
# --- os.kill SIGINT default
import os, signal

os.kill(os.getpid(), signal.SIGINT)
print("survived")
# --- os.kill SIGPIPE default
import os, signal

os.kill(os.getpid(), signal.SIGPIPE)
print("survived")
# --- os.kill SIGSTOP
import os, signal

os.kill(os.getpid(), signal.SIGSTOP)
print("survived")
# --- os.kill SIGCONT
import os, signal

os.kill(os.getpid(), signal.SIGCONT)
print("survived")
# --- os.kill SIGCHLD
import os, signal

os.kill(os.getpid(), signal.SIGCHLD)
print("survived")
# --- os.kill SIGSEGV
import os, signal

os.kill(os.getpid(), signal.SIGSEGV)
print("survived")
# --- os.kill SIGFPE
import os, signal

os.kill(os.getpid(), signal.SIGFPE)
print("survived")
# --- raise_signal SIGTERM default
import signal

signal.raise_signal(signal.SIGTERM)
print("survived")
# --- __assert_fail full
import ctypes

ctypes.CDLL(None).__assert_fail(b"x == 1", b"file.c", 42, b"func")
# --- __assert_fail NULLs
import ctypes

ctypes.CDLL(None).__assert_fail(None, None, -7, None)
# --- __assert_fail empty
import ctypes

ctypes.CDLL(None).__assert_fail(b"", b"", 0, b"")
# --- __assert_fail huge line
import ctypes

ctypes.CDLL(None).__assert_fail(b"a", b"f", 2**31, b"g")
# --- __assert_fail long cond
import ctypes

ctypes.CDLL(None).__assert_fail(b"c" * 3000, b"f" * 3000, 1, b"g" * 3000)
# --- __assert_fail non-ascii
import ctypes

ctypes.CDLL(None).__assert_fail("x é中".encode(), b"f", 1, b"\xff\xfe")
# --- __assert_fail bad ptr
import ctypes

ctypes.CDLL(None).__assert_fail(ctypes.c_void_p(0x7FFFFFFF), b"f", 1, b"g")
# --- __assert_fail restype argtypes
import ctypes

f = ctypes.CDLL(None).__assert_fail
f.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p]
f.restype = None
f(b"a", b"b", 3, b"c")
print("survived")
# --- _abort_js via ctypes
import ctypes

ctypes.CDLL(None)._abort_js()
print("survived")
# --- emscripten_force_exit
import ctypes

ctypes.CDLL(None).emscripten_force_exit(3)
print("survived")
# --- emscripten_run_script missing
import ctypes

l = ctypes.CDLL(None)
print(hasattr(l, "emscripten_run_script"))
# --- trap by wasm unreachable (call null fn ptr)
import ctypes

ctypes.CFUNCTYPE(None)(0)()
print("survived")
# --- call bad table index
import ctypes

ctypes.CFUNCTYPE(None)(99999999)()
print("survived")
# --- memory OOB via ctypes
import ctypes

print(ctypes.string_at(0xFFFFFFF0, 4))
# --- deep recursion C stack
import sys

sys.setrecursionlimit(10**7)


def f(n):
    return f(n + 1)


try:
    f(0)
except RecursionError:
    print("RecursionError")
# --- MemoryError huge alloc
try:
    b = bytearray(2**31)
    print("ok", len(b))
except MemoryError:
    print("MemoryError")
# --- MemoryError 5 GiB
try:
    b = bytearray(5 * 2**30)
    print("ok")
except MemoryError:
    print("MemoryError")
# --- faulthandler enable
import faulthandler

faulthandler.enable()
print("ok")
# --- faulthandler dump
import faulthandler, sys

faulthandler.dump_traceback(sys.stdout)
# --- sys.exit in finally
import sys

try:
    sys.exit(3)
finally:
    print("finally ran", flush=True)


# --- exit in __del__ order
class A:
    def __del__(self):
        print("del ran", flush=True)


a = A()
import sys

sys.exit(0)
# --- sys.exit inside except
import sys

try:
    1 / 0
except ZeroDivisionError:
    sys.exit(11)
# --- sys.exit(0) with stdout unflushed text
print("line")
import sys

sys.exit(0)
# --- threading exit
import threading

try:
    t = threading.Thread(target=lambda: print("in thread"))
    t.start()
    t.join()
except RuntimeError as e:
    print("RuntimeError", e)
# --- sys.excepthook custom + uncaught
import sys

sys.excepthook = lambda *a: print("hook", a[0].__name__, flush=True)
raise KeyError("k")
# --- sys.__stderr__ closed then exit
import sys

sys.stderr.close()
sys.exit(3)
# --- stdout closed then print
import sys, os

os.close(1)
try:
    print("x", flush=True)
except OSError as e:
    sys.stderr.write("ERR " + str(e.errno) + "\n")
# --- exit code from sys.exit(-1) C-level
import sys

sys.exit(-1)
