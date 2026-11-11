# Differential audit, area "files": our guest against the real Pyodide 315.0.0a2 (Node, MEMFS)

Nothing was fixed in this step (no change to `wasm/`, `src/`, `tests/`). Added: `tools/diff_pyodide.py` (the harness) and
`tools/diff_probes/` (the probes). Machine: Linux 6.18 (Firecracker VM), the host runs as **root**, wasmtime-py from the
dev environment, ours built with `tools/build_data.sh` at `410bede`. Baseline: `pyodide@315.0.0a2` on Node 22 via
`pyo_run.sh` (cwd `/home/pyodide`; ours has cwd `/`; all probes use absolute paths under `/tmp/dp_<pid>`).

## 1. The harness

```
uv run python tools/diff_pyodide.py [-q] tools/diff_probes/files_open.py [more probes]
```

It runs a probe on the real Pyodide and on ours (fused, dynamic; stdin is `/dev/null`), normalises the probe's own
directory (`/tmp/dp_<digits>`), `0x...` addresses and uv's warning lines, and prints a unified diff per flavor
(`-` Pyodide, `+` ours); exit status 0 when there is no difference. A probe prints one line per case,
`case-id | result` (`ERR ERRNO_NAME` for an `OSError`, `EXC Name` for another exception). A probe without its own
`def case(` (or a `# standalone` comment) gets `tools/diff_probes/_prelude_files.py` put in front (`case`, `w`, `tree()` = the
common tree of files/dirs/links/modes, `NAMES` = about 40 argument classes, `fresh()`, `op()`).
`files_crash_*.py` are standalone one-shot programs for a trap, hang or fatal error: one case ends the process, so they
cannot share a run (run them by hand with `pyo_run.sh` and `python -m pyodide_wasmtime --flavor ...`).

## 2. Probe files (cases per run; differing lines of the unified diff, divided by two, approximate)

Fused and dynamic **agree on every probe**: the diffs are identical line for line (checked by script on all 15 outputs; the
only two that first differed were probe bugs printing a time and an uninitialised buffer, both fixed in the probes).

| probe | what | cases | differing (fused = dynamic) |
|---|---|---|---|
| `files_open.py` | open/openat: 38 path classes x 22 flag combinations, create modes x umask, dir_fd, read/write by access mode | 865 | ~179 |
| `files_stat.py` | stat/lstat/fstat/readlink/exists/realpath over 40 path classes; /, /tmp, /dev, /proc, /lib...; fd 0-2; bad fds; nlink/size/blocks | 515 | ~119 |
| `files_ops_a.py` | unlink, rmdir, mkdir, makedirs, symlink, link over the path classes | 340 | ~36 |
| `files_ops_b.py` | rename/replace (src, dst, to-self, to-sub, dir/file/link combinations) | 292 | ~53 |
| `files_ops_c.py` | removedirs, rmtree, copy/copy2/copyfile/copytree/move, dir_fd forms, `.`/`..`/root, cwd removal | 300 | ~55 |
| `files_meta.py` | chmod/fchmod/chown/lchown/utime/access/truncate/statvfs x classes; 19 modes; 22 times (s and ns); umask | 1049 | ~166 |
| `files_io.py` | lseek/pread/pwrite/read/write/readv/writev/ftruncate/fsync, offsets 0..2**63, sizes 0..1 MiB, append, holes, mmap, fds | 472 | ~48 |
| `files_fdtable.py` | descriptor numbering, 2000 open fds, dup/mmap on fds above 1024 | 55 | ~14 |
| `files_mmap.py` | mmap of files (read, write, copy, offset, bad) | 15 | 0 |
| `files_dirs.py` | listdir/scandir/walk/glob/pathlib/chdir over classes; 5000-entry dir; modify while listing; cwd; statvfs; tempfile, zipfile, shutil, tarfile scenarios; /dev, /proc, /etc | 881 | ~75 |
| `files_fcntl.py` | fcntl F_GETFD/SETFD/GETFL/SETFL/DUPFD, dup/dup2/dup3, flock/lockf, ioctl, posix_fadvise, odd open flags, std descriptors | 216 | ~68 |
| `files_libc.py` | the same calls with exact kernel semantics through ctypes (`posix_fallocate`, `mknod`, `mkfifo`, `utimensat`/`futimens` with UTIME_NOW/OMIT, `fchmodat`/`faccessat`/`fchownat`/`unlinkat` flags, `openat`/`fstatat` with dirfd classes, `statx`, `preadv`/`pwritev`, `dup3`, `statfs`) | 571 | ~138 |
| `files_emptypath.py` | `""` as the path of 38 calls, with cwd `/` and `B/d`, with and without dir_fd | 80 | ~39 |
| `files_isolated.py` | the NEW items below, re-run one by one | 53 | ~43 |
| `files_stdio_closed.py` | close(1), then write/fstat/print/open | 10 | ~5 |
| `files_ctypes.py` | which libc names are reachable through `CDLL(None)` | 1 | 0 |
| `files_crash_*.py` (7) | one-shot: whence, fd 3, read(0,0), lseek overflow, utimensat nsec, utime 2**53, big pwrite | 7 | see section 3 (N1-N4, P1-P3) |

About 5,700 cases in all. Pyodide itself dies (fatal error, process ends) on some inputs, which would hide every later
line: these were moved to the crash probes (P1-P3 below). `os.mkfifo`, `os.mknod`, `os.posix_fallocate`, `os.pwritev`
do not exist in either Python (AttributeError on both), so they are reached through ctypes (`files_libc.py`).

## 3. NEW differences (not in `docs/import_audit.json`)

Severity: **crash** (guest killed, hang, poisoned state) > wrong errno / wrong behaviour > cosmetic. "POSIX" says which side is right on Linux.
Every item was re-run alone (`files_isolated.py` or a `files_crash_*.py`) and is deterministic, on both flavors.

### 3.1 Crash, hang, poisoned state (fix first)

| id | case | Pyodide | ours | glue's reason | POSIX-right | fix location |
|---|---|---|---|---|---|---|
| N1 | `os.lseek(fd, 0, whence)` with whence 3 (SEEK_DATA), 4 (SEEK_HOLE), 7, -1 (`files_crash_whence.py`) | `EINVAL` | **guest dead**: `a host function failed, the guest is dead: WasmtimeError ... fd_seek: Invalid enum value Whence` (the raw value goes to WASI `fd_seek`, whose enum conversion traps) | `___syscall_llseek`/`_fd_seek` in FS.llseek: `whence` other than 0-2 is `EINVAL` (28) | Pyodide for 7/-1 (EINVAL); Linux supports 3/4 (SEEK_DATA/HOLE; EINVAL or ENXIO is acceptable here) | adapter `llseek`/`lseek` section: map whence, else EINVAL, before the WASI call |
| N2 | `os.read(0, 0)` (stdin from `/dev/null` (EOF); with a pipe that has data no answer either within 20 s) (`files_crash_read0_stdin.py`) | `b''` at once | **hangs forever** (killed by timeout) | n/a (MEMFS stdin read with length 0 returns 0) | Pyodide: a 0-length read returns 0 without waiting | adapter/host `fd_read` for fd 0: length 0 returns 0 before touching stdin (`os.read(0, 1)` is fine) |
| N3 | `os.close(3)` (`files_crash_fd3.py`) | `EBADF` (3 is a free number) | closes **the guest's root preopen**: every later `open`, `listdir`, `exists` is `EBADF`, the interpreter's own imports fail, the run ends with a traceback. Also `fstat(3)` is the root directory (mode 16895), the first `open()` returns 4 (Pyodide 3), `fcntl/dup/read` on 3 work | none (MEMFS has no preopens) | Linux: 3 is the first free number; a program may use or close it | the preopen descriptors must not be in the guest's fd space: host/adapter fd map (descriptor layer), or refuse `close`/`dup`/`read` on a preopen with `EBADF` as the minimum |
| N4 | `os.lseek(fd, 2**63-1, 0)` then any `lseek(fd, n>0, 1)`, `lseek(fd, 2**62, 1)` three times, `lseek(fd, 2**63-1, 2)` (`files_crash_lseek_overflow.py`) | `EFBIG` | `OSError: [Errno 0] Error`, and then **every later call of that kind raises `SystemError: ... returned a result with an exception set`** (the interpreter keeps an exception pending; `print` still works) | `FS.llseek`: `position < 0` -> `EINVAL`; 2**63-1 offset: `bigintToI53Checked` -> `EFBIG` | Linux: `EINVAL` for a negative result, `EOVERFLOW` for SEEK_CUR/END overflow | adapter `llseek`: check the sum for overflow and a negative result, return a positive errno; a WASI call that fails with errno 0 must not return -0 |
| N5 | trailing: after `os.close(1)`, `print()` | `EBADF` | prints nothing and succeeds; the next `open()` gets 4 not 1 (descriptors 0/1/2 are never reused); interpreter shutdown prints `OSError: [Errno 8] Bad file descriptor` for the flush, exit 255 | `FS.close` frees the slot | Linux | descriptor layer (std streams are being redone in another step: report only) |

### 3.2 Wrong errno or wrong behaviour

| id | case | Pyodide | ours | glue's reason | POSIX-right | severity | fix location |
|---|---|---|---|---|---|---|---|
| N6 | the empty path `""` in **every path call** (`open`, `listdir`, `scandir`, `readlink`, `unlink`, `rmdir`, `mkdir`, `rename`, `symlink`, `link`, `truncate`, `os.walk`, `open(..., dir_fd=)`...) (`files_emptypath.py`, 39 lines) | `ENOENT` | treated as `"."`: `open('')` returns a descriptor of the cwd, `listdir('')` lists the cwd, `walk('')` walks it, `mkdir('')` `EEXIST`, `unlink('')` `EISDIR`, `rmdir('')` `EINVAL`, `rename('', x)` `EBUSY` (`stat('')` and `access('')` do give `ENOENT`) | `FS.lookupPath`: `if(!path) throw ENOENT` | Pyodide (Linux: ENOENT) | medium: `os.listdir(os.path.dirname(f))` for a bare name silently lists the cwd | adapter path resolution: an empty path is `ENOENT` (not only in stat/access), before the call reaches the WASI `.` rewrite |
| N7 | trailing slash on a directory: `os.rmdir('d/')`, `shutil.rmtree('d/')`, `os.removedirs('d/')`, `rmdir('lnd/')` (symlink to dir) | succeeds (`rmdir lnd/` ENOTDIR) | `EINVAL` | `FS.rmdir` strips the slash | Linux: `rmdir("d/")` works; `rmdir("lnd/")` is `ENOTDIR` | medium: `shutil.rmtree('dir/')` is a common call | adapter `unlinkat`/`rmdir`: strip the trailing slash (WASI `path_remove_directory` refuses it with EINVAL on wasmtime) |
| N8 | trailing slash on a **file** or link: `stat('f/')`, `open('f/')`, `exists('f/')`, `copy('f/')`, `chmod/utime/truncate/statvfs('f/')`, `unlink('f/')`, `rename`/`move`, `samefile`, `readlink('f/')` | works as if no slash (**Pyodide bug**) | `ENOTDIR` (`readlink` `ENOTDIR` where Pyodide `EINVAL`; `exists` False) | `FS.lookupPath` drops empty path parts | **ours** (Linux: ENOTDIR) | cosmetic: the Pyodide side is the bug | none (keep) |
| N9 | `lstat('lnd/')`, `chmod(.., follow_symlinks=False)` on `lnd/`, `readlink('lnd/')`, `open('lnd/', O_NOFOLLOW)` (symlink to dir with a slash) | `lstat` gives the link, `readlink` works, `O_NOFOLLOW` `ELOOP` | follows the link (dir): `readlink` `EINVAL`, `O_NOFOLLOW` opens the dir | MEMFS ignores the slash | **ours** (a trailing slash forces the follow) | cosmetic | none |
| N10 | `os.read/pread/ftruncate/fsync` on a **directory** fd | `read`/`pread` `EISDIR`, `ftruncate` `EINVAL`, `fsync` ok | all `EBADF` (`open(dir)` works, `fstat` works) | `FS.read` -> `EISDIR`; `doTruncate` | Pyodide (Linux: EISDIR, EINVAL, fsync ok on a directory) | wrong errno (Python's `open(dir)` is `IsADirectoryError` either way; only raw fd users see it) | adapter: map WASI `EBADF` from a directory descriptor on `fd_read`/`fd_pread` to `EISDIR`, `fd_filestat_set_size` to `EINVAL`; `fsync` of a dir: success |
| N11 | `os.open(dir, O_WRONLY/O_RDWR/O_TRUNC)` on a directory, `open('dro', O_WRONLY)` | `EISDIR` | `EACCES` (the adapter checks the mode bits before the type); with `O_CREAT|O_EXCL` on `d/` ours `EISDIR`, Pyodide `EEXIST` | `mayOpen`: directory + write -> `EISDIR` | Linux: `EISDIR`; `O_CREAT|O_EXCL` on an existing dir `EEXIST` | wrong errno | adapter `openat` check order: type before permission; EXCL: `EEXIST` first |
| N12 | `O_CREAT\|O_DIRECTORY` (any target) | `ENOTDIR` (file), `EISDIR` (dir) | `EINVAL` | `FS.open` order | Linux: `EINVAL` for O_CREAT\|O_DIRECTORY on a new name, `ENOTDIR`/`EISDIR` as Pyodide on existing | **ours** matches Linux 6.x for a new name; Pyodide differs on others | none (note) |
| N13 | `open('bl', O_CREAT\|O_EXCL)` on a dangling symlink; `loop` link | Pyodide creates the target (**bug**), `ELOOP` | `EEXIST` | `FS.open` follows | **ours** | cosmetic | none |
| N14 | `truncate(path)` on a file with mode `0444`/`0000` | `EACCES` | succeeds (`open(ro, O_WRONLY)` is `EACCES` in ours: the permission check is on `open` only) | `doTruncate` checks `nodePermissions(w)` | Linux: EACCES for a non-root user; the host runs as root here, so this is also (b) | low, inconsistent with `open` | adapter `truncate`: the same mode check `openat` does; for `ftruncate` the descriptor's access mode decides |
| N15 | `readv`/`writev`/`preadv`/`pwritev` with several buffers (`os.readv(fd, [b1, b2])`, `writev`, libc `preadv`/`pwritev`, 1000 buffers) | all buffers are filled/written, returns the total | only the **first** buffer is used, returns its length (1 for 1000 one-byte buffers; `readv` leaves the 2nd buffer zeroed) | `doReadv`/`doWritev` loop | POSIX allows a short count; but no loop in CPython retries `writev`, so data written by `os.writev` is silently short | medium: partial writes of `os.writev`, `socket`-less code that assumes completion | adapter `readv`/`writev`: loop over the iovecs (or one WASI call with all iovecs) |
| N16 | `os.pread(fd, 5_000_000, 0)` on a 10 MB file | 5000000 | 65536 (capped); `os.read` of the same is not capped | `FS.read` | a short read is allowed, `FileIO.readall` loops, direct `pread` users do not | low-medium | adapter `pread` cap: loop until the count or EOF |
| N17 | `dup`/`mmap` on a descriptor number >= 1024 (open 1030 files, `os.dup(fd1029)`) | ok (`MAX_OPEN_FDS` 4096) | `EBADF` for dup and mmap (read/fstat/lseek/fcntl on the same fd work) | `FS.MAX_OPEN_FDS:4096` | Linux: up to RLIMIT_NOFILE | low | adapter dup/mmap descriptor table size (1024) |
| N18 | descriptor numbering: first `open()` | 3 | 4; after 2000 opens and closing them all, the next `open()` returns **2003**, not the lowest free number (wasmtime's table is LIFO); `os.close(a)` then `open` gives `a` only when `a` was the last freed | `FS.nextfd` lowest free from 0 | Linux: lowest free | low-medium: code that relies on numbering (`dup2` targets, `select`), also hits N3 | descriptor layer: own the numbering (map guest number -> host fd, lowest free) |
| N19 | `dup2(fd, 100)`, `(fd, 500)`, `(fd, 1000)`, `(fd, 2000)` on an unused target | ok | `EBADF` (known for 50: the target must be open; see section 4) | `dup3` | Linux ok | (known gap, wider than documented: any unused number) | descriptor layer |
| N20 | scandir/listdir while the directory is **changed** (`files_dirs.py`) | changes during the loop are seen: unlinking entries shortens the result (unlink one: 19, unlink all unseen: 5, rename one: 12 of 20); 5 files created: 20 | unlinked or renamed entries are still returned (20 of 20); with 5 files **created** during the loop `os.scandir` returned 25 names of which `new02`, `new04` **twice** (22 distinct) | `___syscall_getdents64` keeps `stream.getdents` (a name snapshot) and indexes it by `llseek` offset; why the counts are short in Pyodide was not traced | POSIX: an entry that is not added or removed must be returned exactly once; a created one at most once. **duplicates are a bug** | medium (duplicates) | host `getdents` cookie handling in `_host.py` (readdir by name offset vs cookie): iterate by a stable key |
| N21 | `fstat` of an unlinked-but-open file: `st_nlink` | 1 (**Pyodide bug**) | 0 | MEMFS has no nlink | **ours** | cosmetic | none |
| N22 | `st_nlink` of directories, `stat('/')` | always 1 | real (2 + subdirs; `/` 5, `/tmp` 3), `blocks` 8 vs 1, regular `blocks` of a 3 MB file 5866 vs 734 | MEMFS `getattr` nlink 1, `blocks=ceil(size/512)` | ours (host values); Pyodide's `blocks` is wrong | cosmetic (host-dependent, b) | none |
| N23 | stdio `fstat` `st_nlink`; `ftruncate(1,0)`, `fsync(0/1/2)`, `utime(1)` | nlink 1; `ftruncate` `EINVAL`; `fsync` ok; `utime` ok | nlink 0; `EBADF`; `EBADF`; `EBADF` | MEMFS device streams | Linux on a tty/pipe: `ftruncate` `EINVAL`, `fsync` `EINVAL`/ok, `utime` ok | wrong errno | adapter: stdio descriptors answer as character devices (`EINVAL`), not `EBADF` |
| N24 | `/dev`, `/proc`, `/home`, `/dev/null`, `/dev/zero`, `/dev/urandom`, `/dev/stdout`, `/dev/tty`, `/proc/self/fd`, `os.devnull` | exist (MEMFS devices: `/dev/null` 8630 chr 0666, `/dev/urandom`, `/dev/tty`, `/dev/shm`, `/dev/stdin`...; `/proc/self/fd` lists 0-3; `/home/pyodide`) | **`ENOENT`** for all of them: `open(os.devnull)`, `open('/dev/null','w')`, `open('/dev/urandom','rb')`, `stat('/dev')` fail; `/etc` exists (ssl, services) where Pyodide has none; `/lib` mode 0o755 vs 0o777 | `FS.createDefaultDirectories` / `createDefaultDevices` | Linux has all of them | **high for portability**: `subprocess`-free code such as `open(os.devnull, 'w')`, `random` seeding by `/dev/urandom`, `tempfile` | host: create `/dev/null`, `/dev/zero`, `/dev/urandom`, `/dev/random`, `/dev/tty`... in the guest root (device streams in the host function layer) |
| N25 | `os.chdir` / `rmdir` of the cwd: `rmdir(cwd)` then `getcwd()` | `EBUSY` on `rmdir` of cwd in one run, `ENOENT` from `getcwd` in another (state-dependent) | `rmdir` succeeds, `getcwd()` returns the removed path | `mayDelete`: `getPath(node)===cwd` -> `EBUSY` | Linux: rmdir ok, `getcwd` `ENOENT`; relative opens in it `ENOENT` (ours right) | low | adapter `getcwd`: `ENOENT` when the cwd no longer exists |
| N26 | `rename('.', x)`, `rename('/', x)`, `rename(x, '/')`, `rmdir('/')`, `unlink('.')`/`('..')`, `rmdir('emptyd/..')`, `rmdir('f/.')` | `ENOENT`/`EINVAL`/`ENOTEMPTY`/`EBUSY`, `unlink('.')` `ENOENT` | `EBUSY`/`EBUSY`/`EBUSY`/`EINVAL`, `unlink('.')` `EISDIR`, `rmdir('emptyd/..')` `ENOTEMPTY`, `rmdir('f/.')` `EINVAL` | various | mixed; Linux: `rename('.', x)` `EBUSY` or `EINVAL`, `unlink('.')` `EISDIR`, `rmdir('.')` `EINVAL`, `rmdir('x/..')` `ENOTEMPTY` | ours is close to Linux | cosmetic | none |
| N27 | `chown(path, 1000, 1000)`, `fchown(fd, 123, 456)` | no-op, uid stays 0 (**Pyodide bug**) | the ids are stored | `doChown` ignores uid/gid | ours (as root) | (b) host-dependent: a non-root host answers EPERM | none |
| N28 | `umask`: create with mode 0666, umask 077; `mkdir(m, 0o777)` umask 027; `open(O_CREAT, 0o7777)` | Pyodide ignores `os.umask`: 0644/0755 always, strips setuid/sticky | ours applies it: 0600, 0750, keeps 07755 | MEMFS `FS.umask` fixed 0o022 | ours | cosmetic (ours right) | none |
| N29 | `utimensat` precision and range: `utime(f, ns=(1,2))`, `(100, 5)` ns, `nsec 999999999` | rounded to milliseconds (`999000000`, `(0,0)` for 1,2 ns) (**Pyodide bug**) | exact ns | `FS.utime` takes ms | ours | cosmetic | none |
| N30 | `linkat(..., AT_SYMLINK_FOLLOW)` / nofollow of a symlink via libc | `EMLINK` (**Pyodide bug**) | creates the link (a hard link to the file / to the link) | MEMFS | ours | cosmetic | none |
| N31 | `faccessat('bl', flags=AT_SYMLINK_NOFOLLOW/0xffff)` on a dangling link; `openat(AT_FDCWD, "")` | `ENOENT` | 0 (nofollow sees the link); `openat("")` ok (= N6) | | Linux: nofollow ok (0) (ours right) | cosmetic | none |
| N32 | `openat(dirfd=file fd, ...)`, `mkdirat`, `utimensat`, `fstatat` with a **file** descriptor as dirfd | `ENOTDIR` | `EBADF` (also `openat(1, ".")`) | `calculateAt` | Linux: `ENOTDIR` | wrong errno | adapter: a non-directory dirfd -> `ENOTDIR` |
| N33 | `fstatat(AT_EMPTY_PATH)` with a bad fd, `fstatat(badfd, "")` | `EBADF` | `ENOENT` | | Linux: `EBADF` | wrong errno | adapter |
| N34 | `os.posix_fadvise(fd, 0, 0, 99)`, `posix_fadvise(.., len=-1)`, `dup3` bad flags (1), `fcntl(F_DUPFD, -1)`, `access(p, 99)` | `EINVAL` (dup3 flags is known) | `None`/0; fcntl F_DUPFD with min -1 returns an fd; `access` with a bad mode is False | | Linux: `EINVAL` | wrong errno (low) | adapter validation of enums (cf. N1: each WASI enum conversion is a trap risk; check `fadvise` advice, `fd_advise`) |
| N35 | `F_GETFL`/`F_SETFL` content | `0o2100002`-style (adds `O_LARGEFILE 0o100000` and `0o2000000`; keeps `O_CREAT\|O_TRUNC\|O_SYNC` bits) | only access mode, `O_APPEND`, `O_NONBLOCK` | | Linux reports access mode + O_APPEND/O_NONBLOCK/O_SYNC/O_LARGEFILE | cosmetic | none |
| N36 | `O_ACCMODE` (3) in `os.open` flags | **Pyodide fatal** (`TypeError ... 'includes'` in `nodePermissions`, process ends) | ours: the open **succeeds** (returns fd 4) | `flagsToPermissionString` has no entry for 3 | Linux: `EINVAL` | low (neither is right; Pyodide's is a crash) | adapter `openat`: access mode 3 is `EINVAL` |
| N37 | `os.getlogin()`, `os.environ['HOME']` (`/home/pyodide`), `PWD`, `os.path.expanduser('~')` | `web_user`/`/home/pyodide` | `ENXIO`, `None`, `'~'` | glue sets HOME, PWD | | not a file call: belongs to the `env` area | note only |
| N38 | `os.listdir('/')` | `['dev','home','lib','proc','tmp']` | `['_pw_1.rc','_pw_1.py','etc','lib','tmp']` (the run files `_pw_N.py/.rc` that `Pyodide.run` writes into the guest's root are visible to the program) | | | cosmetic | host: put the run files outside the guest's root or hide `_pw_*` |

### 3.2b Pyodide crashes found on the way (cannot be diffed; Pyodide is wrong, ours answers)

| id | case | Pyodide | ours |
|---|---|---|---|
| P1 | `utime(f, (2**53, 2**53))` or `(2**40, ...)` then any `stat` of f (`files_crash_utime.py`) | `RangeError: NaN cannot be converted to a BigInt` in `writeStat`, fatal | `EINVAL` (the known gap: Pyodide accepts 2**40 and -5) |
| P2 | `pwrite(fd, b'x', 2**40)` (`files_crash_bigpwrite.py`), `ftruncate` beyond ~2**32 gives `EFBIG` at 2**40 | `RangeError: Array buffer allocation failed`, fatal | a sparse file (host) |
| P3 | `libc.pwritev(fd, NULL, -1, 0)`, `os.open(f, O_ACCMODE)`, `utimensat` with `tv_nsec = 10**9` (`files_crash_utimensat.py`; ours `EINVAL`) | fatal / stores NaN | `EINVAL` / ok |

## 4. KNOWN differences re-observed (audit entry: gap)

| entry | gap | observed in |
|---|---|---|
| `__syscall_openat` (and every path call) | host path limits: 256-byte name and a 4096-byte symlink target give `ENAMETOOLONG`; a surrogate (non-UTF-8) name gives `EILSEQ` (WASI paths are UTF-8); Pyodide makes them (a surrogate name is stored mangled) | `open n256 *` (13), `surrogate` (13+), `symlink long target 4096/5000`; every class x call in ops/meta/stat/dirs |
| `__syscall_dup` | the offset is not shared (`dup shares offset`, `F_DUPFD shares offset`, `dup lseek on dup moves orig`, `dup write via dup`: ours 0, Pyodide 3 / `b'CD23456789'` vs `b'ABCD456789'`); dup after rename or unlink fails (`ENOENT`) or reopens another file (`dup after unlink+recreate` reads `b'new'`) | `files_fcntl.py` |
| `__syscall_dup3` | target must be open (see N19); flags are not checked (`dup3` flags=1 returns 78, Pyodide `EINVAL`); no shared offset (`dup2 shares offset`, `dup2 target pos unchanged src`) | `files_fcntl.py`, `files_libc.py` |
| `__syscall_fcntl64` | `F_DUPFD`/`F_DUPFD_CLOEXEC` ignore the minimum number (11 cases `min=50..2000`: ours returns a lower number) | `files_fcntl.py` |
| `__syscall_mknodat` | `ENOSYS` for FIFO/chr/blk/socket (libc `mknod`, `mkfifo`, `mkfifoat`, `mknodat`: 36 lines); `mknod` of a regular file also differs; Pyodide makes the nodes (its ENOENT/EEXIST/EACCES answers for bad paths are produced before the type is looked at, ours is `ENOSYS` first) | `files_libc.py` |
| `__syscall_utimensat` | times before 1970 and after 2554: `utime(f, (-5, 10))`, `(-1,-1)`, `2**40`, `ns=(-1,-1)`: `EINVAL`, Pyodide accepts | `files_meta.py` (re-run alone `files_crash_utime.py`) |
| `__syscall_openat` (`os.pipe`) | `os.pipe` `ENOSYS` (other step) | `files_fcntl.py` |

## 5. Host-dependent (the guest's files live on the host)

* The host runs as root in this audit: permission checks that Linux/Pyodide do for a non-root user are bypassed by the host for calls that
  go straight to the host kernel: `truncate` of a 0444/0000 file (N14), `chown` (N27), `stat('dnone/x')` is `ENOENT` (the host
  says "missing", Pyodide `EACCES`), `open('dnone/x')` the same. As non-root these would follow the adapter's own checks. Re-run as a normal user to separate them.
* `listdir`/`scandir`/`walk`/`glob` **order** is the host directory's (Pyodide: MEMFS insertion order): 4 `walk` lines and 2 `listdir order` lines; sort for comparing.
* `st_nlink` of directories, `st_blocks`, `st_dev`, `st_blksize` (4096 both), `statvfs` numbers (all positive, `f_namemax` 255 both) are the host's.
* names: 256 bytes, surrogate escapes (`os.fsencode` of `'\udcff'` is not valid UTF-8): EILSEQ/ENAMETOOLONG (see section 4).
* Ours `/lib/python315.zip` has mode 0644 and 3 MB `blocks` 5866 where Pyodide has 0666 / 734.

## 6. Not probed, and why

* `renameat2` flags (RENAME_NOREPLACE/EXCHANGE/WHITEOUT): not in musl's libc of this build (`renameat2` is absent from the exported names, `files_ctypes.py`); `os.rename` never uses it.
* `getdents64` through the raw syscall with a buffer size: Python only goes through `readdir`/`scandir`; the 5000-entry directory (count, uniqueness, `d_type`, sorted equal, `rmtree`) shows no difference.
* `fallocate` modes other than 0 (`FALLOC_FL_*`): `posix_fallocate` is mode 0; Pyodide returns `EOPNOTSUPP` for others (glue `-138`); not reachable through ctypes without raw `syscall`.
* `sync`/`fdatasync` of a directory and `fsync` durability: nothing observable.
* dup/pipe/socket/stdio dup (the other step); `os.dup2` onto 0/1/2 was not run.
* Windows/macOS hosts: not available; symlink behaviour there is in the audit's known gaps.
* A non-root host: only root was available (section 5).
* `O_ACCMODE`, `utime` huge times, `pwritev(-1)`: Pyodide dies, so they are only in the crash probes.
* `st_atime` updates on read and `noatime`: not deterministic.

## 7. Suggested order of fixes (for the orchestrator)

1. N1 (trap in `fd_seek`), N2 (hang on `read(0, 0)`), N3 (closing/using the preopen fd 3), N4 (lseek overflow poisons the interpreter): small, in the adapter/host, each with a one-line probe in `tests/`.
2. N24 (`/dev/null`, `/dev/zero`, `/dev/urandom`, `/dev/tty`), N6 (empty path), N7 (`rmdir`/`rmtree` with a trailing slash), N15 (`readv`/`writev` iovecs), N20 (scandir duplicates).
3. Wrong errno group: N10, N11, N23, N32, N33, N34 (and a sweep of every WASI enum argument for the trap risk of N1).
4. The rest are cosmetic or ours-is-right (N8, N9, N12, N13, N21, N27-N31, N35, N36).
