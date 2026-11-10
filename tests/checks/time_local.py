# localtime, mktime, tzname and strftime in the host's time zone (TZ), from 1970 on, with the changes of DST and a
# local time that does not exist or happens twice (the .expected files are what Pyodide on Node prints in that TZ)
import time

print("tz", time.tzname, time.timezone, time.daylight, time.altzone)
for t in [
    0, -1, 10**9, 2**31, 1585443599, 1585443600, 1585447199, 1603587599, 1603587600, 1603591200, 1593561600,
    1593604800, 1604188800, 1700000000, 4102444800, 9467251200, 253402300799,
    8640000000001, 10**13, 10**17, -(2**63),
]:  # fmt: skip
    try:
        g, loc = time.gmtime(t), time.localtime(t)
        print(t, tuple(loc)[:9], loc.tm_gmtoff, loc.tm_zone)
    except BaseException as e:
        print(t, type(e).__name__, getattr(e, "errno", ""))

for tt in [
    (2020, 7, 1, 12, 0, 0, 0, 0, -1), (2020, 7, 1, 12, 0, 0, 0, 0, 0), (2020, 7, 1, 12, 0, 0, 0, 0, 1),
    (2020, 1, 1, 12, 0, 0, 0, 0, 1), (2020, 1, 1, 12, 0, 0, 0, 0, 0), (2020, 3, 29, 3, 30, 0, 0, 0, -1),
    (2020, 3, 29, 3, 30, 0, 0, 0, 0), (2020, 3, 29, 3, 30, 0, 0, 0, 1), (2020, 3, 29, 4, 0, 0, 0, 0, -1),
    (2020, 3, 8, 2, 30, 0, 0, 0, -1), (2020, 11, 1, 1, 30, 0, 0, 0, -1), (2020, 10, 25, 3, 30, 0, 0, 0, -1),
    (2020, 10, 25, 3, 30, 0, 0, 0, 0), (2020, 10, 25, 3, 30, 0, 0, 0, 1), (2020, 10, 4, 2, 15, 0, 0, 0, -1),
    (2020, 13, 1, 0, 0, 0, 0, 0, -1), (2020, 0, 1, 0, 0, 0, 0, 0, -1), (2020, 2, 30, 25, 61, 61, 0, 0, -1),
    (1970, 1, 1, 0, 0, 0, 0, 0, -1), (50, 1, 1, 0, 0, 0, 0, 0, -1), (275760, 9, 13, 0, 0, 0, 0, 0, -1),
    (275761, 1, 1, 0, 0, 0, 0, 0, -1), (9999, 12, 31, 23, 59, 59, 0, 0, -1), (3000, 1, 1, 0, 0, 0, 0, 0, -1),
]:  # fmt: skip
    try:
        print("mktime", tt, time.mktime(tt))
    except BaseException as e:
        print("mktime", tt, type(e).__name__, e)

for fmt in ["%Z %z", "%c"]:
    print(fmt, time.strftime(fmt, time.localtime(1593561600)), time.strftime(fmt, time.localtime(1609459200)))
