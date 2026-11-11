# ruff: noqa
# type: ignore
# isolate
# emscripten_dlopen through ctypes callbacks (asynchronous on Pyodide: only what is visible right after the call).
import ctypes
import time

S = B + "/so/"
libc = ctypes.CDLL(None)
CB_OK = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
CB_ERR = ctypes.CFUNCTYPE(None, ctypes.c_void_p)
EV = []


def on_ok(ud, h):
    EV.append(("ok", ud))


def on_err(ud):
    EV.append(("err", ud))


OK, ERR = CB_OK(on_ok), CB_ERR(on_err)


def edl(path, flags=2, ok=OK, err=ERR, ud=7):
    del EV[:]
    r = libc.emscripten_dlopen(path, flags, ud, ok, err)
    return (r, list(EV))


def after(path, secs, **kw):
    edl(path, **kw)
    time.sleep(secs)
    return list(EV)


P = lambda n: (S + n).encode()  # noqa: E731
case("sym-emscripten_dlopen", lambda: hasattr(libc, "emscripten_dlopen"))
case("sym-emscripten_dlopen_promise", lambda: hasattr(libc, "emscripten_dlopen_promise"))
case("edl-ok-path", edl, P("ok.so"))
case("edl-ok-then-CDLL", lambda: (edl(P("ok.so")), ctypes.CDLL(S + "ok.so").val())[1])
case("edl-sleep0-then-events", after, P("ok.so"), 0)
case("edl-sleep-then-events", after, P("ok.so"), 0.05)
case("edl-junk", edl, P("junk.so"))
case("edl-junk-sleep", after, P("junk.so"), 0.05)
case("edl-null-callbacks", lambda: libc.emscripten_dlopen(P("ok.so"), 2, 0, None, None))
case("edl-null-onsuccess", lambda: libc.emscripten_dlopen(P("ok.so"), 2, 0, None, ERR))
case("edl-null-onerror-bad-file", lambda: libc.emscripten_dlopen(P("junk.so"), 2, 0, OK, None))
case("edl-flags-global", edl, P("ok.so"), 0x100)
case("edl-flags-0", edl, P("ok.so"), 0)
case("edl-needed-ok", after, P("need_ok.so"), 0.05)
case("edl-needed-missing", after, P("need_missing.so"), 0.05)
case("edl-twice", lambda: (edl(P("ok.so")), after(P("ok.so"), 0.05))[1])
case("edl-dlerror-after-junk", lambda: (after(P("junk.so"), 0.05), ctypes.CDLL(None).dlerror.__class__.__name__)[1])
case("edl-missing-file-sleep", after, P("missing_xyz.so"), 0.05)
