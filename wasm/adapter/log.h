// Emscripten_log: _emscripten_log_formatted / emscripten_log_impl_js. Included only by adapter.c.
#ifndef ADAPTER_LOG_H
#define ADAPTER_LOG_H

#include "common.h"
#include "state.h"

// ================================================================== emscripten_log: _emscripten_log_formatted / emscripten_log_impl_js
// The glue prints with console.error / warn / info / debug / log, which Node sends to stderr (error, warn) or stdout
// (the others), and with err / out for the flags that do not ask for the console. All of them are one line:
// error and warn go to stderr, everything else to stdout. The call stack that EM_LOG_C_STACK / EM_LOG_JS_STACK ask
// for is JavaScript's (new Error().stack): there is none here, the message is printed without it.
WASI("fd_write") i32 w_fd_write(i32 fd, const void *iovs, i32 n, i32 *nwritten);
static void write_all(i32 fd, const char *s, i32 n) {  // WASI may write less than asked: again until it is all out
    while (n > 0) {
        u32 iov[2];
        iov[0] = (u32)s, iov[1] = (u32)n;
        i32 w = 0;
        if (w_fd_write(fd, iov, 1, &w) || w <= 0) return;
        s += w, n -= w;
    }
}
static void log_line(i32 fd, const char *s, i32 n) {
    char nl[2];
    nl[0] = 10, nl[1] = 0;
    write_all(fd, s, n);
    write_all(fd, nl, 1);
}

EXPORT("emscripten_log_impl_js") void log_impl_js(const char *s) { log_line(2, s, slen(s)); }

EXPORT("_emscripten_log_formatted") void log_formatted(i32 flags, const char *s) {
    i32 n = slen(s);
    if (flags & 24)  // the glue strips trailing white space before it appends the stack
        while (n > 0 && (s[n - 1] == ' ' || (s[n - 1] >= 9 && s[n - 1] <= 13))) n--;
    log_line((flags & 6) ? 2 : 1, s, n);
}

#endif
