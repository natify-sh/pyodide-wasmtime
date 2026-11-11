# ruff: noqa
# type: ignore
# TIME matrix 2: mktime / timegm on tuples (year/month/day/h/m/s/isdst edges), strptime, struct_time round trips.
import calendar
import datetime
import errno
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


YEARS = [
    -271821,
    -1,
    0,
    1,
    50,
    69,
    70,
    99,
    100,
    101,
    1899,
    1900,
    1901,
    1969,
    1970,
    1971,
    1999,
    2000,
    2001,
    2020,
    2021,
    2037,
    2038,
    2100,
    2400,
    9999,
    10000,
    275759,
    275760,
    275761,
    999999,
    1000000,
    1000001,
    2**31 - 1,
    2**31,
    -(2**31),
]
for y in YEARS:
    for mo, d, h, mi, s in [
        (1, 1, 0, 0, 0),
        (2, 29, 12, 0, 0),
        (12, 31, 23, 59, 59),
        (3, 29, 2, 30, 0),
        (3, 29, 3, 30, 0),
        (10, 25, 2, 30, 0),
        (10, 25, 3, 30, 0),
        (3, 8, 2, 30, 0),
        (11, 1, 1, 30, 0),
        (6, 15, 12, 0, 0),
        (13, 1, 0, 0, 0),
        (0, 1, 0, 0, 0),
        (2, 30, 25, 61, 61),
        (1, 0, 0, 0, 0),
        (1, 32, -1, -1, -1),
    ]:
        for dst in (-1, 0, 1):
            tt = (y, mo, d, h, mi, s, 0, 0, dst)
            c("mktime %r" % (tt,), lambda: time.mktime(tt))
            if dst == -1:
                c("timegm %r" % (tt,), lambda: calendar.timegm(tt))
                c("asctime %r" % (tt,), lambda: time.asctime(tt))
for m in range(-14, 26):
    tt = (2020, m, 15, 0, 0, 0, 0, 0, -1)
    c("mktime month %d" % m, lambda: time.mktime(tt))
    c("timegm month %d" % m, lambda: calendar.timegm(tt))
for fmt, s in [
    ("%Y-%m-%d", "2020-02-29"),
    ("%Y-%m-%d", "2021-02-29"),
    ("%d/%m/%y", "01/01/68"),
    ("%d/%m/%y", "01/01/69"),
    ("%H:%M:%S %p", "11:59:59 PM"),
    ("%Y %j", "2020 366"),
    ("%Y %j", "2021 366"),
    ("%a %b %d %Y", "Sat Feb 29 2020"),
    ("%Y-%m-%d %Z", "2020-01-01 UTC"),
    ("%Y-%m-%d %z", "2020-01-01 +0530"),
    ("%Y-%m-%d %z", "2020-01-01 -0000"),
    ("%s", "0"),
    ("%Y", "10000"),
    ("%Y", "0000"),
    ("%U %Y %w", "05 2020 3"),
]:
    c("strptime %r %r" % (fmt, s), lambda: tuple(time.strptime(s, fmt)))
    c("dt.strptime %r %r" % (fmt, s), lambda: datetime.datetime.strptime(s, fmt).isoformat())
for y, m, d in [(1970, 1, 1), (1, 1, 1), (9999, 12, 31), (2000, 2, 29), (1900, 2, 28), (2038, 1, 19)]:
    for h in (0, 12, 23):
        dt = datetime.datetime(y, m, d, h, 30)
        c("dt.timestamp %s" % dt, lambda: dt.timestamp())
        c("dt.astimezone %s" % dt, lambda: str(dt.astimezone()))
        c("dt.astimezone-utc %s" % dt, lambda: str(dt.astimezone(datetime.timezone.utc)))
        c("dt.local-ts %s" % dt, lambda: datetime.datetime.fromtimestamp(dt.timestamp()).isoformat())
        c("dt.timetuple %s" % dt, lambda: tuple(dt.timetuple()))
        c("dt.utctimetuple %s" % dt, lambda: tuple(dt.utctimetuple()))
for fmt in [
    "%a",
    "%A",
    "%b",
    "%B",
    "%c",
    "%C",
    "%d",
    "%D",
    "%e",
    "%F",
    "%g",
    "%G",
    "%h",
    "%H",
    "%I",
    "%j",
    "%k",
    "%l",
    "%m",
    "%M",
    "%n",
    "%p",
    "%P",
    "%r",
    "%R",
    "%s",
    "%S",
    "%t",
    "%T",
    "%u",
    "%U",
    "%V",
    "%w",
    "%W",
    "%x",
    "%X",
    "%y",
    "%Y",
    "%z",
    "%Z",
    "%%",
    "%E",
    "%Ey",
    "%Od",
    "%:z",
    "%5Y",
    "%-d",
    "%_d",
    "%^a",
    "%#d",
    "%",
]:
    for t in (0, 1585443600, 1603591200, -1, 2**31):
        c("strftime %r %d" % (fmt, t), lambda: time.strftime(fmt, time.localtime(t)))
        c("strftime-gm %r %d" % (fmt, t), lambda: time.strftime(fmt, time.gmtime(t)))
