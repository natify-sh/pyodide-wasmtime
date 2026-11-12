> **History.** This is the write-up of the experiment (2026-11-10, from wasmhost) the package grew out of. It says "not in CI" and
> names scripts (`prepare.sh`, `run_tests.py`, `run_pyodide_adapter.py`...) that are now `tools/*.sh`, `tests/` and `src/pyodide_nojs/`;
> see the README for the current state. The mechanics below are unchanged.

> **Historical measurement:** measured when the host's `/dev` was mounted with `--dev`, since removed (the adapter serves a virtual `/dev`, BACKLOG W2).

# Pyodide without JavaScript: the Emscripten glue as wasm (experiment, 2026-11-10)

Not a goal and not part of wasmhost: an experiment of what is possible, by hand on Linux, **not in CI**.
It continues `docs/experiments/pyodide_nojs/` of wasmhost (2026-11-05/06), where a Python host answered
every import of `pyodide.asm.wasm`. Here the Emscripten `env` glue is moved into wasm, after the shape of
Wasmtime's `wasi_snapshot_preview1` adapter: system calls, the dynamic loader, libffi's calls, sockets, time,
the trampoline. **Pyodide is not rebuilt**: `pyodide.asm.wasm` and `python_stdlib.zip` are the npm package's
(315.0.0-alpha.2, Python 3.15.0rc1), with only the offline conversion of legacy exceptions to `exnref`.

**One set of sources, two builds**, both run by wasmtime-py and both passing the same checks:

* **dynamic**: `adapter.wasm` next to the unchanged `pyodide.asm.wasm`, linked at run time with the
  shim/fixup of wit-component (five modules);
* **fused**: `fuse.py` merges `pyodide.asm.wasm`, the adapter, the trampoline, the stubs and the GOT globals
  into **one core module** (`wasm-merge`) that imports only `wasi_snapshot_preview1` (27), `loader` (4) and
  `net` (9).

## Results (`run_tests.py`, both builds)

| check | what it shows |
|---|---|
| `shape` | `adapter.wasm` has no memory or data section and no stack, and imports only WASI, the main module's memory/table/stack pointer/allocator and the host's `loader`/`net`/`aux`; the fused module imports only `wasi_snapshot_preview1`, `loader`, `net` |
| `numpy` | numpy 2.4.3 (13 extension modules loaded by the loader in wasm) prints exactly `numpy_check.expected` (the same lines as wasmhost's Python-host experiment) |
| `openssl` | the lock's `libopenssl` 1.1.1w in the guest through ctypes: version, `SHA256` equal to hashlib's, `SSL_CTX_new` |
| `net` | through the host's fetch: `pyodide.http.pyfetch`, `micropip.install(["six", "attrs", "requests"])` from PyPI, `requests.get`, and a binary Pyodide wheel (`cffi`) installed by micropip and loaded by the adapter's loader |
| `tls` | **HTTPS made by the guest itself**: CPython's real `_ssl` (built here) over Pyodide's OpenSSL, sockets by the adapter over the host's socket operations: a TLS 1.3 handshake with pypi.org, the certificate verified, `urllib.request.urlopen` |
| `tls_micropip` | micropip and `requests` over the guest's own TLS: no host fetch at all |
| `tls_refuses` | with no CA, the guest refuses the server's certificate ("self signed certificate in certificate chain") |
| `numpy_wheel` | micropip installs numpy's wheel from the CDN **as it is** (legacy exceptions); the loader converts its two modules at dlopen with `wasm-opt.wasm` (Binaryen as WASI, in-process), then `numpy_check.expected` exactly |

15 of 15 passed (2026-11-10, after `prepare.sh` from scratch: 36 s; the checks: 3 min 43 s). Wall time on one
machine (2 cores): numpy about 12 s on either build (the Python host of wasmhost's experiment: 14-15 s);
`tls_micropip` 22 s; `numpy_wheel` 25 s dynamic, 17 s fused (the first run compiles `wasm-opt.wasm` once and
caches it).

## How it is put together

### The adapter (`adapter.c`, about 1 200 lines)

C, built by `build.sh` with clang 18 as an Emscripten-style side module (`-fPIC -shared`), following the
rules of Wasmtime's adapter (its `verify/` tool):

* **no data section**: clang turned a chain of `?:` into a lookup table in `.rodata` (the trap Wasmtime's
  `byte-array-literals` crate exists for): `-fno-jump-tables`; names are built from integer constants;
* **no stack of its own** (`-z stack-size=0`): it runs on Pyodide's stack and on Pyodide's pointers;
* **state** in wasm globals (inline asm, as Wasmtime's `get_state_ptr`) pointing at blocks from the main
  module's `malloc`: directory cookies, the preopens, the loaded libraries, the sockets.

`build.sh` re-exports the imported memory (wasmtime's WASI reads the caller's `memory` export; `wasm-ld`
refuses `--export-memory` with `--shared`).

What it answers (the `env` imports of `pyodide.asm.wasm`, 49 of 263; the other 214 are the JavaScript bridge,
GL and the like, zero/null stubs):

* **files**: `openat`, `stat`/`lstat`/`fstat`/`newfstatat`, `getdents64`, `readlinkat`, `faccessat`, `getcwd`,
  `mkdirat`, `unlinkat`, `rmdir`, `renameat`, `ftruncate64` over WASI preview1; the preopens are read once
  (`fd_prestat_*`, as wasi-libc does) and an absolute path goes to the longest matching one; modes and times
  are accepted and ignored;
* **the loader** (`_dlopen_js`, `_dlsym_js`, `ffi_closure_*`): the file through WASI, `dylink.0` (sizes and
  **NEEDED**: the libraries a module needs are loaded first, found as the glue finds them: the runtime paths, `LD_LIBRARY_PATH`, else the name as written), the GOT (its own
  symbols, the main module's, the libraries loaded before), memory from `calloc`, table slots, relocations,
  constructors;
* **`ffi_call_js`** (ctypes and cffi calls) and **`ffi_prep_closure_loc_js`** (callbacks): host operations (`loader.ffi_call`,
  `ffi_prep`, `ffi_slot`, `ffi_free`). The host calls the table function with its real wasm type (any arity, 64-bit, floats,
  structs, variadic calls) as `wasmTable.get(fn)(...args)` does, and a callback is a host function of the closure's signature
  in a table slot (freed slots are reused). The earlier `call_indirect` dispatch (`tools/gen_ffi.py`, `FFI_STATIC=1`) was
  removed: it still needed the host for closures and time, so it was no build without a host;
* **sockets**: `socket`, `connect`, `sendto`, `recvfrom`, `shutdown`, `getpeername`/`getsockname`,
  `getsockopt` (`SO_TYPE` is a stream: ssl checks it), `poll`, `ioctl(FIONBIO)`, `getaddrinfo` and
  `_emscripten_lookup_name` (IPv4, as Emscripten's own: one `addrinfo`); a socket is a guest descriptor from
  4096 on, and the main module's `fd_read`/`fd_write`/`fd_close`/`fd_fdstat_get` reach the adapter first
  (OpenSSL reads and writes its socket with `read`/`write`), other descriptors pass on to WASI;
* **time**: `_gmtime_js`, `_localtime_js`, `_timegm_js`, `_mktime_js`, `_tzset_js` in UTC (OpenSSL checks
  certificate dates with them; as stubs every date was a format error);
* `emscripten_date_now`/`get_now`, `resize_heap`, `get_heap_max`, `_emscripten_get_progname`.

### The host (`run_pyodide_adapter.py`)

What a wasm module cannot do, or what is a real system call:

| host side | what |
|---|---|
| WASI preview1 | wasmtime's own (`define_wasi`); the guest's `/` is a temporary folder with the stdlib zip and the site folder; `PREOPEN_DEV=1` adds the host's `/dev` (OpenSSL reads `/dev/urandom`) |
| `loader.instantiate`, `sym`, `got_set`, `call` | the host holds the instances and their exports by name: instantiate a module with the main module's memory, table, stack pointer and tags (a name with no definition is bound lazily, as the glue does; a module with legacy exceptions is converted first by `wasm-opt.wasm`, in-process), look up an export (a global's value, or a function's table slot), set a GOT global, call an export |
| `net.socket`, `connect`, `send`, `recv`, `poll`, `close`, `shutdown`, `name`, `resolve` | the host's sockets (WASI preview1 has no `connect`); errors in WASI's numbering, which is Emscripten's |
| `fetch` (optional) | HTTP and TLS by the host, as a browser's fetch or `wasi:http`; reached by the guest through ctypes (a table slot written to `_hostnet_slots.py`) |

Dynamic build: the **shim** (WAT generated from the import list) exports every `env` function (the ones the
adapter answers `call_indirect` through its table) and the 280 `GOT.func` globals, and the four routed WASI
functions; then the main module, the trampoline module, the adapter, and the **fixup** fills the shim's table.
Fused build: the same pieces merged by `fuse.py`; nothing is generated or linked at run time.

The trampoline (`_PyEM_TrampolineCall_JS`, what JavaScript's `wasmTable.get(f)(a, b, c)` does) is WAT:
`ref.test` on the table entry's type, then `call_ref`; it needs wasm GC.

### wasm-opt at run time (`wasm-opt.wasm`, `wasmtools.py`, `build_binaryen.sh`)

Pyodide's wheels are built with legacy wasm exceptions, which wasmtime does not run. The modules of
`prepare.sh` are converted at build time (npm's Binaryen under Node), but a wheel micropip installs at run time
reaches the loader unconverted. For that the runner has Binaryen's `wasm-opt` as **one more wasm module**:

* `wasm-opt.wasm`: Binaryen version_132 built for `wasm32-wasip1` with wasi-sdk 34 (`build_binaryen.sh`):
  C++ exceptions as `-fwasm-exceptions` in the exnref form (Binaryen throws and catches internally), one thread
  (wasip1 has none: Binaryen's pool falls back), DWARF and names stripped (25.3 MB -> 12.5 MB). It imports only
  `wasi_snapshot_preview1` (15). Its `--translate-to-exnref` output of `pyodide.asm.wasm` is **byte-identical**
  to npm's Binaryen 132 (sha256 `a2b7d1e3...`).
* `wasmtools.py` runs it in-process: a store of its own, WASI with one preopen (a temporary folder), the host's
  stdout/stderr; the compiled code is cached next to it (`wasm-opt.wasm.cwasm`, keyed by the wasmtime-py version
  and the file), so a conversion of `pyodide.asm.wasm` takes about 3 s after the first.
* The loader (`dl_instantiate`): when a module does not compile because of legacy exceptions, it converts it
  with `$WASM_OPT` (a `.wasm` run in-process, or a command) or `PYODIDE_DIR/wasm-opt.wasm`, then instantiates.
  So the run time needs wasmtime-py only: no Node, no native Binaryen. The build keeps npm's Binaryen
  (`wasm-opt`, `wasm-merge`): a build dependency, not a run-time one.
* Building it: about 12 min on 2 cores. With `BUILD_LLVM_DWARF=OFF`, version_132 does not build
  (`src/passes/Outlining.cpp` includes `llvm/Support/Allocator.h` through `suffix_tree.h`, whose include path
  comes only with DWARF on).

### Networking in the guest (`hostnet.py`)

* `hostnet.install()`: `pyodide.http.pyfetch`/`open_url`, a urllib handler for http and https, and urllib3's
  emscripten fetch, all on the host's fetch;
* `hostnet.native()`: the guest's own sockets and TLS; urllib3 keeps its socket backend (its emscripten one
  needs JavaScript);
* `hostnet.run(coro)`: an asyncio loop with no I/O (micropip is async; the default loop needs a socketpair).

### TLS in the guest (`build_ssl.sh`)

Pyodide removed `ssl` on purpose (changelog of 314, PR #6044): `_ssl` is a Python stub, `_ssl` and `_hashlib`
are `*disabled*` in its CPython `Setup.local`, and its `ssl.py` raises "TLS not supported in this environment"
in `do_handshake`. The lock still has `libopenssl` 1.1.1w (CPython 3.15 needs >= 1.1.1). `build_ssl.sh` compiles
CPython 3.15.0rc1's `Modules/_ssl.c` as a side module against it, with the Python headers of Pyodide's
xbuildenv, Emscripten 6.0.5's libc headers and OpenSSL 1.1.1w's headers (`opensslconf.h` from its Configure);
clang 18 needs `ssl_prelude.h` (the `__*_C` macros Emscripten 6's musl expects) and `OPENSSL_THREADS` is defined
(Pyodide's OpenSSL has no threads; Pyodide has one). The site folder gets `_ssl.cpython-315-wasm32-emscripten.so`
(NEEDED `libssl.so`, `libcrypto.so`), the two libraries and CPython's own `Lib/ssl.py`; `PYTHONPATH` puts them
before the stdlib zip. `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` name the host's CA bundle copied into the guest.

**In this sandbox TLS goes through an intercepting egress gateway** (issuer "Egress Gateway SDS Issuing CA",
the same one the host's own Python sees), whose CA is in the bundle; a run elsewhere uses the public CAs.

## Found on the way

* **The sandbox is real**: the Python host followed a symlink out of its root; wasmtime's WASI does not leave
  the preopen (the runner copies the site folder inside).
* **Codecs**: the frozen `encodings` package looks in `/lib/python3.15/encodings`, which does not exist (the
  stdlib is the zip); every codec but the frozen ones was missing (`zipfile` needs `cp437`). The runner writes a
  `sitecustomize.py` that adds the zip's `encodings`.
* **Output is fully buffered** (stdout is not a terminal and nothing calls `Py_Finalize`): the runner flushes.
* **`coverage` 7.6.12 of this Pyodide build is broken**: its tracer imports `env.MyFrame_BorrowCode`, defined
  nowhere; bound lazily, the first call fails, as it would in Pyodide's own glue.
* **numpy through micropip**: its two legacy-exception modules are converted at dlopen by `wasm-opt.wasm`
  (`numpy_wheel`).

## Toolchain (what built what)

| artifact | compiler | target, libraries | flags that matter |
|---|---|---|---|
| `adapter.wasm` | Ubuntu clang 18.1.3, LLD 18.1.3 (`build.sh`) | `wasm32`, no libc (`-nostdlib`); a PIC side module | `-O2 -fPIC -fno-builtin -fno-jump-tables -fvisibility=hidden`; `wasm-ld --experimental-pic -shared -z stack-size=0`; the `memory` export appended by a patch |
| `_ssl.cpython-315-wasm32-emscripten.so` | Ubuntu clang 18.1.3, LLD 18.1.3 (`build_ssl.sh`) | `wasm32-unknown-emscripten`; headers: Emscripten 6.0.5's musl and system headers (from its sources: no emcc is run), Pyodide's xbuildenv 315.0.0a2 (Python 3.15.0rc1), OpenSSL 1.1.1w; linked against the lock's `libssl.so`/`libcrypto.so` | `-O2 -fPIC -DPy_BUILD_CORE_MODULE -DOPENSSL_THREADS -include ssl_prelude.h`; 159 075 bytes, the same on every build |
| `wasm-opt.wasm` (shipped, run time) | clang 23.1.0 of wasi-sdk 34 (`clang version 23.1.0-wasi-sdk`, LLVM `895aa2c`; `build_binaryen.sh`) | `wasm32-wasip1` (`wasi-sdk-p1.cmake`); wasi-sdk's `eh/` libc++, libc++abi, libunwind; wasi-libc's emulated signal, process clocks, mman | Binaryen version_132, Release, `-fwasm-exceptions -mllvm -wasm-use-legacy-eh=false`, LTO off, `BUILD_LLVM_DWARF=ON`, 8 MiB stack; then `--strip-debug --strip-producers` (25 339 196 -> 12 505 200 bytes, sha256 `17b98456...f174`) |
| `pyodide.asm.wasm` (exnref), numpy's two modules, `pyodide_fused.wasm` | npm's Binaryen 132.0.0 under Node (`wasm-opt`, `wasm-merge`): build only | | `--all-features --disable-compact-imports` (`--translate-to-exnref`; `wasm-merge ... --skip-export-conflicts`) |

wasi-sdk 34 is `wasi-sdk-34.0-x86_64-linux.tar.gz` of its GitHub release, checked by the SHA-256 in
`build_binaryen.sh` (`b761e3a0...b2c4`, taken from the download: the release has no published checksum file).
Pyodide is not rebuilt, and Emscripten's compiler is used nowhere.

## Reproduce

```sh
sh prepare.sh work            # downloads (pinned, checked), conversions, builds: adapter.wasm, _ssl.so, the fused module
python3 run_tests.py work     # all checks on both builds; --offline skips the network ones; -k NAME runs one
```

Tools: node + npm (Binaryen from npm, for the build only), curl, git, python3 with `pip install wasmtime` (50.0.1 was used),
clang and wasm-ld 18 with the wasm32 target, perl and make (OpenSSL's Configure). One check by hand:

```sh
python3 run_pyodide_adapter.py work/pyo work/site adapter.wasm "$(cat checks/numpy_check.py)"                  # dynamic
python3 run_pyodide_adapter.py work/pyo work/site work/pyo/pyodide_fused.wasm "$(cat checks/numpy_check.py)"   # fused
```

## Usage

The runner takes the Pyodide folder, a site folder (copied into the guest as `site-packages`), the build
(`adapter.wasm` for dynamic, `work/pyo/pyodide_fused.wasm` for fused) and the Python code to run:

```sh
python3 run_pyodide_adapter.py work/pyo SITE_DIR BUILD "python code"
```

**Your own code, network through the host** (the host makes HTTP and TLS; any site folder with micropip):

```sh
python3 run_pyodide_adapter.py work/pyo work/site_net work/pyo/pyodide_fused.wasm '
import hostnet, micropip
hostnet.install()                               # first: pyfetch, urllib and urllib3 go to the host
hostnet.run(micropip.install("requests"))       # hostnet.run: the asyncio loop
import requests; print(requests.get("https://pypi.org/pypi/six/json").json()["info"]["version"])
'
```

**Your own code, the guest's own TLS** (the host gives only sockets; `site_tls` has the real `_ssl`, the two
OpenSSL libraries, CPython's `ssl.py` and micropip; `PREOPEN_DEV=1` for `/dev/urandom`):

```sh
PREOPEN_DEV=1 python3 run_pyodide_adapter.py work/pyo work/site_tls adapter.wasm '
import hostnet, micropip
hostnet.native()                                # urllib3 on its socket backend (not the JavaScript one)
hostnet.run(micropip.install("requests"))
import requests, ssl; print(ssl.OPENSSL_VERSION, requests.get("https://pypi.org/simple/six/").status_code)
'
```

**numpy through micropip** (its two modules use legacy exceptions; the loader converts them when it loads them,
with `work/pyo/wasm-opt.wasm`):

```sh
python3 run_pyodide_adapter.py work/pyo work/site_net work/pyo/pyodide_fused.wasm '
import hostnet, micropip
hostnet.install()
hostnet.run(micropip.install("https://cdn.jsdelivr.net/pyodide/v315.0.0a2/full/numpy-2.4.3-cp315-cp315-pyemscripten_2026_5_wasm32.whl"))
import numpy as np; print(np.__version__, np.arange(10).sum())
'
```

**One build only** (after `prepare.sh` has made `work/` once):

```sh
sh build.sh                                     # adapter.wasm, from adapter.c
sh build_ssl.sh work                            # _ssl.so (+ libssl, libcrypto, ssl.py) into work/site_tls
sh build_binaryen.sh work                       # wasm-opt.wasm (shipped; this rebuilds it, ~12 min on 2 cores)
python3 wasmtools.py wasm-opt.wasm in.wasm --all-features --disable-compact-imports --translate-to-exnref -o out.wasm
WASM_MERGE="node work/dl/binaryen/package/bin/wasm-merge" \
  python3 fuse.py work/pyo/pyodide.asm.wasm adapter.wasm work/pyo/pyodide_fused.wasm   # the fused module (after build.sh)
```

The fused module must be made again after every change to `adapter.c`; the dynamic build picks up
`adapter.wasm` as it is.

## Next

[`NOTES-FUSEDWASI-AND-TESTSUITE.md`](NOTES-FUSEDWASI-AND-TESTSUITE.md):
* **fusedwasi** 0.1.0b3 gives a core module the `wasi:*@0.2.6` imports on wasmtime-py: the adapter's sockets
  on `wasi:sockets` would remove `net`, and the fused module would import WASI 0.1, WASI 0.2 and `loader` only;
* **Pyodide's test suite**: CPython's tests (819 modules in `python_tests.yaml`) apply as they are; the
  `@run_in_pyodide` tests with a small backend (`test_python_socket.py`, 36 tests, is the adapter's sockets);
  the JavaScript API tests are N/A.

## What this does not show

* One engine (wasmtime-py). The dynamic build needs several instances sharing a memory and a table (the
  JavaScript engines and waboros can, pywasm3 cannot); the trampoline needs wasm GC. The fused module needs
  only WASI preview1 and the host's `loader`/`net` operations, but was run only here.
* The loader: `RTLD_LOCAL` scopes are honoured now (see docs/IMPORT_AUDIT.md for what still differs).
* A ctypes call or callback goes through the host (a Python function per call): slower than a call in wasm, as exact in types as JavaScript's.
* Sockets: IPv4 lookups, blocking host sockets (timeouts kept by `poll`), no `bind`/`listen`/`accept`, no UDP
  tested, no `select` on mixed descriptors.
* `getdents64` with a buffer that splits entries across calls was not tested alone; no `fsync`, no modes.

## Files

| file | what |
|---|---|
| `adapter.c`, `build.sh` | the adapter and its build (`adapter.wasm`) |
| `run_pyodide_adapter.py` | the host: both builds, the loader and socket operations, the fetch |
| `fuse.py` | the fused build |
| `hostnet.py` | the guest's networking helpers |
| `build_ssl.sh`, `ssl_prelude.h` | the real `_ssl` for Pyodide 315 |
| `wasm-opt.wasm`, `wasmtools.py`, `build_binaryen.sh` | Binaryen's wasm-opt as WASI, run in-process at dlopen; how it is built |
| `prepare.sh` | downloads, conversions and builds into a work folder |
| `run_tests.py` | the checks on both builds |
| `checks/` | the check programs, `*.expected` (exact) and `net_check.observed` (one run of 2026-11-10) |
| `NOTES-FUSEDWASI-AND-TESTSUITE.md` | next steps: fusedwasi (WASI 0.2 for core modules on wasmtime-py) in place of `net`, and what of Pyodide's official test suite applies without JavaScript |
