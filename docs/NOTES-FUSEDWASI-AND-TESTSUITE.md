# Notes: fusedwasi as the host, and Pyodide's official test suite

Two next steps for this experiment, not done here. Facts are marked as either checked (in the fusedwasi
repository at `v0.1.0b3` = `5e0d354`, and in Pyodide's repository at tag `315.0.0a2` = `c47e555`) or as
estimates.

## 1. fusedwasi 0.1.0b3: WASI 0.2 imported by a core module, on wasmtime-py

**What it is (checked, fusedwasi README and `docs/host_scope.md`).**

- fusedwasi gives a *core* module the flat core form of the `wasi:*@0.2.6` functions: 200 stable imports of the command world and of `wasi:http`, of which `wasi:sockets` is 58 and `wasi:http` is 63.
- `wasi_snapshot_preview1` is implemented over the same state. There is one table of descriptors for both families.
- It comes in C and as a Python twin. The twin runs on wasmtime-py (`tests/neutral/neutral_wasmtime.py`).
- So "WASI 0.2 the way we use 0.1" works on wasmtime-py today. Wasmtime itself offers 0.2 only to components: its core `Linker.define_wasi` is 0.1.
- **Alpha.** Its README says `wasi:sockets` and `wasi:http` are unstable, with "no promise on their behaviour or their names until a real program uses them".

**What it would change here.**

| today | with fusedwasi |
|---|---|
| WASI 0.1: wasmtime's built-in WASI | WASI 0.1 and 0.2: fusedwasi (`State`, `Guest`), one state |
| `net.*`: 9 operations of our own in Python (socket, connect, send, recv, poll, close, shutdown, name, resolve) | gone: the adapter calls `wasi:sockets/tcp-create-socket`, `tcp` (start/finish-connect, the two streams), `ip-name-lookup`, `wasi:io/poll`, `wasi:io/streams` |
| the host's fetch (urllib in the runner) behind `hostnet.fetch` | optional: `wasi:http/outgoing-handler` (the twin has TLS through `ssl`); the guest's own TLS (`_ssl`) needs only the sockets |
| fused module imports `wasi_snapshot_preview1` (27), `net` (9), `loader` (4) | `wasi_snapshot_preview1`, `wasi:*@0.2.6`, `loader` (4) |

- **The loader stays the one import of our own:** instantiate, sym, got_set, call, which is `dlopen` of a wheel at run time. Neither WASI 0.2 nor the component model has it: a component cannot instantiate a new core module while it runs.
- **The socket code moves from the Python host into the adapter (C).** This is the same job Wasmtime's preview1 adapter does (0.1 calls over 0.2 imports), here from Emscripten's syscalls.
  - The fd routing stays: socket descriptors ≥ 4096 are the adapter's, mapped onto 0.2 resource handles.
  - `poll` becomes `wasi:io/poll.poll` over the streams' pollables.
  - `getaddrinfo` becomes `resolve-addresses` plus `resolve-next-address`.
- **`cabi_realloc`.** A 0.2 function that returns a list or a string calls the guest's `cabi_realloc`. The adapter can export one over the main module's `malloc`. That keeps the adapter's rules: no data, no stack of its own.
- **Cost (an estimate, to be measured).** Every WASI call becomes a Python function of the twin, instead of wasmtime's Rust. Reading the stdlib zip and files at import time is where this would show.
- **For fusedwasi itself.** Pyodide (`ssl`, `pip`/`micropip`, `requests`) would be the "real program" that its README says the unstable sockets and http are waiting for. Its `host_scope.md` already records `ssl`, an HTTPS request and `pip install` running on its host of `wasi2_python`.

**Plan.**

1. Keep the two builds and the 15 checks of `run_tests.py`.
2. Rewrite the socket part of `adapter.c` onto the 0.2 imports, and add a host mode in the runner: `--host fusedwasi`, the imports bound by `fusedwasi.signatures.find_import`.
3. Run the same checks on both hosts. Measure the import time of numpy and the TLS handshake on both.
4. Drop `net` from `check_adapter_shape` once fusedwasi passes.

## 2. Pyodide's official test suite: what applies without JavaScript

All counts were checked in `pyodide` at `315.0.0a2`. The suite has three kinds of tests, and they need different handling here.

**a) CPython's own tests (`src/tests/python_tests.yaml` and `test_core_python.py`): applicable as they are.**

- The list has 819 test modules: 38 marked `xfail` (skipped whole) and 56 with `skip` globs (tests excluded inside the module).
- `test_cpython_core` loads the package `test` (in the lock as `test-1.0.0-py2.py3-none-any.whl`: CPython's `Lib/test` plus `_testcapi`, `_testbuffer`, `_testmultiphase`, `_ctypes_test` built as side modules). For each module it runs `test.libregrtest.main.main([name], match_tests=..., verbose=True)` inside Pyodide.
- Code 4 means "no tests ran" (skip). A module that raises `unittest.SkipTest` at import is a skip.
- None of this needs JavaScript. A runner here is one guest process per module:
  - the `test` wheel goes into a site folder;
  - the side modules are converted to exnref by `wasm-opt.wasm`, or at dlopen;
  - the same snippet runs with the yaml's skips;
  - stdout is read.
- Pyodide gives a timeout of 30 s per module (more for some).
- This gives the honest number: modules passed / failed / skipped / xfail, compared with Pyodide's own list on node.
- **Expected differences, in both directions:**
  - The FS is real WASI preopens, not MEMFS. Some `os`/`shutil` tests may behave better and some differently.
  - Sockets are real host sockets, not the node bridge.
  - `ssl` is real (Pyodide's is a stub, so `test_ssl` is meaningful here).
  - There are no threads (as in Pyodide).
  - Signals: the adapter has no `raise`.

**b) Tests decorated with `@run_in_pyodide`: applicable with a small backend.**

- `pytest_pyodide.run_in_pyodide` serialises the test function's body and runs it inside Pyodide. The test file itself runs on the host.
- A replacement backend would give that body to `run_pyodide_adapter.py`, instead of selenium/node, and bring back the result or the exception.
- Where these tests are:
  - **core `src/tests`:** 379 of 680 test functions carry the decorator. Many still call into JS inside the body (`from js import ...`, `pyodide.ffi`). Those are not applicable, and only a run can tell how many.
  - **packages in this repository:** test files of 16 packages plus `_tests/test_packages_common.py`, 50 test functions (most packages now live in pyodide-recipes, and the lock of this alpha has 31 packages). numpy has 13, scipy 10, micropip 7, cffi 1, pytest 4, and `test-cpp-exceptions` has 4 (C++ exceptions across side modules: a good test of the exnref conversion).
- **The most direct one for this experiment:** `src/tests/test_python_socket.py`, 36 tests, all `@run_in_pyodide`, marked `only_node`.
  - The host starts a TCP server on 127.0.0.1 in a thread, and the guest connects with `socket`.
  - That is exactly the adapter's sockets, today over `net` and later over `wasi:sockets`.
  - Here the host and the guest are in one process, which these tests already assume for node.

**c) Tests of the JavaScript API: not applicable by definition, and to be counted as N/A rather than as failures.**

- These call `selenium.run_js`, test `pyodide.ffi`, `JsProxy`/`PyProxy`, type conversions, webloop, web workers, snapshots or the console.
- The biggest files: `test_jsproxy.py` 107, `test_pyproxy.py` 87, `test_typeconversions.py` 98, `test_pyodide.py` 76, `test_package_loading.py` 47 (loadPackage from JS), `test_stack_switching.py` 23 (JSPI), `test_webloop.py` 23.
- `test_cmdline_runner.py` (26) tests Pyodide's node CLI. A CLI of our own would need its own equivalent.

**Order.**

1. (a), the whole list, with a table by module. This needs only the `test` wheel and a loop.
2. `test_python_socket.py` from (b), first on `net` and then on fusedwasi. It is the one A/B test for section 1.
3. The package tests from (b): numpy, cffi, micropip, test-cpp-exceptions.
4. The rest of (b) from `src/tests`, with the JS-calling ones counted as N/A.
