# ruff: noqa
# type: ignore
# One minimal program per NEW difference of docs/DIFF_AUDIT_runtime.md (run each alone: they are deterministic).
# --- N1 mktime year -271821 isdst=1
import time

for tt in [
    (-271821, 6, 15, 12, 0, 0, 0, 0, 1),
    (-271821, 6, 15, 12, 0, 0, 0, 0, 0),
    (-271821, 6, 15, 12, 0, 0, 0, 0, -1),
    (275760, 6, 15, 12, 0, 0, 0, 0, 1),
]:
    try:
        print(tt, time.mktime(tt))
    except OverflowError as e:
        print(tt, "OverflowError", e)
# --- N2 proc_exit status above 125 (os._exit)
import os

os._exit(255)
# --- N2b proc_exit status above 125 (default action of SIGTERM)
import os, signal

os.kill(os.getpid(), signal.SIGTERM)
# --- N2c proc_exit status above 125 (C exit(200))
import ctypes

ctypes.CDLL(None).exit(200)
# --- N3 CPU-time clocks
import time

for cid in (2, 3):
    try:
        print(cid, time.clock_gettime(cid) >= 0, time.clock_getres(cid))
    except OSError as e:
        print(cid, "OSError", e.errno)
try:
    print("process_time", time.process_time() >= 0)
except RuntimeError as e:
    print("process_time RuntimeError", e)
import ctypes

print("clock()", ctypes.CDLL(None).clock() >= 0)
# --- N4 sys.exit(True)
import sys

sys.exit(True)
# --- N5 callback with 3 args that makes a WASI call with an out structure (stack alignment)
import os
from ctypes import CFUNCTYPE, c_int, c_double


def body(*a):
    os.fstat(1)
    return 0


print(CFUNCTYPE(c_int, c_int, c_double, c_int)(body)(1, 0.5, 2), flush=True)
# --- N5b the same with 2 args (aligned by luck)
import os
from ctypes import CFUNCTYPE, c_int, c_double


def body(*a):
    os.fstat(1)
    return 0


print(CFUNCTYPE(c_int, c_int, c_double)(body)(1, 0.5), flush=True)
# --- N6 sys.excepthook is used for an uncaught exception
import sys

sys.excepthook = lambda *a: print("custom hook", a[0].__name__, flush=True)
raise KeyError("k")
# --- N7 stdout buffering when the guest traps
import ctypes

print("printed before the trap")
ctypes.CDLL(None).abort()
# --- N8 HOME, USER, PATH and the helpers that use them
import os

print({k: os.environ.get(k) for k in ("HOME", "USER", "LOGNAME", "PATH", "LANG", "PYTHONINSPECT")})
print(os.path.expanduser("~"), os.get_exec_path())
import pathlib

try:
    print(pathlib.Path.home())
except RuntimeError as e:
    print("RuntimeError", e)
import getpass

try:
    print(getpass.getuser())
except Exception as e:
    print(type(e).__name__, e)
# --- N9 sys.path order and stdlib dir
import sys

print(sys.path, sys._stdlib_dir, repr(sys.executable), sys.flags.inspect)
# --- N10 side module imports of the glue's library (dlsym of emscripten_* functions)
import ctypes

L = ctypes.CDLL(None)
for n in (
    "emscripten_get_now_res",
    "emscripten_random",
    "emscripten_console_log",
    "emscripten_run_script",
    "emscripten_force_exit",
    "emscripten_out",
):
    print(n, hasattr(L, n))
