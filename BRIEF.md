# Read this first

The briefing for anyone (person or agent) who starts work on this repository. Everything else is reference material: read it when a task needs it. The rules of work are in [CLAUDE.md](CLAUDE.md).

## What this project is, in one paragraph

**pyodide-wasmtime runs Pyodide's CPython, and its wheels, on wasmtime with no JavaScript.** Pyodide's `pyodide.asm.wasm` imports 263 functions from `env`: Emscripten's JavaScript glue. Here the glue is **wasm**
(`wasm/adapter.c`, built with wasi-sdk 34's clang, after the shape of Wasmtime's preview1 adapter: no data section, no stack of its own): system calls over WASI, the dynamic loader (`dlopen` of a wheel), libffi calls, sockets,
time, the trampoline. The Python host (`src/pyodide_wasmtime/_host.py`, class `Pyodide`) gives what a wasm module cannot do: wasmtime's WASI, four loader operations and the host's sockets. Pyodide is **not rebuilt**: its wasm is the npm
package's, with the legacy wasm exceptions converted once to `exnref`. The package is an **alpha** and meant to be a ready solution for anything Pyodide runs without the browser's JavaScript, not for numpy only.

## What it is NOT

* **Not Pyodide's JavaScript API.** `js`, `pyodide.ffi`, `JsProxy`/`PyProxy`, `loadPackage` from JS need the bridge; the 214 `env` imports that are the bridge, GL and the like are zero/null stubs. Tests that need them are N/A, not failures.
* **Not a rebuild of Pyodide or of Emscripten.** One Pyodide build is supported (`PYODIDE_VERSION` 315.0.0-alpha.2, ABI `pyemscripten_2026_5_wasm32`); the adapter answers that build's imports.
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
_host.py (Pyodide)  WASI = wasmtime's own; loader ops (instantiate/sym/got_set/call); net ops (sockets); the host's fetch; run() = PyRun_SimpleString
_engine.py          the engine, the machine-code cache (~/.cache/pyodide-wasmtime), wasm-opt.wasm run in-process
tests/              offline + network + Pyodide's official CPython suite, each on BOTH builds;  CI: build.yml -> tests.yml / publish.yml
```

## Where it is, and what is next

* **Done (2026-11-10):** the package on branch `claude/ecstatic-cray-to1b3t` (not yet merged): both builds, CLI, API, wheel (13 MB), tests, CI written. Offline tests pass locally on both builds; a part of the official suite passes (see the PR / CI for the current numbers). CI has not yet run end to end.
* **Next** (from [docs/NOTES-FUSEDWASI-AND-TESTSUITE.md](docs/NOTES-FUSEDWASI-AND-TESTSUITE.md)): read the CI run and fix what it shows; then the rest of the official suite (`test_python_socket.py`, the package tests of numpy/cffi/micropip/test-cpp-exceptions); WASI 0.2 over fusedwasi, replacing the `net` operations.
* **Standards we follow:** core WebAssembly 3.0 (exnref, GC, function references), the `dylink.0` convention (LLVM/Emscripten tool-conventions) for side modules, PEP 783 for the wheel tag (`pyemscripten_YYYY_N_wasm32`), WASI 0.1 now and 0.2/0.3 for sockets, HTTP and files next (replacing our `net` operations). The `loader.*` interface (four functions) is our own extension and the contract between the adapter and a host.
* **Waiting for the owner:** a pull request (the assistant does not open one); the decision about the license/size policy of Pyodide artifacts in the wheel (they are carried now; the alternative is a download at first run with a sha256 check); `CLAUDE.md` rules that were taken from wasmhost and are not yet confirmed for this project (below).

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
| the adapter | `wasm/adapter.c` |
| the host | `src/pyodide_wasmtime/_host.py`, `_engine.py`, `_wasm.py`, `guest/hostnet.py` |
| the build | `tools/` (`fetch.sh`, `build_data.sh`, `build_adapter.sh`, `build_binaryen.sh`, `build_ssl.sh`, `prepare_testenv.sh`, `fuse.py`), `package.json` (the pinned versions) |
| licenses of the bundled binaries | `licenses/NOTICE` |

The maintainer writes in Ukrainian; code, comments, commits and documents are in English. When the maintainer is confused, explain it simply and say honestly what was not verified and what was a guess.
