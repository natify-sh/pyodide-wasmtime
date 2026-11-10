# Read this first

The briefing for anyone (person or agent) who starts work on this repository. Everything else is reference material: read it when a task needs it. The rules of work are in [CLAUDE.md](CLAUDE.md).

## What this project is, in one paragraph

**pyodide-wasmtime runs Pyodide's CPython, and its wheels, on wasmtime with no JavaScript.** Pyodide's `pyodide.asm.wasm` imports 263 functions from `env`: Emscripten's JavaScript glue. Here the glue is **wasm**
(`wasm/adapter.c`, built with wasi-sdk 34's clang, after the shape of Wasmtime's preview1 adapter: no data section, no stack of its own): system calls over WASI, the dynamic loader (`dlopen` of a wheel), libffi calls, sockets,
time, the trampoline. The Python host (`src/pyodide_wasmtime/_host.py`, class `Pyodide`) gives what a wasm module cannot do: wasmtime's WASI, the loader operations, libffi's calls and callbacks, the host's time zone, the host's sockets and `statvfs`. Pyodide is **not rebuilt**: its wasm is the npm
package's, with the legacy wasm exceptions converted once to `exnref`. The package is an **alpha** and meant to be a ready solution for anything Pyodide runs without the browser's JavaScript, not for numpy only.

## What it is NOT

* **Not Pyodide's JavaScript API.** `js`, `pyodide.ffi`, `JsProxy`/`PyProxy`, `loadPackage` from JS need the bridge; the 169 `env` imports that are the bridge (158) and hooks without meaning here (11) are zero/null stubs, listed one by one in `docs/IMPORT_AUDIT.md`. Tests that need them are N/A, not failures.
* **Not a rebuild of Pyodide or of Emscripten.** The one change to Pyodide's binary is made at build time (`tools/patch_main.mjs`): libc's `setsockopt`, which Emscripten compiles to `return 0` without calling the syscall, becomes a call of an import the adapter answers; each such stub needs its own patch. One Pyodide build is supported (`PYODIDE_VERSION` 315.0.0-alpha.2, ABI `pyemscripten_2026_5_wasm32`); the adapter answers that build's imports.
* **Not a sandbox against the host.** The guest's `/` is a temporary folder, but the host's sockets and fetch are real; `mounts` hand host folders over.
* **Not a Node or a Binaryen user at run time.** Node and npm's Binaryen are **build** tools (`tools/*.sh`, CI). The run time needs wasmtime-py and the wasm files in the wheel.
* **Not a Component Model component (for now).** Emscripten's ABI does not fit it: a wheel's `.so` imports the main module's memory, table, stack pointer, exception tag and `GOT.*` globals, which cannot cross component instances; the `env`
  imports are Emscripten's JavaScript glue, not WIT; and `dlopen` needs a new core module at run time, which a component cannot create. So Fastly Compute, Spin and wasmCloud, which run components, are not targets. Stock CPython for WASI
  (e.g. `componentize-py`) cannot load binary wheels at all (WASI has no `dlopen`); **loading Emscripten wheels at run time, by a host we control, is what this project does** and why it exists. Details and the open question: `docs/NOTES-FUSEDWASI-AND-TESTSUITE.md`, section 3.
* **Not wasmhost.** [wasmhost](https://github.com/natify-sh/py-wasmhost) is the sibling (the WebAssembly API on many engines); this package came out of its experiments (`docs/EXPERIMENT.md`) but depends on nothing of it.

## The architecture in five lines

```
data/ (in the wheel):  pyodide.asm.wasm (exnref) + adapter.wasm  -> "dynamic": linked at run time (shim from the import list, trampoline, fixup)
                       pyodide_fused.wasm (tools/fuse.py, wasm-merge) -> "fused": one core module, only instantiated
                       python_stdlib.zip, wasm-opt.wasm (Binaryen 132 as wasm32-wasip1: converts a wheel's legacy exceptions at dlopen, in-process)
_host.py (Pyodide)  WASI = wasmtime's own; loader ops (instantiate/scope/sym/got_set/call/error); net ops (sockets); fs op (statvfs); the host's fetch; run() = PyRun_SimpleString
_engine.py          the engine, the machine-code cache (~/.cache/pyodide-wasmtime), wasm-opt.wasm run in-process
tests/              offline + network + Pyodide's official CPython suite, each on BOTH builds;  CI: build.yml -> tests.yml / publish.yml
```

## Where it is, and what is next

* **Done (2026-11-10):** the package on branch `claude/ecstatic-cray-to1b3t` (not yet merged): both builds, CLI, API, wheel (13 MB), tests, CI written. Offline tests pass locally on both builds; a part of the official suite passes (see the PR / CI for the current numbers). CI has not yet run end to end. `Pyodide(preload=)` starts from a cached memory snapshot (`tests/test_snapshot.py`; the REPL's start to the first prompt 0.7 s -> 0.3 s with asyncio preloaded); one snapshot per packaging is kept, so alternating preloads (e.g. the REPL with and without `--allow-top-level-await`) rewrites it each time.
* **Next** (from [docs/NOTES-FUSEDWASI-AND-TESTSUITE.md](docs/NOTES-FUSEDWASI-AND-TESTSUITE.md)): read the CI run and fix what it shows; then the rest of the official suite (`test_python_socket.py`, the package tests of numpy/cffi/micropip/test-cpp-exceptions); WASI 0.2 over fusedwasi, replacing the `net` operations.
* **Decision kept open (owner, 2026-11-10): the callback of `emscripten_dlopen`.** Now it is a pending call of the interpreter (`Py_AddPendingCall`): it runs right after the call returns, before the next statement; Pyodide runs it from its JavaScript event loop, so there it comes after the current synchronous code. Kept as it is until something needs the other: if a program depends on the order (state set right after the call must precede the callback), switch to option C: queue the job and run it where Pyodide's event loop would turn, in `time.sleep`, `poll`/`select` and at the end of `run()` (a hook on the host's wait operations; how `time.sleep` reaches the host in this build is not measured yet). The other options (run only at the end of `run()`, or synchronously as before) and the probes are in the audit entry of `_emscripten_dlopen_js` (docs/IMPORT_AUDIT.md).
* **The official suite stays red until the gaps are fixed (owner, 2026-11-10).** No list of known failures is added now. What cannot be fixed in this architecture goes into `xfail` at the end, one entry per module with the concrete reason (what WASI, wasmtime or the missing JavaScript lacks); the first step then is to read the current failing modules from the junit files of the CI shards (artifacts `suite-<flavor>-<shard>`), not to run the suite for hours locally.
* **Other Pyodide versions (owner, 2026-11-10): Python 3.14 is not supported for now; noted.** Tried: Pyodide 314.0.7 (CPython 3.14.2, npm) through `--asm-wasm`/`--stdlib` on dynamic: the four start-up warnings are right (CPython version, one unknown import `__syscall_pipe`, no `setsockopt` patch, a 3.14 stdlib zip while the host lays out 3.15) and the run traps at boot with `indirect call type mismatch`. The imports of the two builds agree except: `_gmtime_js` and `_localtime_js` are `(i64, i32) -> void` in 314 and `(i64, i32) -> i32` in 315 (the likely cause of the trap, not proven), 314 has `__syscall_pipe` that 315 lacks, 315 has ten that 314 lacks (`epoll_*`, `pipe2`, `getegid32`/`geteuid32`/`getgid32`, `linkat`, `poll_nonblocking`, `shutdown`); `PYVER` is also fixed in the host. The owner's direction for later: a signature mismatch between a main-module import and the adapter's export must not trap at the call: bind a stub instead and say so with a warning at start (name, both signatures), so another version runs as far as it can; the stub's result must be honest by type (`-ENOSYS` for `__syscall_*`, 0/null otherwise) and the warning must name every stubbed function. Nothing of it is built; the warning for a name the adapter does not know exists, one for a different signature does not.
* **Standards we follow:** core WebAssembly 3.0 (exnref, GC, function references), the `dylink.0` convention (LLVM/Emscripten tool-conventions) for side modules, PEP 783 for the wheel tag (`pyemscripten_YYYY_N_wasm32`), WASI 0.1 now and 0.2/0.3 for sockets, HTTP and files next (replacing our `net` operations). The `loader.*` interface (six operations) is our own extension and the contract between the adapter and a host.
* **Waiting for the owner:** a pull request (the assistant does not open one); the decision about the license/size policy of Pyodide artifacts in the wheel (they are carried now; the alternative is a download at first run with a sha256 check); `CLAUDE.md` rules that were taken from wasmhost and are not yet confirmed for this project (below).

## Direction: one adapter, two ways to run it (decided 2026-11-10; the second is a plan, nothing of it is built)

1. **Host mode (what this branch does).** A Python host on wasmtime-py: `dlopen` of a wheel at run time through the four `loader.*` operations, sockets through `net` (or WASI 0.2 sockets). Full: any Emscripten wheel, `micropip`, TLS in the guest. Everything below "Where it is" is about this mode.
2. **Bundle mode (for hosts that run components: Fastly, Spin, wasmCloud).** A CLI that bundles Pyodide, the chosen wheels and the adapter with **`dlopen` answered inside the module** (a registry of what was linked at build time) into **one component**. A component can not create a module at run time and does not give the host its memory and table, so the set of wheels is fixed when it is bundled. What exists: the component with TCP and DNS over `wasi:sockets` (branch `claude/wasip2-component`, `tools/wasip2/`, `wasm/net_p2.c`); what is missing: the bundling of wheels (bases of memory and table, `GOT`, `__wasm_apply_data_relocs`, the registry), and then `_ssl`, `libssl`, `libcrypto` for HTTPS without `wasi:http`. Decided not to do: `wasi:http` as a host fetch, fusedwasi as a way to host components.
   * Tooling: `wasm-tools-package` (natify-sh, `pip install wasm-tools-package`, Python 3.11+) as an optional dependency of the bundler. **To try first:** `wasm-tools component link --dl-openable NAME=lib.so` with `--use-built-in-libdl` implements exactly this (linking by the `dylink.0` convention, `dlopen` of what was bundled); whether it accepts Pyodide's `MAIN_MODULE` as the base, and Emscripten `.so` files, is unknown. Binaryen's `wasm-merge` is the fallback (it is what `tools/fuse.py` uses).
   * Order: finish the failures of the official suite in host mode; bundle one small module (`_testbuffer.so`) to prove the mechanics; then numpy and `_ssl`; then the CLI.

## Official suite, host mode (2026-11-10, both packagings give the same)

819 modules of Pyodide's CPython suite: first run 500 passed, 103 failed, 185 skipped, 31 xfail (module level: one failing test fails a module). Found since: 29 `__syscall_*` imports of `pyodide.asm.wasm` were answered with 0 ("success") and did nothing; they return ENOSYS now, and `symlinkat`, `linkat`, `truncate64`, `fallocate`, `fdatasync`, `fcntl`, a real `chdir`/`getcwd` and `exit` are real. Of the 103 failing modules, 14 pass after that; the rest group into: `ffi_call_js` limited to integer and pointer signatures (wasm trap in `ctypes`, 18), more unimplemented calls (`pipe2`, `dup`, `chdir` family...), `dlsym` on the main module not finding symbols that are exported (8), "files modified" by tests (6), `clock_gettime` for the process time (3). Not compared with Pyodide on Node. Since then `ffi_call_js` takes any signature and callbacks work (host operations; `test_ctypes.test_callbacks` and `test_libc` pass on both), and `raise()`/`os.kill` call the handlers (`test_signal`'s raise cases).

## Hard rules (short form; the full list is in CLAUDE.md)

* The package has **no run-time Python dependency**; wasmtime-py is the `[wasmtime]` extra (and a dev dependency). Python 3.10+.
* **Node is a build tool only**; one toolchain, **wasi-sdk 34's clang**, builds every wasm we build.
* **Both packagings** (fused, dynamic) are tested everywhere a test runs, **including Pyodide's official suite**.
* Measure, do not guess: a claim about what runs has a command or a CI run behind it; say plainly what was not run (a network check in a sandbox, Windows, macOS).

## Map of the documents

| when you need | read |
|---|---|
| what it is, how to use and build it | `README.md` |
| the rules of work, the roles of agents | `CLAUDE.md`, `.claude/agents/` |
| how the adapter works, what it answers, what was found | `docs/EXPERIMENT.md` |
| WASI 0.2 over fusedwasi, the official test suite plan | `docs/NOTES-FUSEDWASI-AND-TESTSUITE.md` |
| the adapter | `wasm/adapter.c` (includes the sections in `wasm/adapter/*.h`) |
| the host | `src/pyodide_wasmtime/_host.py`, `_engine.py`, `_wasm.py`, `guest/hostnet.py` |
| the build | `tools/` (`fetch.sh`, `build_data.sh`, `build_adapter.sh`, `build_binaryen.sh`, `build_ssl.sh`, `prepare_testenv.sh`, `fuse.py`), `package.json` (the pinned versions) |
| licenses of the bundled binaries | `licenses/NOTICE` |

The maintainer writes in Ukrainian; code, comments, commits and documents are in English. When the maintainer is confused, explain it simply and say honestly what was not verified and what was a guess.
