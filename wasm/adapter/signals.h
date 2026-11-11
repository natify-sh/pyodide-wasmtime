// Signals and timers, the runtime's name. Included only by adapter.c.
#ifndef ADAPTER_SIGNALS_H
#define ADAPTER_SIGNALS_H

#include "common.h"
#include "openfiles.h"

// ================================================================== signals and timers
// raise() and kill(getpid()) call the handler the program set (Python's, which notes the signal); the host can post one
// for Python too (Pyodide.interrupt: JavaScript's Py_EmscriptenSignalBuffer), and a timer the program armed
// (setitimer, alarm) is checked when Python looks for signals, since there is no event loop here to fire it.
EXPORT("__call_sighandler") void call_sighandler(u32 fp, i32 sig) { ((void (*)(i32))fp)(sig); }

typedef struct {
    u32 cell;           // where the host posts a signal number (its address: __nojs_sigcell_addr)
    double deadline[3];  // ITIMER_REAL, VIRTUAL, PROF: when it fires (get_now's clock), 0: not armed
} Sig;
__asm__(".globaltype sig_state, i32\nsig_state:\n");
static Sig *sigst(void) {
    Sig *r;
    __asm__ volatile("global.get sig_state\n\tlocal.set %0" : "=r"(r));
    if (!r) {
        r = (Sig *)calloc(1, sizeof(Sig));
        __asm__ volatile("local.get %0\n\tglobal.set sig_state" : : "r"(r));
    }
    return r;
}

// the host reads the cell's address from here (Pyodide.interrupt); the name is the host's own, hidden from dlsym
EXPORT("__nojs_sigcell_addr") u32 sigcell_addr(void) { return (u32)&sigst()->cell; }

EXPORT("_setitimer_js") i32 setitimer_js(i32 which, double timeout_ms) {
    if ((u32)which > 2) return 0;
    sigst()->deadline[which] = timeout_ms != 0 ? now_ms(1) + timeout_ms : 0;
    if (timeout_ms != 0) {  // Python looks for signals only when the main module's byte says so (what setInterruptBuffer sets)
        u64 nm[4];
        nm[0] = 0x5243534d455f7950ull, nm[1] = 0x49535f4e45545049ull, nm[2] = 0x4e41485f4c414e47ull, nm[3] = 0x474e494c44ull;  // "Py_EMSCRIPTEN_SIGNAL_HANDLING"
        u32 out[2], addr = dl_sym(0, (const char *)nm, 29, out);
        if (out[0] == 1) *(u8 *)addr = 1;
    }
    return 0;
}

EXPORT("_Py_CheckEmscriptenSignals_Helper") i32 check_signals(void) {
    Sig *s = sigst();
    for (i32 which = 0; which < 3; which++) {
        if (s->deadline[which] == 0) continue;
        double now = now_ms(1);
        if (now < s->deadline[which]) continue;
        s->deadline[which] = 0;
        u64 nm[3];
        nm[0] = 0x70697263736d655full, nm[1] = 0x656d69745f6e6574ull, nm[2] = 0x74756full;  // "_emscripten_timeout" (libc's, re-arms an interval)
        u32 out[2], slot = dl_sym(0, (const char *)nm, 19, out);
        if (out[0] == 2 || out[0] == 3) ((void (*)(i32, double))slot)(which, now);  // 3: a slot made by this lookup
    }
    i32 v = (i32)s->cell;
    s->cell = 0;
    return v;
}

// sys._emscripten_info.runtime
EXPORT("_Py_emscripten_runtime") u32 runtime_name(void) { return host_runtime(); }

#endif
