#!/bin/sh
# wasm/adapter.c -> adapter.wasm with wasi-sdk 34's clang (the one toolchain; tools/fetch.sh WORKDIR first):
#   sh tools/build_adapter.sh WORKDIR OUT.wasm
# A data-free, stack-free side module; then the imported memory is re-exported (wasmtime's WASI reads the caller's
# `memory` export; wasm-ld refuses --export-memory with --shared).
set -e
H=$(cd "$(dirname "$0")/.." && pwd)
W=$(cd "$1" && pwd)
S=$W/sdk/wasi-sdk-34.0-x86_64-linux
OUT=$(cd "$(dirname "$2")" && pwd)/$(basename "$2")
T=$(mktemp -d)
python3 "$H/tools/gen_ffi.py" > "$T/ffi_calls.h"  # the dispatch of ffi_call_js for mixed signatures
"$S/bin/clang" --target=wasm32 -O2 -fPIC -nostdlib -fno-builtin -fno-jump-tables -fvisibility=hidden -Wall -Wextra \
  -I"$T" -c "$H/wasm/adapter.c" -o "$T/adapter.o"
"$S/bin/wasm-ld" --experimental-pic -shared --no-entry --unresolved-symbols=import-dynamic -z stack-size=0 "$T/adapter.o" -o "$T/adapter.wasm"
python3 "$H/tools/add_memory_export.py" "$T/adapter.wasm" "$OUT"
rm -rf "$T"
ls -l "$OUT"
