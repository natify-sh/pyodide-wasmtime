"""Emscripten's JavaScript date helpers (`_localtime_js`, `_mktime_js`, `_tzset_js`) in Python: functions of the host's
C library and of the guest's memory, which they are given (`rd`, `wr`)."""

from __future__ import annotations

import calendar
import struct
import time

from ._consts import _U32

# `_localtime_js`, `_mktime_js` and `_tzset_js` read the time zone of the process through `Date` (the host's: its
# TZ and zoneinfo). Here the host's C library answers the offset at an instant (`time.localtime`), and the rest is
# what the JavaScript does with it: its rules for a local time that does not exist or happens twice, its errors
# beyond +-8.64e12 s, its habit of reading a year 0..99 as 19xx in `new Date(year, ...)`, and offsets in whole
# minutes (getTimezoneOffset cuts a seconds part of an old local mean time; the fields of the date keep it).


def _days_from_civil(y: int, m: int, d: int) -> int:  # proleptic Gregorian (H. Hinnant)
    y -= m <= 2
    era = y // 400
    yoe = y - era * 400
    doe = yoe * 365 + yoe // 4 - yoe // 100 + (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    return era * 146097 + doe - 719468


def _civil_from_days(z: int) -> tuple[int, int, int]:
    z += 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    m = mp + (3 if mp < 10 else -9)
    return yoe + era * 400 + (m <= 2), m, doy - (153 * mp + 2) // 5 + 1


_DATE_LIMIT = 8_640_000_000_000  # JavaScript's Date holds +-8.64e15 ms


def _js_make(year: int, mon: int, mday: int, h: int, mi: int, s: int) -> int | None:
    """MakeDate(MakeDay(year, mon, mday), MakeTime(h, mi, s, 0)) of V8, in seconds; None is NaN. A year 0..99 is 19xx
    (the Date constructor and Date.UTC do that), a year or month beyond V8's limits is NaN."""
    if 0 <= year <= 99:
        year += 1900
    if not (-1_000_000 <= year <= 1_000_000 and -10_000_000 <= mon <= 10_000_000):
        return None
    year += mon // 12
    return (_days_from_civil(year, mon % 12 + 1, 1) + mday - 1) * 86400 + h * 3600 + mi * 60 + s


def gmtoff(t: int) -> int:
    """Seconds east of UTC at the instant t."""
    try:
        lt = time.localtime(t)
    except (OverflowError, OSError, ValueError):  # a C library with a narrow time_t (Windows): the nearest it has
        t = min(max(t, 0), 32535215999)
        lt = time.localtime(t)
    off = lt.tm_gmtoff
    if off is None or abs(off) > 2 * 86400:  # not an offset (Windows gives one at 2**31 and beyond): from the fields
        off = calendar.timegm(lt[:6]) - t
    return off


def minutes(t: int) -> int:
    """-Date.getTimezoneOffset() at the instant t: minutes east, cut towards zero."""
    return int(gmtoff(t) / 60)


def utc_from_local(lt: int) -> int:
    """The instant of a wall-clock time (seconds): of two (it happens twice) the earlier, of none (it is skipped)
    the one with the offset from before the change; as ECMAScript's UTC(t)."""
    before, after = gmtoff(lt - 86400), gmtoff(lt + 86400)
    found = [u for u in {lt - before, lt - after} if gmtoff(u) == lt - u]
    return min(found) if found else lt - before


def year_minutes(year: int) -> tuple[int, int]:
    """The offsets (minutes east) of `new Date(year, 0, 1)` and `new Date(year, 6, 1)`."""
    out = []
    for mon in (0, 6):
        lt = _js_make(year, mon, 1, 0, 0, 0)
        out.append(0 if lt is None else minutes(utc_from_local(lt)))
    return out[0], out[1]


def t_localtime(wr, t: int, tm: int) -> int:
    tm &= _U32
    """tm_isdst and tm_gmtoff into the struct; the exact offset (s east) for the fields, or INT_MIN: an error."""
    if abs(t) > _DATE_LIMIT:
        return -(1 << 31)
    off = gmtoff(t)
    winter, summer = year_minutes(_civil_from_days((t + off) // 86400)[0])
    minutes = int(off / 60)
    if not -(1 << 31) <= minutes * 60 < 1 << 31:  # not an offset: a host C library that failed (Windows)
        return -(1 << 31)
    # the offset of the summer (the larger one) is DST when the year has two
    flag = int(summer != winter and minutes == max(winter, summer))
    try:
        wr(tm + 32, struct.pack("<ii", flag, minutes * 60))
    except struct.error as e:
        raise RuntimeError(f"localtime t={t} off={off} winter={winter} summer={summer}: {e}") from e
    return off


def t_mktime(rd, wr, tm: int) -> int:
    tm &= _U32
    sec, mi, hour, mday, mon, year, _wday, _yday, dst = struct.unpack("<9i", rd(tm, 36))
    lt = _js_make(year + 1900, mon, mday, hour, mi, sec)
    if lt is None:
        return -1
    u = utc_from_local(lt)
    if abs(u) > _DATE_LIMIT:
        return -1
    guessed = minutes(u)
    winter, summer = year_minutes(_civil_from_days((u + gmtoff(u)) // 86400)[0])
    dst_off, std_off = max(winter, summer), min(winter, summer)
    if dst < 0:
        dst = int(summer != winter and dst_off == guessed)
    elif (dst > 0) != (dst_off == guessed):
        u += (guessed - (dst_off if dst > 0 else std_off)) * 60
        if abs(u) > _DATE_LIMIT:
            return -1
    days, secs = divmod(u + gmtoff(u), 86400)
    y, m, d = _civil_from_days(days)
    yday = days - _days_from_civil(y, 1, 1)
    fields = (secs % 60, secs // 60 % 60, secs // 3600, d, m - 1, y - 1900, (days + 4) % 7, yday)
    try:
        wr(tm, struct.pack("<8i", *fields) + struct.pack("<i", dst))
    except struct.error as e:
        raise RuntimeError(f"mktime u={u} fields={fields} dst={dst} guessed={guessed}: {e}") from e
    return u


def t_tzset(wr, timezone: int, daylight: int, std_name: int, dst_name: int) -> None:
    timezone, daylight, std_name, dst_name = (x & _U32 for x in (timezone, daylight, std_name, dst_name))
    winter, summer = year_minutes(time.localtime().tm_year)

    def zone(east: int) -> bytes:  # UTC-0200 for two hours east: the sign is of the offset as Date gives it (west)
        return f"UTC{'-' if east <= 0 else '+'}{abs(east) // 60:02d}{abs(east) % 60:02d}".encode()[:16] + b"\0"

    wr(timezone, struct.pack("<I", (-min(winter, summer) * 60) & 0xFFFFFFFF))
    wr(daylight, struct.pack("<i", int(winter != summer)))
    std, dst = (winter, summer) if summer > winter else (summer, winter)  # JS: summerOffset < winterOffset (west)
    wr(std_name, zone(std))
    wr(dst_name, zone(dst))
