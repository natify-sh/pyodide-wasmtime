#!/bin/sh
# Pinned sources for the build, into WORKDIR (each download is checked by SHA-256 or a tag):
#   sh tools/fetch.sh WORKDIR
#   WORKDIR/sdk/wasi-sdk-34.0-x86_64-linux   the one clang/wasm-ld/cmake toolchain every wasm here is built with
#   WORKDIR/dl/pyodide, WORKDIR/dl/binaryen  npm packages (Node + Binaryen are BUILD tools; the run time has neither)
#   WORKDIR/dl/dist                          the files of Pyodide's 315.0.0a2 release (wheels, `test`, lock)
set -e
mkdir -p "${1:-pyo-build}"
W=$(cd "${1:-pyo-build}" && pwd)
mkdir -p "$W/sdk" "$W/dl"
SDK=wasi-sdk-34.0-x86_64-linux
if [ ! -d "$W/sdk/$SDK" ]; then
  curl -sSL --retry 3 -o "$W/sdk/$SDK.tar.gz" "https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-34/$SDK.tar.gz"
  echo "b761e3a0721dbae9c09a0059e5fdb2bf917d1b4a8a7b430fb3b5aafb0984b2c4  $W/sdk/$SDK.tar.gz" | sha256sum -c
  tar xzf "$W/sdk/$SDK.tar.gz" -C "$W/sdk" && rm "$W/sdk/$SDK.tar.gz"
fi
# the versions are package.json's (Dependabot tracks them); the release tarball below must be bumped with them
PKG=$(cd "$(dirname "$0")/.." && pwd)/package.json
PYODIDE_V=$(node -p "require('$PKG').dependencies.pyodide")
BINARYEN_V=$(node -p "require('$PKG').devDependencies.binaryen")
cd "$W/dl"
if [ ! -d pyodide ]; then
  npm pack "pyodide@$PYODIDE_V" "binaryen@$BINARYEN_V" >/dev/null
  mkdir -p pyodide binaryen
  tar xzf "pyodide-$PYODIDE_V.tgz" -C pyodide
  tar xzf "binaryen-$BINARYEN_V.tgz" -C binaryen
fi
if [ ! -d dist ]; then
  REL=pyodide-315.0.0a2.tar.bz2
  curl -sSL --retry 3 -o $REL "https://github.com/pyodide/pyodide/releases/download/315.0.0a2/$REL"
  echo "cd93f79338318074ad041747255a1a82fda7a1f775a204a8b8d42ddfc72b78f0  $REL" | sha256sum -c
  mkdir -p dist && tar xjf $REL -C dist --strip-components=1
fi
echo "ready: $W"
