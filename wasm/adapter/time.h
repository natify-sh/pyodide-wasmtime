// Time: Emscripten's JavaScript date helpers. Included only by adapter.c.
#ifndef ADAPTER_TIME_H
#define ADAPTER_TIME_H

#include "common.h"

// ================================================================== time: Emscripten's JavaScript date helpers
// gmtime and timegm are integer arithmetic with what JavaScript's Date does to them: nothing beyond +-8.64e12 s (an error),
// V8's limits for the year and the month, and a year 0..99 read as 19xx by Date.UTC (so the day of the year, which JavaScript
// counts from Jan 1 of that 19xx, is wrong for the years 1..99: the same wrong number). localtime, mktime and tzset ask
// the host, which knows the time zone (_host.py, `_t_localtime`).
// struct tm: sec, min, hour, mday, mon, year, wday, yday, isdst (i32 each), gmtoff (long), zone.
#define DATE_LIMIT 8640000000000LL
static i64 days_from_civil(i64 y, i64 m, i64 d) {  // proleptic Gregorian, H. Hinnant's algorithm
    y -= m <= 2;
    i64 era = (y >= 0 ? y : y - 399) / 400;
    i64 yoe = y - era * 400;
    i64 doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
    i64 doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097 + doe - 719468;
}

static void fill_tm(i64 t, i32 *tm, i32 js_yday) {
    i64 days = t >= 0 ? t / 86400 : -((-t + 86399) / 86400);
    i64 secs = t - days * 86400;
    tm[0] = (i32)(secs % 60), tm[1] = (i32)(secs / 60 % 60), tm[2] = (i32)(secs / 3600);
    i64 z = days + 719468;
    i64 era = (z >= 0 ? z : z - 146096) / 146097;
    i64 doe = z - era * 146097;
    i64 yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    i64 y = yoe + era * 400, doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    i64 mp = (5 * doy + 2) / 153, d = doy - (153 * mp + 2) / 5 + 1, m = mp + (mp < 10 ? 3 : -9);
    y += m <= 2;
    tm[3] = (i32)d, tm[4] = (i32)(m - 1), tm[5] = (i32)(y - 1900);
    i64 w = (days + 4) % 7;  // 1970-01-01 was a Thursday
    tm[6] = (i32)(w < 0 ? w + 7 : w);
    if (js_yday && y == -271821)  // Date.UTC(y, 0, 1) is NaN, and NaN | 0 is 0
        tm[7] = 0;
    else if (js_yday && y >= 0 && y <= 99)  // (date - Date.UTC(1900 + y, 0, 1)) / 864e5 | 0
        tm[7] = (i32)((t - days_from_civil(1900 + y, 1, 1) * 86400) / 86400);
    else
        tm[7] = (i32)(days - days_from_civil(y, 1, 1));
}

EXPORT("_gmtime_js") i32 gmtime_js(i64 t, i32 *tm) {
    if (t > DATE_LIMIT || t < -DATE_LIMIT) return 1;
    fill_tm(t, tm, 1);
    return 0;
}

EXPORT("_localtime_js") i32 localtime_js(i64 t, i32 *tm) {
    i32 off = host_localtime(t, tm);  // tm_isdst and tm_gmtoff; the exact offset east for the fields, INT_MIN: out of Date's range
    if (off == (i32)0x80000000) return 1;
    fill_tm(t + off, tm, 0);
    return 0;
}

// Date.UTC(...): -1 for NaN; only tm_wday and tm_yday are written
EXPORT("_timegm_js") i64 timegm_js(i32 *tm) {
    i64 y = (i64)tm[5] + 1900, mon = tm[4];
    if (y >= 0 && y <= 99) y += 1900;
    if (y < -1000000 || y > 1000000 || mon < -10000000 || mon > 10000000) return -1;
    y += mon >= 0 ? mon / 12 : -((11 - mon) / 12);
    mon = ((mon % 12) + 12) % 12;
    i64 t = (days_from_civil(y, mon + 1, 1) + tm[3] - 1) * 86400 + (i64)tm[2] * 3600 + (i64)tm[1] * 60 + tm[0];
    if (t > DATE_LIMIT || t < -DATE_LIMIT) return -1;
    i32 f[10];
    fill_tm(t, f, 1);
    tm[6] = f[6], tm[7] = f[7];
    return t;
}

EXPORT("_mktime_js") i64 mktime_js(i32 *tm) { return host_mktime(tm); }

EXPORT("_tzset_js") void tzset_js(i32 *timezone, i32 *daylight, char *std_name, char *dst_name) {
    host_tzset(timezone, daylight, std_name, dst_name);
}

#endif
