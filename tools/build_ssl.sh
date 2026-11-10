#!/bin/sh
# (wasi-sdk 34 clang, the one toolchain) CPython 3.15.0rc1's _ssl as a side module for Pyodide 315.0.0-alpha.2, against the lock's libopenssl 1.1.1w:
#   sh build_ssl.sh WORKDIR        (after prepare.sh fetched WORKDIR/ref; output into WORKDIR/site_tls)
# Pyodide 314+ ships `_ssl` as a Python stub (PR #6044: "_ssl" and "_hashlib" are *disabled* in its CPython
# Setup.local), and its ssl.py refuses handshakes; this puts the real ones back, without rebuilding Pyodide:
# _ssl.cpython-315-wasm32-emscripten.so (NEEDED libssl.so, libcrypto.so) and CPython's own Lib/ssl.py, in a
# folder that comes before the stdlib zip on sys.path.
set -e
H=$(cd "$(dirname "$0")/.." && pwd)
W=$(cd "$1" && pwd)
SDK=$W/sdk/wasi-sdk-34.0-x86_64-linux
R=$W/ref
S=$W/ref/sysroot
B=$W/ref/sslbuild
X=$R/xbuildenv/pyodide-root/cpython/installs/python-3.15.0rc1/include/python3.15
O=$R/openssl-1.1.1w

# Emscripten's sysroot include layout from its sources (as its system_libs.py installs it)
rm -rf "$S" && mkdir -p "$S/include/bits"
E=$R/emscripten/system
cp -r "$E"/lib/libc/musl/include/* "$S/include/"
cp -r "$E"/lib/libc/musl/arch/generic/bits/* "$S/include/bits/"
cp -r "$E"/lib/libc/musl/arch/emscripten/bits/* "$S/include/bits/"
cp -r "$E"/include/* "$S/include/"

# opensslconf.h: OpenSSL's Configure for a 32-bit generic target without threads (the header only; opaque
# structs in 1.1.1 keep the layout independent of these options)
[ -f "$O/include/openssl/opensslconf.h" ] || (cd "$O" &&
  ./Configure linux-generic32 shared no-asm no-threads no-engine no-hw no-weak-ssl-ciphers no-dtls no-dso no-tests no-afalgeng >/dev/null &&
  make include/openssl/opensslconf.h >/dev/null)

# compile: clang 18 lacks the __*_C macros of Emscripten 6's musl (ssl_prelude.h); OPENSSL_THREADS: Pyodide's
# OpenSSL is built without threads, and Pyodide has one thread
mkdir -p "$B"
"$SDK/bin/clang" --target=wasm32-unknown-emscripten --sysroot="$S" -isystem "$S/include/compat" -isystem "$S/include" \
  -include "$H/wasm/ssl_prelude.h" -fPIC -O2 -fvisibility=hidden -DNDEBUG -DPy_BUILD_CORE_MODULE -DOPENSSL_THREADS \
  -I"$X" -I"$X/internal" -I"$R/cpython/Modules" -I"$O/include" -Wno-unused-command-line-argument \
  -c "$R/cpython/Modules/_ssl.c" -o "$B/_ssl.o"
# link as a side module; linking against the two libraries records them as NEEDED in dylink.0
"$SDK/bin/wasm-ld" --experimental-pic -shared --no-entry --unresolved-symbols=import-dynamic "$B/_ssl.o" "$W/testenv/site_ssl/openssl/libssl.so" "$W/testenv/site_ssl/openssl/libcrypto.so" \
  -o "$W/testenv/site_tls/_ssl.cpython-315-wasm32-emscripten.so"
cp "$W/testenv/site_ssl/openssl/libssl.so" "$W/testenv/site_ssl/openssl/libcrypto.so" "$W/testenv/site_tls/"
cp "$R/cpython/Lib/ssl.py" "$W/testenv/site_tls/ssl.py"
ls -l "$W/testenv/site_tls/_ssl.cpython-315-wasm32-emscripten.so"
