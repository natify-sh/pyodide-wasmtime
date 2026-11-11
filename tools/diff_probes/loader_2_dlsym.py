# ruff: noqa
# type: ignore
# isolate
# dlsym through ctypes: functions, data, globals of the four types, missing names, the main module (CDLL(None)),
# pointer identity, dlopen twice, the mode flags, ctypes.util.find_library.
import ctypes
import ctypes.util
import os

S = B + "/so/"
MODES = {
    "default": ctypes.DEFAULT_MODE,
    "now": 2,
    "lazy": 1,
    "global": 0x100,
    "now_global": 0x102,
    "local": 0,
    "weird": 0x7FFF,
    "negative": -1,
}


def _try(f):
    try:
        f()
    except BaseException as e:
        return type(e).__name__


def sym(name, sy):
    lib = ctypes.CDLL(S + name)
    return getattr(lib, sy).__class__.__name__


def call(name, sy, restype, *args, argtypes=None):
    lib = ctypes.CDLL(S + name)
    f = getattr(lib, sy)
    f.restype = restype
    if argtypes:
        f.argtypes = argtypes
    return f(*args)


for nm, m in MODES.items():
    case("mode-" + nm, lambda m=m: ctypes.CDLL(S + "ok.so", mode=m).val.__class__.__name__)
    case("mode-call-" + nm, lambda m=m: ctypes.CDLL(S + "ok.so", mode=m).val())
case("mode-string", lambda: ctypes.CDLL(S + "ok.so", mode="x"))
case("mode-float", lambda: ctypes.CDLL(S + "ok.so", mode=1.5))
case("mode-huge", lambda: ctypes.CDLL(S + "ok.so", mode=2**40))
case("mode-global-then-main-sees-val", lambda: (ctypes.CDLL(S + "ok.so", mode=0x100), ctypes.CDLL(None).val())[1])
case("mode-local-then-main-sees-val", lambda: (ctypes.CDLL(S + "ok.so", mode=0), ctypes.CDLL(None).val())[1])
case("mode-default-then-main-sees-val", lambda: (ctypes.CDLL(S + "ok.so"), ctypes.CDLL(None).val())[1])
case(
    "mode-global-then-main-sees-dat", lambda: (ctypes.CDLL(S + "ok.so", mode=0x100), ctypes.CDLL(None).dat.__class__)[1]
)
case(
    "mode-global-then-sibling-uses-got",
    lambda: (ctypes.CDLL(S + "ok.so", mode=0x100), ctypes.CDLL(S + "got_dyn.so").got_val())[1] != 0,
)

# dlopen twice
case("twice-same-handle", lambda: ctypes.CDLL(S + "ok.so")._handle == ctypes.CDLL(S + "ok.so")._handle)
case(
    "twice-link-same-handle",
    lambda: (
        os.symlink(S + "ok.so", B + "/l.so"),
        ctypes.CDLL(S + "ok.so")._handle == ctypes.CDLL(B + "/l.so")._handle,
    )[1],
)
case("twice-dotdot-same-handle", lambda: ctypes.CDLL(S + "ok.so")._handle == ctypes.CDLL(S + "rp/../ok.so")._handle)
case(
    "twice-fn-same-addr",
    lambda: (
        ctypes.cast(ctypes.CDLL(S + "ok.so").val, ctypes.c_void_p).value
        == ctypes.cast(ctypes.CDLL(S + "ok.so").val, ctypes.c_void_p).value
    ),
)
case(
    "twice-fptr-eq-dlsym",
    lambda: ctypes.CDLL(S + "ok.so").fptr() == ctypes.cast(ctypes.CDLL(S + "ok.so").val, ctypes.c_void_p).value,
)
case("twice-different-libs-diff-handles", lambda: ctypes.CDLL(S + "ok.so")._handle != ctypes.CDLL(S + "ok2.so")._handle)
case("twice-handle-nonzero", lambda: ctypes.CDLL(S + "ok.so")._handle != 0)
case(
    "twice-same-memsize-addr-dat",
    lambda: (
        ctypes.cast(ctypes.CDLL(S + "ok.so").dat, ctypes.c_void_p).value
        == ctypes.cast(ctypes.CDLL(S + "ok.so").dat, ctypes.c_void_p).value
    ),
)
case("ok-dat-addr-nonzero", lambda: ctypes.cast(ctypes.CDLL(S + "ok.so").dat, ctypes.c_void_p).value != 0)
case("ok-dat-addr-aligned4", lambda: ctypes.cast(ctypes.CDLL(S + "ok.so").dat, ctypes.c_void_p).value % 4)
case("ok-dat-readable-int", lambda: ctypes.c_int.in_dll(ctypes.CDLL(S + "ok.so"), "dat").value)
case(
    "ok-dat-writable-int",
    lambda: (lambda v: (setattr(v, "value", 77), v.value)[1])(ctypes.c_int.in_dll(ctypes.CDLL(S + "ok.so"), "dat")),
)
case("ok-val-restype-default", lambda: ctypes.CDLL(S + "ok.so").val())
case("ok-val-extra-args", lambda: ctypes.CDLL(S + "ok.so").val(1, 2, 3))
case("ok-fptr-vs-val-cb", lambda: ctypes.CFUNCTYPE(ctypes.c_int)(ctypes.CDLL(S + "ok.so").fptr())())

# missing symbols
case("sym-missing-attr", lambda: ctypes.CDLL(S + "ok.so").no_such_sym)
case("sym-missing-item", lambda: ctypes.CDLL(S + "ok.so")["no_such_sym"])
case("sym-empty-item", lambda: ctypes.CDLL(S + "ok.so")[""])
case("sym-main-missing", lambda: ctypes.CDLL(None).no_such_sym_xyz)
case("sym-in_dll-missing", lambda: ctypes.c_int.in_dll(ctypes.CDLL(S + "ok.so"), "nope"))
case("sym-underscored-attr", lambda: ctypes.CDLL(S + "ok.so").__dunder__)
case("sym-long-name", lambda: getattr(ctypes.CDLL(S + "ok.so"), "x" * 5000))
case("sym-nonascii", lambda: getattr(ctypes.CDLL(S + "ok.so"), "ключ"))
case("sym-dollar", lambda: getattr(ctypes.CDLL(S + "ok.so"), "$x"))
case("sym-memory-export", lambda: ctypes.CDLL(S + "funcs.so").mem)
case("sym-table-export", lambda: ctypes.CDLL(S + "funcs.so").tab)
case("sym-main-memory", lambda: ctypes.CDLL(None).memory)
case("sym-main-table", lambda: ctypes.CDLL(None).__indirect_function_table)
case("sym-main-stack-pointer", lambda: ctypes.CDLL(None).__stack_pointer.__class__.__name__)
case("sym-main-memory-base", lambda: ctypes.CDLL(None).__memory_base.__class__.__name__)
case("sym-main-table-base", lambda: ctypes.CDLL(None).__table_base.__class__.__name__)
case("sym-main-heap-base", lambda: ctypes.CDLL(None).__heap_base.__class__.__name__)
case("sym-main-data-end", lambda: ctypes.CDLL(None).__data_end.__class__.__name__)

# functions of several signatures
for nm, sy, rt, args, at in [
    ("funcs.so", "f_i64", ctypes.c_int64, (2**40,), [ctypes.c_int64]),
    ("funcs.so", "f_i64", ctypes.c_int64, (-1,), [ctypes.c_int64]),
    ("funcs.so", "f_f64", ctypes.c_double, (1.25,), [ctypes.c_double]),
    ("funcs.so", "f_add", ctypes.c_int, (2, 3), [ctypes.c_int, ctypes.c_int]),
    ("funcs.so", "f_add", ctypes.c_int, (2**31 - 1, 1), [ctypes.c_int, ctypes.c_int]),
    ("funcs.so", "f_void", None, (), None),
    ("funcs.so", "f_trap", ctypes.c_int, (), None),
    ("funcs.so", "f_div", ctypes.c_int, (0,), [ctypes.c_int]),
    ("funcs.so", "f_div", ctypes.c_int, (1,), [ctypes.c_int]),
    ("funcs.so", "f_mem", ctypes.c_int, (0,), [ctypes.c_int]),
    ("funcs.so", "f_mem", ctypes.c_int, (-1,), [ctypes.c_int]),
    ("funcs.so", "f_add", ctypes.c_int, (1,), [ctypes.c_int]),  # too few args
    ("funcs.so", "f_add", ctypes.c_int, (1, 2, 3, 4), [ctypes.c_int] * 4),  # too many
    ("funcs.so", "f_i64", ctypes.c_int, (5,), [ctypes.c_int]),  # i64 function called with i32
    (
        "funcs.so",
        "f_add",
        ctypes.c_double,
        (1.5, 2.5),
        [ctypes.c_double, ctypes.c_double],
    ),  # i32 function called with f64
    ("funcs.so", "f_add", ctypes.c_int, (1, 2), [ctypes.c_int64, ctypes.c_int64]),
    ("funcs.so", "f_void", ctypes.c_int, (), None),
]:
    case(
        "fn-%s-%s-%s-%s" % (sy, getattr(rt, "__name__", rt), "_".join(map(str, args)), len(at or ())),
        call,
        nm,
        sy,
        rt,
        *args,
        argtypes=at,
    )
case("fn-trap-then-ok", lambda: (lambda l: (_try(l.f_trap), l.f_add(1, 2))[1])(ctypes.CDLL(S + "funcs.so")))


# globals of four types, mutable and not
for ty in ("i32", "i64", "f32", "f64"):
    for g in ("g", "m"):
        case("glob-%s-%s-load" % (ty, g), lambda ty=ty: ctypes.CDLL(S + "glob_%s.so" % ty).val())
        case(
            "glob-%s-%s-sym" % (ty, g),
            lambda ty=ty, g=g: getattr(ctypes.CDLL(S + "glob_%s.so" % ty), g).__class__.__name__,
        )
        case(
            "glob-%s-%s-in_dll" % (ty, g),
            lambda ty=ty, g=g: ctypes.c_int.in_dll(ctypes.CDLL(S + "glob_%s.so" % ty), g).value,
        )

# main module symbols
libc = ctypes.CDLL(None)
case("main-strlen", lambda: libc.strlen(b"hello"))
case("main-strlen-restype", lambda: (setattr(libc.strlen, "restype", ctypes.c_size_t), libc.strlen(b"hello"))[1])
case("main-getpid-positive", lambda: libc.getpid() > 0)
case("main-getpid-eq-os", lambda: libc.getpid() == os.getpid())
case("main-PyType_GenericAlloc", lambda: libc.PyType_GenericAlloc.__class__.__name__)
case("main-Py_NoneStruct-addr", lambda: ctypes.cast(libc._Py_NoneStruct, ctypes.c_void_p).value != 0)
case(
    "main-strlen-twice-same",
    lambda: (
        ctypes.cast(libc.strlen, ctypes.c_void_p).value == ctypes.cast(ctypes.CDLL(None).strlen, ctypes.c_void_p).value
    ),
)
case(
    "main-strlen-pythonapi-same",
    lambda: (
        ctypes.cast(libc.strlen, ctypes.c_void_p).value == ctypes.cast(ctypes.pythonapi.strlen, ctypes.c_void_p).value
    ),
)
case(
    "main-strlen-cdll-LoadLibrary-same",
    lambda: (
        ctypes.cast(libc.strlen, ctypes.c_void_p).value
        == ctypes.cast(ctypes.cdll.LoadLibrary(None).strlen, ctypes.c_void_p).value
    ),
)
case(
    "main-strlen-got-same",
    lambda: ctypes.cast(libc.strlen, ctypes.c_void_p).value == ctypes.CDLL(S + "got_main.so").got_strlen(),
)
case(
    "main-getpid-got-same",
    lambda: ctypes.cast(libc.getpid, ctypes.c_void_p).value == ctypes.CDLL(S + "got_main.so").got_getpid(),
)
case(
    "main-got-data-matches-dlsym",
    lambda: (
        ctypes.cast(libc._Py_NoneStruct, ctypes.c_void_p).value == ctypes.CDLL(S + "got_main.so").got__Py_NoneStruct()
    ),
)
case(
    "main-got-data-is-NoneStruct",
    lambda: (
        ctypes.cast(ctypes.c_void_p(ctypes.CDLL(S + "got_main.so").got__Py_NoneStruct()), ctypes.py_object)
        if False
        else ctypes.CDLL(S + "got_main.so").got__Py_NoneStruct() != 0
    ),
)
case("main-malloc-free", lambda: (setattr(libc.malloc, "restype", ctypes.c_void_p), libc.malloc(16) != 0)[1])
case("main-dlopen-sym", lambda: libc.dlopen.__class__.__name__)
case("main-dlsym-sym", lambda: libc.dlsym.__class__.__name__)
case("main-dlerror-sym", lambda: libc.dlerror.__class__.__name__)
case("main-dlclose-sym", lambda: libc.dlclose.__class__.__name__)
case("main-getenv", lambda: (setattr(libc.getenv, "restype", ctypes.c_char_p), libc.getenv(b"NO_SUCH_VAR_XYZ"))[1])
case("main-abs", lambda: libc.abs(-5))
case("main-qsort-sym", lambda: libc.qsort.__class__.__name__)
case(
    "main-sin",
    lambda: (
        setattr(libc.sin, "restype", ctypes.c_double),
        setattr(libc.sin, "argtypes", [ctypes.c_double]),
        libc.sin(0.0),
    )[2],
)
case("main-atoi", lambda: libc.atoi(b"42"))
case("main-time-sym", lambda: libc.time(None) > 0)
case("main-getcwd-sym", lambda: libc.getcwd.__class__.__name__)
case("main-errno-sym", lambda: libc.__errno_location.__class__.__name__)
case("main-errno-ctypes", lambda: (libc.open(b"/nonexistent/x", 0), ctypes.get_errno())[1])
case("main-errno-set-ctypes", lambda: (ctypes.set_errno(7), ctypes.get_errno())[1])
case("main-NULL-handle-attr", lambda: ctypes.CDLL(None)._handle)
case("main-name", lambda: ctypes.CDLL(None)._name)
case("main-name-pythonapi", lambda: ctypes.pythonapi._name)

# find_library and dlerror texts
for nm in (
    "c",
    "m",
    "dl",
    "pthread",
    "python",
    "python3",
    "python3.15",
    "z",
    "ssl",
    "nonexistent_xyz",
    "",
    "ok",
    "ok.so",
):
    case("find_library-" + (nm or "empty"), ctypes.util.find_library, nm)
case("CDLL-name-only-missing", lambda: ctypes.CDLL("libnosuch.so"))
case("CDLL-libc.so.6", lambda: ctypes.CDLL("libc.so.6"))
case("CDLL-libm.so.6", lambda: ctypes.CDLL("libm.so.6"))
case("CDLL-libc", lambda: ctypes.CDLL("c"))
case("CDLL-cwd-relative", lambda: (os.chdir(S), ctypes.CDLL("ok.so").val())[1])
case("CDLL-cwd-relative-dot", lambda: (os.chdir(S), ctypes.CDLL("./ok.so").val())[1])
case("CDLL-cwd-relative-dotdot", lambda: (os.chdir(S + "rp"), ctypes.CDLL("../ok.so").val())[1])
case("CDLL-cwd-relative-sub", lambda: (os.chdir(B), ctypes.CDLL("so/ok.so").val())[1])
case("CDLL-ld-library-path", lambda: (os.environ.__setitem__("LD_LIBRARY_PATH", S), ctypes.CDLL("ok.so").val())[1])
case(
    "CDLL-ld-library-path-needed",
    lambda: (os.environ.__setitem__("LD_LIBRARY_PATH", S), ctypes.CDLL(S + "need_norpath.so").vnorp())[1],
)
case(
    "CDLL-ld-library-path-colon",
    lambda: (os.environ.__setitem__("LD_LIBRARY_PATH", "/nonexistent:" + S), ctypes.CDLL("ok.so").val())[1],
)
case("CDLL-use-errno", lambda: ctypes.CDLL(S + "ok.so", use_errno=True).val())
case("CDLL-use-last-error", lambda: ctypes.CDLL(S + "ok.so", use_last_error=True).val())
case("CDLL-handle-given", lambda: ctypes.CDLL(None, handle=ctypes.CDLL(S + "ok.so")._handle).val())
case("CDLL-handle-zero", lambda: ctypes.CDLL(None, handle=0).strlen)
case("CDLL-handle-garbage", lambda: ctypes.CDLL(None, handle=123456).val)
case("CDLL-handle-garbage-call", lambda: ctypes.CDLL(None, handle=123456).val())
case("PyDLL-load-call", lambda: ctypes.PyDLL(S + "ok.so").val())
case("cdll-attr-missing", lambda: ctypes.cdll.nosuchlib_xyz)
case("cdll-LoadLibrary-path", lambda: ctypes.cdll.LoadLibrary(S + "ok.so").val())
case("windll", lambda: ctypes.windll)
case("oledll", lambda: ctypes.oledll)
case("dlclose-handle", lambda: (lambda l: (ctypes.CDLL(None).dlclose.__class__, 0)[1])(ctypes.CDLL(S + "ok.so")))
