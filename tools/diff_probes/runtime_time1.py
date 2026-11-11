# ruff: noqa
# type: ignore
# TIME matrix 1: gmtime/timegm/localtime/mktime/strftime/asctime/ctime/fromtimestamp, instants around the edges.
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


print("tz | ", time.tzname, time.timezone, time.daylight, time.altzone)
INST = [
    0,
    1,
    -1,
    59,
    60,
    86399,
    86400,
    -86400,
    -86401,
    2**31 - 1,
    2**31,
    2**31 + 1,
    -(2**31),
    -(2**31) - 1,
    2**32 - 1,
    2**32,
    2**32 + 1,
    -(2**32),
    2**33,
    2**40,
    2**53,
    -(2**53),
    2**53 + 1,
    2**62,
    2**63 - 1,
    2**63,
    -(2**63),
    2**64,
    8640000000000,
    8640000000001,
    -8640000000000,
    -8640000000001,
    8639999999999,
    -8639999999999,
    10**9,
    10**10,
    10**11,
    10**12,
    253402300799,
    253402300800,
    -62135596800,
    -62135596801,
    -62167219200,
    -62167219201,
    -62198755200,
    951782400,
    951868800,
    951955200,
    4107542400,
    4107628800,
    1078012800,
    1078099200,
    -2208988800,
    -2209075200,
    946684799,
    946684800,
    1230768000,
    1262303999,
    1262304000,
    1583020800,
    1583107200,
    1582934400,
    1585443599,
    1585443600,
    1585447199,
    1585447200,
    1603587599,
    1603587600,
    1603591199,
    1603591200,
    1615709999,
    1615710000,
    1636275599,
    1636275600,
    1600000000,
    1700000000,
    1.5,
    -1.5,
    0.999999,
    -0.000001,
    2**31 + 0.5,
    1e12,
    1e13,
    1e17,
    float("inf"),
    float("nan"),
    -float("inf"),
    10**30,
    "x",
]
for t in INST:
    c("gmtime %r" % (t,), lambda: tuple(time.gmtime(t)))
    c(
        "localtime %r" % (t,),
        lambda: tuple(time.localtime(t)) + (time.localtime(t).tm_gmtoff, time.localtime(t).tm_zone),
    )
    c("asctime-gm %r" % (t,), lambda: time.asctime(time.gmtime(t)))
    c("ctime %r" % (t,), lambda: time.ctime(t))
    c("calendar.timegm %r" % (t,), lambda: calendar.timegm(time.gmtime(t)))
    c("mktime-local %r" % (t,), lambda: time.mktime(time.localtime(t)))
    c("strftime %r" % (t,), lambda: time.strftime("%Y-%m-%d %H:%M:%S %j %a %b %U %W %w %y %Z %z %%", time.localtime(t)))
    c("strftime-gm %r" % (t,), lambda: time.strftime("%c|%x|%X|%p|%I|%e|%G|%V|%u", time.gmtime(t)))
    c("dt.fromts %r" % (t,), lambda: datetime.datetime.fromtimestamp(t).isoformat())
    c("dt.utcfromts %r" % (t,), lambda: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat())
    c("dt.astimezone %r" % (t,), lambda: str(datetime.datetime.fromtimestamp(t, datetime.timezone.utc).astimezone()))
    c("dt.timestamp %r" % (t,), lambda: datetime.datetime.fromtimestamp(t).timestamp())
