"""Offline: the time functions of Emscripten's glue (`_gmtime_js`, `_timegm_js`, `_localtime_js`, `_mktime_js`,
`_tzset_js`) give what Pyodide on Node gives, in the host's time zone: tests/checks/time_*.expected are the output of
the same scripts in the real Pyodide 315.0.0a2 (Node 22) with TZ set. Both packagings."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import Guest, check_file

ZONES = ["UTC", "Europe/Kyiv", "America/New_York", "Australia/Lord_Howe", "Asia/Kolkata"]


def run_in_zone(guest: Guest, script: str, tz: str, raw: bool = False) -> str:
    """The script in a fresh guest of the host process with TZ=tz (the guest's Date, as in Node, is the host's zone)."""
    cmd = [
        sys.executable,
        "-m",
        "pyodide_wasmtime",
        "--flavor",
        guest.flavor,
        "-c",
        script if raw else check_file(script),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env={**os.environ, "TZ": tz})
    assert r.returncode == 0, r.stderr
    return r.stdout


def expected(name: str) -> list[str]:
    return check_file(name).splitlines()


def test_gmtime_and_timegm_at_the_edges_of_date(guest: Guest) -> None:
    """The error beyond +-8.64e12 s (OSError EINVAL), the year 0..99 read as 19xx, the day of the year that comes
    out of it, V8's limits for timegm: all as the JavaScript does them."""
    assert run_in_zone(guest, "time_gm.py", "UTC").splitlines() == expected("time_gm.expected")


@pytest.mark.parametrize("tz", ZONES)
def test_local_time_in_the_hosts_zone(guest: Guest, tz: str) -> None:
    """localtime, mktime (DST flags, a time that is skipped or happens twice), tzname, timezone, daylight, strftime."""
    if tz != "UTC" and (sys.platform == "win32" or not Path("/usr/share/zoneinfo", tz).exists()):
        pytest.skip(f"the host has no zoneinfo for {tz}")
    out = run_in_zone(guest, "time_local.py", tz).splitlines()
    assert out == expected(f"time_local.{tz.replace('/', '_')}.expected")


ABOVE_2GIB = """
import ctypes as c
big = [bytearray(1_100_000_000), bytearray(1_100_000_000)]  # the heap now reaches past 2 GiB
buf = c.create_string_buffer(1 << 20)
addr = c.addressof(buf)
class T(c.Structure):
    _fields_ = [(n, c.c_int) for n in "sec min hour mday mon year wday yday isdst".split()]
    _fields_ += [("gmtoff", c.c_long), ("zone", c.c_char_p)]
tm = T.from_buffer(buf)
libc = c.CDLL(None)
libc.mktime.restype = c.c_int64
tm.sec, tm.min, tm.hour, tm.mday, tm.mon, tm.year, tm.isdst = 0, 0, 12, 1, 6, 120, -1
t = libc.mktime(c.byref(tm))
print(addr >= 2**31, t, tm.hour, tm.mday, tm.wday, tm.yday)
tt = c.c_int64(1593604800)
tm2 = T.from_buffer(buf, 256)
libc.localtime_r(c.byref(tt), c.byref(tm2))
print(tm2.hour, tm2.mday, tm2.year, tm2.gmtoff)
"""


def test_structs_above_2_gib_are_read_and_written_where_they_are(guest: Guest) -> None:
    """An i32 above 2 GiB is a negative number in wasmtime-py: mktime/localtime on a struct tm up there must not touch
    the other end of the memory."""
    out = run_in_zone(guest, ABOVE_2GIB, "UTC", raw=True).splitlines()
    assert out == ["True 1593604800 12 1 3 182", "12 1 120 0"]
