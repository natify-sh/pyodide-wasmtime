# ruff: noqa
# type: ignore
# Blocking calls: one program per call (a TIMEOUT line is the result). timespec on wasm32 is {int64 sec; int32 nsec; pad}. Run with DIFF_TIMEOUT=20.
# --- nanosleep 1ms
import ctypes

libc = ctypes.CDLL(None)


class TS(ctypes.Structure):
    _fields_ = [("s", ctypes.c_int64), ("n", ctypes.c_int64)]


print("r", libc.nanosleep(ctypes.byref(TS(0, 1000000)), None))
# --- nanosleep 1s
import ctypes

libc = ctypes.CDLL(None)


class TS(ctypes.Structure):
    _fields_ = [("s", ctypes.c_int64), ("n", ctypes.c_int64)]


print("r", libc.nanosleep(ctypes.byref(TS(1, 0)), None))
# --- clock_nanosleep mono 1ms
import ctypes

libc = ctypes.CDLL(None)


class TS(ctypes.Structure):
    _fields_ = [("s", ctypes.c_int64), ("n", ctypes.c_int64)]


print("r", libc.clock_nanosleep(1, 0, ctypes.byref(TS(0, 1000000)), None))
# --- usleep 1ms
import ctypes

print("r", ctypes.CDLL(None).usleep(1000))
# --- sleep(1) libc
import ctypes

print("r", ctypes.CDLL(None).sleep(1))
# --- time.sleep 0.01
import time

time.sleep(0.01)
print("done")
# --- select 10ms
import select

print(select.select([], [], [], 0.01))
# --- poll 10ms
import select

print(select.poll().poll(10))
# --- nanosleep 1e9ns
import ctypes

libc = ctypes.CDLL(None)


class TS(ctypes.Structure):
    _fields_ = [("s", ctypes.c_int64), ("n", ctypes.c_int64)]


print("r", libc.nanosleep(ctypes.byref(TS(0, 1000000000)), None), ctypes.get_errno(), flush=True)
# --- nanosleep neg ns
import ctypes

libc = ctypes.CDLL(None)


class TS(ctypes.Structure):
    _fields_ = [("s", ctypes.c_int64), ("n", ctypes.c_int64)]


print("r", libc.nanosleep(ctypes.byref(TS(0, -1)), None), ctypes.get_errno(), flush=True)
# --- nanosleep neg sec
import ctypes

libc = ctypes.CDLL(None)


class TS(ctypes.Structure):
    _fields_ = [("s", ctypes.c_int64), ("n", ctypes.c_int64)]


print("r", libc.nanosleep(ctypes.byref(TS(-1, 0)), None), ctypes.get_errno(), flush=True)
# --- nanosleep 10ms
import ctypes

libc = ctypes.CDLL(None)


class TS(ctypes.Structure):
    _fields_ = [("s", ctypes.c_int64), ("n", ctypes.c_int64)]


print("r", libc.nanosleep(ctypes.byref(TS(0, 10000000)), None), ctypes.get_errno(), flush=True)
# --- nanosleep 100ms
import ctypes

libc = ctypes.CDLL(None)


class TS(ctypes.Structure):
    _fields_ = [("s", ctypes.c_int64), ("n", ctypes.c_int64)]


print("r", libc.nanosleep(ctypes.byref(TS(0, 100000000)), None), ctypes.get_errno(), flush=True)
# --- nanosleep 999ms
import ctypes

libc = ctypes.CDLL(None)


class TS(ctypes.Structure):
    _fields_ = [("s", ctypes.c_int64), ("n", ctypes.c_int64)]


print("r", libc.nanosleep(ctypes.byref(TS(0, 999000000)), None), ctypes.get_errno(), flush=True)
# --- nanosleep 1s+1ns
import ctypes

libc = ctypes.CDLL(None)


class TS(ctypes.Structure):
    _fields_ = [("s", ctypes.c_int64), ("n", ctypes.c_int64)]


print("r", libc.nanosleep(ctypes.byref(TS(1, 1)), None), ctypes.get_errno(), flush=True)
