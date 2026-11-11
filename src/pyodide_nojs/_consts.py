"""The constants, the errors and the number helpers of the host: no state, no engine, nothing that runs."""

from __future__ import annotations

import errno
import hashlib
import logging
import os
import re
import zipfile
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

from . import _engine, _wasm

log = logging.getLogger("pyodide_nojs")

# the guest's memory, as the functions of the other modules are given it: read n bytes at a pointer, write at a pointer
Reader = Callable[[int, int], bytes]
Writer = Callable[[int, bytes], None]

PYVER = "3.15"  # the Python of the pinned Pyodide (315.0.0-alpha.2 = 3.15.0rc1)
PYVER_FULL = "3.15.0rc1"  # CPython's own version string, a NUL-delimited constant in the pinned pyodide.asm.wasm
FLAVORS = ("fused", "dynamic")
DATA = Path(__file__).resolve().parent / "data"
GUEST = Path(__file__).resolve().parent / "guest"  # Python that runs in the guest: copied to its site-packages
GUEST_SUFFIXES = (".py", ".pth")  # of the files copied, and of the files the snapshot key covers

# The guest's whole environment (the host's is never passed unless `inherit_env`): what Pyodide has on Node
# (Emscripten's USER, LOGNAME, PATH, PWD, LANG; HOME from its loader), and LD_LIBRARY_PATH (where NEEDED are sought).
BASE_ENV = [
    ("USER", "web_user"),
    ("LOGNAME", "web_user"),
    ("PATH", "/"),
    ("PWD", "/"),
    ("HOME", "/home/pyodide"),
    ("LANG", "en_US.UTF-8"),
    ("LD_LIBRARY_PATH", f"/usr/lib:/lib/python{PYVER}/site-packages"),
]
# What the interpreter reads at start only: removed from os.environ once it runs, as in Pyodide (which sets them in its
# configuration). Never taken from the host's environment.
TESTENV_HINT = " (the tests' testenv is made by `sh tools/prepare_testenv.sh pyo-build`)"
GUEST_OWN_ENV = {"PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH"}  # `inherit_env` does not override these

MAX_MEMORY = 4 << 30  # the main module's memory: 65536 pages
MAX_TABLE = 10_000_000  # the glue's WebAssembly.Table limit in V8
SNAPSHOT_VERSION = 1  # the layout of a snapshot file; part of its key

# the host's sockets: errors in WASI's numbering, which is Emscripten's
WASI_ERRNO = {
    n: i
    for i, n in enumerate(
        "SUCCESS 2BIG ACCES ADDRINUSE ADDRNOTAVAIL AFNOSUPPORT AGAIN ALREADY BADF BADMSG BUSY CANCELED CHILD "
        "CONNABORTED CONNREFUSED CONNRESET DEADLK DESTADDRREQ DOM DQUOT EXIST FAULT FBIG HOSTUNREACH IDRM ILSEQ "
        "INPROGRESS INTR INVAL IO ISCONN ISDIR LOOP MFILE MLINK MSGSIZE MULTIHOP NAMETOOLONG NETDOWN NETRESET "
        "NETUNREACH NFILE NOBUFS NODEV NOENT NOEXEC NOLCK NOLINK NOMEM NOMSG NOPROTOOPT NOSPC NOSYS NOTCONN NOTDIR "
        "NOTEMPTY NOTRECOVERABLE NOTSOCK NOTSUP NOTTY NXIO OVERFLOW OWNERDEAD PERM PIPE PROTO PROTONOSUPPORT "
        "PROTOTYPE RANGE ROFS SPIPE SRCH STALE TIMEDOUT TXTBSY XDEV NOTCAPABLE".split()
    )
}

# musl's (Linux's) numbers, which the guest uses, by the NAME of the host's constant; the host's own numbers differ
# The guest's errno numbers are Emscripten's (system/lib/libc/musl/arch/emscripten/bits/errno.h): WASI's for the
# names WASI has, and its own 137.. for the rest; ENOTSUP is EOPNOTSUPP = 138 (not WASI's NOTSUP, 58).
GUEST_ERRNO = {
    **WASI_ERRNO,
    "NOTSUP": 138,
    "OPNOTSUPP": 138,
    "SOCKTNOSUPPORT": 137,
    "PFNOSUPPORT": 139,
    "SHUTDOWN": 140,
    "HOSTDOWN": 142,
    "WOULDBLOCK": WASI_ERRNO["AGAIN"],
    "DEADLOCK": WASI_ERRNO["DEADLK"],
}
ESOCKTNOSUPPORT, EOPNOTSUPP = GUEST_ERRNO["SOCKTNOSUPPORT"], GUEST_ERRNO["OPNOTSUPP"]
# Windows reports socket errors as WSAE* numbers (and its errno.errorcode has them only there): by number, so that the
# translation is the same on every OS
WSA_ERRNO = {
    10004: "INTR", 10009: "BADF", 10013: "ACCES", 10014: "FAULT", 10022: "INVAL", 10024: "MFILE",
    10035: "AGAIN", 10036: "INPROGRESS", 10037: "ALREADY", 10038: "NOTSOCK", 10039: "DESTADDRREQ",
    10040: "MSGSIZE", 10041: "PROTOTYPE", 10042: "NOPROTOOPT", 10043: "PROTONOSUPPORT",
    10044: "SOCKTNOSUPPORT", 10045: "OPNOTSUPP", 10046: "PFNOSUPPORT", 10047: "AFNOSUPPORT",
    10048: "ADDRINUSE", 10049: "ADDRNOTAVAIL", 10050: "NETDOWN", 10051: "NETUNREACH", 10052: "NETRESET",
    10053: "CONNABORTED", 10054: "CONNRESET", 10055: "NOBUFS", 10056: "ISCONN", 10057: "NOTCONN",
    10058: "SHUTDOWN", 10060: "TIMEDOUT", 10061: "CONNREFUSED", 10064: "HOSTDOWN", 10065: "HOSTUNREACH",
}  # fmt: skip


def guest_errno(code: int | None) -> int:
    """A host errno (any OS: by its name, or the WSAE number) -> the guest's positive errno; EIO, logged, if unknown."""
    name = WSA_ERRNO.get(code or 0) or errno.errorcode.get(code or 0, "EIO")[1:]
    if name not in GUEST_ERRNO:
        log.warning("[net] host error %r has no guest errno: EIO", code)
        return GUEST_ERRNO["IO"]
    return GUEST_ERRNO[name]


class GuestFault(Exception):
    """A guest pointer or length outside its memory: EFAULT, never a trap of the host."""


class GuestExit(Exception):
    """The guest called proc_exit (exit(), os._exit(), a signal's default action): the status, 0-255."""

    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


# /etc/services of the guest (musl reads it for getservbyname/getservbyport), and getaddrinfo's fallback
SERVICES = {
    (n, pr): port
    for n, port, prs in (
        ("echo", 7, "tcp udp"),
        ("ftp", 21, "tcp"),
        ("ssh", 22, "tcp"),
        ("telnet", 23, "tcp"),
        ("smtp", 25, "tcp"),
        ("domain", 53, "tcp udp"),
        ("http", 80, "tcp"),
        ("pop3", 110, "tcp"),
        ("ntp", 123, "udp"),
        ("imap", 143, "tcp"),
        ("https", 443, "tcp"),
        ("imaps", 993, "tcp"),
        ("pop3s", 995, "tcp"),
    )  # fmt: skip
    for pr in prs.split()
}


# ---------------------------------------------------------------------------------------------------------------------
# JavaScript's numbers, for the calls that Emscripten's glue makes as `wasmTable.get(fn)(...args)` (ffi_call_js, the
# trampoline): an i32 parameter takes a Number (a fraction is cut, a missing value is 0), an i64 only a BigInt, a float
# a Number (a missing value is NaN); anything else is a TypeError, as in JavaScript.
class _Big(int):
    """A BigInt (what libffi's JavaScript reads for 64-bit values), as against a Number."""


def _to_wasm(v: Any, t: str) -> Any:
    if t == "i32":
        if isinstance(v, _Big):
            raise TypeError("Cannot mix BigInt and other types")
        if isinstance(v, float):
            v = int(v) if v == v and abs(v) != float("inf") else 0
        v = (v or 0) & 0xFFFFFFFF
        return v - (1 << 32) if v >> 31 else v
    if t == "i64":
        if not isinstance(v, _Big):
            raise TypeError(f"Cannot convert {v} to a BigInt")
        v &= 0xFFFFFFFFFFFFFFFF
        return v - (1 << 64) if v >> 63 else v
    if t in ("f32", "f64"):
        if isinstance(v, _Big):
            raise TypeError("Cannot mix BigInt and other types")
        return float("nan") if v is None else float(v)
    raise TypeError(f"a function parameter of type {t} cannot be called from a C signature")


def _from_wasm(res: Any, results: list[str]) -> Any:
    """A wasm result as the JavaScript value: None (undefined) for no result, a BigInt for an i64."""
    if not results:
        return None
    if len(results) > 1:
        return float("nan")
    return _Big(res) if results[0] == "i64" else res


def _num(v: Any, bits: int) -> int:
    """A Number (or undefined) stored into an unsigned typed array of `bits`: cut, wrapped; a BigInt is a TypeError."""
    if isinstance(v, _Big):
        raise TypeError("Cannot mix BigInt and other types")
    if isinstance(v, float):
        v = int(v) if v == v and abs(v) != float("inf") else 0
    return (v or 0) & ((1 << bits) - 1)


_U32 = 0xFFFFFFFF


def code_hash(folder: Path) -> str:
    """A digest of the host's Python: every module directly in `folder` (the package) but `_version.py` (made at
    build time), by name and content. Part of a snapshot's key: a change of any host module invalidates snapshots."""
    return hashlib.sha256(
        b"".join(
            f.name.encode() + b"\0" + f.read_bytes() for f in sorted(folder.glob("*.py")) if f.name != "_version.py"
        )
    ).hexdigest()


def data_dir(path: str | os.PathLike[str] | None = None) -> Path:
    """Where the wasm files are: PATH, else $PYODIDE_NOJS_DATA, else the package's own `data`."""
    return Path(path or _engine.env("PYODIDE_NOJS_DATA") or DATA)


def available_flavors(data: Path) -> list[str]:
    have = []
    if (data / "pyodide_fused.wasm").exists():
        have.append("fused")
    if (data / "pyodide.asm.wasm").exists() and (data / "adapter.wasm").exists():
        have.append("dynamic")
    return have


def _override(path: str | os.PathLike[str] | None, var: str) -> Path | None:
    """The file PATH, else $VAR (an asm_wasm or stdlib that replaces the data directory's): None if neither is set."""
    p = path or _engine.env(var)
    if not p:
        return None
    if not Path(p).is_file():
        raise FileNotFoundError(f"no such file: {p}" + ("" if path else f" (from ${var})"))
    return Path(p)


def override_warnings(asm: Path | None, stdlib: Path | None, data: Path) -> tuple[list[str], list[str]]:
    """What differs in a pyodide.asm.wasm / python_stdlib.zip that is not the pinned build's: (warnings, details).
    Reads bytes only (no compile). Pyodide's own version is not in the wasm, so CPython's version string is compared."""
    warn: list[str] = []
    detail: list[str] = []
    if asm is not None:
        b = asm.read_bytes()
        seen = sorted({m.decode() for m in re.findall(rb"\x00(3\.\d+\.\d+(?:[abc]|rc)?\d*)\x00", b)})
        if PYVER_FULL not in seen:
            warn.append(
                f"{asm} does not carry CPython {PYVER_FULL} (the pinned Pyodide's); its version strings: "
                f"{', '.join(seen) or 'none found'} (only CPython's version is compared: Pyodide's is not in the wasm)"
            )
        imps = {n for m, n, k in _wasm.import_names(b) if k == 0 and m == "env"}
        adapter, known = data / "adapter.wasm", data / "pyodide.asm.wasm"
        if adapter.exists() and known.exists():  # answered: by the adapter, or audited as a stub in the pinned build
            names = {n for m, n, k in _wasm.import_names(known.read_bytes()) if m == "env"}
            names |= set(_wasm.export_names(adapter.read_bytes()))
            new = sorted(imps - names)
            if new:
                warn.append(f"{asm} imports {len(new)} env functions that the adapter does not know (-v lists them)")
                detail.append("unknown env imports: " + ", ".join(new[:10]) + (" ..." if len(new) > 10 else ""))
        if "__syscall_setsockopt_host" not in imps:
            warn.append(
                f"{asm} lacks the setsockopt patch (tools/patch_main.mjs): setsockopt returns 0 and does nothing"
            )
    if stdlib is not None:
        try:
            with zipfile.ZipFile(stdlib) as z:
                cfg = next(n for n in z.namelist() if re.fullmatch(r"_sysconfigdata_[^/]*\.py", n))
                ver = re.search(r"'VERSION': '([^']*)'", z.read(cfg).decode())
            found = ver.group(1) if ver else "?"
        except (OSError, StopIteration, zipfile.BadZipFile):
            found = "?"
        if found != PYVER:
            warn.append(
                f"{stdlib} is for Python {found} (VERSION of its sysconfigdata), the host lays out Python {PYVER}"
            )
    return warn, detail


def _s32(x: int) -> int:
    """x as the signed i32 wasmtime-py wants for a parameter or a result."""
    x &= 0xFFFFFFFF
    return x - (1 << 32) if x >> 31 else x


class MainExports(Mapping):
    """The main module's symbols as dlsym and the GOT see them: its (lazy) exports, those of the adapter in the
    dynamic build (`extra`), and not the JavaScript bridge's stubs (`hidden`)."""

    def __init__(self, base: Mapping) -> None:
        self.base, self.extra, self.hidden = base, {}, set()

    def __getitem__(self, name: str) -> Any:
        if name in self.hidden:
            raise KeyError(name)
        if name in self.extra:
            return self.extra[name]
        return self.base[name]

    def __iter__(self) -> Iterator[str]:
        for n in self.base:
            if n not in self.hidden and n not in self.extra:
                yield n
        yield from (n for n in self.extra if n not in self.hidden)

    def __len__(self) -> int:
        return sum(1 for _ in self)


# exports of the adapter that only the host calls: the guest's dlsym and GOT do not see them (Pyodide has no such name)
SERVICE_EXPORTS = ("__nojs_sigcell_addr", "__nojs_set_runtime")
_JS_MODULES = ("env", "GOT.mem", "GOT.func", "wasi_snapshot_preview1")  # the glue's import object
_GLOBAL_WHY = "global import must be a number, valid Wasm reference, or WebAssembly.Global object"
