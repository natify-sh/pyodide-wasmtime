# Differential audit, area "runtime": our guest against Pyodide 315.0.0a2 on Node

Nothing was fixed in this step; only `tools/diff_pyodide.py`, `tools/diff_probes/runtime_*.py` and this file were added.
Every number below comes from a run of the harness on this machine (Linux, wasmtime-py 50.0.1, Node of the audit's
`work/dl/dist`), on both packagings. **Fused and dynamic agree on every probe** (the same differing cases, the same text).

## 1. The harness

```
uv run python tools/diff_pyodide.py [--tz TZ] [--site DIR] [--flavors fused,dynamic] PROBE.py [PROBE.py ...]
DIFF_TIMEOUT=100 (seconds per run), KEEP=1 (write the normalised outputs next to the probe), PYODIDE_DIST=<dist with pyodide.mjs>
```

* A probe prints one line per case, `case-id | result` (`ERR errno-name` for an OSError, `EXC Type text` for another error).
  A file may hold several programs (`# --- name`), each run in a fresh interpreter (needed for exit and crash probes).
* The probes of the matrices print `>> case-id` before a case: a case that kills the guest becomes `case-id | DEAD` and
  the program restarts after it (`SKIP = n`), so one trap does not hide the rest of the matrix.
* Pyodide is run by a generated Node script (`loadPyodide`, `runPython` of the file; stdout and stderr merged). The exit
  status is derived from what `runPython` throws (`ExitStatus n` -> `n & 255`, `SystemExit` -> its status as `python file`
  would give, another Python exception -> 1, a wasm trap or a fatal error -> 134); ours is the process return code. This
  is an emulation: Pyodide on Node does not end the process on `sys.exit`.
* Normalised: the probe's temp directory, hex addresses, trailing blanks, `<string>:12:`/`<exec>:12:` of warnings,
  tracebacks (cut to `TRACEBACK last-line`), a trap in either report (`TRAP`), a refused proc_exit (`HOSTFAIL reason`).
* `--site DIR` copies a folder into ours and mounts it (NODEFS, `/site`) for Pyodide: used for cffi (`testenv/site_cffi`).
* The CPU time of the harness itself is small; a full run of all probes is about 40 minutes on 4 shared cores.

## 2. Probe files

Case counts are the lines Pyodide printed (a case is one line, plus a few `TRAP`/`EXIT-STATUS` lines).
"diff lines" counts `-` plus `+` lines of the unified diff (so 2 lines = 1 case).

| file | what | cases | diff lines (fused = dynamic) |
|---|---|---|---|
| `runtime_time1.py` | gmtime, localtime (+gmtoff, zone), asctime, ctime, timegm, mktime(localtime), strftime (two formats), fromtimestamp, astimezone, timestamp for 90 instants (0, -1, 2**31, 2**32, 2**53, 2**63, +-8.64e12 and their neighbours, year/leap/DST edges, floats, inf, nan, wrong types) | 1070 per TZ | 0 in each of 7 TZ |
| `runtime_time2.py` | mktime and timegm on 36 years x 15 field sets x isdst -1/0/1, months -14..25, strptime (15 formats), datetime round trips, 50 strftime formats x 5 instants x local/gm | 3439 per TZ | 10 per TZ (5 cases: N1) |
| `runtime_clocks.py` | time/monotonic/perf_counter/process_time/clock_gettime for 24 clock ids, clock_getres, sleep values, nanosleep, clock_nanosleep, usleep, times(), clock(), granularity, ordering | 187 | 36 (N3 and a harmless gcd probe) |
| `runtime_hangs.py` | 15 sleeping calls, one program each, 25 s limit | 15 programs | 0 |
| `runtime_signals.py` | strsignal/getsignal/signal/raise_signal/os.kill(getpid)/pthread_kill/siginterrupt for signals -1..69, SIG_IGN, default actions, valid_signals, alarm/setitimer via ctypes in a busy loop, KeyboardInterrupt, handler exceptions, libc raise/kill | 610 | 10 (known: K1) |
| `runtime_exit.py` | sys.exit with 19 argument classes, os._exit 9, os.abort, uncaught exceptions, atexit (+SystemExit in a handler), unflushed output, C exit/_exit/_Exit/abort/atexit, raise/kill of every default-action signal, `__assert_fail` in 8 forms, `_abort_js`, traps, MemoryError, recursion, excepthook, closed stdout/stderr | 97 programs | 23 programs differ (N2 x 12, N4, N6, N7, N10, N11, and notes: faulthandler frames, closed stdout/stderr at exit, `sys.exit('')` emulation) |
| `runtime_info.py` | sys.*, platform, os.uname/getpid/getuid/.../cpu_count, getrandom/urandom sizes and errors, sysconf (all names), confstr, pathconf, resource (not importable in either), environ, locale, encodings, emscripten heap/now functions, progname, passwd/group, sysconfig, supports_*, dir() of os/signal/time/select, errno table, strerror 0..139 | 585 | 76 (N8, N9, notes) |
| `runtime_ffi.py` | ctypes: every integer/float/long double/pointer class, 30 integer values x 8 functions, 26 libm functions x 24 doubles, variadic snprintf with 40 argument shapes, default restype/argtypes and TypeError texts, >8 and up to 1000 arguments, structs (small, large, nested, unions, bitfields, packed, arrays of 1..65536 bytes) by value as argument/return/3 times, qsort/bsearch comparators, callbacks of every class, a callback that raises, nested callbacks, 10000 closures | 1917 | 4 volatile (an address, an uninitialised result: fixed in the probe afterwards) |
| `runtime_ffi_crash.py` | 37 calls that crash the guest (NULL, wild pointers, wrong signatures, BigInt/Number mismatch, 100-deep struct) | 37 programs | 3 programs (`string_at(0)`/`string_at(None)`: the bytes at address 0, a layout note; the 100-deep struct: K2) |
| `runtime_cffi.py` | cffi 2.0.0 (wheel's `_cffi_backend`): calls, 19 callback signatures (each also through a cast function pointer), struct arguments/returns, qsort/bsearch, onerror/error, 2000 and 1000 callbacks alive | 203 | 12 (N5 again, and an artefact of the restart) |
| `runtime_dlsym.py` | `hasattr(CDLL(None), name)` for the 264 audited imports and 71 libc/emscripten names | 336 | 386 (N10) |
| `runtime_repro.py` | one minimal program per NEW difference (N1..N10): run alone, deterministic | 13 programs | all as listed below |

TZs run for time1/time2: UTC, Europe/Kyiv, America/New_York, Australia/Lord_Howe, Asia/Kolkata, EST5EDT, Pacific/Chatham
(an earlier version of the two files also ran in Europe/Dublin, America/St_Johns, Pacific/Apia, America/Sao_Paulo,
Africa/Casablanca: the same result). The time imports of the audit (`_gmtime_js`, `_timegm_js`, `_localtime_js`,
`_tzset_js`) have **no** difference in 4509 cases x 7 zones; `_mktime_js` has one corner (N1).

### Not a difference, but worth knowing (found while writing the probes)

* The first draft of the clock probe seemed to show that libc `nanosleep` hangs on both sides. It was the probe: on
  wasm32 `struct timespec` is `{int64 sec; int32 nsec; pad}`, 16 bytes, not two `c_long`. With the right layout all 15
  sleeping programs agree.
* `atexit` handlers do not run at the end of a normal run in ours (`print` then end: no `atexit ran`), as in Pyodide's
  `runPython`; CPython's own CLI runs them. Equal to Pyodide (the owner's finding), so not listed as a difference.
* `sys.exit('msg')`, `sys.exit([1])`... in ours print the text to stderr and give 1; the emulated Pyodide side prints the
  same. `sys.exit(2**63)` gives 255 in ours (CPython does the same).
* `resource` is not importable in either (Pyodide: "unvendored", ours: "Unsupported platform"); the texts differ.
  `pwd`, `grp`, `select`, `fcntl` import in both.
* `getdomainname()` returns stack garbage in ours (`b'\x01X\xff\xdf'`) and `b''` in Pyodide: the libc's `uname` leaves the
  field unset and `getdomainname` copies an uninitialised stack word (the same wasm code on both sides; not the adapter).
* A read of guest memory at address 0 (`ctypes.string_at(0, 4)`) gives different bytes: the memory layouts differ (ours
  has no data segment below the same address).

## 3. NEW differences

Severity: crash/trap > wrong exit code/errno/exception > cosmetic. "Fix" names the place; nothing was changed.

| id | case | Pyodide | ours | glue's reason (JS name) | POSIX-right | severity | suggested fix location |
|---|---|---|---|---|---|---|---|
| N5 | a `CFUNCTYPE` callback with 3 or more arguments (`int,double,int`; also cffi `callback("int(...)")` of 9 mixed arguments) that makes a WASI call writing a struct (`os.fstat(1)`, `isatty`, and the traceback printing of an ignored exception): `repro N5` | prints 0, exit 0 | **trap** (134): `wasi_snapshot_preview1::fd_filestat_get/fd_fdstat_get: Pointer not aligned to 8` (the same with 2 arguments works, by luck of the sizes) | `ffi_prep_closure_loc_js` closure: `stackAlloc` keeps the stack pointer 16-aligned; JS WASI has no alignment check | ours: the wasm ABI needs a 16-byte aligned `__stack_pointer`; any host (wasmtime) checks it | **crash**, found from a cffi probe (`onerror` path), any callback that does I/O | `_host.py` `_ffi_closure`: after the last `put`, align `cur` down to 16 before `sp.set_value(ctx, cur)` (and check `_ffi_call` the same way) |
| N2 | `os._exit(n)`, C `exit(n)`, `_exit`, and the default action of a signal (SIGTERM 143, SIGKILL 137, SIGUSR1 138; `raise(SIGSEGV)`/`abort` are traps on both sides and agree) for any status >= 126 or < 0: `repro N2, N2b, N2c` | `ExitStatus n & 255` (255, 143, 137, 200, ...) | host function failed, the guest is dead: `exit with invalid exit status outside of [0..126)`, return code 134, plus a 20-line backtrace on stderr | `exitJS` -> `_proc_exit(status)` takes any number; Node masks it with 255 | exit status `n & 255` | **wrong exit code + noisy failure**; every default-action signal (128+n) ends so | adapter `sc_exit` / the host's `proc_exit` import: mask with 255 in the host function (wasmtime's own WASI refuses >= 126) |
| N3 | `time.clock_gettime(2)`, `(3)` (CLOCK_PROCESS_CPUTIME_ID, CLOCK_THREAD_CPUTIME_ID), `clock_getres(2/3)`, `time.process_time()`, `time.process_time_ns()`, C `clock()`: `repro N3` | work (the monotonic clock, res 1e-9); `process_time` is `clock()`-based | `OSError EBADF`; `process_time()` raises `RuntimeError: the processor time used is not available`; `clock()` returns -1; `clock_getres(0)` and `get_clock_info('time').resolution` are 1e-9 (Pyodide 1e-3: `_clock_res_get` gives 1e6 ns for the realtime clock, cosmetic) | `_clock_time_get`: ids 0..3 are accepted (`checkWasiClock`), 0 = `Date.now`, 1..3 = `emscripten_get_now`; `_clock_res_get` likewise | CPU clocks are valid on Linux | wrong errno + Python exception (anything using `time.process_time`: `profile`, `timeit` of some versions, many benchmarks) | the host's WASI `clock_time_get`/`clock_res_get` (wasmtime's WASI answers EBADF for ids 2, 3): answer them from the monotonic clock, or from `time.process_time_ns()` of the host |
| N4 | `sys.exit(True)` | status 1 | `ValueError: invalid literal for int() with base 10: 'True'` from the host, a traceback, no status | CPython's `handle_system_exit` takes a bool as an int | exit status 1 | wrong behaviour (host bug) | `_host.py` `_WRAPPER`: `_rc = int(_c)` (the status is written as `str(True)` and read back with `int()`) |
| N6 | uncaught exception with a custom `sys.excepthook`: `repro N6` | the hook is called | not called: `traceback.print_exc()` of the wrapper prints | (Pyodide's `eval_code` path reaches `sys.excepthook`) | CPython calls `sys.excepthook` | wrong behaviour | `_host.py` `_WRAPPER`: `except BaseException: _s.excepthook(*_s.exc_info())` |
| N7 | `print("x")` (no flush) then a trap/abort/`os._exit`/a crash, with stdout a pipe or file: `repro N7`; and `sys.stdout.line_buffering` | `True`: the line is out | `False`: the line is lost (CPython on a pipe is block-buffered too, but Pyodide is line-buffered everywhere and code written for it relies on that) | Pyodide's `_pyodide._base` sets stdout line-buffered | CPython: block-buffered unless a tty | data loss on a crash; interleaving of stdout and stderr differs | `_host.py` after start: `sys.stdout.reconfigure(line_buffering=True)` (or the same line in `_AT_START`) |
| N8 | environment: `HOME`, `USER`, `LOGNAME`, `PATH`, `LANG`, `PYTHONINSPECT`, `os.path.expanduser("~")`, `pathlib.Path.home()`, `getpass.getuser()`, `os.getlogin()`, `os.get_exec_path()`: `repro N8` | `HOME=/home/pyodide USER=web_user LOGNAME=web_user PATH=/ LANG=en_US.UTF-8 PYTHONINSPECT=1`; `expanduser('~')=/home/pyodide`, `getuser()=web_user`, `getlogin()=web_user`, `get_exec_path()=['/']`, locale `('en_US','UTF-8')` | none of the first four; `LANG=C.UTF-8`; `expanduser('~')='~'`, `Path.home()` raises `RuntimeError: Could not determine home directory`, `getuser()` raises `OSError: No username set`, `getlogin()` ENXIO, `get_exec_path()=['/bin','/usr/bin']`, locale `('C','UTF-8')`; extra: `PYTHONHOME=/`, `PYTHONPATH=/lib/python3.15/site-packages`, `PYTHONDONTWRITEBYTECODE=1`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE` visible in `os.environ` | the glue's `ENV` object (`USER, LOGNAME, PATH, PWD, HOME, LANG, _`) and `PYTHONINSPECT` set by Pyodide's config | any | wrong behaviour of `Path.home`, `getpass.getuser`, `expanduser` | `_host.py` `BASE_ENV`: add `HOME=/home/pyodide`, `USER`, `LOGNAME`, `PATH=/`; PYTHON* variables could be set through the interpreter's config instead of `environ` (they leak to the guest's children and `os.environ` copies) |
| N9 | `sys.path`, `sys._stdlib_dir`, `sys.executable`, `sys.flags.inspect`, `sys.excepthook.__name__`, `sys.meta_path`, `sys.orig_argv`: `repro N9` | `['', '/lib/python315.zip', '/lib/python3.15/lib-dynload', '/lib/python3.15/site-packages']`, stdlib dir the zip, executable the script path, `inspect=1`, `excepthook` is Pyodide's `print_exception`, `meta_path` has `JsFinder` and `WindowsToLinuxPathFinder` | `['/lib/python3.15/site-packages', '/lib/python315.zip', '/lib/python3.15', '/lib/python3.15/lib-dynload']` (**site-packages first**: a wheel can shadow the stdlib), stdlib dir the folder, `executable=''`, `inspect=0`, default excepthook, no `JsFinder` (JS bridge: documented), `orig_argv=[]` | `PYTHONPATH` set by `BASE_ENV` puts site-packages first; Pyodide's config | normal order is stdlib, then site-packages | cosmetic, except the shadowing | `_host.py` `BASE_ENV` (see N8); `sys.executable` from the progname |
| N10 | `hasattr(CDLL(None), name)` for the glue's library functions that no wasm of the build calls: `emscripten_get_now_res`, `emscripten_random`, `emscripten_console_log/warn/error`, `emscripten_out`, `emscripten_err`, `emscripten_run_script`, `emscripten_run_script_int`, `emscripten_force_exit`, `emscripten_exit_with_live_runtime`, `emscripten_get_callstack`, `emscripten_pc_get_function`, `emscripten_async_call`, `emscripten_set_main_loop`, `emscripten_unwind_to_js_event_loop`, `emscripten_has_asyncify`, `emscripten_get_compiler_setting`, `emscripten_notify_memory_growth` (19 names, not in `import_audit.json`); in `import_audit.json` but absent from dlsym: 11 `hook` and 9 `js-bridge` names, 149 `js-value` names (bridge), `__syscall_epoll_create1/ctl/pwait`, `__syscall_pipe2` | found (the glue's `wasmImports` is the symbol table of a side module) | missing: a wheel whose `.so` imports one of them does not load (not tested here: no compiler for a side module in this step) | `wasmImports` holds every `library_*.js` function | n/a | medium (side modules), the bridge names are deliberate | adapter: the 19 non-bridge names are small (`emscripten_get_now_res`, `emscripten_random`, `emscripten_console_*` to stderr, `emscripten_out/err`, `emscripten_force_exit` = `sc_exit`); the `audit_imports.py` list should include the glue's library, not only the main module's imports |
| N11 | `ctypes.string_at(0x7fffffff)` / a C string pointer beyond the memory in `__assert_fail(cond, file, line, func)`: program `__assert_fail bad ptr` | `Aborted(Assertion failed: , at: f,1,g)` then the fatal error (a JS typed-array read past the end is `undefined`, the string ends) | `Aborted(Assertion failed: ` and a trap (the adapter reads the guest memory directly) | `UTF8ToString` on `HEAPU8` | UB | cosmetic | none needed; noted because the same holds for any adapter read of a bad guest pointer |
| N1 | `time.mktime((-271821, 6, 15, 12, 0, 0, 0, 0, 1))` (year -271821 after Apr 20, isdst=1), 5 cases per zone, the same in 6 zones | `OverflowError: mktime argument out of range` | returns `-8639995118400.0` (in UTC) | `_mktime_js`: `new Date(date.getFullYear(), 0, 1)` is an Invalid Date for -271821 (Jan 1 is before the limit), so `winterOffset` is NaN, `dstOffset` NaN, `dst>0 != (NaN==guessed)` is true and the shift is NaN: -1 | ours is a valid time; Pyodide's is JS's NaN | cosmetic (a corner of a corner) | `_host.py` `_t_mktime`: treat `winter` as NaN when Jan 1 of the year is before -8.64e12 s (`_year_minutes`); only `dst > 0` is affected |

The audit's entries `_gmtime_js`, `_timegm_js`, `_localtime_js`, `_tzset_js`, `emscripten_date_now`, `emscripten_get_now`,
`__call_sighandler`, `_Py_CheckEmscriptenSignals_Helper`, `__assert_fail` (text and status), `_abort_js` (text and 134),
`exit` (no atexit, no flush), `emscripten_get_heap_max`, `ffi_call_js`, `ffi_closure_alloc_js`, `ffi_closure_free_js`,
`_PyEM_TrampolineCall_JS` agree with Pyodide on every case of these probes (the exceptions are in the tables).

## 4. KNOWN differences re-observed

| id | entry (`docs/import_audit.json`) | gap | observed |
|---|---|---|---|
| K1 | `_setitimer_js` | "A timer fires inside a busy Python loop ... JavaScript fires it after the synchronous run" (deliberate) | `alarm(1)` and `setitimer` REAL oneshot/interval, VIRTUAL, PROF in a 1-3 s busy loop: ours delivers (`[14]`, `True`), Pyodide never (`[]`, `False`): 5 cases. A timer that is not due during `sleep(0.2)` and one due during `sleep(0.3)`: both give `[]` on both sides |
| K2 | `ffi_call_js`, `ffi_prep_closure_loc_js` | "an ffi_type nested more than 64 deep ends the interpreter" | a struct nested 100 deep: Pyodide computes `sizeof` 4 and calls the callback; ours traps (and, with stdout block-buffered, loses the `print(sizeof(T))` line: N7) |
| K3 | `emscripten_resize_heap` | "JS also fails a request below the current size once the memory is at its maximum; here it is 1" | `resize_heap(1)` and `(0)` after growing to 0xFFFF0000: Pyodide 0, ours 1 |
| K4 | `_emscripten_system` | `enosys` (a shell of the host is a way out of the sandbox) | `os.system("true")`: Pyodide 0 (child_process), ours -1 |
| K5 | `_emscripten_get_progname` / `_Py_emscripten_runtime` | `./this.program` when not run from a script | the harness runs a script: Pyodide gives its path, ours `./this.program` (`sys.executable` is `''` in ours: N9). `sys._emscripten_info.runtime` is not compared (it is volatile by design) |
| K6 | JS bridge | `JsFinder` in `sys.meta_path`, `_pyodide_core` in `sys.builtin_module_names` (the only name Pyodide has and ours lacks), Pyodide's `excepthook`; `asyncio.run` fails on this Node with "WebAssembly stack switching not supported" (Pyodide's WebLoop) and works in ours | observed in `runtime_info.py` |

## 5. Host-dependent

* `sys.argv`: ours is the file's path (the CLI runs a file), Pyodide's is `['']`.
* `/dev/null` and the other devices are absent without `--dev` (`open('/dev/null')` is ENOENT in ours; Pyodide has them): the
  files area. The probes avoid it.
* `os.cpu_count()`, `sched_getaffinity`, `getloadavg`, `SC_NPROCESSORS_*`, `SC_PHYS_PAGES`: compared as names only in
  `runtime_info.py`; their values are equal on both sides in this run (the answers are fixed in the adapter/libc, not read
  from the host).
* `time.localtime` and friends follow the host's TZ on both sides (the harness gives both the same TZ; with a different
  TZ for the two processes every case differs, as expected).
* The surrogate output (`print('\udcff')`): ours prints one replacement character, Pyodide two (JS decodes the bytes):
  cosmetic.

## 6. Not probed

* The TZ of Windows/macOS hosts (the audit's `gaps` item for `_mktime_js`/`_localtime_js`): this machine is Linux.
* `Pyodide.interrupt()` from another thread (K of `_Py_CheckEmscriptenSignals_Helper`): the harness has no second thread; a
  signal from the host's own side is covered by `tests/test_signals.py`.
* A real side module that imports one of the glue's library functions (N10): no wasm toolchain in this step; only dlsym
  visibility was compared.
* `time.thread_time` and `CLOCK_BOOTTIME`/`CLOCK_TAI` values: `thread_time` does not exist in either; the clock ids
  are compared for type and range only (values are volatile).
* Long-running stability (the 10000-closure case runs once, about a second).
* `resource` (`getrlimit`, `getrusage`, `getpagesize`): the module cannot be imported on either side, so the matrix of
  the brief is empty for it; through ctypes only `getpagesize`/`sysconf(30)` were compared (equal).
* Pyodide's own `loadPackage` of cffi: the wheel was unpacked and put on `sys.path` (NODEFS) for Pyodide, as the brief allowed.
