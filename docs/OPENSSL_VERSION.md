# The OpenSSL of the guest's TLS: where it stands and whether we can go higher

Research report, 2026-11-11. No code of the repository was changed; everything measured was built in a scratch
directory. Purpose: the argument for an upstream proposal to Pyodide when pyodide-wasmtime reaches alpha.
Sources are URLs, files, or the command that produced the number; what could not be verified is in the last section.

## Summary

| route | effort | blocks | evidence |
|---|---|---|---|
| **today**: `_ssl` of CPython 3.15.0rc1 (ours) over the lock's `libopenssl` 1.1.1w (shared, Emscripten-built) | done | 1.1.1 has been end-of-life since 2023-09-11; no `group()`, `get_groups()`, `get_sigalgs()`, no ML-KEM/PQ; needs the host's `/dev` (`--dev`) for entropy | `tools/build_ssl.sh`, `tools/prepare_testenv.sh`; probe below: `OpenSSL 1.1.1w  11 Sep 2023` |
| (a) wait for Pyodide's `libopenssl` bump | unknown (weeks to never) | Pyodide's repo still has 1.1.1w **shared** (`pyodide/pyodide` main `packages/libopenssl/meta.yaml`); the 3.x one lives in `pyodide-recipes` as a **static** library for other packages; `ssl`/`_hashlib` are disabled in Pyodide 314+; open issue #6540 proposes AWS-LC instead | sections 1, 3a |
| **(c) static OpenSSL 3.5.9 LTS into our `_ssl.so`** | **done as a prototype, about 1 day to productise** (build script, CI, NOTICE, a few tests) | none found; one unexplained trap in `ssl.get_sigalgs()` | built here: 342 s with `-j2` under load 12; `_ssl.so` 3.58 MB; `ssl.OPENSSL_VERSION` is `OpenSSL 3.5.9 29 Sep 2026` in the guest; TLS 1.3 to pypi.org and a local TLS server on **both** packagings |
| (b) OpenSSL 3.x as shared `libssl.so` + `libcrypto.so` side modules, wasi-sdk-built | 2 to 4 days (a link recipe, `-shared` export lists, NEEDED handling); gains nothing over (c) for us, but is the shape a Pyodide package needs if several modules share it | needs `--experimental-pic -shared` linking of a large archive and the export list of the OpenSSL API (Emscripten's `EMULATE_FUNCTION_POINTER_CASTS`-like issues not met) | the same objects link as a static part today; the shared link was **not** tried |
| (d) another TLS library for `_ssl` | not feasible for the real `_ssl`; AWS-LC only | CPython's `_ssl.c` and `_hashopenssl.c` speak the OpenSSL API; only AWS-LC (and LibreSSL, partly) are API-compatible | CPython `_ssl.c` `OPENSSL_IS_AWSLC` branches; discuss.python.org thread 44505; Pyodide issue #6540 |
| **fallback: host TLS shim** (a guest `_ssl` in Python, TLS state machine on the host's `ssl`) | about 600 lines of Python + about 150 lines of host code, 1 to 2 weeks with tests | host's OpenSSL differs per platform; API fidelity is partial; no new wasm | prototype in the scratch dir: handshake with a local TLS server, hostname check enforced by the host (section 6) |

## 1. What Pyodide builds, and why 1.1.1w

Facts checked (raw files from `raw.githubusercontent.com`, GitHub pages through the fetch tool):

* The lock of 315.0.0-alpha.2 lists exactly one OpenSSL: `libopenssl 1.1.1w`, `package_type: shared_library`, file
  `libopenssl-1.1.1w.zip`, platform `emscripten_6_0_5`, ABI `2026_5`
  (`python3 -c ... pyodide-lock.json` on `work/dl/dist/pyodide-lock.json`).
* Its recipe (`pyodide/pyodide` tag 315.0.0a2 and `main`, `packages/libopenssl/meta.yaml`; the two are identical): source
  `https://www.openssl.org/source/openssl-1.1.1w.tar.gz`, `./Configure gcc -no-ui-console -no-tests -DHAVE_FORK=0
  -DOPENSSL_NO_SECURE_MEMORY -DNO_SYSLOG ${SIDE_MODULE_CFLAGS}`, static archives first, then `emcc
  ${SIDE_MODULE_LDFLAGS} libcrypto.a -o libcrypto.so` and `libssl.so` linked against `libcrypto.so`. Tags `core`,
  `library`, `shared_library`. So **`main` of `pyodide/pyodide` is still 1.1.1w**; there is no 3.x there.
* A **second** `libopenssl` exists in the new `pyodide/pyodide-recipes` repository
  (`packages/libopenssl/meta.yaml` on main): **OpenSSL 3.6.2**, `type: static_library`, `Configure linux-generic32 no-shared
  no-asm no-tests no-apps no-docs no-dso no-engine no-module no-threads --with-rand-seed=getrandom`, two patches
  (`0001-Allow-getentropy-for-Emscripten.patch`, upstream openssl PR 31882; `0002-Use-send-recv-for-Emscripten-sockets.patch`).
  History (GitHub commits page of `packages/libopenssl`): removed on 2026-06-09 in PR #598 ("Remove RobotRaconteur and
  libopenssl from the distribution": RobotRaconteur was the only user; "we can restore it anytime"), re-added on 2026-08-14
  inside PR #647 "Add database driver packages" ("we should add it back, so that we remember to have these patches").
  It is a build dependency (static, not a lock entry), not what the lock ships.
* `pyodide-recipes` `packages/cryptography/meta.yaml` builds its own OpenSSL 3.6.2 statically: "cryptography v47 requires
  OpenSSL >= 3.0, but Pyodide 314 no longer ships a downstream-linkable OpenSSL ... Build our own and link it statically",
  and points to pyca/cryptography PR #14787 that adds the same path in cryptography's own wheel build.
* **Why `ssl` has no OpenSSL in the main module** (Pyodide 314+): issue #6032 (stdlib unvendoring): re-vendoring everything grew
  the brotli `pyodide.asm.wasm` 2069 KB to 2942 KB (+42%); without OpenSSL +19%. PR #6044 (merged 2026-01-14) replaced
  `ssl` with a stub and disabled `_ssl` and `_hashlib` in `cpython/Setup.local` (still there on main). Its discussion: "OpenSSL is
  too large to vendor ... libcrypto and libssl together are over 3 MB"; "Pyodide actually builds OpenSSL 1.1.1w", "updating
  OpenSSL should be handled separately" (ryanking13 and agriyakhetarpal). Changelog 315.0.0a2 repeats it ("saves more
  than 3 MB").
* **Why 1.1.1 at the start**: not documented. PR #2263 (added `ssl`, `openssl`, `_ssl` packages, 2021-2022) has a commit "Downgrade
  openssl and add test" and no stated reason; issue #2124 used 1.1.1m. 1.1.1 was the long-term release until OpenSSL 3.0 (2021-09-07)
  and Pyodide never revisited it. No patch, toolchain or dependency constraint for 1.1.1 is written anywhere I found. (A guess: the
  recipe needed `-DHAVE_FORK=0`, no secure memory and no syslog, and nobody ported those switches to 3.x; the 3.x recipe above shows
  the replacement set is `no-threads`, `no-dso`, `no-engine`, `no-module`, the getentropy patch and a socket patch.)
* **Planned or discussed bump**: no issue or PR titled "OpenSSL 3" for the shared package was found (GitHub search results
  page for `repo:pyodide/pyodide openssl 3` lists only #6540 and #6032 as relevant). Open on **today's date** (2026-11-11):
  issue #6540 "Try AWS-LC for ssl/hashlib" by ryanking13: linking OpenSSL grew `pyodide.asm.wasm` by about 4 MiB; proposes AWS-LC
  (BoringSSL fork, API-compatible with CPython, backward-compatibility guarantee), with three experiments (size,
  hashlib/ssl function parity, NodeSockFS logic of the stub `ssl.py`). No comments yet.

So the position of Pyodide is: no OpenSSL in the main module for size; the 1.1.1w shared libraries are left over from the
unvendored-`ssl` days; the maintainers' own 3.x work is static and for other packages; the next step they have written down is AWS-LC.

## 2. CPython 3.15 and OpenSSL

Files fetched from `raw.githubusercontent.com/python/cpython/<tag>/...` (`v3.15.0rc1`, `main`, `v3.14.0`, `v3.13.0`, `v3.12.0`).

* **Minimum**: `configure.ac` (3.15.0rc1 and main): `#if OPENSSL_VERSION_NUMBER < 0x10101000L #error "OpenSSL >= 1.1.1 is required"`.
  `Doc/using/configure.rst` main, footnote 8: "OpenSSL 1.1.1 is the minimum possible version to build against, but the series is
  end-of-life and no longer receives public security fixes. Use the latest patch release of a currently supported LTS release
  series ... Other libraries that offer an API compatible with OpenSSL 1.1.1 or later may work, but are not officially
  supported." PEP 644 (3.10) made 1.1.1 the floor. **1.1.1 has not been dropped through 3.15 / main**: `_ssl.c` main still includes
  `_ssl_data_111.h` and has `#if OPENSSL_VERSION_NUMBER < 0x101010cf` and `OPENSSL_VERSION_MAJOR < 3` branches. The thread "Pathway
  to requiring OpenSSL 3 or newer in CPython?" (discuss.python.org 46055, Feb 2024) converged on the low-impact approach (drop
  1.1.1 from CI, document it) with no formal decision. **I found no decision that 3.15 final or 3.16 drops 1.1.1**; a drop is plausible but not announced.
* `_ssl.c` of 3.15.0rc1 knows OpenSSL 3.0, 3.4.1+ (`_ssl_data_36.h`) and **4.0** (`#if OPENSSL_VERSION_NUMBER >= 0x40000000L`);
  `main` adds ECH for 4.0. So the code is current; a 3.x library is the intended target.
* **WASM platforms**: `Platforms/emscripten/config.site-wasm32-emscripten` and `Platforms/WASI` do not configure or build OpenSSL (grep for
  `ssl`: only a README line that `ssl` is among modules not built); `Modules/Setup` has `_ssl`/`_hashlib` commented out. Both modules are
  simply absent from CPython's wasm builds unless a downstream (Pyodide) provides them.
* **What a 1.1.1 build lacks** (the `#if` branches of `_ssl.c` 3.15.0rc1 and the docs): `SSLSocket.group()` (needs 3.2),
  `SSLContext.get_groups()` (3.5), `SSLSocket.client_sigalg()/server_sigalg()` (3.5), `ssl.get_sigalgs()` (3.4), time of a session in
  64 bit (`SSL_SESSION_get_time_ex`, 3.3), EC curve setting through the provider API (`OPENSSL_VERSION_MAJOR < 3` uses the deprecated
  `EC_KEY` path), `x509_object_dup` is compiled in 1.1.1/3.0..3.2 only, error-code tables `_ssl_data_111.h`. `_hashopenssl.c` has `OPENSSL_VERSION_NUMBER >= 0x30000000L` branches (EVP_MD fetch).
  Measured in our guest (`probe.py` through `python -m pyodide_wasmtime --site ...`): with 1.1.1w `get_groups()` raises
  `NotImplementedError: ... requires OpenSSL 3.5 or later`, `get_sigalgs()` raises `... requires OpenSSL 3.4 or later`,
  `set_ecdh_curve("X25519MLKEM768")` raises `ValueError: unknown elliptic curve name`.
* **Our `_ssl` 3.15.0rc1 against 1.1.1w headers** compiles (one `clang` call, `tools/build_ssl.sh`) and runs: `ssl.OPENSSL_VERSION ==
  'OpenSSL 1.1.1w  11 Sep 2023'`, `HAS_TLSv1_3` True, 17 ciphers, TLS 1.3 handshake. Features compiled out are the ones above only.

## 3. Routes to a newer OpenSSL, with what was measured

Toolchain and recipe used (all in `/tmp/claude-0/.../scratchpad/openssl_research/build`): wasi-sdk 34 clang (`clang 23`) from
`work/sdk`, target `wasm32-unknown-emscripten`, the Emscripten 6.0.5 musl headers sysroot that `tools/build_ssl.sh` already assembles, and
`wasm/ssl_prelude.h`; OpenSSL **3.5.9** (release tag `openssl-3.5.9`, 29 Sep 2026, sha256
`603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a` of the tarball as downloaded from the GitHub release):

```
Configure linux-generic32 no-shared no-asm no-threads no-dso no-engine no-module no-apps no-tests no-docs \
  no-quic no-legacy no-afalgeng no-secure-memory --with-rand-seed=getrandom --openssldir=/etc/ssl \
  -fPIC -fvisibility=hidden CC=<wrapper around wasi-sdk clang> AR=llvm-ar RANLIB=llvm-ranlib NM=llvm-nm
make -j2 build_libs                                # libcrypto.a, libssl.a
clang ... -c Modules/_ssl.c (same flags as build_ssl.sh, -I openssl include dirs)
wasm-ld --experimental-pic -shared --no-entry --unresolved-symbols=import-dynamic _ssl.o libssl.a libcrypto.a -o _ssl.cpython-315-wasm32-emscripten.so
```

Patch 0001 (getentropy for `__EMSCRIPTEN__`) is **already in 3.5.9** (`rand_unix.c` line 397: `defined(__wasi__) || defined(__EMSCRIPTEN__)`);
patch 0002 (send/recv for Emscripten sockets in `include/internal/sockets.h`) applied cleanly but is only needed for OpenSSL's own socket BIO (`BIO_s_socket`), which CPython's `_ssl` does not use
for its sockets in our case (it passes the fd through `SSL_set_fd`, and our guest sockets are the adapter's; the TLS test passes either way; untested without it: a guess).

### 3(c) static into `_ssl.so`: built and run

* Build: configure + `make -j2 build_libs` = **342 s wall** on this machine (4 cores shared, load average 10 to 14), 1014 objects, no compile errors, 7 warnings.
  The compile of `_ssl.c` and the link take about 3 s. Pyodide's `-j3` recipe will be faster on a free machine (an estimate, not measured).
* Sizes (bytes; gzip -9):

| artifact | raw | gzip |
|---|---|---|
| today: `libcrypto.so` 1.1.1w | 1 471 004 | 614 480 |
| today: `libssl.so` 1.1.1w | 359 576 | 135 410 |
| today: `_ssl.so` (dynamic) | 158 808 | 55 330 |
| **today total** | **1 989 388** | **805 220** |
| OpenSSL 3.5.9 static in `_ssl.so`, full feature set | 3 582 575 | 1 144 075 |
| OpenSSL 3.5.9 trimmed (no ML-DSA, SLH-DSA, SM2/3/4, EC2M, legacy ciphers, SRP, CMS, CT, TS, OCSP, GOST, CMP, HTTP, comp; ChaCha20-Poly1305, ML-KEM, sockets kept) | 2 957 369 | 971 366 |

  `libcrypto.a` 6.2 MB, `libssl.a` 0.93 MB before linking. The full 3.x link is 1.8x the 1.1.1w set raw (1.4x gzipped): 3.x has the provider
  framework, ML-KEM/ML-DSA/SLH-DSA, QUIC off (`no-quic`), and a much bigger EVP layer. The trimmed row (second build: 202 s wall with `-j2`, 688 objects; same tests pass on it: local TLS server with hostname refusal, pypi.org handshake TLS 1.3, urllib, ML-KEM groups listed; `get_sigalgs()` still traps) removes algorithms nothing in a TLS
  client needs. Further trimming (`no-ec`-curves, `no-dh`, a stripped error-string table `no-err`) was not tried; the remaining 2.96 MB is mostly libcrypto's EVP/provider layer (a guess).
* **Run, both packagings** (`python -m pyodide_wasmtime --flavor fused|dynamic --site <dir with ssl.py and the .so>`; no `libssl.so`/`libcrypto.so` NEEDED any more):
  * `ssl.OPENSSL_VERSION` = `OpenSSL 3.5.9 29 Sep 2026`, `OPENSSL_VERSION_INFO` = `(3, 5, 0, 9, 0)`; all `HAS_*` true except NPN, SSLv2/3.
  * `tests/checks/tls_check.py` (HTTPS to pypi.org by the guest's own sockets and TLS, urllib): `handshake TLSv1.3 TLS_AES_256_GCM_SHA384 | peer cert subject CN: pypi.org`, `raw response: HTTP/1.1 200 OK`, `urllib 200 six` (fused).
  * Local TLS server on 127.0.0.1 (host thread, self-signed cert with a SAN): handshake OK on fused (25 ms) and dynamic (56 ms), echo OK, and
    `ssl.SSLCertVerificationError: Hostname mismatch, certificate is not valid for 'wrong.example'` (so verification, including hostname, works; same with 1.1.1w, 80 ms).
  * **No host `/dev` needed**: 3.5.9 seeds from `getentropy` (WASI `random_get` through the adapter). With 1.1.1w the same script without `--dev`/`preopen_dev`
    fails in `SSLContext(PROTOCOL_TLS_CLIENT)` with `ssl.SSLError: [SSL] malloc failure` (RAND init cannot read `/dev/urandom`). This is a practical gain: the guest no longer needs the host's `/dev` for TLS.
  * `ssl.create_default_context()` takes 0.1 s in the guest (loads the CA bundle found by default paths: `cert_store_stats` 122 CAs here).
  * New features visible: `SSLContext.get_groups()` lists `MLKEM512/768/1024`, `X25519MLKEM768`, `SecP256r1MLKEM768`, `SecP384r1MLKEM1024`; `get_ciphers()` 17; `set_ciphersuites` works. (`set_ecdh_curve("X25519MLKEM768")` is refused by CPython's EC-curve path; hybrids go through `set_groups`, not exercised.)
  * **Unexplained**: `ssl.get_sigalgs()` (calls `SSL_get1_builtin_sigalgs(NULL)`) **traps** with a memory fault (`wasm address 0x70000057`) inside `_ssl_get_sigalgs`
    right after the call. Everything else I probed worked. Not diagnosed (a guess: something in the static build, e.g. a table in a function-pointer cast or the `OBJ_nid2ln` path, differs; try `-O0`, or run the same call in a native build to see if it is OpenSSL's). It must be understood before shipping.
* **Entropy**: `--with-rand-seed=getrandom` plus `getentropy` (musl/Emscripten `getentropy` imported from the main module; the adapter answers it with WASI `random_get`: the import list of the linked `.so` has `getentropy` and no `open`/`read` of `/dev/urandom` was needed in the test above).
* **Threads/atomics**: `no-threads` (Pyodide has one thread; recipe 3.6.2 does the same); `OPENSSL_THREADS` is still defined for CPython's header check as in `build_ssl.sh`.
* **Imports** of the linked `.so` (`env`): 197 libc/CPython functions (`strlen`, `getentropy`, `poll`, `send`, `recv`, `stat`, `tcgetattr`, `sigaction`, `opendir`, ...) plus 19 `GOT.mem` and 3 `GOT.func`; the loader resolved all of them (the ones the guest does not have are the lazy stubs).
* **ABI**: no wasm exceptions, no setjmp; function-pointer casts of OpenSSL (the usual wasm "signature mismatch" risk) did not trap in the handshake paths tested (full TLS 1.3 client handshake, certificate verification). `get_sigalgs` is the only trap seen.

### 3(b) shared `libssl.so` + `libcrypto.so` (not built)

Pyodide's lock `libopenssl` is an Emscripten shared library: `dylink.0` with MEM_INFO (libcrypto 377 664 bytes memory, libssl 63 645) and, for libssl, `NEEDED libcrypto.so`;
`_ssl.so` records `NEEDED libssl.so libcrypto.so` (read from the files with a small parser; `work/testenv/site_tls`). A wasi-sdk-built shared library of the same shape is
what `tools/build_ssl.sh` already produces for `_ssl.so` (`--experimental-pic -shared`, `dylink.0` with NEEDED taken from the linked `.so` inputs). So dlopen by our loader and by Pyodide's JS
`dlopen` are possible in principle (same `env` import and `GOT.*` conventions as the Emscripten 6.0.5 main module, which the `_ssl.so` above already uses). Not tried; needs the `--export` list of the OpenSSL API (everything is hidden in the build above because of `-fvisibility=hidden`; a shared build would need `OPENSSL_EXPORT`-style visibility or `--export-dynamic` on `libcrypto.a`). Estimate 2 to 4 days; benefit only if several modules (`_hashlib`, `cryptography`) must share one copy.

### 3(a) waiting for Pyodide

See section 1: no bump to the shared 1.1.1w is planned; the maintainers are exploring AWS-LC (#6540), which does not give a shared `libopenssl`. Effort for us: zero, outcome: not soon.

### 3(d) another library

CPython's `_ssl.c` is written against the OpenSSL API; only AWS-LC (`OPENSSL_IS_AWSLC` branches already in 3.15: `set_client_sigalgs` "can't set ... on AWS-LC") and, partly, LibreSSL are supported;
discuss.python.org thread 44505 says mainline CPython became fully build- and test-compatible with mainline AWS-LC (PR 133624, May 2025), except TLS 1.3 post-handshake authentication.
rustls, mbedTLS, wolfSSL have no `_ssl` backend (a Python-level binding would be a new `ssl`, not CPython's). AWS-LC is the only real alternative and is Pyodide's own idea (#6540).
Not tried here: AWS-LC needs CMake and Go-free build (the C-only path with `-DDISABLE_GO=1`) and a wasm port; unknown effort (guess: 1 to 2 weeks).

### Known problems of OpenSSL 3 on wasm32

* Size (above); the fix is `no-*` switches and a static link (so the linker removes what `_ssl` does not reference).
* Providers and `OSSL_LIB_CTX`: the default provider is built in (`no-module`, `no-dso`), initialised lazily on first fetch. Measured: `create_default_context()` 0.1 s, first handshake 25 to 56 ms (local), i.e. no visible startup penalty versus 1.1.1w (80 ms measured once). Not a benchmark: single runs.
* `getentropy`: handled (3.5.9 has the patch upstream; PR 31882).
* 32-bit atomics: `no-threads` removes the need; with threads you would need `-pthread` and shared memory, which Pyodide does not use.
* `linux-generic32` is the target of both Pyodide's recipe and this one: wasm32 `long` is 32-bit, `BN_ULLONG` path used; `no-asm` required (no wasm assembly). Performance of RSA/EC is the portable C path (guess: several times slower than native asm; not measured).
* The `dylink` side: a static OpenSSL inside `_ssl.so` means two copies if `_hashlib` or `cryptography` also link OpenSSL (`cryptography` already links its own static 3.6.2). Different versions in one process are a risk only if symbols are shared; with `-fvisibility=hidden` they are not (checked on the section EXPORT of the linked `.so`: exactly `PyInit__ssl` and `__wasm_apply_data_relocs`).

## 4. What a newer version changes for users

* **TLS 1.3 is already in 1.1.1** (our guest negotiates `TLSv1.3` today). 3.x adds: post-quantum hybrid key exchange `X25519MLKEM768` (3.5 LTS) which major servers now offer/prefer (a client without it still works), ML-KEM/ML-DSA/SLH-DSA primitives, `SSLSocket.group()` (3.2), `get_sigalgs()` (3.4), `get_groups()` and signature names (3.5), certificate-compression is not built; better default security level behaviour and a cleaner provider API. OpenSSL 4.0 (released 2026-04-14, per `VERSION.dat`) adds ECH.
* **Security**: 1.1.1w (11 Sep 2023) is the last public 1.1.1 release; later fixes go only to premium-support customers. OpenSSL fixes since then that are in the public 3.x branches (ids and titles verified in `CHANGES.md`; **whether each one also affects 1.1.1 I could not verify: the advisories page openssl-library.org was not reachable**): CVE-2023-5363 (key/IV length resizing), CVE-2024-0727 (PKCS12 NULL deref), CVE-2024-5535 (`SSL_select_next_proto` buffer overread; I recall it lists 1.1.1 as affected), CVE-2024-9143 (OOB memory access with invalid GF(2^m) curve parameters), CVE-2024-13176 (ECDSA timing side channel), CVE-2025-9230 (RFC 3211 KEK unwrap OOB read/write), CVE-2025-9231 (SM2 timing, ARM64), CVE-2025-9232 (HTTP client `no_proxy` OOB read), CVE-2025-15467 (stack overflow in CMS `AuthEnvelopedData` parsing, severity High). For a TLS **client** the exposed surface is smaller than a server's (CMS, PKCS12, SM2 are not on the path) but certificate parsing and verification are. Treat as a guess: for the guest's use as an HTTPS client the practical exposure of 1.1.1w is limited, the reputational and compliance exposure ("EOL crypto library in the wheel") is not.
* **Supported lines** (this session, from `VERSION.dat`/`CHANGES.md` on GitHub: latest releases 3.0.22 (25 Aug 2026), 3.5.9 (29 Sep 2026), 3.6.5 (29 Sep 2026), 4.0.3 (29 Sep 2026)). The LTS and end-of-life dates are **from memory, not verified here** (openssl.org blocked): 3.0 LTS ends 2026-09-07 (so 3.0 is itself EOL now), **3.5 LTS to 2030-04**, 3.6 a short-lived non-LTS, 4.0 non-LTS. Pick **3.5.x (LTS)** for stability; Pyodide's recipes use 3.6.2 (which is already two patch releases behind: 3.6.5).
* **Ciphers, curves, verification**: 3.x defaults (security level 1; TLS 1.0/1.1 and weak ciphers disabled by default, as `create_default_context` sets TLS 1.2 minimum anyway), X.509 strictness is configurable the same way (`VERIFY_X509_STRICT` is a CPython default flag in 3.13+; `verify_flags` 557088 printed by both builds), partial-chain and trust-store behaviour unchanged. FIPS: the 3.x FIPS provider exists, but it is a separately built loadable module (`enable-fips`, needs `dso`/module support, which we turned off); **not offered**.
* **Who benefits**: not browser Pyodide (the browser does TLS; Pyodide's `ssl` is a stub and `pyfetch` uses `fetch`). Beneficiaries: Pyodide runtimes without a browser (ours; Node users of `ssl`/`urllib3`/`requests` whose sockets are provided by NodeSockFS), and any package that must link OpenSSL (`cryptography`, which already needs >= 3.0, `psycopg`, `mysqlclient` in `pyodide-recipes`).

## 5. Upstream proposal outline (to Pyodide)

Position: the shared `libopenssl` 1.1.1w in `pyodide/pyodide` is end-of-life and is the only reason the real `_ssl` of CPython 3.15 cannot show a current OpenSSL outside the browser; Pyodide's own `pyodide-recipes` already builds 3.6.2.

What we ask (smallest first):
1. **Replace the 1.1.1w recipe of `libopenssl`** (shared, for `_ssl`) by the 3.x **static-into-`_ssl`** layout, or at least **bump the shared one to 3.5 LTS**. The `pyodide-recipes` recipe is the starting point; we add `-fPIC -fvisibility=hidden`, drop `no-legacy`-class features (list in 3(c)), and keep `no-threads`, `no-dso`, `no-engine`, `no-module`.
2. **Offer an optional `_ssl` package** (a Pyodide package built from CPython's own `Modules/_ssl.c`, as `pyodide-build` side module) next to the stub, so runtimes with sockets (Node, wasmtime-py, wasmtime/wasmer hosts) can load the real one and browsers do not pay the size. This reverses nothing of PR #6044 (the main module stays small); it only needs the stub `ssl.py` not to shadow the real one when the package is installed (our `tools/build_ssl.sh` puts CPython's `Lib/ssl.py` ahead of the stdlib zip; in the current tree a `--site` folder did not win over the zip stub without a `sys.path.insert`, see section 7).
3. **Do not block on AWS-LC (#6540)**: our measurement gives the numbers it needs for OpenSSL 3.5.9 (below), so the comparison can be made on data.

What we can offer: the build recipe (`tools/build_ssl.sh` plus the OpenSSL configure line), a wasi-sdk 34 clang build (one toolchain, no Emscripten installation needed: the Emscripten sysroot headers suffice), and tests: TLS 1.3 handshake, CA verification, hostname-mismatch refusal, urllib/micropip over TLS on the two packagings, a local-TLS-server test needing no network.

Claims and the measurement behind each (all from section 3):

| claim | number / evidence |
|---|---|
| OpenSSL 3.5.9 LTS builds for `wasm32-unknown-emscripten` with one clang call chain | 342 s `-j2`, 1014 objects, 0 errors, 7 warnings |
| CPython 3.15's own `_ssl.c` compiles and runs against it | `ssl.OPENSSL_VERSION` `3.5.9` in the guest, `HAS_TLSv1_3`, 17 ciphers, ML-KEM groups listed |
| It works on both packagings | local TLS server + pypi.org: fused and dynamic |
| Size cost | full: 3.58 MB (1.14 MB gzip) vs 1.99 MB (0.81 MB gzip) today; trimmed 2.96 MB (0.97 MB gzip) |
| No more host `/dev` for entropy | 1.1.1w without `--dev`: `malloc failure`; 3.5.9: works |
| Not free of problems | `get_sigalgs()` traps (undiagnosed) |

## 6. Fallback: host TLS shim

Owner request D15: if the real wasm `_ssl` is not shipped, a guest-side Python `_ssl` that does TLS by the host's `ssl`.

### 6.1 The `_ssl` surface CPython 3.15's `ssl.py` needs

From `Lib/ssl.py` (`work/ref/cpython`, 3.15.0rc1): `import _ssl`; `from _ssl import OPENSSL_VERSION_NUMBER, OPENSSL_VERSION_INFO, OPENSSL_VERSION`;
`_SSLContext, MemoryBIO, SSLSession`; the exception classes `SSLError, SSLZeroReturnError, SSLWantReadError, SSLWantWriteError, SSLSyscallError, SSLEOFError, SSLCertVerificationError`;
`_txt2obj`/`_nid2obj` (`txt2obj`, `nid2obj`); `RAND_status, RAND_add, RAND_bytes`; `get_sigalgs`; `_DEFAULT_CIPHERS`, `_OPENSSL_API_VERSION`; `enum_certificates`, `enum_crls` (Windows only, guarded);
`get_default_verify_paths`; constants and flags: `HAS_*` (ALPN, SNI, ECDH, NEVER_CHECK_COMMON_NAME, PHA, PSK, TLSv1_x), `PROTO_*`, `VERIFY_*`, `OP_*`, `ALERT_DESCRIPTION_*`, `CERT_*`, `ENCODING_DER`, `HOSTFLAG_NEVER_CHECK_SUBJECT`, `SSL_ERROR_*`, `PROTOCOL_*`.
Pyodide's own stub `src/py/_ssl.py` (234 lines) already provides names and constants, with a `_SSLContext` and `MemoryBIO` that do nothing: a **base to extend** (starting point, not verified for completeness against 3.15).

* `_SSLContext` (a Python class in the shim, keeping the settings): `__new__(cls, protocol)`, properties `check_hostname`, `verify_mode`, `verify_flags`, `options`, `minimum_version`, `maximum_version`, `protocol`, `num_tickets`, `post_handshake_auth`, `keylog_filename`, `security_level`, `sni_callback`, `_host_flags`; methods `load_cert_chain`, `load_verify_locations(cafile, capath, cadata)`, `load_dh_params`, `set_default_verify_paths`, `set_ciphers`, `get_ciphers`, `set_ciphersuites`, `_set_alpn_protocols`, `set_ecdh_curve`, `get_ca_certs`, `cert_store_stats`, `session_stats`, `_wrap_socket(sock, server_side, server_hostname, owner, session)`, `_wrap_bio(incoming, outgoing, server_side, server_hostname, owner, session)`, `_msg_callback`.
* The `_sslobj` the context returns: `read`, `write`, `do_handshake`, `shutdown`, `pending`, `getpeercert(binary_form)`, `get_unverified_chain`, `get_verified_chain`, `cipher`, `shared_ciphers`, `compression`, `version`, `selected_alpn_protocol`, `get_channel_binding`, `verify_client_post_handshake`, `session`, `session_reused`, `server_side`, `server_hostname`, `context`, `owner`, `group`, `client_sigalg`, `server_sigalg`, `uses_ktls_for_send`.
* **Minimal** (enough for `create_default_context`, `wrap_socket`, `urllib`, `http.client`, `requests`/`urllib3`, `micropip` as a client): the exceptions, constants, version triple, `RAND_*` (delegate to `os.urandom`), `_SSLContext` with the settings above stored and `load_verify_locations`, `set_default_verify_paths`, `set_ciphers` (host), `_set_alpn_protocols`, `_wrap_socket` for the client case, and the `_sslobj` methods `read/write/do_handshake/shutdown/pending/getpeercert/cipher/version/selected_alpn_protocol/server_hostname/server_side/context/owner/session*`. Can be stubs (return `None`/raise `NotImplementedError`): `get_unverified_chain`/`get_verified_chain` (3.13+, used by few), `group`, signature-algorithm names, `keylog`, `sni_callback`, `session`/`SSLSession` (resumption), `txt2obj`/`nid2obj` (small table of OIDs), `get_sigalgs`, PHA, `shared_ciphers`, `compression`, `enum_*`, server side (`_wrap_socket(server_side=True)`, `load_cert_chain` used by servers only).
* `urllib3` 2 also reads `ssl.SSLContext.verify_flags`, `ssl.VERIFY_X509_STRICT`, `ssl.OP_NO_*` and `context.minimum_version`; `requests` and `micropip` ride on it.

### 6.2 Host side

Design that the prototype proved: **TLS state machine on the host, sockets stay in the guest.** The host keeps, per TLS connection, a host `ssl.SSLObject` made by `SSLContext.wrap_bio(incoming, outgoing, server_hostname=...)` (`MemoryBIO`s). The guest keeps its own socket (the host's socket in the net table, used through the ordinary adapter calls) and runs a pump:
`op(handshake|read|write)` -> returns `WANT_READ` or done -> guest sends whatever `outgoing` holds on its socket -> if `WANT_READ`, `recv` from the socket (with the guest's timeout/non-blocking semantics, `poll`) and `feed` into `incoming` -> repeat. This is exactly the shape of `ssl.SSLObject`/asyncio's `sslproto`, and it gives `SSLWantReadError`/`SSLWantWriteError` for non-blocking sockets and asyncio for free.
* **Ops** (one generic host call, as `FETCH` is today, written in a table slot to `_hostnet_slots`; **no adapter change**): `ctx_new(protocol, flags)`, `ctx_set(opts...)`, `ctx_load_verify(cadata)`, `ctx_default_paths`, `ctx_set_ciphers`, `obj_new(ctx, server_side, hostname, alpn)`, `feed(bytes)`, `eof`, `drain -> bytes`, `handshake`, `read(n)`, `write(bytes)`, `shutdown`, `info (version, cipher, alpn, peer cert DER)`, `close`. About 15 ops, each a JSON header plus a body, as in `_net_fetch`.
* **`load_verify_locations` from guest-visible files**: the shim reads the file **in the guest** (`cafile`, `capath`) and passes `cadata` (PEM/DER bytes) to the host; the host never reads a guest path.
* **Where verification happens**: on the host, in the host's OpenSSL, against the CA the guest passed or the host's default store. The guest cannot forge a verdict for a context it did not configure, but **the guest chooses the context settings** (`verify_mode = CERT_NONE`, `check_hostname = False`) exactly as with the wasm `_ssl`; and for an untrusted guest, the host can, in addition, enforce policy (minimum version, a CA set) in `ctx_new`, which the wasm `_ssl` cannot (a malicious guest can load its own `_ssl`). Private keys loaded by `load_cert_chain` would travel to the host (acceptable, the host is the trust base here).
* **What the guest sees**: it never touches key material in wasm memory (a small advantage: a guest memory bug cannot leak TLS keys), but the host process holds them.

### 6.3 Platform differences

The host's `ssl` is whatever the host Python links: Linux distro (system OpenSSL 1.1.1/3.0/3.5; this machine: Python 3.13 with `OpenSSL 3.5.9`), python.org Windows/macOS builds (bundled OpenSSL; versions lag, and 3.10-3.12 installers shipped 1.1.1 or 3.0 at different times: **from memory, unverified**), Homebrew/uv Pythons (3.x). Differences: protocol/cipher/group availability (`get_groups()`/ML-KEM only on 3.5+), `set_default_verify_paths` on Windows/macOS (system store via `enum_certificates` on Windows; the host may use its store: arguably an advantage), certificate error strings, `SSL_CERT_FILE` handling, FIPS-mode distro builds. API fidelity therefore equals "the host's `ssl` of that machine", while the guest believes `OPENSSL_VERSION` is what the shim reports (it should report the host's real string). An older host (1.1.1) gives exactly today's situation without wasm.

### 6.4 Estimate, test plan, risks

* Lines: guest `_ssl.py` shim **about 500 to 700 lines of Python** (a context with ~30 attributes, a `_SSLSocket`/`_sslobj`, `MemoryBIO` delegating to host `MemoryBIO`, exceptions mapped by `class` name and `errno`/`reason`, the constants copied from the host's `ssl`/`_ssl` at build); host side **about 120 to 200 lines** (the op table above, object registry per `Pyodide` instance: state lives in the object, not in module globals, to keep `test_two_interpreters_in_one_process` working; cleanup in `close()`); the loader/adapter unchanged. The prototype (74 lines including a local server, a TLS client pump and an override of `_net_fetch`) proves the core.
* Tests, both packagings: unit tests with a local TLS server (host thread) exactly as in the prototype (verified chain, wrong hostname refused, expired/untrusted refused, ALPN, non-blocking `SSLWantReadError`, client `shutdown`, `pending`), `urllib`/`http.client` against it, `urllib3`/`requests` from the wheel against it, `micropip` over it (network tier: PyPI), and `tests/test_pyodide_suite.py`'s `test_ssl` subset (expect many failures that need `_ssl` internals: this is the "API fidelity" gap).
* Risks: (1) API fidelity: CPython's `test_ssl` assumes the C module; (2) host version skew per platform; (3) the guest's blocking semantics: the pump calls `recv` in the guest, so timeouts must follow `settimeout()` as the adapter does; (4) the host holds a lock across a wait is not an issue because the pump never blocks in the host; (5) memory of `MemoryBIO` buffers (copy twice); (6) no server side without `load_cert_chain`; (7) a Python 3.10 host with 1.1.1: behaves as today.

### 6.5 Prototype and measurement

`/tmp/claude-0/-home-user/d2f0afe1-78de-56d0-b524-a430e24fc186/scratchpad/openssl_research/proto/shim_proto.py` (74 lines): a local TLS echo server on 127.0.0.1 (host thread, self-signed certificate with SAN `localhost`, `127.0.0.1`), a `Pyodide` subclass that overrides `_net_fetch` (so the existing generic host op is reused: no repo change) and keeps the `SSLObject`s, and guest code (`hostnet.fetch` as the op channel, the guest's own `socket`) that runs the pump. Result (fused, this machine):

```
 handshake ms 28 ['TLSv1.3', ['TLS_AES_256_GCM_SHA384', 'TLSv1.3', 256], [[['commonName', 'localhost']]]]
verified, name localhost: b'echo:hello'
wrong name refused: SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Host...
total s 2.16 host calls 22
```
That is two connections (one good, one with a wrong `server_hostname`) with 22 host calls in total (about 9 to 11 per connection: new, 3 handshake steps, feeds, drains, info, write, read), 28 ms for the first handshake including the TCP connect and the host's key exchange; the whole run is 2.2 s because of the interpreter start. Not run: dynamic packaging for the shim (the shim does not touch the loader; the same override works in both flavors, a guess), the network tier, `urllib3`.

### 6.6 Comparison

| | real wasm `_ssl` + static OpenSSL 3.5 (route c) | wasm `_ssl` + 1.1.1w (today) | host TLS shim |
|---|---|---|---|
| Security | current LTS in the guest; keys in guest memory; policy cannot be enforced against a guest that loads its own code | **EOL library** | host's OpenSSL (patched by the OS if the host updates); keys in the host; policy can be enforced at `ctx_new` |
| Size added to the wheel | +1.1 MB gzip full (0.97 MB gzip trimmed) over today's 0.8 MB | 0.8 MB gzip (already shipped via the lock) | 0 wasm; Python shim a few tens of KB |
| Portability | identical on all hosts (the wasm carries its own TLS) | same | differs per host: OpenSSL version, Windows/macOS store, FIPS builds |
| API fidelity | full `_ssl` (CPython's own C code); passes the same checks as today | full, minus 3.x features | partial: no sockets-level features (`SSL_set_fd`, PHA, keylog, sessions, sigalgs, server side initially) |
| Effort | about 1 day productise + the `get_sigalgs` trap | 0 | 1 to 2 weeks (+ risk of long tail of `test_ssl`) |
| Needs the host `/dev` | no | yes (`--dev`) | no |
| Works with the project's rules (one toolchain, no run-time Node, both packagings) | yes (wasi-sdk 34 clang) | yes | yes (no wasm) |

Recommendation (a guess from the above): ship route (c) as the default real TLS (smaller effort, full fidelity, security fixed by version), keep the host shim only as a documented fallback for environments that cannot carry the 3.6 MB (or trimmed) wasm; the existing `hostnet` fetch (HTTPS by the host's urllib) already covers "just fetch" users.

## 7. Side findings

* In this working tree (data built 2026-11-11 11:54, `testenv/site_tls` from 2026-11-10), `python -m pyodide_wasmtime --flavor fused --dev --site .../site_tls -c "import ssl; ..."` gives `OpenSSL (stub)` and `/lib/python315.zip/ssl.py`: the `--site` folder copied into `site-packages` comes **after** the stdlib zip on `sys.path` (`['', '/lib/python315.zip', '/lib/python3.15/lib-dynload', '/lib/python3.15/site-packages']`) while the zip now contains Pyodide's stub `ssl.py` and `_ssl.py`. `tests/test_checks.py::test_the_guests_own_tls` expects the real one, so this is either a stale `python_stdlib.zip` or a regression of the `build_ssl.sh` comment "a folder that comes before the stdlib zip"; I worked around it with `sys.path.insert(0, '/lib/python3.15/site-packages')` (not investigated, network tests were not run by me against the repository's test suite).
* The sandbox's egress proxy presents a certificate for **any** SNI name, so `wrap_socket(..., server_hostname="wrong.example")` to pypi.org "succeeds" here with both builds (the peer certificate's SAN is the requested name). That is not a bug of the guest: the local-server test above (hostname mismatch refused by both 1.1.1w and 3.5.9) is the valid check; `tests/checks/tls_check.py`'s last step ("hostname check works") is not asserted by `tests/test_checks.py` (`TLS` patterns) and cannot pass through such a proxy.

## 8. What I could not verify

* **openssl.org / openssl-library.org are not reachable** from the session (proxy 403 / ENOTFOUND): the LTS end dates (3.0 on 2026-09-07, 3.5 to 2030-04), the 3.6 and 4.0 support windows, and **which CVEs affect 1.1.1** are from memory or only partly from GitHub's `CHANGES.md` (which lists fixes in 3.x branches). The latest release numbers (3.0.22, 3.5.9, 3.6.5, 4.0.3 and dates) are from `VERSION.dat`/`CHANGES.md` on GitHub.
* GitHub's API is blocked and `pyodide/pyodide`, `pyodide/pyodide-recipes` are not attached to the session: issue/PR content came from the fetch tool's summary of GitHub pages (a small model), not raw text; quotes are as reported by it (PRs #6044, #598, #647, #2263, issues #6540, #6032). The full commit history of the 1.1.1w recipe beyond three commits shown was not read, so "why 1.1.1" is **not established** beyond what is quoted.
* Whether Pyodide will accept the proposal; whether the `pyodide-build` toolchain (Emscripten's `emcc`) links the same OpenSSL differently from wasi-sdk's clang; Pyodide's JavaScript `dlopen` of the produced `.so` was not tried (only our Python loader on both packagings).
* The `ssl.get_sigalgs()` trap (cause unknown), shared-library route (b) (not built), AWS-LC (not built), performance of crypto (not benchmarked), memory use, behaviour under `-O0`/`-Os`, patch 0002's necessity, the dynamic packaging for the host shim, the network test tier of the repository, and the complete `test_ssl` of CPython against the 3.5.9 build.
* Timings are single runs on a 4-core machine at load 10 to 14, shared with another agent: they show order of magnitude only.
