# ruff: noqa
# type: ignore
# isolate
# CDLL of every side module of _sides.py, by absolute path: what loads, what the error text is, and what a call gives.
import ctypes
import os

S = B + "/so/"
open(B + "/emptydir_marker", "w").close()
os.makedirs(B + "/adir.so", exist_ok=True)
os.symlink(S + "ok.so", B + "/link_ok.so")
os.symlink(B + "/nowhere.so", B + "/broken.so")


def load_call(path, fn="val", mode=ctypes.DEFAULT_MODE):
    lib = ctypes.CDLL(path, mode=mode)
    f = getattr(lib, fn)
    f.restype = ctypes.c_int
    r = f()
    return r > 0 if fn.startswith("got_") else r


def load_only(path, mode=ctypes.DEFAULT_MODE):
    ctypes.CDLL(path, mode=mode)
    return "loaded"


# paths that are not modules
for nm, p in [
    ("missing", S + "missing_xyz.so"),
    ("directory", S + "rp"),
    ("dir_so_name", B + "/adir.so"),
    ("empty_path", ""),
    ("dot", "."),
    ("root", "/"),
    ("symlink", B + "/link_ok.so"),
    ("broken_symlink", B + "/broken.so"),
    ("trailing_slash", S + "ok.so/"),
    ("dotdot", S + "rp/../ok.so"),
    ("long255", S + "x" * 255),
    ("long256", S + "x" * 256),
    ("nonascii", S + "ключ.so"),
    ("not_so_ext", B + "/emptydir_marker"),
]:
    case("load-path-" + nm, load_only, p)
case("load-path-bytes", lambda: ctypes.CDLL(os.fsencode(S + "ok.so")) and "loaded")
case("load-path-surrogate", lambda: ctypes.CDLL(S + "\udcff.so") and "loaded")
case("load-path-None-str", lambda: ctypes.CDLL(None) and "loaded")
case("load-path-int", lambda: ctypes.CDLL(5))
case("load-path-nul", lambda: ctypes.CDLL(S + "ok.so\0x"))

# every module: load, then call val (or the module's own function)
for nm in sorted(SIDES):
    case("load-" + nm, load_only, S + nm)
for nm, fn in [
    ("ok.so", "val"),
    ("ok2.so", "val2"),
    ("nodata.so", "val"),
    ("nodylink.so", "val"),
    ("mem0.so", "val"),
    ("mem_1k.so", "val"),
    ("mem_gb.so", "val"),
    ("tab0.so", "val"),
    ("tab_big.so", "val"),
    ("align_big.so", "val"),
    ("align_0.so", "val"),
    ("align_3.so", "val"),
    ("need_ok.so", "vneed"),
    ("need_norpath.so", "vnorp"),
    ("need_rpathdir.so", "vrp"),
    ("rp/need_sub.so", "vsub"),
    ("need_dollar.so", "vdollar"),
    ("need_rel.so", "vrel"),
    ("cyc_a.so", "va"),
    ("self.so", "vself"),
    ("dy_unknown_sub.so", "val"),
    ("dy_old.so", "val"),
    ("post_inst.so", "val"),
    ("ctor.so", "val"),
    ("sig_ok.so", "val"),
    ("got_main.so", "got_strlen"),
    ("got_main.so", "got_getpid"),
    ("got_main.so", "got__Py_NoneStruct"),
    ("got_dyn.so", "got_val"),
    ("got_dyn.so", "got_dat"),
    ("env_getpid.so", "call_getpid"),
    ("env_unknown.so", "call_no_such_env_fn_xyz"),
    ("env_bridge.so", "call_JsArray_count_js"),
    ("env_emlog.so", "call_emscripten_get_now"),
    ("imp_wasi.so", "wr"),
    ("imp_wasi.so", "rnd"),
]:
    case("call-" + nm + "-" + fn, load_call, S + nm, fn)
# the wasm-side failures do not corrupt the next load
case("after-failures-ok", load_call, S + "ok.so", "val")
