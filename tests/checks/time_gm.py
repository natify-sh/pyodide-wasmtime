# gmtime and timegm at the edges of JavaScript's Date (the .expected file is what Pyodide on Node prints); run with TZ=UTC
import ctypes as c
import time

libc = c.CDLL(None)


class T(c.Structure):
    _fields_ = [(n, c.c_int) for n in "sec min hour mday mon year wday yday isdst".split()] + [
        ("gmtoff", c.c_long),
        ("zone", c.c_char_p),
    ]


libc.timegm.restype = c.c_int64
libc.timegm.argtypes = [c.POINTER(T)]

print("tz", time.tzname, time.timezone, time.daylight)
for t in [
    0, -1, -86401, 10**9, 2**31, -(2**31), 253402300799, 253402300800, -62135596800, -62135596801, -62167219200,
    -62162000000, -60000000000, -59000000000, 8640000000000, 8640000000001, -8640000000000, -8640000000001,
    -8640000000000 + 86400 * 100, -8640000000000 + 86400 * 270, 10**13, 10**15, 10**17, 2**53, -(2**53), 2**62, -(2**63),
]:  # fmt: skip
    try:
        g = time.gmtime(t)
        print(t, tuple(g)[:9])
    except BaseException as e:
        print(t, type(e).__name__, getattr(e, "errno", ""))

for y, m, d, h, mi, s in [
    (2020, 7, 1, 12, 0, 0), (1970, 1, 1, 0, 0, 0), (1969, 12, 31, 23, 59, 59), (50, 1, 2, 0, 0, 0), (1, 1, 1, 0, 0, 0),
    (99, 12, 31, 0, 0, 0), (100, 1, 1, 0, 0, 0), (275760, 9, 13, 0, 0, 0), (275761, 1, 1, 0, 0, 0),
    (2020, 14, 1, 0, 0, 0), (2020, 2, 30, 25, 61, 61), (1000000, 1, 1, 0, 0, 0), (-271821, 4, 20, 0, 0, 0),
    (-271821, 4, 19, 23, 59, 59),
]:  # fmt: skip
    x = T(s, mi, h, d, m - 1, y - 1900, 99, 99, 0, 0, None)
    r = libc.timegm(c.byref(x))
    print("timegm", (y, m, d, h, mi, s), r, x.sec, x.min, x.hour, x.mday, x.mon, x.year, x.wday, x.yday)
