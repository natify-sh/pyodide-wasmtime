# ruff: noqa
# type: ignore
# CLOCKS: types, ranges, ordering only (values are volatile); clk ids, clock_getres, sleep, nanosleep, thread/process time.
import errno
import os
import time


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
        print(cid, "| EXC", type(e).__name__, str(e)[:80], flush=True)


now = time.time()
c("time type", lambda: type(now).__name__)
c("time near-host(5s)", lambda: abs(now - __import__("datetime").datetime.now().timestamp()) < 5)
c("time > 2025", lambda: now > 1.7e9)
c("time_ns type", lambda: type(time.time_ns()).__name__)
c("time_ns ~ time", lambda: abs(time.time_ns() / 1e9 - time.time()) < 1)

for nm in ["monotonic", "perf_counter", "process_time"]:
    f = getattr(time, nm)
    c(nm + " type", lambda: type(f()).__name__)
    c(nm + " >=0", lambda: f() >= 0)
    c(nm + " ordered", lambda: (lambda a, b: a <= b)(f(), f()))
    c(nm + "_ns type", lambda: type(getattr(time, nm + "_ns")()).__name__)
    c(
        nm + " info",
        lambda: (lambda i: (i.implementation, i.monotonic, i.adjustable, i.resolution))(time.get_clock_info(nm)),
    )
c(
    "time info",
    lambda: (lambda i: (i.implementation, i.monotonic, i.adjustable, i.resolution))(time.get_clock_info("time")),
)
c("clock info bad", lambda: time.get_clock_info("x"))
for nm in [
    "CLOCK_REALTIME",
    "CLOCK_MONOTONIC",
    "CLOCK_MONOTONIC_RAW",
    "CLOCK_PROCESS_CPUTIME_ID",
    "CLOCK_THREAD_CPUTIME_ID",
    "CLOCK_BOOTTIME",
    "CLOCK_TAI",
    "CLOCK_PROF",
    "CLOCK_UPTIME",
    "CLOCK_HIGHRES",
]:
    c(nm + " const", lambda: getattr(time, nm, "missing"))
for cid in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 17, 18, 255, 1000, -1, -2, 2**31, 2**32 - 1, -(2**31)]:
    c("clock_gettime %d" % cid, lambda: (lambda v: (type(v).__name__, v >= 0))(time.clock_gettime(cid)))
    c("clock_gettime_ns %d" % cid, lambda: (lambda v: (type(v).__name__, v >= 0))(time.clock_gettime_ns(cid)))
    c("clock_getres %d" % cid, lambda: time.clock_getres(cid))
    c("pthread_getcpuclockid-less cid %d" % cid, lambda: time.clock_gettime(cid) <= time.clock_gettime(cid) + 1e-3)
c("clock_gettime str", lambda: time.clock_gettime("a"))
c("clock_gettime None", lambda: time.clock_gettime(None))
c("clock_settime REALTIME", lambda: time.clock_settime(0, 1e9))
c("clock_settime MONO", lambda: time.clock_settime(1, 1e9))
c("clock_settime_ns", lambda: time.clock_settime_ns(0, 10**18))
c("process_time<=monotonic-ish", lambda: time.process_time() < 100)
c("thread_time exists", lambda: hasattr(time, "thread_time"))
for s in [0, 0.0, 0.001, 0.01, 1e-9, -1, -0.5, float("nan"), float("inf"), "x", None, 2**70, 1e300, 10**-30]:

    def sl(s=s):
        t0 = time.monotonic()
        time.sleep(s)
        el = time.monotonic() - t0
        return ("slept", s >= 0 and el >= min(s, 5) * 0.9 - 0.002 and el < 5)

    if s in (float("inf"), 2**70, 1e300):
        c("sleep %r" % (s,), lambda: time.sleep(s) if False else "skipped")
    else:
        c("sleep %r" % (s,), sl)
import ctypes

libc = ctypes.CDLL(None)


class TS(ctypes.Structure):
    _fields_ = [("s", ctypes.c_int64), ("n", ctypes.c_int64)]


for sec, ns in [
    (0, 0),
    (0, 1),
    (0, 1000),
    (0, 1000000),
    (0, 999999999),
    (0, 1000000000),
    (0, -1),
    (-1, 0),
    (0, 2**31 - 1),
    (0, 2**31),
    (1, 0),
]:

    def nano(sec=sec, ns=ns):
        req, rem = TS(sec, ns), TS(7, 7)
        t0 = time.monotonic()
        r = libc.nanosleep(ctypes.byref(req), ctypes.byref(rem))
        e = ctypes.get_errno()
        return (r, (rem.s, rem.n) if r else "-", time.monotonic() - t0 < 2)

    c("nanosleep %d.%d" % (sec, ns), nano)
for clk in [0, 1, 4, 6, 99]:

    def csl(clk=clk):
        req = TS(0, 1000000)
        t0 = time.monotonic()
        r = libc.clock_nanosleep(clk, 0, ctypes.byref(req), None)
        return (r, time.monotonic() - t0 < 2)

    c("clock_nanosleep %d" % clk, csl)


def abs_sleep():
    t = TS()
    libc.clock_gettime(1, ctypes.byref(t))
    t.n += 5000000
    t.s, t.n = t.s + t.n // 10**9, t.n % 10**9
    return libc.clock_nanosleep(1, 1, ctypes.byref(t), None)


c("usleep 1000", lambda: libc.usleep(1000))
c("usleep 2000000-big", lambda: libc.usleep(1))
c("sleep(0) libc", lambda: libc.sleep(0))
c(
    "gettimeofday",
    lambda: (lambda tv, r: (r, tv.s > 1.7e9, tv.n < 10**6))(
        *(lambda tv: (tv, libc.gettimeofday(ctypes.byref(tv), None)))(TS())
    ),
)
c("times()", lambda: (lambda b: libc.times(ctypes.byref(b)) != 0)(TS()))
c("clock()", lambda: libc.clock() >= 0)
c("os.times types", lambda: tuple(type(x).__name__ for x in os.times()))
c("os.times elapsed>0", lambda: os.times().elapsed > 0)
c("os.times children zero", lambda: os.times()[2:4])
c("os.times system>=0", lambda: os.times().system >= 0)
c("os.times user<100", lambda: os.times().user < 100)
c("resolution perf_counter", lambda: (lambda d: 0 <= d < 0.1)(time.perf_counter() - time.perf_counter()))
mono = [time.monotonic_ns() for _ in range(2000)]
c("monotonic never back (2000)", lambda: all(a <= b for a, b in zip(mono, mono[1:])))
c("monotonic distinct values >1", lambda: len(set(mono)) > 1)
rt = [time.time_ns() for _ in range(2000)]
c("time_ns resolution gcd", lambda: __import__("math").gcd(*rt[:50]) in (1, 1000, 1000000) or "other")
c("time_ns ms-granular", lambda: all(x % 1000000 == 0 for x in rt))
c("monotonic_ns ms-granular", lambda: all(x % 1000000 == 0 for x in mono))
c("perf_counter_ns ms-granular", lambda: all(time.perf_counter_ns() % 1000 == 0 for _ in range(50)))
c("monotonic zero point (<1e6 s)", lambda: time.monotonic() < 1e6)
c("perf_counter zero point (<1e6 s)", lambda: time.perf_counter() < 1e6)
c("uptime-like >= 0", lambda: time.clock_gettime(7) if hasattr(time, "CLOCK_BOOTTIME") else "n/a")
