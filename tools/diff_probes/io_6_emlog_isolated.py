# ruff: noqa
# type: ignore
# isolate
# emscripten_log family, libc output, process calls: one case per interpreter (Pyodide dies on some).
import ctypes
import fcntl
import io
import os
import select
import selectors
import stat
import sys
import termios

libc = ctypes.CDLL(None, use_errno=True)
# emscripten_log family through ctypes
for fn in (
    "emscripten_log",
    "emscripten_log_impl_js",
    "_emscripten_log_formatted",
    "emscripten_out",
    "emscripten_err",
    "emscripten_outn",
    "emscripten_errn",
    "emscripten_console_log",
    "emscripten_console_warn",
    "emscripten_console_error",
    "emscripten_console_trace",
    "emscripten_get_callstack",
    "emscripten_debugger",
    "emscripten_pc_get_function",
    "emscripten_print_double",
    "_emscripten_out",
    "_emscripten_err",
    "emscripten_dbg",
    "emscripten_dbgn",
    "emscripten_run_script",
    "emscripten_run_script_int",
    "emscripten_run_script_string",
    "emscripten_get_now",
    "emscripten_get_compiler_setting",
    "emscripten_throw_string",
    "emscripten_throw_number",
    "emscripten_exit_with_live_runtime",
    "emscripten_force_exit",
    "emscripten_get_heap_max",
    "emscripten_resize_heap",
    "emscripten_get_heap_size",
    "emscripten_stack_get_free",
    "emscripten_stack_get_base",
    "emscripten_stack_get_end",
    "emscripten_stack_get_current",
    "emscripten_random",
    "emscripten_date_now",
    "emscripten_performance_now",
    "emscripten_sleep",
    "emscripten_scan_registers",
    "emscripten_has_asyncify",
    "emscripten_asm_const_int",
    "emscripten_notify_memory_growth",
    "emscripten_console_debug",
    "emscripten_console_info",
):
    case("sym-" + fn, lambda fn=fn: hasattr(libc, fn))
libc.emscripten_log.argtypes = None
for fl in (0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 3, 5, 6, 1 | 2, 1 | 4, 1 | 512, 1 | 256, 8 | 1, 0xFFFF, -1):
    case("emlog-flags-%d" % fl, lambda fl=fl: libc.emscripten_log(fl, b"[emlog %d]", 5))
case("emlog-empty", lambda: libc.emscripten_log(0, b""))
case("emlog-newlines", lambda: libc.emscripten_log(0, b"[a\nb\n]\n\n"))
case("emlog-trailing-space", lambda: libc.emscripten_log(0, b"[x]   \t"))
case("emlog-percent-s", lambda: libc.emscripten_log(0, b"[%s]", b"str"))
case("emlog-percent-d-neg", lambda: libc.emscripten_log(0, b"[%d]", -1))
case("emlog-percent-f", lambda: libc.emscripten_log(0, b"[%f]", ctypes.c_double(1.5)))
case("emlog-percent-x", lambda: libc.emscripten_log(0, b"[%x]", 255))
case("emlog-percent-ld", lambda: libc.emscripten_log(0, b"[%ld]", ctypes.c_long(2**31 - 1)))
case("emlog-percent-lld", lambda: libc.emscripten_log(0, b"[%lld]", ctypes.c_longlong(2**40)))
case("emlog-percent-p", lambda: libc.emscripten_log(0, b"[%p]", None) if False else "skipped")
case("emlog-percent-c", lambda: libc.emscripten_log(0, b"[%c]", 65))
case("emlog-percent-percent", lambda: libc.emscripten_log(0, b"[100%%]"))
case("emlog-percent-s-null", lambda: libc.emscripten_log(0, b"[%s]", None))
case("emlog-big", lambda: libc.emscripten_log(0, b"x" * 20000))
case("emlog-nonascii", lambda: libc.emscripten_log(0, "[ключ]".encode()))
case("emlog-invalid-utf8", lambda: libc.emscripten_log(0, b"[\xff\xfe]"))
case("emlog-impl-js", lambda: libc.emscripten_log_impl_js(b"[impl_js]"))
case("emlog-impl-js-null", lambda: libc.emscripten_log_impl_js(None))
case("emlog-impl-js-empty", lambda: libc.emscripten_log_impl_js(b""))
for nm in (
    "emscripten_out",
    "emscripten_err",
    "emscripten_console_log",
    "emscripten_console_warn",
    "emscripten_console_error",
    "emscripten_dbg",
):
    case("em-" + nm, lambda nm=nm: getattr(libc, nm)(b"[%s]" % nm.encode()))
    case("em-" + nm + "-empty", lambda nm=nm: getattr(libc, nm)(b""))
for nm in ("emscripten_outn", "emscripten_errn", "emscripten_dbgn"):
    case("em-" + nm, lambda nm=nm: getattr(libc, nm)(b"[%s-abcdef]" % nm.encode(), 5))
    case("em-" + nm + "-0", lambda nm=nm: getattr(libc, nm)(b"[zero]", 0))
    case("em-" + nm + "-big", lambda nm=nm: getattr(libc, nm)(b"[big]", 100))
case("em-print-double", lambda: libc.emscripten_print_double(ctypes.c_double(1.5), None, 0))
case("libc-puts", lambda: libc.puts(b"[puts]"))
case("libc-printf", lambda: libc.printf(b"[printf %d]\n", 5))
case("libc-printf-no-newline", lambda: libc.printf(b"[printf-nonl]"))
case("libc-fflush", lambda: libc.fflush(None))
case("libc-write-1", lambda: libc.write(1, b"[cwrite]\n", 9))
case("libc-write-2", lambda: libc.write(2, b"[cwrite2]\n", 10))
case("libc-write-bad-fd", lambda: (libc.write(99, b"x", 1), ctypes.get_errno())[1])
case("libc-read-0", lambda: (libc.read(0, ctypes.create_string_buffer(10), 10), ctypes.get_errno())[0])
case("libc-fputs-stdout", lambda: libc.fputs(b"[fputs]\n", ctypes.c_void_p.in_dll(libc, "stdout")))
case("libc-fputs-stderr", lambda: libc.fputs(b"[fputs-err]\n", ctypes.c_void_p.in_dll(libc, "stderr")))
case("libc-putchar", lambda: libc.putchar(65))
case("libc-putchar-nl", lambda: libc.putchar(10))
case("libc-perror", lambda: libc.perror(b"[perror]"))
case("libc-fprintf-stderr", lambda: libc.fprintf(ctypes.c_void_p.in_dll(libc, "stderr"), b"[fprintf-err %d]\n", 3))
case("libc-setvbuf", lambda: libc.setvbuf(ctypes.c_void_p.in_dll(libc, "stdout"), None, 2, 0))
case("libc-isatty", lambda: [libc.isatty(i) for i in (0, 1, 2)])
case("libc-ttyname", lambda: libc.ttyname(0))
case("libc-getchar-eof", lambda: libc.getchar())
case("libc-fgets-eof", lambda: libc.fgets(ctypes.create_string_buffer(10), 10, ctypes.c_void_p.in_dll(libc, "stdin")))
case("libc-feof-stdin", lambda: libc.feof(ctypes.c_void_p.in_dll(libc, "stdin")))
case("libc-ferror-stdout", lambda: libc.ferror(ctypes.c_void_p.in_dll(libc, "stdout")))
case("libc-fileno-stdout", lambda: libc.fileno(ctypes.c_void_p.in_dll(libc, "stdout")))
case("libc-fwrite-stdout", lambda: libc.fwrite(b"[fwrite]\n", 1, 9, ctypes.c_void_p.in_dll(libc, "stdout")))
case("libc-sleep-0", lambda: libc.sleep(0))
case("libc-usleep", lambda: libc.usleep(1000))
case("libc-nanosleep-neg", lambda: libc.nanosleep(ctypes.byref(ctypes.c_longlong(-1)), None))
case("libc-clock", lambda: libc.clock() >= 0)
case("libc-system-null", lambda: libc.system(None))
case("libc-system-echo", lambda: libc.system(b"echo hi"))
case("os-system-echo", lambda: os.system("echo hi"))
case("os-popen", lambda: os.popen("echo hi").read())
case("subprocess-run", lambda: __import__("subprocess").run(["echo", "hi"]))
case("os-fork", lambda: os.fork())
case("os-spawn", lambda: os.spawnv(os.P_WAIT, "/bin/true", ["true"]))
case("os-wait", lambda: os.wait())
case("os-kill-self-0", lambda: os.kill(os.getpid(), 0))
case("os-kill-other", lambda: os.kill(99999, 0))
case("os-getppid", lambda: os.getppid() >= 0)
case("os-nice", lambda: os.nice(0))
case("os-umask", lambda: (os.umask(0o22), os.umask(0o22))[1])
case("os-times", lambda: len(os.times()))
case("os-pathconf", lambda: os.pathconf("/", "PC_NAME_MAX"))
case("os-statvfs", lambda: os.statvfs("/").f_bsize > 0)
case("os-get-exec-path", lambda: os.get_exec_path())
case("os-defpath", lambda: os.defpath)
case("os-confstr", lambda: os.confstr("CS_PATH"))
case("os-device-encoding-0-1-2", lambda: [os.device_encoding(i) for i in (0, 1, 2, 3)])
