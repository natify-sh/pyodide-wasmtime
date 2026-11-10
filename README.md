# pyodide-wasmtime

Pyodide's CPython, and its wheels, run by [wasmtime](https://github.com/bytecodealliance/wasmtime-py) **with no JavaScript**. No browser, no Node, none of Pyodide's glue.
**Alpha:** the API and the wasm in the package change without notice; one Pyodide build is supported (below).

```sh
pip install 'pyodide-wasmtime[wasmtime]'
pyodide-wasmtime -c "import sys; print(sys.version, sys.platform)"      # 3.15.0rc1 ... emscripten
pyodide-wasmtime script.py arg1 arg2
pyodide-wasmtime                                                        # a REPL on a terminal; the script on stdin otherwise
```
```python
from pyodide_wasmtime import Pyodide

with Pyodide() as py:  # the fused build; Pyodide("dynamic") for the other
    py.run("import json; print(json.dumps({'a': 1}))")  # 0 if it ran, 1 if it raised, N for sys.exit(N)
    py.run("import sys; sys.exit(3)")  # -> 3, the interpreter stays usable
```

It is meant to run anything Pyodide runs without the browser's JavaScript: the standard library, binary Emscripten wheels
(numpy and the rest of Pyodide's lock: `site=` folders, or `micropip` over the host's fetch or the guest's own TLS),
files (`mounts={"/data": "/host/dir"}`), sockets, `ctypes`/`cffi`. What needs the JavaScript bridge (`js`, `pyodide.ffi`,
`pyodide.http` outside `hostnet`) does not exist here: those 214 `env` imports are zero/null stubs.

| | |
|---|---|
| Pyodide | **315.0.0-alpha.2** (`pyodide_wasmtime.PYODIDE_VERSION`), Python 3.15.0rc1, Emscripten 6.0.5, wheels of ABI `pyemscripten_2026_5_wasm32` (`PYODIDE_ABI`) |
| Python | 3.10+ (the host); CPython and PyPy |
| Needs at run time | wasmtime-py (`[wasmtime]`, 50.0.1+) and the wasm files **in the wheel**: `pyodide.asm.wasm`, `python_stdlib.zip`, `adapter.wasm`, `pyodide_fused.wasm`, `wasm-opt.wasm`. No Node, no native Binaryen |

## How it works
Pyodide's `pyodide.asm.wasm` imports 263 functions from `env`: Emscripten's JavaScript glue. Here the glue is **wasm**, after the
shape of Wasmtime's `wasi_snapshot_preview1` adapter (`wasm/adapter.c`, about 1 200 lines of C, no data section, no stack of its own):
system calls over WASI, the dynamic loader (`dlopen` of a wheel's `.so`), libffi's calls, sockets, time, the trampoline.
The host (`_host.py`) gives what a wasm module cannot do: wasmtime's WASI, the loader operations (it holds the instances by name),
libffi's calls and callbacks (a call is made with the callee's real wasm type, as the JavaScript glue does), the host's time zone and
the host's sockets. `Pyodide.interrupt(signum=2)` posts a signal to Python (a `KeyboardInterrupt` in a running loop). **Pyodide is not rebuilt**: its wasm is the npm package's, with the legacy wasm exceptions converted once to
`exnref` (wasmtime does not run the legacy ones).

Two packagings of the same sources, both in the wheel, both tested:

* **`fused`** (default): `pyodide_fused.wasm`, one core module (`tools/fuse.py`, `wasm-merge`) that imports only `wasi_snapshot_preview1`, `loader` and `net`;
* **`dynamic`**: `pyodide.asm.wasm` and `adapter.wasm` linked at run time (a shim generated from the import list, the trampoline, a fixup).

Wheels with legacy exceptions (every Emscripten wheel of Pyodide's CDN with C++ exceptions, numpy's two modules...) are converted at
`dlopen` by **`wasm-opt.wasm`**: Binaryen 132 as a `wasm32-wasip1` module, run in-process by wasmtime-py. Machine code of the big modules is cached in
`~/.cache/pyodide-wasmtime` (`$PYODIDE_WASMTIME_CACHE`), so a start takes a few seconds.

More in [docs/EXPERIMENT.md](docs/EXPERIMENT.md) (the experiment this came from: results, what the adapter answers, TLS in the guest, what was found on the way)
and [docs/NOTES-FUSEDWASI-AND-TESTSUITE.md](docs/NOTES-FUSEDWASI-AND-TESTSUITE.md) (WASI 0.2 over fusedwasi, next).

## Build (CI does this; Node is a build tool only)
One toolchain: **wasi-sdk 34's clang** builds `adapter.wasm`, `wasm-opt.wasm` and the guest's `_ssl`; Binaryen's `wasm-opt`/`wasm-merge` come from npm (`package.json` pins Pyodide and Binaryen; Dependabot tracks them).

```sh
uv sync
sh tools/build_data.sh work         # -> src/pyodide_wasmtime/data/*  (wasm-opt.wasm from source takes ~12 min; WASM_OPT_WASM=path reuses one)
sh tools/prepare_testenv.sh work    # -> work/testenv: numpy, micropip, openssl, the real _ssl, the `test` wheel, python_tests.yaml
uv build --wheel                    # the wheel carries data/ (the wasm is built, not committed)
```
Needs: node, npm, curl, git, cmake and ninja (for `wasm-opt.wasm`), perl and make (OpenSSL's `opensslconf.h`).

## Tests
```sh
uv run pytest -m "not network and not suite"     # offline: the interpreter, the shape of the wasm, numpy, openssl: both builds
uv run pytest -m network                         # PyPI and jsDelivr: the host's fetch, the guest's TLS, micropip, numpy's wheel
uv run pytest -m suite                           # Pyodide's official CPython test suite (python_tests.yaml, libregrtest), both builds
PYODIDE_SUITE_FLAVORS=fused PYODIDE_SUITE_SHARD=3/8 uv run pytest -m suite -k test_json      # a part
```
The suite runs one guest process per test module, as Pyodide's `test_cpython_core` does: `xfail` entries are reported as xfail (`PYODIDE_SUITE_RUN_XFAIL=1` runs them),
`skip` globs are passed on. Not included: the tests of the JavaScript API and `@run_in_pyodide`, which need a browser or Node.
CI (`tests.yml`): the offline tests on Linux, Windows and macOS (Python 3.10 and 3.15), the network checks, and the suite in 8 shards per build.

## Licenses
MIT for this repository. The wheel carries binaries under their own licenses: Pyodide (MPL-2.0, with CPython's PSF license and Emscripten's/musl's MIT), Binaryen (Apache-2.0) and wasi-sdk's libraries: see [licenses/NOTICE](licenses/NOTICE).
