#!/bin/sh
# The run time's wasm-opt: Binaryen version_132 as a wasm32-wasip1 module, with wasi-sdk 34:
#   sh tools/build_binaryen.sh WORKDIR   -> src/pyodide_wasmtime/data/wasm-opt.wasm (or $OUT)
# ~12 min on 2 cores; wasi-sdk 34 (tools/fetch.sh) is the one toolchain. The loader runs it in-process under
# wasmtime-py (_tools.py) to convert a wheel's legacy exceptions at dlopen; the build itself uses npm's Binaryen.
#   - C++ exceptions: Binaryen uses them (Precompute, the parsers), so -fwasm-exceptions in the exnref form
#     (-wasm-use-legacy-eh=false; wasmtime has no legacy exceptions) and wasi-sdk's eh/ libc++, libunwind
#   - threads: wasip1 has none; Binaryen's thread pool catches the failed std::thread and runs on one
#   - BUILD_LLVM_DWARF stays ON: with it OFF, version_132's Outlining pass still includes llvm/Support headers
#   - then DWARF and names are stripped (25.3 MB -> 12.5 MB; the code is unchanged)
set -e
# OUT: where wasm-opt.wasm goes (default: next to this script's parent, src/pyodide_wasmtime/data)
sh "$(dirname "$0")/fetch.sh" "$1" >/dev/null
H=$(cd "$(dirname "$0")/.." && pwd)
W=$(cd "$1" && pwd)
OUT=${OUT:-$H/src/pyodide_wasmtime/data/wasm-opt.wasm}
mkdir -p "$W/ref" && cd "$W/ref"
SDK=wasi-sdk-34.0-x86_64-linux
[ -d binaryen ] || git clone -q --depth 1 --branch version_132 https://github.com/WebAssembly/binaryen 2>/dev/null
S=$W/sdk/$SDK
F="-fwasm-exceptions -mllvm -wasm-use-legacy-eh=false -D_WASI_EMULATED_SIGNAL -D_WASI_EMULATED_PROCESS_CLOCKS -D_WASI_EMULATED_MMAN"
mkdir -p binaryen-build && cd binaryen-build
cmake -G Ninja ../binaryen -DCMAKE_TOOLCHAIN_FILE=$S/share/cmake/wasi-sdk-p1.cmake -DWASI_SDK_PREFIX=$S \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTS=OFF -DBUILD_SHARED_LIBS=OFF -DENABLE_WERROR=OFF -DBYN_ENABLE_LTO=OFF -DINSTALL_LIBS=OFF \
  -DCMAKE_C_FLAGS="$F" -DCMAKE_CXX_FLAGS="$F" \
  -DCMAKE_EXE_LINKER_FLAGS="-fwasm-exceptions -lunwind -lwasi-emulated-signal -lwasi-emulated-process-clocks -lwasi-emulated-mman -Wl,-z,stack-size=8388608" >/dev/null
ninja wasm-opt
node "$W/dl/binaryen/package/bin/wasm-opt" bin/wasm-opt --all-features --disable-compact-imports --strip-debug --strip-producers -o "$OUT"
ls -l "$OUT"
