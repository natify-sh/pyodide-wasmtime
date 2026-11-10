#!/bin/sh
# EXPERIMENT (branch claude/wasip2-component): pyodide_fused.wasm as a WASI 0.2 component, run by stock `wasmtime run`.
#   sh tools/wasip2/build.sh WORKDIR      (after tools/build_data.sh: needs src/pyodide_wasmtime/data/pyodide_fused.wasm)
# -> WORKDIR/p2/pyodide.component.wasm, WORKDIR/p2/root (a guest "/": the stdlib zip), and the command to run it.
# What it does to the fused module: `loader.*` (dlopen of a wheel) and `net.*` become stubs (-1 / -ENOSYS: no wheels at run time,
# no sockets yet); a `_start` (WAT) passes WASI args to Py_BytesMain; `cabi_realloc` is added; then Binaryen's wasm-merge puts it
# together and wasm-tools' `component new` adapts wasi_snapshot_preview1 to WASI 0.2 with Wasmtime's own adapter.
set -e
H=$(cd "$(dirname "$0")/../.." && pwd)
mkdir -p "${1:-work}"
W=$(cd "${1:-work}" && pwd)/p2
mkdir -p "$W" && cd "$W"
B=https://github.com/bytecodealliance
fetch() { # name url sha256
  [ -f "$1" ] || { curl -sSL --retry 3 -o "$1" "$2"; echo "$3  $1" | sha256sum -c; }; }
fetch wasm-tools.tgz $B/wasm-tools/releases/download/v1.263.0/wasm-tools-1.263.0-x86_64-linux.tar.gz 21c036c1740a0552124c79c6e2170cb61c5b016005671a6d5bc06cf642165431
fetch wasmtime.txz $B/wasmtime/releases/download/v50.0.1/wasmtime-v50.0.1-x86_64-linux.tar.xz 685466455dd42a14774a86c36c8f2e45cbb9bd6d92a850139315df60a75498a5
fetch adapter.wasm $B/wasmtime/releases/download/v50.0.1/wasi_snapshot_preview1.command.wasm 0b4fe490390ecc9c2222f969f65b179e658a3327e005efd4ddc959766132a3c4
[ -d wasm-tools-1.263.0-x86_64-linux ] || tar xzf wasm-tools.tgz
[ -d wasmtime-v50.0.1-x86_64-linux ] || tar xJf wasmtime.txz
WT=$W/wasm-tools-1.263.0-x86_64-linux/wasm-tools
WM=$W/wasmtime-v50.0.1-x86_64-linux/wasmtime
python3 "$H/tools/wasip2/gen_net.py" > net.wat
cp "$H/tools/wasip2/start.wat" "$H/tools/wasip2/loader.wat" .
for m in start loader net; do "$WT" parse $m.wat -o $m.wasm; done
DATA=${DATA:-$H/src/pyodide_wasmtime/data}
# --rename-export-conflicts: the stubs export names the libc of Pyodide exports too (close, socket, ...)
node "$W/../dl/binaryen/package/bin/wasm-merge" "$DATA/pyodide_fused.wasm" pyodide loader.wasm loader net.wasm net start.wasm start \
  --all-features --disable-compact-imports --rename-export-conflicts -o merged.wasm
"$WT" validate --features all merged.wasm
"$WT" component new merged.wasm --adapt wasi_snapshot_preview1=adapter.wasm -o pyodide.component.wasm
"$WT" validate --features all pyodide.component.wasm
rm -rf root && mkdir -p root/lib/python3.15/site-packages root/lib/python3.15/lib-dynload
cp "$DATA/python_stdlib.zip" root/lib/python315.zip
printf "import encodings\nencodings.__path__.append('/lib/python315.zip/encodings')\n" > root/lib/python3.15/site-packages/sitecustomize.py
ls -l pyodide.component.wasm
echo "run: $WM run -W all-proposals=y --dir $W/root::/ --env PYTHONHOME=/ --env PYTHONPATH=/lib/python3.15/site-packages $W/pyodide.component.wasm -c 'print(1 + 1)'"
