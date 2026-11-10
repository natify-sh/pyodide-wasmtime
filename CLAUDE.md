# CLAUDE.md

Context and rules for working on pyodide-wasmtime with an agent. The way of work is taken from [wasmhost](https://github.com/natify-sh/py-wasmhost); where a rule below comes from the owner's words for this project it says so,
the rest is wasmhost's practice carried over and open to the maintainer's correction.

**Start with [`BRIEF.md`](BRIEF.md)**: what the project is, what it is not, and what is next.

## What this is
Pyodide's CPython run by wasmtime-py with no JavaScript: the Emscripten glue is a wasm adapter (`wasm/adapter.c`), the host is Python. Two packagings of the same sources, **fused** (one core module) and **dynamic**
(`pyodide.asm.wasm` + `adapter.wasm`), both in the wheel. An alpha, meant as a ready solution for anything Pyodide runs without the browser's JavaScript.

The maintainer communicates in Ukrainian; code, comments, commit messages and docs are in English.

## Hard rules
* **No run-time Python dependencies.** wasmtime-py is the `[wasmtime]` extra and a dev dependency; a missing engine says so (`_engine.require_wasmtime`). Python 3.10+. (The owner, 2026-11-10.)
* **The run time needs wasmtime-py and the wasm files of the package** (`pyodide.asm.wasm`, `wasm-opt.wasm`, `python_stdlib.zip`, `adapter.wasm`, `pyodide_fused.wasm`), **no Node and no native Binaryen**. Node and npm's Binaryen
  (`wasm-opt`, `wasm-merge`) exist only in the build (`tools/*.sh`) and in CI. (The owner, 2026-11-10.)
* **One toolchain: wasi-sdk 34's clang** builds every wasm we build (`adapter.wasm`, `wasm-opt.wasm`, the guest's `_ssl`); no `clang` from the system. (The owner, 2026-11-10.)
* **Both packagings are tested** wherever a test runs, and **Pyodide's official test suite** (`tests/test_pyodide_suite.py`, `python_tests.yaml`, libregrtest) runs on both, locally and in CI. A feature that works on one only is not done. (The owner, 2026-11-10.)
* **The supported Pyodide is pinned in `package.json`** (Dependabot tracks it); the adapter answers that build's `env` imports. A bump needs the new release sha in `tools/fetch.sh`, `PYODIDE_VERSION`/`PYODIDE_ABI`
  in `src/pyodide_wasmtime/__init__.py`, `PYVER` if Python changes, and a green CI on both packagings.
* **State lives in the `Pyodide` object, never in module globals**: two interpreters in one process must work (`test_two_interpreters_in_one_process`).
* **What cannot work is reported, not faked**: an import the adapter does not answer is a stub that returns 0/null (the JavaScript bridge: documented in BRIEF.md); a missing build or engine is an error that says what to run.
* **The wheel carries built wasm that is not committed** (`src/pyodide_wasmtime/data/` is ignored; CI builds it). The bundled binaries keep their licenses (`licenses/NOTICE`): a new one gets its text and a line there.
* **Measure, do not guess.** A claim about what runs has the command or the CI run behind it; a number has the command (and the machine) it came from. Say plainly what was not run (network checks need PyPI and jsDelivr, which a sandbox may block).
* **Nothing is pushed to `main`.** Every change goes through a pull request that the owner opens; the assistant works on a branch, does not open a pull request, rename the branch or squash history.
* **Do not copy the designs of wasmhost** (backends, a WebAssembly API): this is a separate project.

## How work is organised: one orchestrator, one subagent per step

The main session is the **orchestrator**. It does not implement steps itself: it chooses the next step, writes the brief, hands it to a subagent, **verifies** the result and fixes what the subagent got wrong. Every step of
implementation, investigation or measurement is done by a subagent with a fresh context, so the main session keeps the whole picture and stays small.

### Which model does what

| role | model | agent (`.claude/agents/`) | typical steps |
|---|---|---|---|
| **orchestrator** (main session) | **the strongest available** | — | pick the next step, write briefs, verify, fix small mistakes, keep the docs true, ask the maintainer |
| implementer | **Sonnet** | `implementer` | one scoped step: the host, a loader or net operation, a build script, tests, a CI job |
| reviewer | **Opus** | `reviewer` | an independent read of a high-stakes diff (the adapter, the loader, exception conversion, sockets and TLS, the build pins) with a fresh context and without the implementer's conclusions |
| runner | **Haiku** | `runner` | read CI logs and report which jobs and shards failed and why, summarise the junit files of the suite, run a build or a benchmark, mechanical edits |

### A step, from start to end

1. **Choose** (orchestrator): the next open item. One step = one goal that a command (or a CI job) can confirm. If it cannot be stated that way, it is not a step yet.
2. **Brief** (orchestrator), using the template below. A subagent knows only what the brief says.
3. **Do** (subagent): works only inside the brief's scope; if the step needs more than the scope or the budget, **stops and reports**.
4. **Report** (subagent): files changed, the commands run and their output, what is left, questions. No claim without the command that shows it.
5. **Verify** (orchestrator): read the diff against the brief (inside the scope? under the budget? no new dependency, nothing for later, no unrelated edits?); run `uv run ruff check . && uv run ruff format --check .` and
   `uv run pyright`; check the docs (README, BRIEF, `licenses/NOTICE`). The offline tests and the official suite are run by CI (and locally for a part: `PYODIDE_SUITE_SHARD`, `-k`); push the branch and read the jobs of
   Build wasm, Tests and Pre-commit. For the adapter, the loader, sockets and TLS a `reviewer` reads the diff with no access to the implementer's reasoning.
6. **Fix** (orchestrator): a small mistake (about 20 lines, obvious) in the main session; anything larger goes back to a subagent with a precise list; a second failure on the same point goes to the maintainer.
7. **Close**: one commit per step (what and why), `git fetch` and `git pull --ff-only` first, push, and **look at CI**. A red CI is fixed at once, not left. A step is done when it is implemented, tested
   (CI green, and said plainly where it was not run), the docs are true, and the owner agrees.

### The brief (template)

```
Goal:        <one sentence, as a result a command or a CI job shows>
Context:     <what exists, which files; what was tried and ruled out>
Read first:  <the 1-3 documents or files that matter; not the whole repository>
Scope:       <files that may change>      Out of scope: <what must not change>
Budget:      <~N lines of diff; stop and report if more is needed>
Acceptance:  <exact commands and the CI jobs that must be green, on both packagings>
Docs:        <README, BRIEF, licenses/NOTICE: which this step makes untrue>
Report:      files changed, commands run with output, docs updated, open questions
```

### Against over-engineering (applies to every agent)

* The smallest change that makes the acceptance command pass. No code "for later".
* No new module, class, layer, plugin point or option unless the brief names the need; no abstraction before its second real use.
* No rewrite of working code that the step does not require; no drive-by reformatting.
* When unsure between two designs, implement neither: report both with their costs.

## Working on the code
* `wasm/adapter.c` is the glue as wasm: one translation unit that includes the sections in `wasm/adapter/*.h` (header-only, `common.h` first; `tools/build_adapter.sh` compiles `adapter.c` only). Wasmtime's adapter rules hold (checked by `tests/test_shape.py`): **no data section** (`-fno-jump-tables`, names built from integer constants), **no stack of its own** (`-z stack-size=0`, it runs on Pyodide's stack),
  state in wasm globals pointing at blocks from the main module's `malloc`. It imports only WASI, the main module's memory/table/stack pointer/allocator and the host's `loader`/`net`/`aux`.
* `src/pyodide_wasmtime/_host.py` (`Pyodide`): `_start` builds either flavor; `run()` executes code in the guest's `__main__` through a wrapper that turns `SystemExit` into a status (Emscripten's `exit()` ends in `unreachable`).
  `_engine.py` is the one engine (exceptions, function references, GC), the machine-code cache in the user's cache dir, and `wasm-opt.wasm` run in-process. `_wasm.py` is the WAT of the dynamic build; import types come from `Module.imports`
  (wasmtime-py prints every reference type as `anyref`; here they are all `externref`). `guest/hostnet.py` runs inside the guest.
* Wheels with legacy exceptions are converted at `dlopen` by `wasm-opt.wasm` (`Pyodide.converted` counts them); the modules the build ships are converted at build time.
* The tests need the build: `sh tools/build_data.sh work` and `sh tools/prepare_testenv.sh work` (`WASM_OPT_WASM=path` skips the 12-minute build of `wasm-opt.wasm`). A missing build is a skip locally and a failure with `CI` set.
* A host function must not hold the engine across a wait for another thread; there are no threads here (as in Pyodide).

## Commands
```
uv sync                                                    # dev environment (add --group suite for the official suite)
uv run ruff check . && uv run ruff format --check .
uv run pyright
sh tools/build_data.sh work                                # the wasm of the package -> src/pyodide_wasmtime/data (needs node, npm; cmake + ninja for wasm-opt.wasm)
sh tools/prepare_testenv.sh work                           # numpy, micropip, openssl, the real _ssl, the `test` wheel -> work/testenv
uv run pytest -m "not network and not suite"               # offline, both packagings
uv run pytest -m network                                   # PyPI and jsDelivr
uv run pytest -m suite                                     # Pyodide's official CPython suite, both packagings (long; PYODIDE_SUITE_SHARD=I/N, PYODIDE_SUITE_FLAVORS=fused)
uv run python -m pyodide_wasmtime [--flavor fused|dynamic] -c "print(1 + 1)"
uv build --wheel                                           # the wheel carries data/
```
CI: `build.yml` (wasm-opt.wasm cached, data, testenv), `tests.yml` (offline on Linux/Windows/macOS, network, the suite in 8 shards per packaging), `pre-commit.yml`, `publish.yml` (wheel only: the wasm is built, not committed).
