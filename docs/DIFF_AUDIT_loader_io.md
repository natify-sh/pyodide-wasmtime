# Differential audit: loader, mmap, standard streams and poll (ours against the real Pyodide 315.0.0a2 on Node)

Nothing was fixed in this step: `wasm/adapter*`, `src/` and `tests/` are untouched. The harness, the probes and this
report are new. Machine: Linux, 4 shared cores, wasmtime-py 50.0.1, Node 22; ours built from `410bede`
(`tools/build_data.sh`), the baseline is `work/dl/dist` (Pyodide 315.0.0a2 on Node). Every number below is from the
runs of these probes; the raw outputs are not committed (`--keep DIR` writes them).

## 1. The harness

```
PYODIDE_DIST=<dir with pyodide.mjs> uv run python tools/diff_pyodide.py [--flavors fused,dynamic] [--keep DIR] \
    [--ours-arg=--dev] [--isolate] [--jobs N] tools/diff_probes/PROBE.py ...
```

* `tools/diff_pyodide.py` puts `tools/diff_probes/_prelude_io.py` in front of a probe (the fresh directory `B`, `case(id, fn)`
  that prints `id | result` or `id | ERR ENAME`/`EXC Type: text`, and the side modules of `_sides.py` written to
  `B/so/`), runs it on Pyodide (Node, `/dist` = NODEFS of `PYODIDE_DIST`) and on ours (`--mount /dist=...`), fused and
  dynamic, normalises (the probe directory, addresses, pids, inode numbers, times, the text after `| CRASH`) and prints
  a unified diff per flavor. Exit 0 if there is no difference.
* A probe with `# isolate` on a line of its own near the top (or `--isolate`) runs every case in a fresh interpreter
  (3 targets x N cases, 60 s each): necessary for the loader (a failed load leaves state in the glue: after one failed
  GOT.mem import every later load on Pyodide fails with "undefined symbol 'errno'", and a NEEDED name resolves only
  after an earlier load by path) and for cases that kill the guest. A dead isolated case shows as `id | CRASH ...`.
* `tools/diff_probes/_sides.py` builds the side modules with `tests/sidemod.py` (about 150 files: dylink.0 variants,
  NEEDED chains 2/3/5/10/25/50, cycles, rpaths, GOT.func/GOT.mem, env imports, globals of the four types, traps in
  start/ctors, junk, truncated). Probe files are guest programs (`# ruff: noqa`, `# type: ignore`).

## 2. Probe files, cases, differences

"Differences" = cases whose line differs from Pyodide, from the last run of the file. Fused and dynamic agree
(same case ids) except where marked.

| file | cases | fused | dynamic | notes |
|---|---|---|---|---|
| loader_1_load.py (isolated) | 215 | 22 | 21 | paths, every module of `_sides`, calls; the 1 extra on fused is `load-path-long255` = an artefact (the 300-char cut of the output with a B of another length, fixed afterwards: B is fixed width now) |
| loader_2_dlsym.py (isolated) | 166 | 16 | 14 | modes, dlopen twice, dlsym, globals, main symbols, pointer identity, find_library, CDLL names, handles; flavors differ in `sym-main-memory-base/table-base` (text only) |
| loader_3_wheels.py | 78 | 0 | 0 | numpy 2.4.3 wheel unzipped from `/dist`: 13 `.so`, 34 submodule imports, linalg/fft/random/memmap/ctypeslib, a junk/empty/PyInit-less extension |
| loader_4_edl.py (isolated) | 18 | 13 | 13 | `emscripten_dlopen` with ctypes callbacks |
| mmap_1_matrix.py | 624 | 7 | 7 | length x offset x access x prot x flags x fd kinds, anonymous, 80 operations, two mappings, truncate/unlink/rename under a mapping |
| mmap_2_libc_isolated.py (isolated) | 74 | 1 | 1 | libc mmap/munmap/msync/mprotect/madvise |
| io_1_streams.py | 604 | 151 | 151 | sys.std*, isatty, terminal size, ioctl/termios/fcntl/blocking/fsync/lseek/fstat on fds 0-2, a file, a dir, pipe ends, /dev/null (most of the 151 are the pipe and /dev/null rows: no pipe, no /dev) |
| io_2_poll.py | 111 | 38 | 38 | select/poll/selectors, timeouts, epoll absent |
| io_3_dev_env_log.py | 500 | 176 | 176 | 21 device paths x 13 operations, /proc, /sys, directories, the environment and the C getenv/setenv, sysconf (without `--dev`; with `--ours-arg=--dev` 278/300, see 5) |
| io_4_isolated.py (isolated) | 62 | 19 | 19 | hangs, zero-length reads, closing std fds, descriptor numbers, EMFILE, signals/exit |
| io_5_poll_isolated.py (isolated) | 37 | 14 | 14 | libc poll/epoll/eventfd, pipes, socketpair |
| io_6_emlog_isolated.py (isolated) | 155 | 47 | 47 | emscripten_log (22 flag values, about 14 formats), emscripten_out/err/..., libc stdio, system, fork/spawn |

About 2750 cases. After the last runs I only changed: `_prelude_io.py` (B has a fixed width), a `pollcase` helper in
io_5 (its pipe rows said NameError on Pyodide), ruff formatting; loader_3 was re-run after that (0 differences), the
others were checked with a dry listing of their case ids.

## 3. NEW differences (not in `import_audit.json`)

Severity: HANG/crash > wrong result > wrong errno > cosmetic. Cases were reproduced alone (isolated runs and one-off
scripts), both flavors, unless marked.

| case-id | Pyodide | ours | the glue's reason | POSIX-right | severity | fix location |
|---|---|---|---|---|---|---|
| os-read-stdin-0, os-readv-stdin-empty-buffer, os-readv-stdin-no-buffers, sys-stdin-buffer-raw-read-0, ...raw-readinto-empty, sys-stdin-fd-open-read-0 (`os.read(0, 0)`, `os.readv(0, [])`) | `b''` / 0 | HANG forever (60 s timeout; stdin /dev/null or a pipe with data, both flavors; `os.read(file, 0)` and `sys.stdin.read(0)` are fine) | `doReadv`: total length 0 returns 0 | Pyodide | HANG | adapter `x_fd_read` (sockets.h:281): return 0 for a total length of 0 before `w_fd_read`, or the host stdin read |
| op: `os.closerange(3, 200)`, `os.close(3)`/`close(4)` (io_4 `fd-close-3`, `fd-fstat-3..5`, `fd-first-open`) | fds 3.. are free; closerange is harmless | fds 3, 4, 5 are the WASI preopened directories (`fstat(3)` is a directory); closing them makes EVERY later path call fail with EBADF (open, listdir, stat, `import`); first `os.open` returns 6 (Pyodide 3), 7, ... | MEMFS has no preopens; `FS.streams` starts at 3 | Pyodide (fds are the process's) | HANG-class: the guest is unusable after `os.closerange(3, N)` (used by daemonising/close_fds code) | adapter `x_fd_close` (sockets.h:310): refuse or ignore preopen fds; ideally a descriptor layer that starts at 3 |
| writev-file-3, readv-file (`os.writev(f, [b"x", b"y", b"z"])`, `os.readv(f, [a, b])`, `os.writev(1, [b"[wv", b"1]\n"])`) | all buffers: 3 / 6 / 6 | only the FIRST non-empty buffer: returns 1 / 3 / 3, the file gets `x`, stdout gets `[wv`; also with 70000+70000 bytes (70000 vs 140000) | `doWritev` gathers all iovecs (`_fd_write`) | Pyodide (a regular file never does a short write) | wrong result (silent short count) | adapter `x_fd_read`/`x_fd_write` (sockets.h:281, 299): for non-sockets loop over the iovecs like the socket path does (stop at a short count); wasmtime's WASI writes only the first iovec |
| os-fsync-0/1/2, os-fsync-dir (`os.fsync(sys.stdout.fileno())`, `os.fsync(dirfd)`) | `None` | EBADF (fdatasync is fine: audit `__syscall_fdatasync`) | `_fd_sync`: `stream.stream_ops?.fsync?.()` returns 0 for a stream without fsync | Pyodide for dirs (Linux fsync(dir) is valid); a tty/pipe is EINVAL on Linux | wrong errno, an exception in common write-then-fsync code | adapter: route `fd_sync` like `fd_datasync` (writes.h:114) |
| ioctl-FIONBIO-0/1/2/dir, fcntl-SETFL-nonblock-0/1/2/dir, os-set-blocking-0/1/2/dir; os-get-blocking-0/1/2, fcntl-GETFL-0/1/2 | FIONBIO ok; `set_blocking` ok; `get_blocking(0..2)` False; F_GETFL 2048/2049/2049 | EBADF for all of them on fds 0-2 and on a directory (files and sockets are fine); `get_blocking` True; F_GETFL 0/1/1 | `fcntl` F_SETFL writes `stream.flags`; `FIONBIO` succeeds on an open stream (the glue lines read do not show why) | ours for `get_blocking`; `set_blocking` must succeed | wrong errno (breaks `os.set_blocking(sys.stdin.fileno(), False)`, asyncio pipe transports) | adapter `sc_fcntl64`/`sc_ioctl` (sockets.h:264): accept F_SETFL/FIONBIO for std streams and dirs |
| os-ftruncate-stdout | EINVAL | EBADF | not read in the glue | Pyodide | wrong errno | adapter ftruncate for fds 0-2 |
| sys-stdin/stdout/__stdin__/__stdout__ `line_buffering` | True | False: a `print()` through a pipe appears when the program ends or flushes (measured: `print('first'); sleep(2); print('second')` through a pipe delivers both lines after 2 s) | Pyodide's stdio objects are line buffered | Pyodide is friendlier; CPython block-buffers a pipe | cosmetic/behaviour (no live output through pipes) | host: build sys.stdout with `line_buffering=True` (or write_through) |
| load-ctor_trap.so (a trap in `__wasm_call_ctors` of a side module) | `OSError: could not load dynamic lib: ... RuntimeError: unreachable`; the library is not loaded | `CDLL` SUCCEEDS; 40 lines of Python+wasm traceback `[loader] _dl_call failed` go to stderr (host `_dl_call`, `_host.py:934`) | `loadWebAssemblyModule` lets the exception out | Pyodide (a failed constructor fails the load) | wrong result (a broken library looks loaded) + noise | host `_dl_call` returns the failure to the adapter's `load_lib`, which fails the dlopen |
| edl-ok-then-CDLL (`emscripten_dlopen(ok.so)` then `CDLL(ok.so).val()` in the next statement) | AttributeError `Tried to lookup unknown symbol "val"` (the library is still "loading", no exports) | 7 (loaded already) | async glue | n/a | consequence of the known callback-timing gap (it is the visible form of it) | none (see 4) |
| select-*-0.2-elapsed, poll-*-0.2-elapsed, selectors-select-0.2-elapsed (16 rows) | returns at once, never waits for the timeout (`select([],[],[],0.2)` takes 0 s; with nothing ready it is a busy loop) | waits 0.2 s | `___syscall_poll(fds, nfds, timeout)` ignores `timeout` (`doPollSync`) | ours | Pyodide bug; ours is right (audit `__syscall_poll` says "full") | none |
| mmap fd-stdin/fd-stdout/fd-pipe (`mmap.mmap(0/1, 100, ACCESS_READ)`) | ENODEV / EACCES (stdout is write-only) / ENODEV | ENOSYS for all three | not read in the glue | Pyodide (ENODEV for a char device/pipe, EACCES for a write-only fd) | wrong errno | adapter `mmap_js` (mmap.h): check the fd kind before ENOSYS |
| sym-main-memory-base, sym-main-table-base (`CDLL(None).__memory_base`) | `unknown symbol "__memory_base" in dynamic lib: __main__` | fused: `function '__memory_base' not found` (no dlerror text); dynamic: same text as Pyodide | `__dlsym_js` | Pyodide | cosmetic; the flavors disagree | fused `dlsym(NULL)` |
| sym-memory-export/sym-table-export/sym-main-memory (a wasm memory/table export of a side module) | `function 'mem' not found` | `Tried to lookup unknown symbol "mem"` | `__dlsym_js` returns the JS object, 0 | both are errors | cosmetic | none |
| load-path-trailing_slash (`CDLL(".../ok.so/")`) | loads | ENOENT-style `Failed to find dynamic library` | `PATH.normalize` + MEMFS lookup ignore the slash | ours (Linux: ENOTDIR) | Pyodide leniency | none |
| load-path-empty_path, load-path-dot, load-path-surrogate, load-path-broken_symlink | texts `Error: Unexpected call to locateFile(".")` / `Error: Failed to find dynamic library "<p>"` | `[object Object]` for empty/dot/surrogate; `Failed to find ...` for the broken link (Pyodide `[object Object]`) | the exception that `findLibraryFS`/`locateFile` throws | n/a | cosmetic dlerror text | adapter `dl_open` error text |
| CDLL-libc.so.6, CDLL-libm.so.6, CDLL-libc | `Unexpected call to locateFile("libc.so.6")` | `Failed to find dynamic library "libc.so.6"` | `locateFile` of a bare name | n/a | cosmetic | none |
| load-mem_huge, mem_max32, align_huge, tab_huge (dylink.0 memsize 2^31, 2^32-1, alignment 40, table 2^31) | loads (mem), RangeError (table); the glue does not check `malloc` (malloc(2^31) fails on both) | `RangeError: WebAssembly.Memory(): out of memory` for all four | `getMemory` result unchecked | ours | Pyodide bug; ours errors | none |
| load-tab0.so, call-tab0.so (a module that writes a table slot but says table size 0) | loads (the table has slack) | LinkError `undefined element: out of bounds table access` | n/a | invalid module | cosmetic | none |
| load-env_emlog.so (`env.emscripten_get_now` imported as `() -> i32`; the real one is `() -> f64`) | loads, value coerced (JS import) | LinkError `imported function does not match the expected type` | JS functions take any wasm signature | n/a | cosmetic (only for names that are JS functions on Pyodide) | none |
| load-badver/trunc_*/trailing/start_trap/ctor texts | V8 `CompileError: ... expected version 01 00 00 00` etc. | wasmtime texts (`unknown binary version`, `module is truncated or malformed`, `LinkError: ... wasm trap`) | engine messages | n/a | cosmetic (engine text, known as "V8 LinkError texts" for the cases the adapter copies) | none |
| io_5 libc-poll-huge-nfds (`poll(NULL, 2**30, 0)`) | fatal error (table index out of bounds) | -1 (EINVAL) | `doPollSync` loops over nfds | ours | Pyodide bug | none |
| io_5 socketpair, mmap_2 c-mmap-off2^40 | Pyodide dies (socketpair: fatal; munmap of a 2^40 offset: `RangeError: Array buffer allocation failed` in `expandFileStorage`) | works (loopback pair; a sparse host file) | MEMFS | ours | Pyodide bug | none |
| process time (found while reading the io_6 output, outside this area): `time.process_time()`, `time.clock_gettime(CLOCK_PROCESS_CPUTIME_ID / CLOCK_THREAD_CPUTIME_ID)`, libc `clock()` | works | `RuntimeError: the processor time used is not available` / `OSError EBADF` / `-1` (both flavors) | `clock_time_get` of the CPU-time clocks | Pyodide | wrong result; a common call fails | host `clock_time_get` for ids 2 and 3, or the adapter (time.h); a "time" agent should own it |

Note on how the descriptor numbers show: io_2/io_5 rows such as `select-file-rwx | ([3],[3],[])` against `[6]` are the first
row of this table (descriptors start at 6), not separate differences.

## 4. KNOWN differences seen again

| entry | gap | observed as |
|---|---|---|
| `_emscripten_dlopen_js` | callback fires at the end of the call, Pyodide only on the event loop | edl-ok-path `(0, [])` vs `(0, [('ok', 7)])`, edl-sleep0/edl-sleep, edl-junk, edl-needed-ok/missing, edl-twice |
| `_emscripten_dlopen_js` | a missing top-level file is fatal on Pyodide, onerror here | edl-missing-file-sleep: CRASH vs `[('err', 7)]`; the null-callback cases die on both (Pyodide after the case line, in the async callback; ours inside the call) |
| `_dlsym_js` | console/out/err, run_script, throw_*, get_compiler_setting, ... are not answered | io_6 `sym-emscripten_out/err/outn/errn/console_*/print_double/run_script*/...` True vs False; `em-emscripten_out...` AttributeError |
| `_dlsym_js` | the JS bridge is hidden from the GOT, a zero stub as env function | load-got_bridge (Pyodide loads, ours `undefined symbol 'JsArray_count_js'`); call-env_bridge (Pyodide: `memory access out of bounds`, fatal; ours: guest dead) |
| `_dlsym_js` | env function that is not answered traps when called | call-env_unknown: both die with `cannot resolve symbol no_such_env_fn_xyz` (different process exit text) |
| `_munmap_js`/`_msync_js`/`_mmap_js` | a mapping owns a dup of its descriptor | op-flush-after-fdclose (EBADF vs `(None, None)`), op-close-after-fdclose-data (`b'\x00\x01'` vs `b'\t\x01'`), op-trackfd-fdclosed-write (EBADF vs written) |
| `__syscall_pipe2` | os.pipe() ENOSYS | every pipe row of io_1/io_2/io_5 (os.pipe, select/poll on a pipe, FIONREAD on a pipe, `isatty-pipe`, `fd-pipe`) |
| `__syscall_dup`, `__syscall_dup3`, `__syscall_fcntl64` | dup(0/1/2), dup2 onto stdio, F_DUPFD minimum | os-dup-stdout-*, os-dup2-stdout-to-9, os-dup-stdin-isatty, os-fdopen-1-write, os-dup2-stdout-to-0, fcntl-DUPFD-0/1/2 (ENOSYS), fcntl-DUPFD-file/dir (`>= 50` False) |
| `_emscripten_system` | system() ENOSYS | libc-system-echo -1, os-system-echo -1, libc-system-null 0 (Pyodide 1); os.popen and subprocess.run fail on both (equal) |
| `_emscripten_log_formatted` | stack flags print no JS stack | the emlog-flags rows with the stack bits (EM_LOG_C_STACK/JS_STACK): Pyodide prints `Error at jsStackTrace ...`, ours the message only (all other flag values and formats equal; 22 flags x message forms) |
| `__syscall_openat` | path limits are the host's | not re-observed (long names in loader_1: 255/256 bytes behave the same) |
| `_dlopen_js` | NEEDED depth cap; a failed load leaves no entry | depth 2..50 equal (not the cap); the "failed load registers the name" is the Pyodide side effect that forced `# isolate` (after one failed GOT import every later load fails on Pyodide) |

## 5. Host-dependent or by design (not Pyodide behaviour either way)

* `/dev`, `/proc`, `/home`, `/etc`: Pyodide has `/dev/{null,random,urandom,tty,tty1,stdin,stdout,stderr,shm}` (no
  `/dev/zero`, `/dev/full`, `/dev/fd`), `/proc/self` (a `fd` dir that lists the open streams), `/home/pyodide`,
  `/home/web_user`, no `/etc`; ours has none of the first three and has `/etc/{services,ssl}`; cwd is `/` (Pyodide
  `/home/pyodide`); root listing shows the host's mounts (`_pw_*.py`, `probe`, `dist`) -- 176 rows of io_3, all
  `ENOENT`/`False` for `/dev/*`. With `--dev` ours exposes the host's /dev (112 nodes: `/dev/zero`, `/dev/full`, ...,
  `isatty(/dev/null)` True, `st_rdev` 0,0, `/dev/stdin|stdout` EPERM, `/dev/tty` EIO); the sandbox's own `/dev/null` is a
  regular file (a shell redirection replaced it), so the `--dev` numbers (fused 278, dynamic 300 rows) vary with it and
  are not reliable.
* Environment: Pyodide `HOME=/home/pyodide USER=web_user LOGNAME PATH=/ PWD=/ LANG=en_US.UTF-8` (so `getlogin()`
  `web_user`, `getlocale()` `en_US`); ours `LANG=C.UTF-8` plus `PYTHONHOME`, `PYTHONPATH`, `PYTHONDONTWRITEBYTECODE`,
  `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `LD_LIBRARY_PATH` (both have that one); `os.getlogin()` ENXIO;
  `os.get_exec_path()` `['/bin','/usr/bin']` vs `['/']`; `sys.argv` `['-c']` vs `['']`, `sys.executable` `''`.
* Permission bits: `/lib` and the stdlib are `drwxr-xr-x`/`-rw-r--r--` (host files) against MEMFS `rwxrwxrwx`.
* `stat` of `/dev/*` device numbers (host).

## 6. Equal on both (what the 2750 cases mostly show)

Loader: absolute/relative/symlinked/dotdot/long/non-ASCII/bytes/NUL/None/int paths and the errors; dlopen twice (same
handle, also through a symlink and `..`); the 8 `mode=` values; CDLL(None) symbols (`strlen`, `getpid`, `malloc`,
`PyType_GenericAlloc`, `_Py_NoneStruct`, `dlopen`...), pointer identity of a main function through `CDLL(None)`,
`pythonapi`, `cdll.LoadLibrary` and a GOT.func import; GOT.mem of a main data symbol; dlsym of functions, data
(`c_int.in_dll`), globals (i32/f32/f64 mutable and immutable; i64 fails the same way with V8's TypeError text);
signature mismatch LinkError texts for a main-module function; missing/unknown env import (traps the same); NEEDED
chains of depth 2/3/5/10/25/50, a cycle, a self-NEEDED, `$ORIGIN` rpath, a subdirectory rpath, an absolute rpath,
`LD_LIBRARY_PATH`, `$ORIGIN` in a NEEDED name; `find_library` for 13 names; `CDLL(handle=...)`; dylink.0 with unknown
subsection / old `dylink` section / bad alignment 3 and 20; numpy 2.4.3 (13 extension modules) and everything probed in
it; `time.sleep`; mmap: 624 cases (0 and negative and 2^31-2^63 lengths and offsets, ACCESS_*, prot x flags x O_*,
anonymous, 80 operations, resize, madvise, move, find/readline/slice, two mappings, truncate/unlink/rename/chmod under a
mapping, mtime after flush/close, sparse files over 4 GiB, libc mmap/munmap/msync/mprotect/madvise errors); stdio:
isatty/ttyname/get_terminal_size, `TIOCGWINSZ`/`TCGETS`... on fds 0-2 and a file/dir, `input()` and `read` from EOF
stdin, print to a closed stdout, closing fds 0-2, `emscripten_log` with 22 flags and about 14 formats, `emscripten_log_impl_js`,
libc `puts/printf/fputs/putchar/perror/write/getchar` on the std streams, `setenv/putenv/getenv` round trips through
ctypes (both directions, bad names, 100000-byte values, 2000 variables), `os.environ.clear`, TZ.

## 7. What was not probed, and why

* `emscripten_dlopen_promise`, `dlclose` (nothing to observe), scipy/other wheels: only numpy is in the test
  environment; weak GOT imports (the glue's `required` flag is set by the main module, not by the side module here);
  `LD_LIBRARY_PATH` with several entries beyond one colon pair; side modules with threads or exceptions-in-flight.
* The NEEDED depth cap (known, measured in the audit), `RTLD_NODELETE`/`dlclose` refcounts.
* A terminal on fds 0-2: the harness gives both sides no tty (stdin /dev/null, stdout/stderr a pipe). `TIOCGWINSZ` on
  a tty, line discipline, raw mode and `emscripten_set_up_async_input_device_js` need an interactive session.
* `select` on a real tty or socket readiness is the sockets agent's area; here only files, std streams and pipes.
* Windows and macOS hosts (only CI can show them).
* The `mmap` cases that depend on the host file system's permissions (a read-only file on disk) were not probed (known gap).
