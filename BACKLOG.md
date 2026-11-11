# BACKLOG

Everything that is open, in one place (2026-11-11). `BRIEF.md` says what the project is and which decisions are made; this file says
what is left. An item is removed when it is done (the commit says so) or decided against (a line in BRIEF.md says why).
Order inside a section is not a priority; the order of work is at the end.

## 1. Waiting for the owner (a decision, not work)

| id | question | state |
|---|---|---|
| D1 | `emscripten_dlopen` callback: now a pending call of the interpreter (before the next statement); option C = at sleep/poll/end of `run()` | B kept, documented in BRIEF.md |
| D2 | Pyodide's own pipe quirks we copy: unbounded buffer, no EPIPE for a write with no reader | copied; may change |
| D3 | Which Pyodide bugs to mirror (trailing slash on a file works there, `umask` ignored, `chown` a no-op, `st_nlink` of an unlinked file, ms-rounded `utimensat`, `O_CREAT|O_EXCL` on a dangling symlink, libc `linkat` gives EMLINK) | after the files audit: recommendation is NOT to copy |
| D4 | The guest's root: files on the host's disk (now) or an in-memory root ported from Pyodide's MEMFS (+ a host API to move files in and out, mounts as real host folders, maybe a lazy overlay) | PARKED (owner, 2026-11-11: no win seen for now): the root stays on the host's disk. Revisit if there is a real need: many Windows users, identical results without mounts, isolation from the disk. A scope study (docs/MEMFS_SCOPE.md when it arrives) records the cost: do not start the port without a new reason |
| D5 | Guest fd numbers decoupled from WASI's (fd 3 is the root preopen now: first new fd is 4; WASI gives the last freed number, not the lowest) | proposed (see W5), not decided |
| D6 | `wasm-opt.wasm` (12.5 MB, 12-minute build): keep the CI cache, or publish it as a release asset fetched by sha256 (not committed) | asked, not answered |
| D7 | Ctrl-C in the CLI mapped to `Pyodide.interrupt()` | asked, not answered |
| D8 | Windows symlink fix needs a Windows run to isolate (hypothesis: wasmtime resolves the target from the root); skipped on win32 | documented in the audit |
| D9 | Policy for the license/size of Pyodide artifacts in the wheel (carried now; alternative: download at first run); the owner opens the pull request | BRIEF.md |
| D10 | The official suite stays red until fixed; what cannot be fixed becomes `xfail` with a reason | decided, see S1 |
| D14 | Decided 2026-11-11: the guest STARTS in `/home/pyodide` (as Pyodide), not in `/`; the tests that assume `/` are fixed with it (snapshots too); `--mount-cwd` mounts at `/work` (one constant `CWD_MOUNT` in `_cli.py`); `inherit_env` protects only `PYTHONHOME`, `PYTHONPATH`, `LD_LIBRARY_PATH`; `sys.executable` stays `''` (Pyodide's value is a Node artifact: the `_` variable of its process): a documented difference, no work | decided; the cwd change is in batch B2 |
| D11 | When Pyodide 315 is released (now 315.0.0-alpha.2): bump the pin (tools/fetch.sh sha, `PYODIDE_VERSION`/`ABI`, `PYVER`) | later |

Decided and written in BRIEF.md (do not reopen without a reason): dynamic is the default, fused stays in the wheel; sockets follow the host's kernel;
POLLHUP is not normalised; Python 3.14 is not supported for now (direction: a signature mismatch becomes a stub with a warning, not a trap);
the browser-free `emscripten_*` names are not planned; HTTPS in a component would be the guest's own TLS (wasip2, later); long paths: the host's answer.

## 2. Work: files and descriptors (from `docs/DIFF_AUDIT_files.md`, N-numbers are its rows)

* **W1 crashes and hangs:** done except N3's numbering (the preopen numbers are hidden from the guest now, but the first `open()` is still 4 and `close(3)`/`dup2(x, 3)` say EBADF where Pyodide has a free number: W5) and N5 after `close(1)` print still works and shutdown prints a traceback (exit 255).
* **W2 `/dev` as virtual objects in the adapter** (same on every OS, fixes Windows): `/dev/null`, `zero`, `urandom`/`random`, `tty`, `stdin`/`stdout`/`stderr`; `/dev`, `/proc` (what Pyodide has), `/home`. Fixes `test_logging`, `test_shutil` and `os.devnull`; today `--dev` mounts the host's `/dev` (absent on Windows).
* **W3 errors and paths:** N6 the empty path is "." in about 20 calls (must be ENOENT); N7 `rmdir('d/')`/`rmtree('d/')` EINVAL; N10 read/pread/ftruncate/fsync on a directory fd; N11 write-open of a directory (EISDIR); N23 ftruncate/fsync/utime on stdio; N32 file fd as dirfd (ENOTDIR); N33 `fstatat` bad dirfd + empty path; N34 `dup3` flags, `fadvise` advice, `access` mode unchecked; N14 `truncate` on a 0444 file vs `open` for write; N36 `os.open(f, 3)`.
* **W4 multiple buffers and sizes:** N15 `readv`/`writev`/`preadv`/`pwritev` handle only the first buffer (wasmtime on files; the pipes loop already); N16 `pread` capped at 64 KiB; fails `test_os.test_posix` test_readv/test_writev.
* **W5 descriptor numbering:** guest numbers decoupled from WASI's (lowest free like POSIX, first fd 3, preopens hidden: fixes N3, N18, N19, N17, dup2 to any number, `MAXFD` 1024 vs Pyodide's 4096); plain `open` returns the lowest free number.
* **W7 (new, from the MEMFS study)** `listdir`/`scandir` of a large directory is about 400x slower than Pyodide's (5000 entries: 5-15 s against 0.01-0.04 s): hypothesis: each `getdents64` asks wasmtime's `fd_readdir` from the cookie and wasmtime enumerates the whole host directory every time (quadratic). Fix: read the whole listing once per descriptor and serve from a snapshot (about 40 lines, as Pyodide does); probably also fixes N20 (duplicates); worth doing on any root. Also unexplained: stdlib imports are 2-3x slower than Pyodide's though reading the zip is faster (not file-system-bound); 10,000 small file creates 5x slower.
* **W6** N20 `scandir` returns duplicates when files are created in the loop (cause in Pyodide's glue not traced); `st_nlink`, `st_blocks` differences (host-dependent).
* Known partial (platform limits, in the audit): `mknodat` FIFO/char/block/socket (WASI cannot create), `utimensat` outside 1970..2554 (WASI u64 ns), `symlinkat` across preopens (cap-std), epoll (3 `__syscall_epoll_*`: ENOSYS, no decision), `_emscripten_system` (ENOSYS on purpose: a shell would be a sandbox escape).
* Check later: `open_at` with a pipe or socket as dirfd (resolves against the root; Linux gives ENOTDIR).

## 3. Work: the official suite (`docs/` has none; CI junit artifacts `suite-<flavor>`; 13 modules fail on both builds, 2026-11-11)

* **S1** read the failures, fix what can be fixed, the rest `xfail` with the concrete reason.
* `test_logging`, `test_shutil`: `/dev/null` (W2). `test_time`, `test_profile`, `test_profiling.test_tracing_profiler`: "the processor time used is not available" (`process_time`, `clock_gettime(CLOCK_PROCESS_CPUTIME_ID)`, `times`): nobody owns it, small. `test_os.test_posix`: readv/writev (W4). `test_os.test_os`: symlink `followlinks`, broken links in `walk`/`fwalk`, `scandir('')`. `test_posixpath`: EILSEQ for `b'/\xff'` (undecodable names). `test_pathlib`: mtime precision (`utimes` is microseconds). `test_filecmp`: not analysed. `test_importlib.import_.test_path`: no `importlib.metadata`; `test_importlib.test_namespace_pkgs`: no `email` (how does Pyodide on Node get them: probably an unvendored package loaded on demand); `test_importlib.extension.test_finder`: extension suffix `'.abi3-"wasm32-emscripten".so'` (quotes in a sysconfig value?).

## 4. Work: terminal and stdin

* **T1 `_pyrepl` / terminal** (BRIEF "terminal support"): `termios` TCGETS/TCSETS/TIOCGWINSZ through the host (the sockets step left ENOTTY), real readiness `poll` on stdin, SIGWINCH through `Pyodide.interrupt`, Windows keeps the simple REPL, tests on a pty, a reviewer. `dup(0)` works now; `test_pyrepl.*` pass in the suite.
* **T2** the stdin concern the owner raised (stdin behaviour in the CLI/tests): not analysed since the first remark; the CLI REPL reads lines in the host (prompt_toolkit if installed, else input()).
* **T3** `Pyodide.interrupt` from another thread is unsafe (Store is not thread-safe): options (a) cached data pointer, (b) epoch interruption, (c) poll in a host callback; the audit entry of `_Py_CheckEmscriptenSignals_Helper` is `partial`.

## 5. Work: the differential audit (task #17)

* Files: done (`docs/DIFF_AUDIT_files.md`). Runtime: done (`docs/DIFF_AUDIT_runtime.md`, 12 probe files, about 7500 cases per TZ-run; time functions show NO difference in 7 zones x 4509 cases). Loader/io: the agent is still running.
* **R-rows from the runtime audit (new differences, each with `tools/diff_probes/runtime_repro.py` as the acceptance probe):**
  * R7/R8 left: `sys.executable` is empty (Pyodide has the host process's `_` variable, a Node artifact) and `sys.flags.inspect` is 0 (`PYTHONINSPECT=1` is not mirrored); `/home` has no `web_user` folder (Pyodide has both).
  * R9 19 glue library functions that no wasm of the build calls (`emscripten_get_now_res`, `emscripten_random`, `emscripten_console_*`, `emscripten_run_script`, `emscripten_force_exit` ...) are missing from dlsym and not in `import_audit.json` (`audit_imports.py` should list the glue's library too); R10 `__assert_fail` with a pointer outside memory traps while printing; R11 `mktime((-271821, 6, 15, ...))` returns a value where Pyodide raises OverflowError.
  * Known and re-observed: `_setitimer_js` fires in a busy loop (deliberate), a struct nested 100 deep traps in `ffi_call_js`, `emscripten_resize_heap`, `os.system` -1, progname, the JS bridge.
  * Not probed: Windows/macOS TZ, `interrupt()` from another thread, a side module importing an `emscripten_*` function, `resource` (cannot be imported on either side).
* Decided (owner, 2026-11-11): **D12** the CPU-clock ids (`clock_gettime(2/3)`, `process_time`, `clock`) give the host's REAL CPU time (Pyodide answers with the monotonic clock: a deliberate difference, write it in the audit entry); **D13 (final)** model A, as wasmtime does: the API and the CLI are ISOLATED by default (the guest sees only what it is given: its root, `mounts=`, `env=`; nothing of the host's environment or files) and the host's world is switched on by flags: `--inherit-env` (pass the host's variables), `--env K=V`, `--mount HOST:GUEST` (a host folder), maybe `--mount-cwd` (the current folder in one flag, for the CLI as a `python` replacement). The default environment is Pyodide's own minimal one: Pyodide itself sets `USER=web_user`, `LOGNAME=web_user`, `PATH=/`, `PWD=/`, `HOME=/home/web_user` and `LANG=<language>.UTF-8` (Emscripten's `getEnvStrings`) and its loader `HOME ??= /home/pyodide` (pyodide.mjs): we use `HOME=/home/pyodide` and create it with `/tmp`; CPython itself starts without them (without `HOME` `expanduser('~')` stays `~`, `Path.home()`/`getpass.getuser()` raise). Not mirrored: `PYTHONINSPECT=1`. What the guest still shares with the host, to decide one by one: the NETWORK (real sockets, `hostnet` fetch; a `network=False` switch?), the time zone and locale (the host's `TZ`), the host's `/dev` with `--dev` (to be replaced by the virtual `/dev` of W2), the CA bundle read for TLS, process facts.
* **L-rows from the loader/io audit** (`docs/DIFF_AUDIT_loader_io.md` in branch `worktree-agent-a77fde6b06071244a`, commit 59ebf9f, NOT merged yet: it has its own `tools/diff_pyodide.py` and `_prelude.py` that must be unified with the two merged ones; about 2750 cases; numpy 2.4.3 loads all 13 extension modules and 78 cases agree; mmap 616 of 624; loader chains, rpaths, globals, V8 LinkError texts equal):
  * L1 `os.read(0, 0)`, `os.readv(0, [])`, `sys.stdin.buffer.raw.read(0)` hang (= files N2: in fix batch 1); L2 closing fds 3-5 (the preopens) kills every later path call and the first `os.open` is 6 (= files N3: batch 1 hides the preopens; W5 renumbers).
  * L3 multi-buffer `readv`/`writev` use only the first buffer (= W4); L4 `os.fsync` on fds 0-2 and on a directory fd gives EBADF (Pyodide: ok); L5 `FIONBIO`, `F_SETFL(O_NONBLOCK)`, `os.set_blocking` on fds 0-2 and directories give EBADF (and `os.get_blocking(0..2)` is True where Pyodide says False: ours is POSIX-right).
  * L6 a trap in a side module's `__wasm_call_ctors`: Pyodide raises OSError and the library stays unloaded; ours succeeds in `CDLL` and prints a 40-line traceback (`_dl_call` in `_host.py`). L7 lower: `ftruncate` on std streams (EBADF vs EINVAL), `mmap` of fd 0/1/pipe (ENOSYS vs ENODEV/EACCES), `line_buffering` False on stdout and stdin (batch 1 does stdout), cosmetic dlerror texts.
  * Pyodide bugs where ours is right (D3, the owner decides): `select`/`poll` ignore the timeout and return at once (`___syscall_poll`), `poll(NULL, 2**30, 0)` and `socket.socketpair()` are fatal on Pyodide, an mmap flush at offset 2**40 is a fatal RangeError, a dylink.0 memsize above 2 GiB kills it or loads with an unchecked malloc.
  * Seen again, known: `emscripten_dlopen` callback timing, the hidden bridge, the dup'd mmap descriptor, `os.system`, the log stack flags. Host-dependent: `/dev`, `/proc`, `/home`, `/etc`, the environment and `cwd` (`/` instead of `/home/pyodide`: part of D13: set the guest's cwd to `/home/pyodide`?), permission bits.
* `tools/diff_pyodide.py` needs `PYO_RUN` (a script running a Python file in the real Pyodide on Node); make a real tool of it (a node script on the npm `pyodide` package, a build-time tool) instead of a scratchpad script.
* Re-run the root-dependent rows (N14, N27) as a non-root user.

## 6. Work: reviews not done yet (CLAUDE.md: a `reviewer` reads high-stakes diffs)

* the virtual descriptor layer (`wasm/adapter/vfd.h`, 308 lines, a new table, placeholders, `fd_renumber`, routed WASI imports);
* the override feature (`asm_wasm`/`stdlib`, conversion of a legacy-exception main module, snapshot key);
* the Windows/macOS host changes (`_poll`, pending errors, `SO_ACCEPTCONN`, localtime guards);
* the new tests were not all run against the old build to show "fails before" (say which in each report).

## 7. Work: the platforms (CI is the only check there)

* Unverified guesses to look at in the next CI logs: UDP `send` without a peer on Windows (WSAENOTCONN mapped to EDESTADDRREQ without a log), `_t_localtime` on Windows (fixed by the offset from the fields: green now), poll HUP after `shutdown` on Windows (the host adds it), the wasm stack 1 MiB and the NEEDED depth cap 800/1500 (Linux measured only), `chmod /tmp` at start on Windows.
* Offline matrix: 6 jobs (3 OS x Python 3.10/3.15) plus the suite 2 and build 2 and network 1: fewer if the runners are the limit.

## 8. Work: loader, ffi, time, misc

* `ffi`: a ctypes call costs about 59 us and a callback 168 us (Python host overhead): a per-cif decode cache (validated: a cif address can be reused); wasm exceptions cannot cross the host frames (a C++ throw/sjlj through ffi_call, closures, the trampoline kills the guest).
* Loader: JS-implemented functions accept any signature in Pyodide (a trampoline on a mismatch: not done, a gap); the failed-load registry and the hidden bridge are deliberate differences; `emscripten_dlopen` is `partial` (no event loop). The names the glue resolves and we do not (1293: bridge, GL/SDL, about 265 others): no wheel of the release imports them; answer the few a real wheel needs when one turns up (scan: wheels' `env` imports against the list, script in the scratchpad).
* A warning for a different SIGNATURE of an import (we warn for an unknown name only) and the stub-instead-of-trap (BRIEF, Python 3.14).
* Time: `_mktime_js`/`_localtime_js` clamp to [0, 32535215999] on a narrow `time_t` (Windows); zone names other than UTC are not understood by the Windows CRT (tests skip them there).

## 9. Later: wasip2 and the bundle mode (only after everything above; the owner's order)

* Branch `claude/wasip2-component` (experiment): Python, files, TCP, DNS under `wasmtime run`; needs `net_pollv` in `wasm/net_p2.c` before any merge, and everything the p1 side got since (real `setsockopt`, non-blocking, bind/listen/accept, Emscripten errno numbers, UDP).
* Bundle mode (BRIEF "Direction"): a CLI that bakes the wheels in (`dlopen` answered inside the module by a registry), try `wasm-tools component link --dl-openable`; `wasm-tools-package` as an optional bundler dependency.
* HTTPS in a component: the guest's own TLS (`_ssl` bundled), the CA bundle (baked in = frozen at build time, or a preopen), `wasi:random` for OpenSSL, `wasi:clocks` for certificate dates (the host-side time operations of this branch must move), size. `wasi:http` was left out ("for now"; some hosts give only `wasi:http`).
* Theory only: a Rust host (fast ffi, threads, a thread-safe interrupt, but a platform wheel and a rewrite) and a host compiled to a component with wasmtime's Pulley interpreter (not tried).
* `fusedwasi` cannot be used on component hosts; it could fix part of the suite on p1 (statfs is missing there).

## Order of work now (2026-11-11)

Done: the three differential audits, the first fix batch (B1: crashes, exit status, CPU clock, environment, preopens), the descriptor layer, the harness.
Running: independent reviews of the descriptor layer (`vfd.h`) and of B1 (section 6); their findings become fixes before anything else touches those files.
Next, one batch at a time (they touch the same adapter and host files: no two in parallel), each with a `reviewer` pass on the diff:
1. B2 (stdio, small): `close(1)` and the other standard descriptors (N5), `fsync` on 0-2 and directories (L4), `FIONBIO`/`set_blocking` on 0-2 and directories (L5), `ftruncate` on std (EINVAL), the guest's cwd `/home/pyodide` and the tests that assume `/` (D14), a trap in a side module's `__wasm_call_ctors` (L6).
2. B3 (directories and multiple buffers): W4 (`readv`/`writev`/`preadv`/`pwritev` loop, `pread` above 64 KiB), W7 (the `getdents` snapshot), N20.
3. B4 (`/dev` and paths): W2 virtual `/dev`, `/proc/self/fd`, W3 (empty path, trailing slash on `rmdir`, the errno sweep of N10/N11/N23/N32-N34/N36), `os.devnull`; then the suite items they fix (`test_logging`, `test_shutil`, `test_os.test_posix`).
4. B5 (numbering, the biggest): W5/D5 decoupled descriptor numbers (first fd 3, lowest free, `dup2` to any number, 4096 descriptors, preopens hidden for good), plain `open` returns the lowest free number, N17-N19.
5. The remaining suite modules (S1: process time may be fixed by B1: read the next CI), then T1 terminal and T3, then xfail for what is left.
6. Section 9 last.
