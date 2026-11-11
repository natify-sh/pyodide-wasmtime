#!/bin/sh
# The wasm the package carries, into src/pyodide_wasmtime/data (or $DATA), from pinned sources:
#   sh tools/build_data.sh WORKDIR
#   pyodide.asm.wasm      Pyodide 315.0.0-alpha.2's, with libc's setsockopt stub made an import (tools/patch_main.mjs), legacy exceptions -> exnref (Binaryen 132 from npm: a BUILD tool)
#   python_stdlib.zip     the same release's
#   adapter.wasm          wasm/adapter.c, built with wasi-sdk 34's clang (the one toolchain)
#   pyodide_fused.wasm    the three above merged into one core module (tools/fuse.py, wasm-merge)
#   wasm-opt.wasm         Binaryen 132 as wasm32-wasip1 (tools/build_binaryen.sh, ~12 min); $WASM_OPT_WASM names a
#                         ready one (CI passes the cached artifact), else an existing one in DATA is kept
# Needs: node + npm (Binaryen's wasm-opt and wasm-merge), curl, git, cmake and ninja (only for wasm-opt.wasm), python3
# with wasmtime-py (fuse.py checks its result with it).
set -e
H=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "${1:-pyo-build}"
W=$(cd "${1:-pyo-build}" && pwd)
DATA=${DATA:-$H/src/pyodide_wasmtime/data}
mkdir -p "$DATA"
sh "$H/tools/fetch.sh" "$W" >/dev/null
# wasm-opt.wasm (the slow, mostly serial-link build) needs only the fetched sources: it runs beside the steps below
BG=
if [ -z "$WASM_OPT_WASM" ] && [ ! -f "$DATA/wasm-opt.wasm" ]; then
  OUT="$DATA/wasm-opt.wasm" sh "$H/tools/build_binaryen.sh" "$W" & BG=$!
fi
OPT="node $W/dl/binaryen/package/bin/wasm-opt"
node "$H/tools/patch_main.mjs" "$W/dl/binaryen/package" "$W/dl/pyodide/package/pyodide.asm.wasm" "$W/pyodide.patched.wasm"
$OPT "$W/pyodide.patched.wasm" --all-features --disable-compact-imports --translate-to-exnref -o "$DATA/pyodide.asm.wasm"
cp "$W/dl/pyodide/package/python_stdlib.zip" "$DATA/"
sh "$H/tools/build_adapter.sh" "$W" "$DATA/adapter.wasm"
if [ -n "$WASM_OPT_WASM" ]; then cp "$WASM_OPT_WASM" "$DATA/wasm-opt.wasm"; fi
if [ -n "$BG" ]; then wait "$BG"; fi
WASM_MERGE="node $W/dl/binaryen/package/bin/wasm-merge" PYTHONPATH="$H/src" \
  python3 "$H/tools/fuse.py" "$DATA/pyodide.asm.wasm" "$DATA/adapter.wasm" "$DATA/pyodide_fused.wasm"
ls -l "$DATA"
