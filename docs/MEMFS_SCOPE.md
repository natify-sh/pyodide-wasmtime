# MEMFS_SCOPE: an in-memory root ported from Pyodide's MEMFS, and the mounts as a port of NODEFS

A study (2026-11-11, an independent reviewer agent, read-only; nothing was built). **Decision of the owner: parked** (BACKLOG.md D4): the root
stays on the host's disk because no win was seen for now. This file keeps the cost and the numbers for the day the question comes back.
Every timing was taken on 4 shared cores with a load average of 10.5-12 and varied up to 4x between runs: ratios are indicative; quiet-machine
numbers are still to be measured. The probes are in the scratchpad of that session (`memfs/`: `imports.py`, `storm.py`, `dir5000.py`, `big.py`,
`mem.mjs`, `hostcall.py`).

## Short answer
The port fits the adapter's rules (no data section, no own stack, state in malloc'd blocks). MEMFS itself is small; the cost is the generic file
system layer it needs (path lookup, its own fd table and streams, a mount table). **+1,700 to +2,600 lines of C with WASI mounts kept**: the adapter
(3,371 lines now) goes to about 5,100-6,000. A port of MEMFS alone does not make the guest look like Pyodide: the port must reproduce `FS` and
`SYSCALLS` of the glue too.

## 1. What MEMFS is in the glue (pyodide.asm.mjs, 315.0.0a2)
* Minified sizes: `MEMFS` 6.1 KB, `FS` 29.9 KB, `SYSCALLS` 1.8 KB, the `___syscall_*`/`_fd_*` functions 21.6 KB (about 12 KB for files), `PIPEFS` 4.6 KB, `TTY` 1.9 KB, `PATH`+`PATH_FS` 2.2 KB.
* Node types: directory, regular file, symlink, character device. A FIFO or block device is EPERM (63). No `link` (EMLINK 34; `os.link` does not exist in this build).
* File data: one `Uint8Array` per file plus `usedBytes`; capacity doubles below 1 MiB, then x1.125 (minimum 256), the old data is copied at each growth. The data lives in JavaScript ArrayBuffers OUTSIDE the 4 GiB wasm memory (a 100 MB file grew `arrayBuffers` by 104,857,600 B; a 1 GiB sparse `pwrite` worked). `mmap` copies the data unless it already lives in `HEAP8` (in practice never); `msync` writes the whole mapping back.
* Attributes: `ino` a global counter from 1, never reused; `dev` 1; `nlink` always 1; uid/gid always 0 (`chown` a no-op); size 4096 for a directory; blksize 4096, blocks = ceil(size/4096); times are `Date.now()` in ms (`utime` rounds ns to ms); `statfs` constants (blocks 1e6, bfree 5e5, files = nextInode, namelen 255).
* Directory order: `[".", "..", ...Object.keys(contents)]` = JavaScript key order: canonical array-index names (below 2^32-1) first in numeric order, then the others in insertion order; an unlinked and re-created name moves to the end (measured: `['1','2','10','4294967294','b','a','c','01','z9','-1','4294967295']`).
* `getdents64`: a snapshot of the names at the first call; fixed 280-byte records, `d_off = (idx+1)*280`; each name is looked up again and errno 28 skips the entry (why a FIFO in a NODEFS mount is invisible); names are cut at 256 bytes. Hypothesis (not traced): a name removed after the snapshot makes the lookup throw ENOENT and aborts the call: the "short counts" of N20.
* Limits: link loop 40 (ELOOP); no name or path length limit (only the 256-byte cut in getdents); an empty path is ENOENT; trailing slashes are dropped by `lookupPath` (the N8/N9 bug).
* Permissions: `nodePermissions` checks ANY of the user/group/other bits, ignores the owner, applies to everyone (reading a 0000 file is EACCES even as uid 0); the umask is fixed 0o022 (`__syscall_umask_js` only changes Node's process umask); `mayDelete` is EBUSY for the root or the cwd; `rename` checks EXDEV across mounts and EINVAL/ENOTEMPTY into a subdirectory.
* Created at start: `/tmp`, `/home/web_user`, `/dev` (null, tty, tty1, random, urandom, shm, shm/tmp, stdin/stdout/stderr), `/proc/self/fd` (a pseudo-mount); `pyodide.mjs` then makes `/lib`, `/lib/python3.15/site-packages`, `lib-dynload`, `/home/pyodide`, chdirs there and writes `/lib/python315.zip` with `FS.writeFile`.
* Streams: `nextfd` the lowest free from 0 up to `MAX_OPEN_FDS` 4096; `dupStream` shares `stream.shared` (position and flags); fds 0-2 are opens of `/dev/stdin|stdout|stderr`.
* Mounts: `FS.mount(type, opts, path)`; `lookupPath` crosses into `mounted.root`; `..` at a mount's root goes to the parent in the guest's tree.

## 2. The components of a C port (lines, risk)
| component | lines | notes |
|---|---|---|
| inode store (mode, ino, ns times, size, link target, parent, mount; one global hash keyed (parent ino, name) as `FS.nameTable` plus a per-directory insertion list for order) | 250-400 | readdir order including the numeric-key quirk; rename keeps the order |
| file data: chunked (64 KiB pages in a per-file page array, null = hole, small files one exact malloc up to 4 KiB) | 150-300 | contiguous storage as MEMFS does costs realloc copies (MEMFS's own 100 MB write: 1.8-2.5 s) and a 1 GiB sparse pwrite would take 1 GiB of heap; mmap is a copy already, dlopen copies today (`read_file`) |
| `lookupPath` port: cwd, `..`, ELOOP 40, follow/nofollow, parent mode, mount crossing, empty path, trailing slash | 200-300 | replaces `fixpath`/`phys`/`resolve`/`ncomp`/`lead_dots_only` (about 400 lines) for the root |
| syscalls on the VFS: openat (flags, EXCL/TRUNC/DIRECTORY/NOFOLLOW, mayOpen order), stat family, mkdir, unlink, rmdir, renameat, symlink, readlink, chmod/fchmod/fchmodat, chown, utimensat (i64 ns), truncate/ftruncate, fallocate, faccessat, getdents64, statfs, mknod | 600-900 | the bulk; each error has an order to copy |
| stream layer: read/write/pread/pwrite/readv/writev looping over every iovec, lseek (whence validated, overflow checked), O_APPEND, shared offset on dup | 250-400 | the routed WASI imports dispatch on the object kind |
| own fd table (decoupled numbers: D5/W5) | replaces the number scheme of vfd.h | FORCED by the VFS: a VFS fd is not a WASI fd. Lowest free from 0, MAXFD 4096; the placeholder trick (`sock_fd`, `fd_alloc`, `fd_renumber`, about 110 lines) goes, pipes stay |
| `/dev` nodes (null, zero, urandom via `random_get`, random, tty, tty1, stdin/out/err), `/dev/shm`, `/proc/self/fd` | 100-180 | replaces W2 |
| mount dispatch (a path under a mount goes to the WASI preopen with the rest of the path; today's code becomes the "wasi" backend) | 80-150 | `lookupPath` returns (backend, preopen fd, rest) |
| `dlopen` `read_file` and mmap from the VFS | 40-80 | |

Totals: new code 1,900-2,900; removed or shrunk 150-300; **net +1,700 to +2,600**; `adapter.wasm` (72 KB now) about +50-100 KB (an estimate).

Per section of `wasm/adapter/*.h` with a VFS root and WASI mounts: common.h (113) unchanged; state.h (80) preopens stay, the cookie table goes to the VFS stream; cwd.h (49) replaced by a node-based cwd; metadata.h (171) not needed for the root, stays only if mounts keep recorded modes; openfiles.h (741) `resolve`/`fixpath`/`phys` (~400) become the mount backend only, `put_stat`/`fcntl`/`lseek` get a VFS branch; writes.h (385) every call gets a VFS branch, `rel_target`/`relink` (~150) only for mounts; vfd.h (308) numbering rewritten (~110 out, ~150-250 in), pipes (~120) unchanged; mmap.h (151) about unchanged; owners.h (119) small change; loader.h (684) `read_file` gets dispatch; sockets.h (331) the routed `fd_*` (~60) dispatch on the new kind; time.h, signals.h, log.h, ffi.h unchanged. Fused and dynamic: one source, no difference found.

## 3. The host side
* `_setup_root` (about 25 lines) and the temporary folder disappear; `/lib/python3.15/lib-dynload`, `/tmp`, `/home/pyodide`, `/etc` are created through the API at start; `run()` writes `_pw_N.py`/`.rc` into the root today (N38): with a VFS the code goes through guest memory or `/tmp` and the status comes back from memory; `_probe`/`_save` read the root on the host (with a VFS the files are part of memory); `_preopen_dir` and `fs.statvfs` stay for mounts; `cli.py` reads `py.root / "_repl"` (needs an API read); `tests/test_files.py` uses `py.root` twice.
* The host API a MEMFS root needs, modelled on Pyodide's (`pyodide.FS`: `writeFile`, `readFile`, `mkdir`, `mkdirTree`, `readdir`, `stat`, `unlink`, `rename`, `symlink`, `mount`/`unmount`, `analyzePath`; `unpackArchive`; `mountNodeFS`; `loadPackage`): methods on `Pyodide` that call the adapter's existing syscall exports with guest-malloc'd buffers (about 150-250 Python lines, no new adapter exports): `write_file`/`read_file` (about 4 guest calls per file, 0.1-0.3 ms), `mkdir`, `listdir`, `stat`, `unlink`, `rename` (one or two calls), `put_tree`/`get_tree` (N files x the above; 5,000 files about 1 s per start, an estimate), `import_archive`/`export_archive`, `site=`/wheels (a 30 MB wheel: 30 MB written, then the unpacked size lives in memory), `mounts=` unchanged.
* Snapshots: the VFS is in linear memory, a snapshot captures it as is (a preload that writes files could be snapshotted; the "files changed" rule of `_save` could go); the snapshot grows by the VFS size; `site=` could stop disabling snapshots.
* Start-up: writing the 3 MB zip is 1-5 ms of copying; our start-and-exit took 1.3-1.8 s, Pyodide's `loadPyodide` 6.3-8.3 s (measured).
* Memory ceiling: files share the 4 GiB with the heap: a full heap is `malloc` failing: ENOSPC for writes, ENOMEM elsewhere (Pyodide keeps data outside the heap): a deliberate difference to document.
* Overlay (lower layer read lazily from a host folder, writes in memory with copy-up): full overlay +400-700 C lines (whiteouts and opaque directories, rename of a lower directory EXDEV or recursive copy-up, readdir merge, inode numbers change at copy-up, hard links break, an fd opened before copy-up sees stale data); it is a mount with a copy-up layer on top (as IDBFS wraps MEMFS's `node_ops`). A cheaper alternative, recommended: LAZY HOST-BACKED FILES (the glue's `createLazyFile` idea): MEMFS nodes whose bytes come from a host file at the first read and become ordinary data at the first write or truncate: about 100-150 lines, no whiteouts, no merge; covers the stdlib zip and `site=`.

## 4. Performance (measured, noisy)
| workload | Pyodide 315a2 on Node (MEMFS) | ours now (host root, WASI) |
|---|---|---|
| imports of 19 stdlib modules cold / re-import | 1.81-2.10 s / 1.74-2.20 s | 3.04-4.23 s / 3.19-4.30 s |
| the same with `sys.path` reduced to the zip | 1.71 / 1.58 s | 3.94-5.55 / 3.56-4.92 s |
| reading every member of the stdlib zip (683, 10.97 MB) | 0.339 s | 0.151-0.156 s |
| CPU only, 2M-iteration loop | 1.11-1.18 s | 1.05 s |
| 40,000 calls: 10,000 x stat+open+read+close | 0.31-0.46 s (7.7-11.4 us/call) | 0.52-0.72 s, 2.51 s in one later run (13-63 us/call) |
| 10,000 file creates of 100 B / unlinks | 0.69-0.88 s / 0.18-0.27 s | 3.76-6.19 s / 0.54-2.54 s |
| directory of 5000 entries: create / listdir / scandir+is_file / scandir+stat / rmtree | 0.40-0.55 / 0.013-0.040 / 0.014-0.062 / 0.037-0.125 / 0.05-0.19 s | 0.53-2.84 / **5.2-11.4** / 5.0-14.5 / 5.4-15.8 / 5.7-9.3 s |
| 100 MB write in 1 MiB chunks / read in chunks / `read()` whole | **1.84-2.53** / 0.018-0.037 / 0.11-0.29 s | 0.044-0.137 / 0.025-0.057 / 0.25-0.47 s |
| memory per file | 330-466 B JS heap + data in arrayBuffers (RSS +1.0-1.5 KB per small file) | not measured |
| per call `os.stat` / `os.fstat` / `os.pread` | 5.3 / 1.4 / 2.4 us | 29-83 / 24-55 / 12-23 us |

* Imports are not file-system-bound (reading the zip is faster in ours, the CPU speed is equal, a zip-only `sys.path` keeps the 2-3x gap; the cause is not attributed): do not use import time as a MEMFS gain, only require that it does not get worse.
* **`listdir` of a large directory is our biggest gap: 5-15 s against 0.01-0.04 s (about 400x).** Hypothesis, not verified: each `getdents64` call asks wasmtime's `fd_readdir` from the cookie with a buffer of `count + 512` bytes and wasmtime enumerates (and stats) the whole host directory on every call: quadratic. A fix inside today's design (read the whole listing once per descriptor and serve from a snapshot, as Pyodide does) is about 40 lines and would probably also fix N20 (the duplicates). Worth doing whatever D4 decides, because mounts keep WASI.
* MEMFS's own large-file write is slow because of its x1.125 growth copies; chunked storage avoids that.

## 5. What disappears with a MEMFS root ("choice" = the port decides whether to copy a Pyodide bug, D3)
| row | now | with a MEMFS root | remains for WASI mounts? |
|---|---|---|---|
| N1 whence trap | guest dead | gone | yes until validated (3-line fix: do anyway) |
| N2 `read(0,0)` hang / L1 | hang | stays (stdio) | fix anyway |
| N3 `close(3)` preopen / L2 | root lost | gone | gone too |
| N4 lseek overflow | SystemError | gone | yes until fixed |
| N5 `close(1)` | 0-2 never reused | changes (own table can reuse them) | n/a |
| N6 empty path | treated as "." | gone | gone |
| N7 `rmdir('d/')` | EINVAL | gone | yes (WASI refuses the slash) |
| N8, N9 trailing slash | ours right | choice | ours right |
| N10, N11, N32, N33, N36 | wrong errno | gone | partly yes |
| N13, N21, N27-N31 | Pyodide bugs (O_EXCL dangling, nlink, chown, umask, ms times, EMLINK, nofollow) | choice; recommend ns times and a real umask | |
| N14 truncate on 0444 (host root) | host-dependent | gone | yes |
| N15/L3 readv/writev, N16 pread 64 KiB | short counts | gone | yes until the iovec loop (W4: do anyway) |
| N17-N19, dup offset, F_DUPFD minimum, dup3 flags | differ | gone | gone (same fd table) |
| N20 scandir duplicates | dups | gone (snapshot) | yes until the getdents snapshot |
| N22, `st_blocks`/`st_dev`, `/lib` modes, readdir order | host values | gone (MEMFS values; order insertion plus the numeric quirk as a choice) | yes |
| N23/L4/L5/L7 stdio errnos | differ | stays unless 0-2 become device nodes | |
| N24 `/dev`, `/proc`, `/home`, `os.devnull` (W2, `test_logging`, `test_shutil`) | ENOENT | gone | |
| N25 rmdir of cwd | ok | EBUSY | |
| N34 enum validation | missing | gone in VFS code | yes |
| N38 `_pw_*` visible in `/` | visible | gone | |
| 256-byte names, surrogate names (EILSEQ), 4096-byte link targets | host limits | gone (byte names) | yes |
| `mknodat` FIFO | ENOSYS | Pyodide's EPERM, or real FIFOs via pipes (choice) | yes |
| utimensat range | 1970..2554 | gone (i64 ns) | yes |

BACKLOG items: W1 N1/N4 gone for the root (N2/N5 stay); W2 subsumed; W3 mostly gone for the root; W4 gone for the root (mounts still need the loop); W5 becomes a prerequisite of the port; W6 gone for the root; S1: `test_logging`, `test_shutil`, `test_os.test_posix` (readv) should go, `test_os`, `test_posixpath`, `test_pathlib` probably (not run), `test_filecmp` unknown. Windows/macOS notes that go away for the root: D8 (symlinks; stays for mounts), `chmod /tmp`, `--dev` missing on Windows, case-insensitive names, reserved names, permission bits, long-path limits, directory order and nlink; all stay inside mounts.

## 6. Alternatives
* littlefs or FatFs in the adapter: block-device file systems; neither has symlinks or POSIX modes, FAT has no inodes; each needs the same FS layer on top plus block emulation: more than MEMFS and less like Pyodide.
* A WASI implemented in Python (fusedwasi/wasmhost style): every file call becomes a Python host call (59-105 us), 10-50x MEMFS-in-C; the Emscripten-to-WASI mapping in the adapter stays.
* Keep the host root and fix row by row: the W1/W3/W4/W6 fixes are about 200-400 lines; the host-dependent rows remain (order, nlink, permissions as root, Windows, name limits), and so do D5's fd numbering and the `listdir` slowness unless the getdents snapshot is added.
* Inside the port: chunked data (recommended) over contiguous; one global (parent, name) hash plus a per-directory insertion list (recommended); permission checks as Pyodide's (recommended; what the oracle shows and the adapter does today).

## 7. Risks, undetermined, order of work
* Risks: the fd table rewrite (W5) touches sockets, pipes, mmap; `vfd.h` was not reviewed when this was written; file data inside 4 GiB gives a lower ceiling than Pyodide; every errno order in `FS.*` has to be copied; the D3 choices multiply the test matrix; the adapter grows by 50-75%.
* Not determined: quiet-machine numbers, why imports are 2-3x slower in ours, whether the getdents hypothesis is right, `adapter.wasm` growth, our memory per file, Windows/macOS behaviour, the cause of N20's short counts on Pyodide.
* Do anyway, now: W1 (N1, N2, N4 and a minimal N3 guard), R1/R2, the W4 iovec loop (mounts keep it), the getdents snapshot. Wait for D4/D5: W2, W3, W5, W6 (the owner parked D4: they go on the host root).
* A 2-day prototype (if ever): the FS core (inode hash, chunked data, `lookupPath`, own fd table for VFS fds only) and MEMFS for `/` only; open, read, write, pread/pwrite, readv/writev, lseek, close, stat family, mkdir, unlink, rmdir, rename, getdents64, symlink, readlink; the stdlib through `write_file`; no mounts, no overlay; about 1,200 lines. Acceptance on a quiet machine, both packagings: storm <= 10 us/call; 5000-entry directory listdir <= 0.05 s, create <= 0.6 s, rmtree <= 0.2 s; 10,000 creates <= 0.9 s; 100 MB write <= 0.3 s and read <= 0.1 s; overhead <= 256 B per file; imports no slower than today; the `files_*` diff probes from about 1,100 differing cases to under 150, the rest being D3 choices.

## 8. The mounts as a port of Emscripten's NODEFS
* NODEFS in the glue (about 5.4 KB minified): flags mapped to Node's constants (strips O_CLOEXEC, O_NONBLOCK, O_LARGEFILE, O_DIRECTORY, O_DIRECT; EINVAL for anything left); errors through `convertNodeCode` ("UNKNOWN" is EINVAL); 16 operations: node ops `getattr` (lstat), `setattr` (chmod, utimes/lutimes, truncate), `lookup`, `mknod` (mkdir or `writeFileSync('')`), `rename` (it unlinks the destination first: not atomic), `unlink`, `rmdir`, `readdir`, `symlink`, `readlink`, `statfs`; stream ops `getattr` (fstat), `setattr`, `open`, `close` (refcounted for dup), `dup`, `read`/`write` (positional), `llseek` (fstat for SEEK_END), `mmap`/`msync` (copy, write back). No `link`. Inode numbers are the FS's own counter; `dev` the host's; times in ms; a FIFO in the folder is invisible. Windows quirks NODEFS special-cases itself: the read bits are copied to execute (`mode |= (mode&292)>>2`), `chmod` keeps only `mode&384`, `blksize`/`blocks` defaults: even Pyodide leaks these OS differences through mounts.
* Confinement: NODEFS does not confine on the host side, but the generic `lookupPath` walks every component in the guest's tree and resolves every symlink in the guest's namespace (measured: a link to `/etc/passwd` inside the mount resolves to the guest's own `/etc/passwd`; `up -> ../../..` lands on the guest's root; `/mnt/..` is the guest's root). The remaining hole is a race between the guest's lstat and the host's open.
* Size: Python side about 200-300 lines (16 host operations, errno mapping, a handle table, the Windows tweaks); adapter side about 300-450 lines for both packagings. If NODEFS replaced WASI for mounts, about 700-900 lines of WASI-specific code could go (`fixpath`/`phys`/`ncomp`/`lead_dots_only` ~330, `rel_target`/`relink` ~150, metadata.h 171, orphan tracking ~50): the adapter at about 4,600-5,600 lines with a MEMFS root.
* Security beyond NODEFS: Linux/macOS: walk on the host with `os.open(name, O_NOFOLLOW | O_DIRECTORY, dir_fd=parent)` per component and a final `O_NOFOLLOW` open (about 50-100 lines, one syscall per component, `os.stat` 1.5 us); closes the race except hard links made by the host's own users. Windows: Python has no `dir_fd`/`openat`: reject reserved names (CON, NUL, COM1...), `:` (alternate streams), names ending in a dot or a space, then `realpath` + `commonpath` against the root: racy; junctions or reparse points created concurrently escape; case-insensitivity and 8.3 names alias paths. A guest symlink with an absolute target is stored on the host as is (wasmtime refuses that today, which is why `rel_target` exists): not an escape for the guest, but host tools later follow it out. The `fs.statvfs` escape the file audit found is of the same class: every operation that takes a host path must go through the confined walk.
* Speed: a guest call that adds one Python host operation (`time.localtime`) costs 59-105 us; one that stays in the adapter (`time.gmtime`) 1.4-1.8 us; native WASI operations measured 12-83 us: a NODEFS port at one host call per syscall is about 1-3x today's per-operation cost; done literally as NODEFS (a `lookup` per component) a 4-component path costs 4-5 calls, 4-10x slower: one host operation per syscall taking (mount id, path relative to the mount) with the confined walk in the host.
* Rows that go for mounts: N1, N4, N7, N10, N11, N15, N16, N32-N34, path/name limits apart from the OS's own, absolute and `..` symlinks (D8 for links the guest makes), `statfs`, preopen numbering, the utimensat range. Rows that stay: everything the OS decides (order, nlink, blocks, permissions by the host user, Windows modes/case/reserved names, FIFOs). It also works with a host root (the root becomes a NODEFS mount of the temporary folder): about 60% of the MEMFS port's cost, every host-dependence stays.
* Oracle: `pyodide.mountNodeFS('/mnt', hostdir)` against `--mount /mnt=hostdir` on ours (`tools/diff_pyodide.py` already mounts `/dist` this way); a fresh host folder per run under the same absolute name; normalise inode numbers and decide on time precision.
* Recommendation: keep WASI for mounts now; build the NODEFS port later, only after the FS core exists (the MEMFS root or W5), under the condition that the mount rows in the oracle stay significant after W1/W4, or the owner wants mounts to behave like a native Python on that OS; do not build it if Windows confinement must be strict or per-operation speed on mounts matters more than semantics.
* Overall: (1) MEMFS root + host API + lazy host-backed files: the best match with Pyodide, +1,700-2,600 lines; (2) MEMFS + a full overlay: +400-700 more lines and new risks, only if the guest must write over a host project in place; (3) host root as now, fixed row by row: the cheapest (200-400 lines), every host-dependence and D5 remain. Decide D4 together with D5: the own fd table is needed by any of the FS-layer options.
