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


def run_in_zone(guest: Guest, script: str, tz: str) -> str:
    """The script in a fresh guest of the host process with TZ=tz (the guest's Date, as in Node, is the host's zone)."""
    cmd = [sys.executable, "-m", "pyodide_wasmtime", "--flavor", guest.flavor, "-c", check_file(script)]
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
