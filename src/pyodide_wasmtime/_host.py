"""CPython of Pyodide (`pyodide.asm.wasm`) run by wasmtime-py with no JavaScript.

The Emscripten `env` glue is wasm (`adapter.wasm`, C, after the shape of Wasmtime's preview1 adapter); this file is
what a wasm module can not do itself: WASI (wasmtime's own), the four operations of the loader (the host holds the
instances and their exports by name) and the host's sockets (WASI preview1 has no `connect`).

Two builds of the same sources, one `Pyodide` class:

* ``dynamic``: ``pyodide.asm.wasm`` + ``adapter.wasm``, linked at run time (a shim generated from the import list, the
  trampoline, and a fixup of the shim's table);
* ``fused``: ``pyodide_fused.wasm``, one core module made at build time (`tools/fuse.py`), only instantiated.
"""

from __future__ import annotations

import contextlib
import ctypes
import errno
import hashlib
import importlib.metadata
import json
import logging
import os
import re
import select
import shutil
import socket
import ssl
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from . import _engine, _wasm

log = logging.getLogger("pyodide_wasmtime")

PYVER = "3.15"  # the Python of the pinned Pyodide (315.0.0-alpha.2 = 3.15.0rc1)
FLAVORS = ("fused", "dynamic")
DATA = Path(__file__).resolve().parent / "data"

BASE_ENV = [
    ("PYTHONHOME", "/"),
    ("LANG", "C.UTF-8"),
    ("PYTHONPATH", f"/lib/python{PYVER}/site-packages"),
    ("PYTHONDONTWRITEBYTECODE", "1"),
]

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


MSG_FLAGS = {
    1: "MSG_OOB",
    2: "MSG_PEEK",
    4: "MSG_DONTROUTE",
    0x20: "MSG_TRUNC",
    0x40: "MSG_DONTWAIT",
    0x80: "MSG_EOR",
    0x100: "MSG_WAITALL",
    0x4000: "MSG_NOSIGNAL",
    0x8000: "MSG_MORE",
}
SOCK_LEVELS = {1: "SOL_SOCKET", 0: "IPPROTO_IP", 6: "IPPROTO_TCP", 41: "IPPROTO_IPV6"}
SOCK_OPTIONS = {
    **{
        (1, n): v
        for n, v in enumerate(
            "SO_DEBUG SO_REUSEADDR SO_TYPE SO_ERROR SO_DONTROUTE SO_BROADCAST SO_SNDBUF SO_RCVBUF SO_KEEPALIVE "
            "SO_OOBINLINE".split(),
            1,
        )
    },
    (1, 13): "SO_LINGER",
    (1, 15): "SO_REUSEPORT",
    (1, 18): "SO_RCVLOWAT",
    (1, 19): "SO_SNDLOWAT",
    (1, 30): "SO_ACCEPTCONN",
    (0, 1): "IP_TOS",
    (0, 2): "IP_TTL",
    (0, 33): "IP_MULTICAST_TTL",
    (0, 34): "IP_MULTICAST_LOOP",
    **{
        (6, n): v
        for n, v in enumerate("TCP_NODELAY TCP_MAXSEG TCP_CORK TCP_KEEPIDLE TCP_KEEPINTVL TCP_KEEPCNT".split(), 1)
    },
    (41, 16): "IPV6_UNICAST_HOPS",
    (41, 18): "IPV6_MULTICAST_HOPS",
    (41, 19): "IPV6_MULTICAST_LOOP",
    (41, 26): "IPV6_V6ONLY",
}
AI_FLAGS = {
    1: "AI_PASSIVE",
    2: "AI_CANONNAME",
    4: "AI_NUMERICHOST",
    8: "AI_V4MAPPED",
    16: "AI_ALL",
    32: "AI_ADDRCONFIG",
    1024: "AI_NUMERICSERV",
}
NI_FLAGS = {1: "NI_NUMERICHOST", 2: "NI_NUMERICSERV", 4: "NI_NOFQDN", 8: "NI_NAMEREQD", 16: "NI_DGRAM"}
EAI_CODES = {
    getattr(socket, "EAI_" + n): code
    for n, code in (
        ("BADFLAGS", -1),
        ("NONAME", -2),
        ("AGAIN", -3),
        ("FAIL", -4),
        ("FAMILY", -6),
        ("SOCKTYPE", -7),
        ("SERVICE", -8),
        ("MEMORY", -10),
        ("SYSTEM", -11),
        ("OVERFLOW", -12),
        ("ADDRFAMILY", -2),
        ("NODATA", -2),
    )  # fmt: skip
    if hasattr(socket, "EAI_" + n)
}
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


# What the guest runs for one `run()`: the user's code in __main__, SystemExit as an exit status (the interpreter must
# survive it: Emscripten's exit() ends in `unreachable`), any other error as a traceback and status 1.
_WRAPPER = """\
import sys as _s, __main__ as _m, traceback as _t
_rc = 0
try:
    exec(compile(open({src!r}).read(), "<string>", "exec"), _m.__dict__)
except SystemExit as _e:
    _c = _e.code
    if _c is None: _rc = 0
    elif isinstance(_c, int): _rc = _c
    else: print(_c, file=_s.stderr); _rc = 1
except BaseException:
    _t.print_exc(); _rc = 1
_s.stdout.flush(); _s.stderr.flush()
open({rc!r}, "w").write(str(_rc))
del _s, _m, _t, _rc
"""


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


def _days_from_civil(y: int, m: int, d: int) -> int:  # proleptic Gregorian (H. Hinnant)
    y -= m <= 2
    era = y // 400
    yoe = y - era * 400
    doe = yoe * 365 + yoe // 4 - yoe // 100 + (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    return era * 146097 + doe - 719468


def _civil_from_days(z: int) -> tuple[int, int, int]:
    z += 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    m = mp + (3 if mp < 10 else -9)
    return yoe + era * 400 + (m <= 2), m, doy - (153 * mp + 2) // 5 + 1


_U32 = 0xFFFFFFFF
_DATE_LIMIT = 8_640_000_000_000  # JavaScript's Date holds +-8.64e15 ms


def _js_make(year: int, mon: int, mday: int, h: int, mi: int, s: int) -> int | None:
    """MakeDate(MakeDay(year, mon, mday), MakeTime(h, mi, s, 0)) of V8, in seconds; None is NaN. A year 0..99 is 19xx
    (the Date constructor and Date.UTC do that), a year or month beyond V8's limits is NaN."""
    if 0 <= year <= 99:
        year += 1900
    if not (-1_000_000 <= year <= 1_000_000 and -10_000_000 <= mon <= 10_000_000):
        return None
    year += mon // 12
    return (_days_from_civil(year, mon % 12 + 1, 1) + mday - 1) * 86400 + h * 3600 + mi * 60 + s


def data_dir(path: str | os.PathLike[str] | None = None) -> Path:
    """Where the wasm files are: PATH, else $PYODIDE_WASMTIME_DATA, else the package's own `data`."""
    return Path(path or os.environ.get("PYODIDE_WASMTIME_DATA") or DATA)


def available_flavors(data: Path) -> list[str]:
    have = []
    if (data / "pyodide_fused.wasm").exists():
        have.append("fused")
    if (data / "pyodide.asm.wasm").exists() and (data / "adapter.wasm").exists():
        have.append("dynamic")
    return have


def ca_bundle() -> bytes:
    """The host's CA certificates for the guest's OpenSSL (`SSL_CERT_FILE`): the environment's, Python's, system's."""
    files = [
        os.environ.get("SSL_CERT_FILE"),
        ssl.get_default_verify_paths().cafile,
        "/etc/ssl/certs/ca-certificates.crt",
    ]
    try:
        import certifi  # type: ignore[import-not-found,unused-ignore]

        files.append(certifi.where())
    except ImportError:
        pass
    out, seen = b"", set()
    for f in files:
        if f and f not in seen and os.path.exists(f):
            seen.add(f)
            out += Path(f).read_bytes() + b"\n"
    return out


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
        yield from self.extra

    def __len__(self) -> int:
        return sum(1 for _ in self)


class Pyodide:
    """One Python (Pyodide's CPython) in wasm, run by wasmtime.

    >>> py = Pyodide()                       # the dynamic build from the package's data (fused if only that is there)
    >>> py.run("print(1 + 1)")               # 0 if the code ran, -1 if it raised (the traceback is on stderr)

    ``site``: a folder (or several) copied into the guest's ``site-packages`` (a wheel unpacked, ``micropip``...);
    ``mounts``: ``{guest path: host folder}`` preopened as they are (the guest can write there);
    ``preopen_dev``: the host's ``/dev`` (OpenSSL reads ``/dev/urandom``); ``env``: more environment variables.
    The guest's ``/`` is a temporary folder (stdlib zip, site-packages); it is not a sandbox against the host's own
    network: ``socket`` and the host's fetch are real.

    ``preload``: Python source run once at start (as ``run(preload)``). The memory after it is cached in a snapshot file
    in the cache dir, so a next start with the same preload and settings restores it instead of booting Python
    (``$PYODIDE_WASMTIME_SNAPSHOT=0`` turns that off). The preload must only import and compute: it must not print (it
    prints at snapshot time only); opening files or sockets, ``chdir``, writing files, ``dlopen``, ``ctypes`` symbol
    lookups or callbacks, and signals or timers make the snapshot be skipped (a normal start,
    the preload run once); with ``site=`` or ``mounts=`` there is no snapshot at all.
    """

    def __init__(
        self,
        flavor: str | None = None,
        *,
        site: str | os.PathLike[str] | list[str | os.PathLike[str]] | None = None,
        mounts: dict[str, str | os.PathLike[str]] | None = None,
        preopen_dev: bool | None = None,
        env: dict[str, str] | None = None,
        data: str | os.PathLike[str] | None = None,
        wasm_opt: str | os.PathLike[str] | None = None,
        preload: str | None = None,
    ) -> None:
        wt = _engine.require_wasmtime()
        self._wt = wt
        self.data = data_dir(data)
        have = available_flavors(self.data)
        if flavor is None:
            flavor = os.environ.get("PYODIDE_WASMTIME_FLAVOR") or (
                "dynamic" if "dynamic" in have else (have[0] if have else "dynamic")
            )
        if flavor not in FLAVORS:
            raise ValueError(f"flavor must be one of {FLAVORS}, not {flavor!r}")
        if flavor not in have:
            raise FileNotFoundError(
                f"no {flavor} build in {self.data} (found: {have or 'nothing'}); see tools/build_data.sh"
            )
        self.flavor = flavor
        self.site = [site] if isinstance(site, (str, os.PathLike)) else list(site or [])
        self.mounts = {k: str(v) for k, v in (mounts or {}).items()}
        self.preopen_dev = bool(os.environ.get("PREOPEN_DEV")) if preopen_dev is None else preopen_dev
        self.env = dict(env or {})
        self.preload = preload
        self.restored = False  # the guest came from a snapshot
        self._net_slots: tuple[int, int] = (0, 0)
        opt = os.environ.get("WASM_OPT") or wasm_opt or self.data / "wasm-opt.wasm"
        self.wasm_opt = str(opt) if (os.environ.get("WASM_OPT") or wasm_opt or Path(opt).exists()) else None
        # state of the running guest
        self.root: Path | None = None
        self.cur: list = []  # the Caller (or the Store) of the running host function
        self.instances: list = [None]  # id -> {exports (name -> extern, in export order), got (GOT globals)}
        self.slots: dict = {}  # (instance, export name) -> table slot
        self.scopes: dict[int, list[int]] = {}  # a dlopen call's scope -> the instances loaded in it
        self._tfuncs: dict[bytes, int] = {}  # the table's functions (by engine handle) -> first slot
        self._tscanned = 0
        self._wasi_linker: Any = None  # wasmtime's WASI functions, for the side modules that import them
        self._dlreason = ""  # why the last instantiate failed
        self.socks: dict = {}
        self.netlog: list[str] = []
        self.protoents: dict[str, int] = {}  # getprotobyname's answers, by name (guest addresses)
        self.lazy: list[str] = []
        self.converted = 0  # modules whose legacy exceptions the loader converted at dlopen
        self.summary = ""
        self._started = False
        self._runs = 0
        self._exited: int | None = None
        self.ex: Any = None
        self.table: Any = None
        # table slots of freed closures (ffi_closure_free_js), reused last in, first out
        self.free_slots: list[int] = []
        # table index -> (Func, parameter types, result types) of the functions called by ffi_call_js and the trampoline
        self.functions: dict[int, tuple] = {}
        self.func_pool: dict[tuple, list] = {}  # signature -> (Func, state) of freed closures, ready for the next one
        # set when the guest holds what only the host's side keeps (a closure's table slot, a signal word or timer): a
        # snapshot of the memory would not hold it, so none is taken. (The time zone libc read at init is in the
        # snapshot's key instead: every interpreter reads it.)
        self.host_state = False
        self.live_funcs: dict[int, tuple] = {}  # table slot -> (signature, Func, state) of a closure in use
        self._cell = 0  # the word with a pending signal (_Py_CheckEmscriptenSignals_Helper), in the guest's memory
        self._pending = 0  # a signal posted before the guest asked for the word
        self.memory: Any = None
        self.store: Any = None

    # ------------------------------------------------------------------ the guest's root
    def _setup_root(self) -> None:
        self.root = root = Path(tempfile.mkdtemp(prefix="pyodide_wasmtime_"))
        (root / "lib" / f"python{PYVER}" / "lib-dynload").mkdir(parents=True)  # CPython looks for it at start
        shutil.copy(self.data / "python_stdlib.zip", root / "lib" / f"python{PYVER.replace('.', '')}.zip")
        sp = root / "lib" / f"python{PYVER}" / "site-packages"
        sp.mkdir()
        for s in self.site:  # inside the preopen: WASI does not follow a link out of it
            shutil.copytree(s, sp, dirs_exist_ok=True)
        for guest in self.mounts:  # a placeholder, so that a directory listing of the parent shows the mount
            (root / guest.lstrip("/")).mkdir(parents=True, exist_ok=True)
        (root / "etc" / "ssl").mkdir(parents=True)
        (root / "etc" / "ssl" / "cert.pem").write_bytes(ca_bundle())
        (root / "etc" / "services").write_text("".join(f"{n} {p}/{pr}\n" for (n, pr), p in SERVICES.items()))
        shutil.copy(Path(__file__).with_name("guest") / "hostnet.py", sp)
        # the frozen `encodings` package looks in /lib/python3.15/encodings, which does not exist: the stdlib is the
        # zip (Pyodide's JavaScript sets this up); without it every codec but the frozen ones is missing
        # Pyodide's _socket was built without the constant SO_REUSEADDR (musl's value is 2), which asyncio and
        # socketserver look up; setsockopt itself is real (tools/patch_main.mjs)
        (sp / "sitecustomize.py").write_text(
            f"import encodings\nencodings.__path__.append('/lib/python{PYVER.replace('.', '')}.zip/encodings')\n"
            "import _socket\n_socket.SO_REUSEADDR = 2\n"
        )

    def _drop_stubs(self) -> None:
        """The fused module exports the zero/null stubs of the JavaScript bridge (the merge made them functions);
        the glue marks them `stub` and dlsym and the GOT do not see them: nor do we. Needs the pyodide.asm.wasm
        and adapter.wasm of the package (without them every export stays)."""
        main_path, adapter_path = self.data / "pyodide.asm.wasm", self.data / "adapter.wasm"
        if not (main_path.exists() and adapter_path.exists()):
            return
        wasm = main_path.read_bytes()
        exports = self.instances[0]["exports"]
        answered = set(_wasm.export_names(adapter_path.read_bytes())) | set(_wasm.export_names(wasm)) | {_wasm.TRAMP}
        for mod, name, kind in _wasm.import_names(wasm):
            if mod == "env" and kind == 0 and name not in answered:
                exports.hidden.add(name)

    # ------------------------------------------------------------------ the loader's host interface
    # Five operations a wasm module cannot do itself, because the host holds the instances and their exports by
    # name: instantiate, scope, got_set, sym, call. The rest of `_dlopen_js` (the file, dylink.0 and its bounds, memory
    # from calloc, the GOT, relocations, constructors, dlerror) runs in the adapter.
    #
    # What a module's `env` imports see, as in Emscripten's glue: the main module (in the dynamic build with the
    # adapter's exports), then the libraries loaded RTLD_GLOBAL, and, when the function is first called (the glue's
    # lazy stubs), the libraries of the dlopen call's own scope (its NEEDED libraries; the last one wins) and last
    # the module's own exports.
    def _span(self, a: int, n: int) -> int:
        """The guest address a (wasmtime passes i32 as SIGNED: -1 is 0xFFFFFFFF) after checking that [a, a+n) lies in
        the memory; n is a size_t, so a negative one is a huge one. GuestFault (EFAULT) otherwise."""
        a = a + (1 << 32) if a < 0 else a
        n = n + (1 << 32) if n < 0 else n
        if a >> 32 or n >> 32 or a + n > self.memory.data_len(self.cur[-1]):
            raise GuestFault(f"{a:#x}+{n:#x} is outside the memory")
        return a

    def _rd(self, a: int, n: int) -> bytes:
        a = self._span(a, n)
        return bytes(self.memory.read(self.cur[-1], a, a + (n + (1 << 32) if n < 0 else n)))

    def _wr(self, a: int, data: bytes) -> None:
        data = bytes(data)
        self.memory.write(self.cur[-1], data, self._span(a, len(data)))

    def _env_func(self, name: str, scope: int = 0, own: dict | None = None) -> Any:
        wt = self._wt
        ids = [0] + [i for i in range(1, len(self.instances)) if self.instances[i]["global"]]
        if scope:
            ids += reversed(self.scopes.get(scope, []))
        for i in ids:
            e = self.instances[i]["exports"].get(name)
            if isinstance(e, wt.Func):
                return e
        e = (own or {}).get(name)
        return e if isinstance(e, wt.Func) else None

    def _dl_fail(self, kind: str, exc: BaseException) -> int:
        """A failed load: the reason as the glue's `${e}` prints it (the adapter asks for it with loader.error 11)."""
        why = [ln.strip() for ln in str(exc).splitlines() if ln.strip()]
        self._dlreason = f"{kind}: {why[-1] if why else type(exc).__name__}"
        log.info("[loader] instantiate failed: %s: %s", type(exc).__name__, exc)
        return -1

    # the reasons of loader.error, as Emscripten's glue words them (`${e}` of the error it throws)
    _DL_WHY = {
        1: 'Error: Failed to find dynamic library "{arg}"',
        2: "Error: need to see wasm magic number",
        3: "Error: need the dylink section to be first",
        4: "Error",
        5: "RangeError: byte length of Uint32Array should be a multiple of 4",
        6: "CompileError: WebAssembly.Module(): module is truncated or malformed",
        7: "Error: Dynamic linking error: undefined symbol '{arg}'",
        8: "[object Object]",
        9: "RangeError: WebAssembly.Memory(): out of memory",
        10: "Error: too many nested NEEDED libraries",
    }

    def _dl_error(self, code: int, np_: int, nn: int, ap: int, an: int) -> None:
        """dlerror's text: the glue's own, set through the main module's __dl_seterr."""
        name = self._rd(np_, nn).decode("utf-8", "replace") if np_ else "__main__"
        arg = self._rd(ap, an).decode("utf-8", "replace") if ap else ""
        if code == 12:
            text = f'Tried to lookup unknown symbol "{arg}" in dynamic lib: {name}'
        else:
            why = self._dlreason if code & 255 == 11 else self._DL_WHY.get(code & 255, "Error").format(arg=arg)
            text = ("'Could not" if code & 256 else "could not") + f" load dynamic lib: {name}\n{why}"
        c = self.cur[-1]
        ex = self.instances[0]["exports"]
        msg = text.encode("utf-8", "replace")
        blk = ex["malloc"](c, 8 + len(msg) + 1)  # [the %s argument][the format "%s"][the text]
        self._wr(blk, struct.pack("<I", blk + 8) + b"%s\0\0" + msg + b"\0")
        ex["__dl_seterr"](c, blk + 4, blk)  # the format and the pointer to its arguments
        ex["free"](c, blk)

    def _dl_instantiate(self, p: int, n: int, mb: int, tb: int, scope: int) -> int:
        wt = self._wt
        c = self.cur[-1]
        data = self._rd(p, n)
        if data[:4] != b"\0asm":  # wasmtime.Module would also take WAT text
            return self._dl_fail("Error", ValueError("need to see wasm magic number"))
        try:
            try:
                module = wt.Module(_engine.engine(), data)
            except Exception as exc:  # legacy exceptions (a wheel micropip just installed): Binaryen's wasm-opt, here
                if "legacy_exceptions" not in str(exc) or not self.wasm_opt:
                    raise
                module = wt.Module(_engine.engine(), _engine.translate_to_exnref(data, self.wasm_opt))
                self.converted += 1
                log.info("[loader] converted legacy exceptions to exnref (%d bytes)", n)
            wasi = [
                i.name
                for i in module.imports
                if i.module == "wasi_snapshot_preview1" and i.name not in _wasm.WASI_ROUTED
            ]
            if wasi and "memory" not in {e.name for e in module.exports}:
                # WASI reads the memory of its caller from the caller's `memory` export, which a side module lacks
                module = wt.Module(_engine.engine(), _wasm.with_memory_export(data))
        except Exception as exc:
            return self._dl_fail("CompileError: WebAssembly.Module()", exc)
        try:
            linker = wt.Linker(_engine.engine())
            own: dict = {}
            got: list = []
            i32 = wt.ValType.i32()
            main = self.instances[0]["exports"]
            for imp in module.imports:
                m, nm, ty = imp.module, imp.name, imp.type
                if m == "env" and nm == "memory":
                    item = self.memory
                elif m == "env" and nm == "__indirect_function_table":
                    item = self.table
                elif m == "env" and nm in ("__memory_base", "__table_base"):
                    item = wt.Global(c, wt.GlobalType(i32, False), wt.Val.i32(mb if nm == "__memory_base" else tb))
                elif m == "env" and nm == "__stack_pointer":
                    item = main["__stack_pointer"]
                elif isinstance(ty, wt.TagType):
                    item = main.get(nm) or wt.Tag(c, ty)
                elif m == "env" and isinstance(ty, wt.FuncType):
                    item = self._env_func(nm)
                    if item is None:  # as Emscripten's glue: resolved when called, an error only if still missing then
                        hit: list = []

                        def lazy(caller, *args, _n=nm, _sc=scope, _own=own, _hit=hit):
                            if not _hit:
                                f = self._env_func(_n, _sc, _own)
                                if f is None:
                                    raise RuntimeError(f"Dynamic linking error: cannot resolve symbol {_n}")
                                _hit.append(f)
                            return _hit[0](caller, *args)

                        item = wt.Func(self.store, ty, lazy, access_caller=True)
                        self.lazy.append(nm)
                elif m == "wasi_snapshot_preview1" and isinstance(ty, wt.FuncType):
                    # the glue gives a side module the main module's WASI imports: the adapter's (fd_read, fd_write,
                    # fd_close, fd_fdstat_get) or wasmtime's own
                    item = self._env_func(nm) if nm in _wasm.WASI_ROUTED else None
                    if item is None:
                        item = self._wasi_func(nm)
                elif m in ("GOT.mem", "GOT.func"):
                    item = wt.Global(c, wt.GlobalType(i32, True), wt.Val.i32(0))
                    got.append(item)
                else:
                    raise RuntimeError(f"unresolved import {m}.{nm}")
                linker.define(c, m, nm, item)
            inst = linker.instantiate(c, module)
            ex = inst.exports(c)
            exports = {e.name: ex[e.name] for e in module.exports}
            own.update(exports)
            self.instances.append({"exports": exports, "got": got, "global": False})
            return len(self.instances) - 1
        except Exception as exc:
            return self._dl_fail("LinkError: WebAssembly.Instance()", exc)

    def _wasi_func(self, name: str) -> Any:
        wt = self._wt
        if self._wasi_linker is None:
            self._wasi_linker = wt.Linker(_engine.engine())
            self._wasi_linker.define_wasi()
        return self._wasi_linker.get(self.cur[-1], "wasi_snapshot_preview1", name)

    def _dl_scope(self, id_: int, scope: int) -> None:
        """The module is loaded: its exports join the global namespace (scope 0) or the dlopen call's scope."""
        if scope:
            self.scopes.setdefault(scope, []).append(id_)
        else:
            self.instances[id_]["global"] = True

    def _dl_got_set(self, id_: int, i: int, v: int) -> None:
        self.instances[id_]["got"][i].set_value(self.cur[-1], v)

    def _table_slot(self, f: Any) -> tuple[int, bool]:
        """The table slot that holds function `f` (the glue's getFunctionAddress: the pointer C takes of a function
        and the one dlsym gives are the same number), else a new slot. -> (slot, made now)."""
        wt = self._wt
        c = self.cur[-1]
        key = bytes(f._func)
        size = self.table.size(c)
        for i in range(self._tscanned, size):  # the table is scanned once, then only what was added
            g = self.table.get(c, i)
            if isinstance(g, wt.Func):
                self._tfuncs.setdefault(bytes(g._func), i)
        self._tscanned = size
        slot = self._tfuncs.get(key)
        if slot is not None:
            g = self.table.get(c, slot)  # a slot that was set again since is not the function any more
            if isinstance(g, wt.Func) and bytes(g._func) == key:
                return slot, False
        slot = self.table.grow(c, 1, wt.Val.funcref(f))
        self._tfuncs[key] = slot
        self._tscanned = slot + 1
        return slot, True

    def _dl_sym(self, id_: int, p: int, n: int, out: int) -> int:
        wt = self._wt
        c = self.cur[-1]
        name = self._rd(p, n).decode("utf-8", "replace")
        exports = self.instances[id_]["exports"]
        e = exports.get(name)
        if isinstance(e, wt.Global):
            self._wr(out, struct.pack("<II", 1, 0))
            return e.value(c) & 0xFFFFFFFF
        if isinstance(e, wt.Func):
            if (id_, name) in self.slots:
                slot, new = self.slots[(id_, name)], False
            else:
                slot, new = self._table_slot(e)
                self.slots[(id_, name)] = slot
            # kind 3: a slot made by this lookup, with the export's index (the glue's symbolIndex)
            self._wr(out, struct.pack("<II", 3 if new else 2, list(exports).index(name) if new else 0))
            return slot
        self._wr(out, struct.pack("<II", 0, 0))
        return 0

    def _dl_call(self, id_: int, p: int, n: int) -> int:
        e = self.instances[id_]["exports"].get(self._rd(p, n).decode())
        if isinstance(e, self._wt.Func):
            e(self.cur[-1])
            return 1
        return 0

    # ------------------------------------------------------------------ the host's fetch (HTTP and TLS by the host)
    def _net_fetch(self, req_p: int, req_n: int, body_p: int, body_n: int, out_p: int) -> int:
        """As a browser's fetch or wasi:http: request as JSON + body; the answer is two blocks from the main module's
        malloc: JSON meta (status, reason, headers, url) and the body."""
        c = self.cur[-1]
        try:
            req = json.loads(self._rd(req_p, req_n))
            body = self._rd(body_p, body_n) if body_n else None
            r = urllib.request.Request(
                req["url"], data=body, headers=req.get("headers") or {}, method=req.get("method") or "GET"
            )
            try:
                resp = urllib.request.urlopen(r, timeout=60)
                st, reason, hdrs, data, url = (
                    resp.status,
                    resp.reason,
                    list(resp.headers.items()),
                    resp.read(),
                    resp.geturl(),
                )
            except urllib.error.HTTPError as e:
                st, reason, hdrs, data, url = e.code, e.reason, list(e.headers.items()), e.read(), e.url
            meta = {"status": st, "reason": str(reason), "headers": hdrs, "url": url}
            self.netlog.append(f"{req.get('method') or 'GET'} {req['url']} -> {st} ({len(data)} bytes)")
        except Exception as exc:
            meta, data = {"error": f"{type(exc).__name__}: {exc}"}, b""
            self.netlog.append(f"{req_n} -> {meta['error']}")
        blocks: list[int] = []
        for b in (json.dumps(meta).encode(), data):
            p = self.ex["malloc"](c, max(1, len(b)))
            self._wr(p, b)
            blocks += [p, len(b)]
        self._wr(out_p, struct.pack("<IIII", *blocks))
        return 0

    # ------------------------------------------------------------------ the host's sockets
    # The guest passes its own structures (sockaddr, msghdr, addrinfo, option values) as pointers and the host reads
    # and writes them, so the adapter stays small. The numbers are musl's (Linux's); the host's differ (macOS,
    # Windows), so options, flags and error codes are translated by NAME.
    @staticmethod
    def _werr(exc: OSError) -> int:
        """A host OSError -> -errno in the guest's (Emscripten's) numbering."""
        return -guest_errno(getattr(exc, "errno", None))

    def _cstr(self, p: int) -> str | None:
        """The NUL-terminated string at p (at most 4096 bytes: GuestFault if there is no end inside the memory)."""
        if not p:
            return None
        out = bytearray()
        for i in range(4096):
            b = self._rd(p + i, 1)  # GuestFault past the end of memory
            if b == b"\0":
                return out.decode("utf-8", "replace")
            out += b
        raise GuestFault("string too long")

    def _sockaddr(self, s: socket.socket, p: int, n: int) -> tuple:
        """The sockaddr at p (n bytes) as the host's address tuple for socket s."""
        want = 2 if s.family == socket.AF_INET else 10
        raw = self._rd(p, min(n, 128)) if p and n >= 2 else b""
        if len(raw) < 2:
            raise OSError(errno.EINVAL, "bad sockaddr")
        if int.from_bytes(raw[:2], "little") != want:
            raise OSError(errno.EAFNOSUPPORT, "address family")
        if len(raw) < (16 if want == 2 else 28):
            raise OSError(errno.EINVAL, "short sockaddr")
        return self._sockaddr_tuple(raw)

    @staticmethod
    def _sockaddr_tuple(raw: bytes) -> tuple:
        port = int.from_bytes(raw[2:4], "big")
        if raw[0] == 2:
            return socket.inet_ntop(socket.AF_INET, raw[4:8]), port
        return (
            socket.inet_ntop(socket.AF_INET6, raw[8:24]),
            port,
            int.from_bytes(raw[4:8], "big") & 0xFFFFF,  # the flow label is 20 bits
            int.from_bytes(raw[24:28], "little"),
        )

    @staticmethod
    def _sockaddr_bytes(addr: tuple) -> bytes:
        """The host's address tuple as a sockaddr_in (an IPv4 address) or sockaddr_in6 (an IPv6 one, with the flow
        label and scope id if the tuple has them); ValueError for any other shape."""
        if not isinstance(addr, tuple) or len(addr) not in (2, 4) or not isinstance(addr[0], str):
            raise ValueError(f"not an internet address: {addr!r}")
        port = int(addr[1]).to_bytes(2, "big")
        if len(addr) == 2 and ":" not in addr[0]:
            return b"\2\0" + port + socket.inet_aton(addr[0]) + bytes(8)
        flow, scope = (int(addr[2]), int(addr[3])) if len(addr) == 4 else (0, 0)
        ip = socket.inet_pton(socket.AF_INET6, addr[0].split("%")[0])
        return b"\x0a\0" + port + (flow & 0xFFFFF).to_bytes(4, "big") + ip + (scope & 0xFFFFFFFF).to_bytes(4, "little")

    def _sockaddr_out(self, sa: int, lenp: int, addr: tuple | None) -> None:
        """Write an address to the caller's buffer (sa, *lenp = its size); *lenp becomes the real size (0: none)."""
        if not sa or not lenp:
            return
        try:
            raw = self._sockaddr_bytes(addr) if addr else b""
        except (ValueError, OSError):  # a shape no internet address has (a host that answers oddly): no address
            raw = b""
        cap = int.from_bytes(self._rd(lenp, 4), "little")
        self._wr(sa, raw[:cap])
        self._wr(lenp, len(raw).to_bytes(4, "little"))

    @staticmethod
    def _msg_flags(flags: int) -> int:
        """musl's MSG_* bits -> the host's. DONTWAIT is the adapter's business, NOSIGNAL is moot (no SIGPIPE here)."""
        out = 0
        for bit, name in MSG_FLAGS.items():
            if flags & bit:
                if name == "MSG_DONTWAIT":  # the call is made non-blocking instead (_nonblocking)
                    flags &= ~bit
                    continue
                v = getattr(socket, name, None)
                if v is None and name != "MSG_NOSIGNAL":
                    raise OSError(errno.EOPNOTSUPP, name)
                out |= v or 0
                flags &= ~bit
        if flags:
            raise OSError(errno.EOPNOTSUPP, "flags")
        return out

    def _new_handle(self, s: socket.socket) -> int:
        h = max(self.socks, default=0) + 1
        self.socks[h] = s
        return h

    def _n_socket(self, domain: int, type_: int, proto: int) -> int:
        if domain not in (2, 10):
            return -GUEST_ERRNO["AFNOSUPPORT"]
        if type_ not in (1, 2):
            return -ESOCKTNOSUPPORT
        if proto not in (0, 6 if type_ == 1 else 17):
            return -GUEST_ERRNO["PROTONOSUPPORT"]
        try:
            s = socket.socket(
                socket.AF_INET if domain == 2 else socket.AF_INET6,
                socket.SOCK_STREAM if type_ == 1 else socket.SOCK_DGRAM,
            )
        except OSError as e:
            return self._werr(e)
        return self._new_handle(s)

    def _n_bind(self, h: int, sa: int, n: int) -> int:
        s = self.socks[h]
        try:
            s.bind(self._sockaddr(s, sa, n))
        except OSError as e:
            return self._werr(e)
        return 0

    def _n_listen(self, h: int, backlog: int) -> int:
        try:
            self.socks[h].listen(backlog if backlog >= 0 else socket.SOMAXCONN)
        except OSError as e:
            return self._werr(e)
        return 0

    @staticmethod
    @contextlib.contextmanager
    def _nonblocking(s: socket.socket, on: int):
        """The guest asked for a call that must not wait (a non-blocking socket, MSG_DONTWAIT): the host socket, which
        is blocking otherwise, is not for the length of the call."""
        if on:
            s.setblocking(False)
        try:
            yield
        finally:
            if on:
                s.setblocking(True)

    def _n_accept(self, h: int, sa: int, lenp: int, nb: int) -> int:
        try:
            with self._nonblocking(self.socks[h], nb):
                conn, addr = self.socks[h].accept()
            conn.setblocking(True)
        except OSError as e:
            return self._werr(e)
        self._sockaddr_out(sa, lenp, addr)
        return self._new_handle(conn)

    def _n_connect(self, h: int, sa: int, n: int, nb: int) -> int:
        """A non-blocking socket starts the connection and answers EINPROGRESS; it completes in the background (poll
        for POLLOUT, then SO_ERROR), as in the kernel. The host socket itself stays blocking."""
        s = self.socks[h]
        try:
            addr = self._sockaddr(s, sa, n)
            if nb:
                s.setblocking(False)
                try:
                    err = s.connect_ex(addr)
                finally:
                    s.setblocking(True)
                if err:
                    raise OSError(errno.EINPROGRESS if err == 10035 else err, "connect")  # Windows: WSAEWOULDBLOCK
            else:
                s.connect(addr)
        except OSError as e:
            self.netlog.append(f"socket connect -> {e}")
            return self._werr(e)
        self.netlog.append(f"socket connect {addr[0]}:{addr[1]}")
        return 0

    def _n_sendto(self, h: int, p: int, n: int, flags: int, sa: int, salen: int) -> int:
        s = self.socks[h]
        try:
            hf = self._msg_flags(flags)
            data = self._rd(p, n)
            with self._nonblocking(s, flags & 0x40):  # a partial count, or EAGAIN when nothing fits
                if sa:
                    return s.sendto(data, hf, self._sockaddr(s, sa, salen))
                return s.send(data, hf)
        except OSError as e:
            return self._werr(e)

    @staticmethod
    def _recv(s: socket.socket, n: int, flags: int) -> tuple[bytes, tuple | None, int, int]:
        """-> (data cut to n, source address, the size to return, msg_flags). A datagram is read whole, so that a
        short buffer truncates it (MSG_TRUNC in the flags, and in the result if asked) as the kernel does."""
        hf = Pyodide._msg_flags(flags & ~0x20)  # MSG_TRUNC is applied here
        n = min(n + (1 << 32) if n < 0 else n, 1 << 20)  # a size_t; a stream read may return less than asked
        with Pyodide._nonblocking(s, flags & 0x40):
            if s.type == socket.SOCK_DGRAM:
                data, addr = s.recvfrom(65536, hf)
                return data[:n], addr, (len(data) if flags & 0x20 else min(n, len(data))), 0x20 if len(data) > n else 0
            data, addr = s.recvfrom(n, hf)
        return data, addr, len(data), 0

    def _n_recvfrom(self, h: int, p: int, n: int, flags: int, sa: int, lenp: int) -> int:
        try:
            data, addr, ret, _ = self._recv(self.socks[h], n, flags)
        except OSError as e:
            return self._werr(e)
        self._wr(p, data)
        self._sockaddr_out(sa, lenp, addr)
        return ret

    def _msghdr(self, msg: int) -> tuple[int, int, list[tuple[int, int]], int]:
        """struct msghdr of wasm32 (name, namelen, iov, iovlen, control, controllen, flags) -> name, namelen, the
        iovecs as (base, len), controllen"""
        name, namelen, iov, iovlen, _ctl, ctllen, _fl = struct.unpack("<7I", self._rd(msg, 28))
        if iovlen > 1024:  # IOV_MAX: refused before anything is read
            raise OSError(errno.EMSGSIZE, "iovlen")
        return name, namelen, list(struct.iter_unpack("<II", self._rd(iov, 8 * iovlen))), ctllen

    def _n_sendmsg(self, h: int, msg: int, flags: int) -> int:
        s = self.socks[h]
        try:
            name, namelen, iovs, ctllen = self._msghdr(msg)
            if ctllen:  # SCM_RIGHTS, SCM_CREDENTIALS...: nothing can carry them to the host
                return -EOPNOTSUPP
            hf = self._msg_flags(flags)
            data = b"".join(self._rd(b, n) for b, n in iovs)
            with self._nonblocking(s, flags & 0x40):
                if name:
                    return s.sendto(data, hf, self._sockaddr(s, name, namelen))
                return s.send(data, hf)
        except OSError as e:
            return self._werr(e)

    def _n_recvmsg(self, h: int, msg: int, flags: int) -> int:
        name, _namelen, iovs, _ctllen = self._msghdr(msg)
        try:
            data, addr, ret, mflags = self._recv(self.socks[h], sum(n for _, n in iovs), flags)
        except OSError as e:
            return self._werr(e)
        pos = 0
        for b, n in iovs:  # every buffer, in order
            self._wr(b, data[pos : pos + n])
            pos += n
        if name:
            self._sockaddr_out(name, msg + 4, addr)
        else:
            self._wr(msg + 4, bytes(4))
        self._wr(msg + 20, struct.pack("<II", 0, mflags))  # msg_controllen: no ancillary data; msg_flags
        return ret

    def _poll(self, socks: list, events: list[int], timeout_ms: int) -> list[int]:
        """revents (POLLIN 1, PRI 2, OUT 4, ERR 8, HUP 16, NVAL 32) of the sockets (None: a closed handle)."""
        t = None if timeout_ms < 0 else timeout_ms / 1000
        live = [(i, s) for i, s in enumerate(socks) if s is not None and s.fileno() >= 0]
        out = [32] * len(socks)
        if not hasattr(select, "poll"):  # Windows: select(); an error condition is all its third set can say
            rd, wr, ex = select.select(
                [s for i, s in live if events[i] & 1], [s for i, s in live if events[i] & 4], [s for _, s in live], t
            )
            for i, s in live:
                out[i] = (1 if s in rd else 0) | (4 if s in wr else 0) | (8 if s in ex else 0)
            return out
        masks: dict[int, int] = {}
        for i, s in live:
            ev = events[i]
            masks[s.fileno()] = masks.get(s.fileno(), 0) | (
                (select.POLLIN if ev & 1 else 0) | (select.POLLPRI if ev & 2 else 0) | (select.POLLOUT if ev & 4 else 0)
            )
        p = select.poll()
        for fd, m in masks.items():
            p.register(fd, m)
        got = dict(p.poll(None if t is None else t * 1000))
        for i, s in live:
            r = got.get(s.fileno(), 0)
            g = (
                (1 if r & select.POLLIN else 0)
                | (2 if r & select.POLLPRI else 0)
                | (4 if r & select.POLLOUT else 0)
                | (8 if r & select.POLLERR else 0)
                | (16 if r & select.POLLHUP else 0)
                | (32 if r & select.POLLNVAL else 0)
            )
            out[i] = g & (events[i] | 8 | 16 | 32)
        return out

    def _n_poll(self, h: int, events: int, timeout_ms: int) -> int:
        return self._poll([self.socks.get(h)], [events], timeout_ms)[0]

    def _n_pollv(self, n: int, hp: int, evp: int, timeout_ms: int, revp: int) -> int:
        """Several sockets at once (poll): handles and events are arrays of i32 in the guest's memory, the revents are
        written back. With no sockets it is a sleep. Returns how many are ready."""
        if n == 0:
            if timeout_ms > 0:
                time.sleep(timeout_ms / 1000)
            return 0
        handles = struct.unpack(f"<{n}i", self._rd(hp, 4 * n))
        events = list(struct.unpack(f"<{n}i", self._rd(evp, 4 * n)))
        revents = self._poll([self.socks.get(h) for h in handles], events, timeout_ms)
        self._wr(revp, struct.pack(f"<{n}i", *revents))
        return sum(1 for x in revents if x)

    def _n_close(self, h: int) -> int:
        s = self.socks.pop(h, None)
        if s:
            s.close()
        return 0

    def _n_shutdown(self, h: int, how: int) -> int:
        try:
            self.socks[h].shutdown(how)
        except OSError as e:
            return self._werr(e)
        return 0

    def _n_name(self, h: int, peer: int, sa: int, lenp: int) -> int:
        s = self.socks[h]
        try:
            addr = s.getpeername() if peer else s.getsockname()
        except OSError as e:
            return self._werr(e)
        self._sockaddr_out(sa, lenp, addr)
        return 0

    @staticmethod
    def _option(level: int, opt: int) -> tuple[int | None, int | None]:
        """musl's (level, option) numbers -> the host's, found by the NAME of the constant; None: the host has none."""
        return (
            getattr(socket, SOCK_LEVELS.get(level, ""), None),
            getattr(socket, SOCK_OPTIONS.get((level, opt), ""), None),
        )

    def _n_setopt(self, h: int, level: int, opt: int, valp: int, ln: int) -> int:
        """setsockopt (the import patched into the main module, tools/patch_main.mjs): applied to the host's socket."""
        s = self.socks[h]
        hl, ho = self._option(level, opt)
        if hl is None or ho is None:
            return -GUEST_ERRNO["NOPROTOOPT"]
        if not 0 <= ln <= 1024:
            return -GUEST_ERRNO["INVAL"]
        raw = self._rd(valp, ln)
        if (level, opt) == (1, 2) and os.name != "posix":
            return 0  # SO_REUSEADDR means "steal the port" on Windows: not what a POSIX program asks
        try:
            s.setsockopt(hl, ho, raw)
        except OSError as e:
            return self._werr(e)
        return 0

    def _n_getopt(self, h: int, level: int, opt: int, valp: int, lenp: int) -> int:
        """getsockopt: the option is found by name in the host's socket module; an unknown one is ENOPROTOOPT."""
        s = self.socks[h]
        cap = int.from_bytes(self._rd(lenp, 4), "little")
        if level == 1 and opt in (3, 38, 39):  # SO_TYPE, SO_PROTOCOL, SO_DOMAIN: musl's numbers, not the host's
            stream = s.type == socket.SOCK_STREAM
            val = {
                3: 1 if stream else 2,
                38: s.proto or (6 if stream else 17),
                39: 2 if s.family == socket.AF_INET else 10,
            }
            raw = val[opt].to_bytes(4, "little")
        else:
            hl, ho = self._option(level, opt)
            if hl is None or ho is None:
                return -GUEST_ERRNO["NOPROTOOPT"]
            try:
                raw = s.getsockopt(hl, ho, min(max(cap, 4), 1024))
            except OSError as e:
                return self._werr(e)
            if (level, opt) == (1, 4) and (
                err := int.from_bytes(raw[:4], "little")
            ):  # SO_ERROR: an errno, in the guest's numbers
                raw = (-self._werr(OSError(err, ""))).to_bytes(4, "little")
        self._wr(valp, raw[:cap])
        self._wr(lenp, min(len(raw), cap).to_bytes(4, "little"))
        return 0

    def _n_ioctl(self, h: int, op: int, argp: int) -> int:
        """FIONREAD: the bytes a read would get now (for a datagram socket: the size of the next datagram)."""
        s = self.socks[h]
        try:
            import fcntl
            import termios

            n = int.from_bytes(fcntl.ioctl(s.fileno(), termios.FIONREAD, bytes(4)), "little")
        except ImportError:  # Windows: peek
            s.setblocking(False)
            try:
                n = len(s.recv(65536, socket.MSG_PEEK))
            except BlockingIOError:
                n = 0
            except OSError as e:
                return self._werr(e)
            finally:
                s.setblocking(True)
        except OSError as e:
            return self._werr(e)
        self._wr(argp, n.to_bytes(4, "little"))
        return 0

    def _n_resolve(self, np_: int, n: int, ap: int) -> int:
        name = self._rd(np_, n).decode()
        try:
            ip = socket.gethostbyname(name)
        except OSError:
            return -GUEST_ERRNO["NOENT"]
        self.netlog.append(f"resolve {name} -> {ip}")
        self._wr(ap, socket.inet_aton(ip))
        return 0

    # ------------------------------------------------------------------ libffi's emscripten port: calls and closures
    # What pyodide.asm.mjs does in ffi_call_js / ffi_prep_closure_loc_js, with the type of the function from the wasm
    # table (a JavaScript call tolerates any signature: extra arguments are dropped, missing ones are undefined).
    @staticmethod
    def _down(cur: int, size: int, align: int) -> int:
        """cur - size, aligned down, on the guest's stack: GuestFault if a size from the guest takes it below 0."""
        new = (cur - size) & ~(max(align, 1) - 1)
        if size < 0 or new < 0:
            raise GuestFault(f"{size:#x} bytes do not fit on the stack")
        return new

    def _u32(self, a: int) -> int:
        return struct.unpack("<I", self._rd(a, 4))[0]

    def _unbox(self, t: int) -> tuple[int, int]:
        """A struct of one member is that member (libffi's JS `unbox_small_structs`): (type pointer, type id)."""
        for _depth in range(64):
            tid = struct.unpack("<H", self._rd(t + 6, 2))[0]
            if tid != 13:
                return t, tid
            first, second = struct.unpack("<II", self._rd(self._u32(t + 8), 8))
            if first == 0:
                return t, 0
            if second != 0:
                return t, 13
            t = first
        raise RuntimeError("an ffi_type of structs inside structs, too deep")

    def _table_func(self, idx: int) -> Any:
        f = self.table.get(self.cur[-1], idx)
        if not isinstance(f, self._wt.Func):
            raise TypeError(f"table entry {idx} is null")
        return f

    def _js_call(self, idx: int, args: list) -> Any:
        """`wasmTable.get(idx)(...args)`: args are Numbers (int, float) or BigInts (_Big); the JavaScript result. What a
        table entry is does not change (only a closure's slot does: `_ffi_prep`, `_ffi_free`), so its type is kept."""
        ctx = self.cur[-1]
        known = self.functions.get(idx)
        if known is None:
            f = self._table_func(idx)
            ty = f.type(ctx)
            known = self.functions[idx] = (f, [str(t) for t in ty.params], [str(t) for t in ty.results])
        f, types, results = known
        vals = [_to_wasm(args[k] if k < len(args) else None, t) for k, t in enumerate(types)]
        return _from_wasm(f(ctx, *vals), results)

    def _call_any(self, fn: int, a: int, b: int, c: int) -> int:
        fn &= _U32  # a, b, c are JavaScript Numbers: signed
        """`_PyEM_TrampolineCall_JS` for a table entry whose type the WAT trampoline does not know."""
        return _to_wasm(self._js_call(fn, [a, b, c]), "i32")

    def _ffi_call(self, cif: int, fn: int, rvalue: int, avalue: int) -> None:
        cif, fn, rvalue, avalue = cif & _U32, fn & _U32, rvalue & _U32, avalue & _U32
        ctx = self.cur[-1]
        _abi, nargs, atp, rtp, _bytes, _flags, nfixed = struct.unpack("<7I", self._rd(cif, 28))
        if nargs > 1000:  # a wasm function has at most 1000 parameters
            raise RuntimeError(f"a cif of {nargs} arguments")
        _rp, rid = self._unbox(rtp)
        if rid == 15:
            raise RuntimeError("complex ret marshalling nyi")
        if rid > 15:
            raise RuntimeError(f"Unexpected rtype {rid}")
        sp = self.ex["__stack_pointer"]
        orig = cur = sp.value(ctx)
        args: list = []
        ret_by_arg = rid in (4, 13)
        if ret_by_arg:
            args.append(rvalue)
        aptrs = struct.unpack(f"<{nargs}I", self._rd(avalue, 4 * nargs)) if nargs else ()
        atypes = struct.unpack(f"<{nargs}I", self._rd(atp, 4 * nargs)) if nargs else ()
        for i in range(nfixed):
            ap = aptrs[i]
            tp, tid = self._unbox(atypes[i])
            if tid in (1, 9, 10, 14):
                args.append(self._u32(ap))
            elif tid == 2:
                args.append(struct.unpack("<f", self._rd(ap, 4))[0])
            elif tid == 3:
                args.append(struct.unpack("<d", self._rd(ap, 8))[0])
            elif tid in (5, 6):
                args.append(struct.unpack("<B" if tid == 5 else "<b", self._rd(ap, 1))[0])
            elif tid in (7, 8):
                args.append(struct.unpack("<H" if tid == 7 else "<h", self._rd(ap, 2))[0])
            elif tid in (11, 12):
                args.append(_Big(struct.unpack("<Q", self._rd(ap, 8))[0]))
            elif tid == 4:
                args.extend(_Big(x) for x in struct.unpack("<QQ", self._rd(ap, 16)))
            elif tid == 13:
                size, align = struct.unpack("<IH", self._rd(tp, 6))
                cur = self._down(cur, size, align)
                self._wr(cur, self._rd(ap, size))
                args.append(cur)
            else:
                raise RuntimeError("complex marshalling nyi" if tid == 15 else f"Unexpected type {tid}")
        if nfixed != nargs:  # the variadic part: a block on the stack, its address the last argument
            structs = []
            for i in range(nargs - 1, nfixed - 1, -1):
                ap = aptrs[i]
                tp, tid = self._unbox(atypes[i])
                if tid in (5, 6):
                    cur = self._down(cur, 1, 1)
                    self._wr(cur, self._rd(ap, 1))
                elif tid in (7, 8):
                    cur = self._down(cur, 2, 2)
                    self._wr(cur, self._rd(ap, 2))
                elif tid in (1, 9, 10, 14, 2):
                    cur = self._down(cur, 4, 4)
                    self._wr(cur, self._rd(ap, 4))
                elif tid in (3, 11, 12):
                    cur = self._down(cur, 8, 8)
                    self._wr(cur, self._rd(ap, 8))
                elif tid == 4:
                    cur = self._down(cur, 16, 8)
                    self._wr(cur, self._rd(ap, 16))
                elif tid == 13:
                    cur = self._down(cur, 4, 4)
                    structs.append((cur, ap, *struct.unpack("<IH", self._rd(tp, 6))))
                else:
                    raise RuntimeError("complex arg marshalling nyi" if tid == 15 else f"Unexpected argtype {tid}")
            args.append(cur)
            for target, ap, size, align in structs:
                cur = self._down(cur, size, align)
                self._wr(cur, self._rd(ap, size))
                self._wr(target, struct.pack("<I", cur))
        if cur == orig:  # nothing on the stack: stackRestore(cur) is a no-op
            res = self._js_call(fn, args)
        else:
            sp.set_value(ctx, cur)
            try:
                res = self._js_call(fn, args)
            finally:
                sp.set_value(ctx, orig)
        if ret_by_arg:
            return
        if rid in (1, 9, 10, 14):
            self._wr(rvalue, struct.pack("<I", _num(res, 32)))
        elif rid in (5, 6):
            self._wr(rvalue, struct.pack("<B", _num(res, 8)))
        elif rid in (7, 8):
            self._wr(rvalue, struct.pack("<H", _num(res, 16)))
        elif rid in (2, 3):
            if isinstance(res, _Big):
                raise TypeError("Cannot mix BigInt and other types")
            x = float("nan") if res is None else float(res)
            try:
                self._wr(rvalue, struct.pack("<f" if rid == 2 else "<d", x))
            except OverflowError:  # a float32 too large for it is an infinity
                self._wr(rvalue, struct.pack("<f", float("inf") if x > 0 else float("-inf")))
        elif rid in (11, 12):
            if not isinstance(res, _Big):
                raise TypeError(f"Cannot convert {res} to a BigInt")
            self._wr(rvalue, struct.pack("<Q", res & 0xFFFFFFFFFFFFFFFF))

    def _ffi_slot(self) -> int:
        """getEmptyTableSlot(): a freed slot (the last freed first), else the table grown by one."""
        self.host_state = True
        if self.free_slots:
            return self.free_slots.pop()
        return self.table.grow(self.cur[-1], 1, self._wt.Val.funcref(None))

    def _ffi_free(self, index: int) -> None:
        index &= _U32
        self.functions.pop(index, None)
        self._ffi_release(index)
        self.table.set(self.cur[-1], index, self._wt.Val.funcref(None))
        self.free_slots.append(index)

    def _ffi_prep(self, closure: int, cif: int, fun: int, user_data: int, codeloc: int) -> int:
        """Puts a host function of the closure's signature into table slot `codeloc`; when the guest calls it, the
        arguments are written to the stack as libffi's `avalue` and `fun(cif, ret, args, user_data)` is called."""
        wt = self._wt
        closure, cif, fun, user_data, codeloc = (x & _U32 for x in (closure, cif, fun, user_data, codeloc))
        _abi, nargs, atp, rtp, _bytes, _flags, nfixed = struct.unpack("<7I", self._rd(cif, 28))
        if nargs > 1000:  # a wasm function has at most 1000 parameters
            raise RuntimeError(f"a cif of {nargs} arguments")
        _rp, rid = self._unbox(rtp)
        i32, i64, f32, f64 = (getattr(wt.ValType, n)() for n in ("i32", "i64", "f32", "f64"))
        if rid == 15:
            raise RuntimeError("complex ret marshalling nyi")
        ret_by_arg = rid in (4, 13)
        if ret_by_arg:
            params, results, rk = [i32], [], "v"
        elif rid == 0:
            params, results, rk = [], [], "v"
        elif rid in (1, 5, 6, 7, 8, 9, 10, 14):
            params, results, rk = [], [i32], "i"
        elif rid == 2:
            params, results, rk = [], [f32], "f"
        elif rid == 3:
            params, results, rk = [], [f64], "d"
        elif rid in (11, 12):
            params, results, rk = [], [i64], "j"
        else:
            raise RuntimeError(f"Unexpected rtype {rid}")
        atypes = struct.unpack(f"<{nargs}I", self._rd(atp, 4 * nargs)) if nargs else ()
        info = []  # (type id, size, alignment) of each argument
        for t in atypes:
            tp, tid = self._unbox(t)
            size, align = struct.unpack("<IH", self._rd(tp, 6))
            info.append((tid, size, align))
        for tid, _s, _a in info[:nfixed]:
            if tid in (1, 5, 6, 7, 8, 9, 10, 14, 13):
                params.append(i32)
            elif tid == 2:
                params.append(f32)
            elif tid == 3:
                params.append(f64)
            elif tid == 4:
                params += [i64, i64]
            elif tid in (11, 12):
                params.append(i64)
            else:
                raise RuntimeError("complex marshalling nyi" if tid == 15 else f"Unexpected argtype {tid}")
        if nfixed < nargs:
            params.append(i32)

        # A wasmtime Func is never freed before its store, so closures reuse them: one per signature and per live
        # closure, with the closure's own data in a list that the Func's callback reads when it is called.
        key = (tuple(str(t) for t in params), tuple(str(t) for t in results))
        self._ffi_release(codeloc)
        pool = self.func_pool.setdefault(key, [])
        if pool:
            func, state = pool.pop()
        else:
            state = []

            def trampoline(caller: Any, *a: Any) -> Any:
                self.cur.append(caller)
                try:
                    return self._ffi_closure(state, a)
                finally:
                    self.cur.pop()

            try:
                func = wt.Func(self.store, wt.FuncType(params, results), trampoline, access_caller=True)
            except Exception:  # JavaScript: convertJsFunctionToWasm failed
                return 1
        state[:] = [closure, nargs, nfixed, info, ret_by_arg, rk]
        self.functions.pop(codeloc, None)
        self.table.set(self.cur[-1], codeloc, func)
        self.live_funcs[codeloc] = (key, func, state)
        self._wr(closure + 4, struct.pack("<III", cif, fun, user_data))
        return 0

    def _ffi_release(self, index: int) -> None:
        """The Func of the closure in table slot `index` goes back to the pool of its signature."""
        held = self.live_funcs.pop(index, None)
        if held:
            key, func, state = held
            state.clear()
            self.func_pool[key].append((func, state))

    def _ffi_closure(self, state: list, a: tuple) -> Any:
        closure, nargs, nfixed, info, ret_by_arg, rk = state
        ctx = self.cur[-1]
        sp = self.ex["__stack_pointer"]
        orig = cur = sp.value(ctx)
        _index, cif, fun, user_data = struct.unpack("<IIII", self._rd(closure, 16))
        j = 0
        if ret_by_arg:
            ret_ptr = a[0] & 0xFFFFFFFF
            j = 1
        else:
            cur = self._down(cur, 8, 8)
            ret_ptr = cur
        cur = self._down(cur, 4 * nargs, 1)
        args_ptr = cur
        slots: dict[int, int] = {}

        def put(c: int, size: int, align: int, data: bytes) -> None:
            nonlocal cur
            cur = self._down(cur, size, align)
            slots[c] = cur
            self._wr(cur, data)

        for c in range(nfixed):
            v = a[j]
            j += 1
            tid, size, align = info[c]
            if tid in (5, 6):
                put(c, 1, 4, struct.pack("<B", v & 0xFF))
            elif tid in (7, 8):
                put(c, 2, 4, struct.pack("<H", v & 0xFFFF))
            elif tid in (1, 9, 10, 14):
                put(c, 4, 4, struct.pack("<I", v & 0xFFFFFFFF))
            elif tid == 13:
                put(c, size, align, self._rd(v & 0xFFFFFFFF, size))
            elif tid == 2:
                put(c, 4, 4, struct.pack("<f", v))
            elif tid == 3:
                put(c, 8, 8, struct.pack("<d", v))
            elif tid in (11, 12):
                put(c, 8, 8, struct.pack("<Q", v & 0xFFFFFFFFFFFFFFFF))
            elif tid == 4:
                put(c, 16, 8, struct.pack("<QQ", v & 0xFFFFFFFFFFFFFFFF, a[j] & 0xFFFFFFFFFFFFFFFF))
                j += 1
        varargs = a[-1] & 0xFFFFFFFF if nfixed < nargs else 0
        for c in range(nfixed, nargs):
            tid, size, align = info[c]
            if tid == 13:
                put(c, size, align, self._rd(self._u32(varargs), size))
            else:
                slots[c] = varargs
            varargs += 4
        if nargs:
            self._wr(args_ptr, struct.pack(f"<{nargs}I", *(slots[c] for c in range(nargs))))
        sp.set_value(ctx, cur)
        try:
            self._table_func(fun)(ctx, *(_to_wasm(x, "i32") for x in (cif, ret_ptr, args_ptr, user_data)))
        finally:
            sp.set_value(ctx, orig)
        if rk == "v":
            return None
        raw = self._rd(ret_ptr, 8)
        if rk == "i":
            return _to_wasm(struct.unpack("<I", raw[:4])[0], "i32")
        if rk == "j":
            return _to_wasm(_Big(struct.unpack("<Q", raw)[0]), "i64")
        if rk == "d":
            return struct.unpack("<d", raw)[0]
        if rk == "f":
            return struct.unpack("<f", raw[:4])[0]
        return None

    # ------------------------------------------------------------------ local time: Emscripten's JS date helpers
    # `_localtime_js`, `_mktime_js` and `_tzset_js` read the time zone of the process through `Date` (the host's: its
    # TZ and zoneinfo). Here the host's C library answers the offset at an instant (`time.localtime`), and the rest is
    # what the JavaScript does with it: its rules for a local time that does not exist or happens twice, its errors
    # beyond +-8.64e12 s, its habit of reading a year 0..99 as 19xx in `new Date(year, ...)`, and offsets in whole
    # minutes (getTimezoneOffset cuts a seconds part of an old local mean time; the fields of the date keep it).
    @staticmethod
    def _gmtoff(t: int) -> int:
        """Seconds east of UTC at the instant t."""
        try:
            return time.localtime(t).tm_gmtoff or 0
        except (OverflowError, OSError, ValueError):  # a C library with a narrow time_t (Windows): the nearest it has
            return time.localtime(min(max(t, 0), 32535215999)).tm_gmtoff or 0

    def _minutes(self, t: int) -> int:
        """-Date.getTimezoneOffset() at the instant t: minutes east, cut towards zero."""
        return int(self._gmtoff(t) / 60)

    def _utc_from_local(self, lt: int) -> int:
        """The instant of a wall-clock time (seconds): of two (it happens twice) the earlier, of none (it is skipped)
        the one with the offset from before the change; as ECMAScript's UTC(t)."""
        before, after = self._gmtoff(lt - 86400), self._gmtoff(lt + 86400)
        found = [u for u in {lt - before, lt - after} if self._gmtoff(u) == lt - u]
        return min(found) if found else lt - before

    def _year_minutes(self, year: int) -> tuple[int, int]:
        """The offsets (minutes east) of `new Date(year, 0, 1)` and `new Date(year, 6, 1)`."""
        out = []
        for mon in (0, 6):
            lt = _js_make(year, mon, 1, 0, 0, 0)
            out.append(0 if lt is None else self._minutes(self._utc_from_local(lt)))
        return out[0], out[1]

    def _t_localtime(self, t: int, tm: int) -> int:
        tm &= _U32
        """tm_isdst and tm_gmtoff into the struct; the exact offset (s east) for the fields, or INT_MIN: an error."""
        if abs(t) > _DATE_LIMIT:
            return -(1 << 31)
        off = self._gmtoff(t)
        winter, summer = self._year_minutes(_civil_from_days((t + off) // 86400)[0])
        minutes = int(off / 60)
        # the offset of the summer (the larger one) is DST when the year has two
        self._wr(tm + 32, struct.pack("<ii", int(summer != winter and minutes == max(winter, summer)), minutes * 60))
        return off

    def _t_mktime(self, tm: int) -> int:
        tm &= _U32
        sec, mi, hour, mday, mon, year, _wday, _yday, dst = struct.unpack("<9i", self._rd(tm, 36))
        lt = _js_make(year + 1900, mon, mday, hour, mi, sec)
        if lt is None:
            return -1
        u = self._utc_from_local(lt)
        if abs(u) > _DATE_LIMIT:
            return -1
        guessed = self._minutes(u)
        winter, summer = self._year_minutes(_civil_from_days((u + self._gmtoff(u)) // 86400)[0])
        dst_off, std_off = max(winter, summer), min(winter, summer)
        if dst < 0:
            dst = int(summer != winter and dst_off == guessed)
        elif (dst > 0) != (dst_off == guessed):
            u += (guessed - (dst_off if dst > 0 else std_off)) * 60
            if abs(u) > _DATE_LIMIT:
                return -1
        days, secs = divmod(u + self._gmtoff(u), 86400)
        y, m, d = _civil_from_days(days)
        yday = days - _days_from_civil(y, 1, 1)
        fields = (secs % 60, secs // 60 % 60, secs // 3600, d, m - 1, y - 1900, (days + 4) % 7, yday)
        self._wr(tm, struct.pack("<8i", *fields) + struct.pack("<i", dst))
        return u

    def _t_tzset(self, timezone: int, daylight: int, std_name: int, dst_name: int) -> None:
        timezone, daylight, std_name, dst_name = (x & _U32 for x in (timezone, daylight, std_name, dst_name))
        winter, summer = self._year_minutes(time.localtime().tm_year)

        def zone(east: int) -> bytes:  # UTC-0200 for two hours east: the sign is of the offset as Date gives it (west)
            return f"UTC{'-' if east <= 0 else '+'}{abs(east) // 60:02d}{abs(east) % 60:02d}".encode()[:16] + b"\0"

        self._wr(timezone, struct.pack("<I", (-min(winter, summer) * 60) & 0xFFFFFFFF))
        self._wr(daylight, struct.pack("<i", int(winter != summer)))
        std, dst = (winter, summer) if summer > winter else (summer, winter)  # JS: summerOffset < winterOffset (west)
        self._wr(std_name, zone(std))
        self._wr(dst_name, zone(dst))

    # ------------------------------------------------------------------ signals and the runtime's name
    def _sigcell(self) -> int:
        """The word that `_Py_CheckEmscriptenSignals_Helper` reads (JavaScript's Py_EmscriptenSignalBuffer)."""
        self.host_state = True
        if not self._cell:
            self._cell = self.ex["malloc"](self.cur[-1], 4)
            self._wr(self._cell, struct.pack("<I", self._pending))
            self._pending = 0
        return self._cell

    def interrupt(self, signum: int = 2) -> None:
        """Post signal `signum` (SIGINT: KeyboardInterrupt) to the guest's Python, as JavaScript's
        ``Py_EmscriptenSignalBuffer[0] = 2`` does. Python takes it when it checks for signals: between bytecodes of the
        running code, within a few dozen of them, not while it waits in a system call. Call it from a host function
        that the guest is calling (a host callback, an ``fd_read`` hook, a socket operation) or between ``run()``
        calls; the guest's memory is written, which is not safe from another thread while the guest runs."""
        if not self._started:
            raise RuntimeError("the guest is not running")
        self.host_state = True
        flag = self.instances[0]["exports"][
            "Py_EMSCRIPTEN_SIGNAL_HANDLING"
        ]  # a byte: Python looks for signals if it is 1
        self._wr(flag.value(self.cur[-1]), b"\x01")
        if self._cell:
            self._wr(self._cell, struct.pack("<I", signum))
        else:
            self._pending = signum

    def _runtime_name(self) -> int:
        """`sys._emscripten_info.runtime`: a string from the guest's malloc, as stringToNewUTF8 gives."""
        try:
            wv = importlib.metadata.version("wasmtime")
        except importlib.metadata.PackageNotFoundError:
            wv = "unknown"
        from . import __version__

        b = f"wasmtime-py {wv} (pyodide-wasmtime {__version__})".encode() + b"\0"
        p = self.ex["malloc"](self.cur[-1], len(b))
        self._wr(p, b)
        return p

    # ------------------------------------------------------------------ the host's view of the files
    def _preopen_dir(self, pfd: int) -> str | None:
        """The host folder of a preopen, named by its WASI descriptor (3 + its place in the order they are opened here:
        the guest's root, the mounts, /dev). The guest never gives the host a path: the adapter has proved that the
        guest's path exists through WASI and names only the preopen it belongs to."""
        assert self.root is not None
        dirs = [str(self.root), *self.mounts.values()]
        if self.preopen_dev:
            dirs.append("/dev")
        return dirs[pfd - 3] if 3 <= pfd < 3 + len(dirs) else None

    def _fs_statvfs(self, pfd: int, buf: int) -> int:
        """statfs of a preopen's folder -> Emscripten's struct statfs64 (88 bytes) at ``buf``; -errno on failure.
        Without os.statvfs (Windows) the numbers come from shutil.disk_usage: the files and ffree counts are 0."""
        try:
            host = self._preopen_dir(pfd)
            if host is None:
                return -WASI_ERRNO["BADF"]
            b = bytearray(88)
            if hasattr(os, "statvfs"):
                st = os.statvfs(host)
                struct.pack_into("<I", b, 4, st.f_bsize)
                struct.pack_into("<5Q", b, 8, st.f_blocks, st.f_bfree, st.f_bavail, st.f_files, st.f_ffree)
                struct.pack_into("<III", b, 56, st.f_namemax, st.f_frsize, st.f_flag)
            else:
                du = shutil.disk_usage(host)
                struct.pack_into("<I", b, 4, 4096)
                struct.pack_into("<5Q", b, 8, du.total // 4096, du.free // 4096, du.free // 4096, 0, 0)
                struct.pack_into("<III", b, 56, 255, 4096, 0)
            self._wr(buf, bytes(b))
            return 0
        except OSError as e:
            return self._werr(e)
        except Exception:  # never a trap in the guest
            return -WASI_ERRNO["IO"]

    def _malloc(self, n: int) -> int:
        """The guest's malloc: its address as an unsigned number (0: no memory)."""
        return self.ex["malloc"](self.cur[-1], n) & 0xFFFFFFFF

    def _n_getaddrinfo(self, node_p: int, service_p: int, hint_p: int, out_p: int) -> int:
        """getaddrinfo: Pyodide's JavaScript validates the input (EAI codes; the defaults stream/6, dgram/17), the
        host's resolver answers, and ALL its addresses are returned as one malloc'd block that freeaddrinfo (it frees
        the first node and its ai_addr only) releases whole."""
        node, service = self._cstr(node_p), self._cstr(service_p)
        flags = family = type_ = proto = 0
        if hint_p:
            flags, family, type_, proto = struct.unpack("<4i", self._rd(hint_p, 16))
        if type_ and not proto:
            proto = 17 if type_ == 2 else 6
        if not type_ and proto:
            type_ = 2 if proto == 17 else 1
        proto = proto or 6
        type_ = type_ or 1
        if node is None and service is None:
            return -2
        if flags & ~(1 | 2 | 4 | 8 | 16 | 32 | 1024):
            return -1
        if flags & 2 and node is None:
            return -1
        if type_ not in (1, 2):
            return -7
        if family not in (0, 2, 10):
            return -6
        port = 0
        if service is not None:
            m = re.match(r"\s*[+-]?\d+", service)  # parseInt(service, 10)
            proto_name = "tcp" if type_ == 1 else "udp"
            if m:
                port = int(m.group()) & 0xFFFF
            elif flags & 1024:
                return -2
            else:
                try:
                    port = socket.getservbyname(service, proto_name)
                except OSError:
                    port = SERVICES.get((service, proto_name), 0)
                    if not port:
                        return -8
        hflags = 0
        for bit, name in AI_FLAGS.items():
            if flags & bit:
                hflags |= getattr(socket, name, 0)
        try:
            found = socket.getaddrinfo(
                node,
                port,
                {0: socket.AF_UNSPEC, 2: socket.AF_INET, 10: socket.AF_INET6}[family],
                socket.SOCK_STREAM if type_ == 1 else socket.SOCK_DGRAM,
                0,
                hflags,
            )
        except socket.gaierror as e:
            return EAI_CODES.get(e.args[0], -4)
        except UnicodeError:
            return -2
        entries = [(2 if f == socket.AF_INET else 10, c, self._sockaddr_bytes(a)) for f, _t, _p, c, a in found]
        if not entries:
            return -2
        canon = ((entries[0][1] or node or "").encode() + b"\0") if flags & 2 else b""
        c = self.cur[-1]
        block = self._malloc(32 * len(entries) + len(canon) + sum(len(sa) for _f, _c, sa in entries[1:]))
        head_sa = self._malloc(len(entries[0][2]))
        if not block or not head_sa:
            for q in (block, head_sa):
                if q:
                    self.ex["free"](c, q)
            return -10  # EAI_MEMORY
        at = block + 32 * len(entries)
        self._wr(at, canon)
        canon_p, at = (at if canon else 0), at + len(canon)
        for k, (fam, _c, sa) in enumerate(entries):
            sa_p = head_sa if k == 0 else at
            at += 0 if k == 0 else len(sa)
            self._wr(sa_p, sa)
            nxt = block + 32 * (k + 1) if k + 1 < len(entries) else 0
            ai = struct.pack("<8I", 0, fam, type_, proto, len(sa), sa_p, canon_p if k == 0 else 0, nxt)
            self._wr(block + 32 * k, ai)
        self._wr(out_p, block.to_bytes(4, "little"))
        return 0

    def _n_getnameinfo(self, sa: int, salen: int, node: int, nodelen: int, serv: int, servlen: int, flags: int) -> int:
        raw = self._rd(sa, min(salen, 28)) if sa and salen >= 2 else b""
        need = {2: 16, 10: 28}.get(int.from_bytes(raw[:2], "little"))
        if need is None or len(raw) < need:
            return -6  # EAI_FAMILY
        hflags = 0
        for bit, name in NI_FLAGS.items():
            if flags & bit:
                hflags |= getattr(socket, name, 0)
        try:
            host, service = socket.getnameinfo(self._sockaddr_tuple(raw), hflags)
        except socket.gaierror as e:
            return EAI_CODES.get(e.args[0], -4)
        except OSError:
            return -4
        for ptr, cap, text in ((node, nodelen, host), (serv, servlen, service)):
            if ptr and cap:
                b = text.encode()
                if len(b) >= cap:
                    return -12  # EAI_OVERFLOW
                self._wr(ptr, b + b"\0")
        return 0

    def _n_protobyname(self, name_p: int) -> int:
        """getprotobyname: a struct protoent {name, aliases, proto} from the host's protocols table (tcp and udp
        even where the host has none), built once per name and kept, as Pyodide keeps its two. 0: unknown."""
        name = self._cstr(name_p) or ""
        if name not in self.protoents:
            try:
                num = socket.getprotobyname(name)
            except OSError:
                num = {"tcp": 6, "udp": 17}.get(name, -1)
            if num < 0:
                return 0
            b = name.encode() + b"\0"
            p = self._malloc(16 + len(b))
            if not p:
                return 0
            self._wr(p, struct.pack("<4I", p + 16, p + 12, num, 0) + b)  # aliases: [NULL]
            self.protoents[name] = p
        return self.protoents[name]

    # what a net operation answers when the guest gave it a pointer outside its memory, or the host failed in a way
    # nobody foresaw: -EFAULT and -EIO, but the name functions answer in EAI_* (or a NULL pointer)
    NET_FAILS = {"getaddrinfo": (-11, -4), "getnameinfo": (-11, -4), "protobyname": (0, 0)}

    def _wrap_net(self, name: str, fn):
        """No exception of a net operation reaches the wasm (it would be a trap that ends the interpreter): a pointer
        outside the memory is EFAULT, a host error is its errno, anything else is logged and EIO."""
        fault, other = self.NET_FAILS.get(name, (-GUEST_ERRNO["FAULT"], -GUEST_ERRNO["IO"]))

        def f(caller, *args):
            self.cur.append(caller)
            try:
                return fn(*args)
            except GuestFault:
                return fault
            except OSError as e:
                return other if name in self.NET_FAILS else self._werr(e)
            except Exception:
                log.exception("[net] %s failed", name)
                return other
            finally:
                self.cur.pop()

        return f

    # The operations that call into the guest (a ctypes call, a callback, the trampoline) or fail on purpose as
    # JavaScript throws: their exceptions (a callee's trap, exit(), a TypeError) reach run(), which ends the guest.
    RAISING = frozenset(
        (
            "ffi_call",
            "ffi_prep",
            "ffi_slot",
            "ffi_free",
            "call_any",
            "localtime",
            "mktime",
            "tzset",
            "sigcell",
            "runtime",
        )
    )

    def _wrap(self, fn, nres: int, fail: int | None = 0):
        """A loader operation: no exception reaches the wasm (it would be a trap that ends the interpreter); a pointer
        outside the memory or an unforeseen host error is logged and answered with `fail` (0; -1 for instantiate).
        `fail=None`: the exception goes on."""

        def f(caller, *args):
            self.cur.append(caller)
            try:
                r = fn(*args)
            except Exception:
                if fail is None:
                    raise
                log.exception("[loader] %s failed", fn.__name__)
                r = fail
            finally:
                self.cur.pop()
            return r if nres else None

        return f

    def _ops(self) -> tuple[dict, dict, dict]:
        wt = self._wt
        i32 = wt.ValType.i32()

        def ft(n, r=1):
            return wt.FuncType([i32] * n, [i32] * r)

        loader = {
            "instantiate": (self._dl_instantiate, ft(5)),
            "scope": (self._dl_scope, ft(2, 0)),
            "got_set": (self._dl_got_set, ft(3, 0)),
            "sym": (self._dl_sym, ft(4)),
            "call": (self._dl_call, ft(3)),
            "ffi_call": (self._ffi_call, ft(4, 0)),
            "ffi_prep": (self._ffi_prep, ft(5)),
            "ffi_slot": (self._ffi_slot, ft(0)),
            "ffi_free": (self._ffi_free, ft(1, 0)),
            "call_any": (self._call_any, ft(4)),
            "localtime": (self._t_localtime, wt.FuncType([wt.ValType.i64(), i32], [i32])),
            "mktime": (self._t_mktime, wt.FuncType([i32], [wt.ValType.i64()])),
            "tzset": (self._t_tzset, ft(4, 0)),
            "sigcell": (self._sigcell, ft(0)),
            "runtime": (self._runtime_name, ft(0)),
            "error": (self._dl_error, ft(5, 0)),
        }
        net = {
            "socket": (self._n_socket, ft(3)),
            "bind": (self._n_bind, ft(3)),
            "listen": (self._n_listen, ft(2)),
            "accept": (self._n_accept, ft(4)),
            "connect": (self._n_connect, ft(4)),
            "sendto": (self._n_sendto, ft(6)),
            "recvfrom": (self._n_recvfrom, ft(6)),
            "sendmsg": (self._n_sendmsg, ft(3)),
            "recvmsg": (self._n_recvmsg, ft(3)),
            "poll": (self._n_poll, ft(3)),
            "pollv": (self._n_pollv, ft(5)),
            "close": (self._n_close, ft(1)),
            "shutdown": (self._n_shutdown, ft(2)),
            "name": (self._n_name, ft(4)),
            "getopt": (self._n_getopt, ft(5)),
            "setopt": (self._n_setopt, ft(5)),
            "ioctl": (self._n_ioctl, ft(3)),
            "resolve": (self._n_resolve, ft(3)),
            "getaddrinfo": (self._n_getaddrinfo, ft(4)),
            "getnameinfo": (self._n_getnameinfo, ft(7)),
            "protobyname": (self._n_protobyname, ft(1)),
        }
        fs = {"statvfs": (self._fs_statvfs, ft(2))}
        return loader, net, fs

    # ------------------------------------------------------------------ start
    def _start(self) -> None:
        wt = self._wt
        engine = _engine.engine()
        self._setup_root()
        assert self.root is not None
        self.store = store = wt.Store(engine)
        wasi = wt.WasiConfig()
        wasi.env = self._wasi_env()
        wasi.preopen_dir(str(self.root), "/")
        for guest, host in self.mounts.items():
            wasi.preopen_dir(host, guest)
        if self.preopen_dev:  # the entropy device OpenSSL reads (/dev/urandom)
            wasi.preopen_dir("/dev", "/dev")
        wasi.inherit_stdin()
        wasi.inherit_stdout()
        wasi.inherit_stderr()
        store.set_wasi(wasi)
        loader_ops, net_ops, fs_ops = self._ops()
        I32 = wt.ValType.i32()  # noqa: N806

        def define_ops(linker):
            for name, (fn, ty) in loader_ops.items():
                linker.define_func(
                    "loader",
                    name,
                    ty,
                    self._wrap(
                        fn, len(ty.results), None if name in self.RAISING else -1 if name == "instantiate" else 0
                    ),
                    access_caller=True,
                )
            for name, (fn, ty) in net_ops.items():
                linker.define_func("net", name, ty, self._wrap_net(name, fn), access_caller=True)
            for name, (fn, ty) in fs_ops.items():
                linker.define_func("fs", name, ty, self._wrap_net(name, fn), access_caller=True)

        if self.flavor == "fused":
            main_mod = _engine.load_module(self.data / "pyodide_fused.wasm")
            linker = wt.Linker(engine)
            linker.define_wasi()
            define_ops(linker)
            self.ex = _engine.LazyExports(store, linker.instantiate(store, main_mod), main_mod)
            self.memory, self.table = self.ex["memory"], self.ex["__indirect_function_table"]
            self.instances[0] = {"exports": MainExports(self.ex), "got": []}
            self._drop_stubs()
            mods: dict[str, int] = {}
            for i in main_mod.imports:
                mods[i.module] = mods.get(i.module, 0) + 1
            self.summary = "fused: one module; its imports: " + ", ".join(f"{k} ({v})" for k, v in mods.items())
        else:
            main_path = self.data / "pyodide.asm.wasm"
            adapter_bytes = (self.data / "adapter.wasm").read_bytes()
            _wasm.check_sections(adapter_bytes)
            adapter_mod = _engine.load_module(self.data / "adapter.wasm")
            allowed = {
                "memory",
                "__indirect_function_table",
                "__stack_pointer",
                "__memory_base",
                "__table_base",
                "malloc",
                "calloc",
                "free",
                "emscripten_builtin_memalign",
                "_emscripten_find_dylib",
            }
            for i in adapter_mod.imports:
                assert i.module in ("wasi_snapshot_preview1", "loader", "aux", "net", "fs") or (
                    i.module == "env" and i.name in allowed
                ), (i.module, i.name)
            adapter_names = [
                e.name
                for e in adapter_mod.exports
                if isinstance(e.type, wt.FuncType) and not e.name.startswith("__wasm")
            ]
            fwd = {n: k for k, n in enumerate([*adapter_names, _wasm.TRAMP])}
            main_mod = _engine.load_module(main_path)
            imports = _wasm.func_imports(main_mod)
            got = [i.name for i in main_mod.imports if i.module == "GOT.func"]
            shim_mod = wt.Module(engine, wt.wat2wasm(_wasm.shim_wat(imports, fwd, got)))
            shim = wt.Linker(engine).instantiate(store, shim_mod).exports(store)

            linker = wt.Linker(engine)
            linker.define_wasi()
            linker.allow_shadowing = True
            for n in _wasm.WASI_ROUTED:
                if n in fwd:
                    linker.define(store, "wasi_snapshot_preview1", n, shim["wasi:" + n])
            n_env = {"adapter": 0, "stub": 0}
            for m, n, _ps, _rs in imports:
                if m == "env":
                    linker.define(store, m, n, shim[n])
                    n_env["adapter" if n in fwd else "stub"] += 1
            for g in got:
                linker.define(store, "GOT.func", g, shim["got:" + g])
            self.ex = _engine.LazyExports(store, linker.instantiate(store, main_mod), main_mod)
            self.memory, self.table = self.ex["memory"], self.ex["__indirect_function_table"]
            self.instances[0] = {"exports": MainExports(self.ex), "got": []}

            tl = wt.Linker(engine)
            tl.define(store, "env", "__indirect_function_table", self.table)
            define_ops(tl)  # the trampoline's fallback for a type it does not know is a host operation
            tramp = tl.instantiate(store, wt.Module(engine, wt.wat2wasm(_wasm.TRAMP_WAT))).exports(store)

            al = wt.Linker(engine)
            al.define_wasi()
            al.define(store, "env", "memory", self.memory)
            al.define(store, "env", "__indirect_function_table", self.table)
            al.define(store, "env", "__stack_pointer", self.ex["__stack_pointer"])
            al.define(store, "env", "__memory_base", wt.Global(store, wt.GlobalType(I32, False), wt.Val.i32(0)))
            al.define(store, "env", "__table_base", wt.Global(store, wt.GlobalType(I32, False), wt.Val.i32(0)))
            for f in ("malloc", "calloc", "free", "emscripten_builtin_memalign", "_emscripten_find_dylib"):
                al.define(store, "env", f, self.ex[f])
            al.define(store, "aux", "table_grow", tramp["table_grow"])
            define_ops(al)
            adapter = al.instantiate(store, adapter_mod).exports(store)
            # what the fused module exports: the main module's symbols and the adapter's (dlsym(NULL), the GOT)
            self.instances[0]["exports"].extra.update({n: adapter[n] for n in adapter_names})
            self.instances[0]["exports"].extra[_wasm.TRAMP] = tramp[_wasm.TRAMP]
            table = shim["table"]  # fixup
            for n, k in fwd.items():
                table.set(store, k, wt.Val.funcref(tramp[n] if n == _wasm.TRAMP else adapter[n]))
            self.summary = (
                f"dynamic: env imports: {n_env['adapter']} answered by the adapter, {n_env['stub']} stubs in the "
                f"shim; {len(got)} GOT.func globals in the shim"
            )

        # networking: the host's fetch and the main module's free in table slots, named to the guest in a file
        f_fetch = wt.Func(store, wt.FuncType([I32] * 5, [I32]), self._wrap(self._net_fetch, 1), access_caller=True)
        slots = (
            self.table.grow(store, 1, wt.Val.funcref(f_fetch)),
            self.table.grow(store, 1, wt.Val.funcref(self.ex["free"])),
        )
        sp = self.root / "lib" / f"python{PYVER}" / "site-packages"
        (sp / "_hostnet_slots.py").write_text(f"FETCH = {slots[0]}\nFREE = {slots[1]}\n")
        log.info("[host] %s; WASI: wasmtime's own; the host's loader ops: %s", self.summary, ", ".join(loader_ops))
        self.cur.append(store)
        self._boot(slots)

    def _wasi_env(self) -> list[tuple[str, str]]:
        return [
            *BASE_ENV,
            ("SSL_CERT_FILE", "/etc/ssl/cert.pem"),
            ("REQUESTS_CA_BUNDLE", "/etc/ssl/cert.pem"),
        ] + list(self.env.items())

    # ------------------------------------------------------------------ snapshot of the memory after `preload`
    def _snapshot_path(self) -> Path:
        files = [
            "python_stdlib.zip",
            *(["pyodide_fused.wasm"] if self.flavor == "fused" else ["pyodide.asm.wasm", "adapter.wasm"]),
        ]

        def isatty(fd: int) -> bool:  # WASI inherits the OS's fds, not Python's sys.std* objects
            try:
                return os.isatty(fd)
            except (OSError, ValueError):
                return False

        key = hashlib.sha256(
            json.dumps(
                [
                    SNAPSHOT_VERSION,
                    self.flavor,
                    [_engine._stamp((self.data / f).resolve()).decode() for f in files],
                    PYVER,
                    self.preload,
                    hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    hashlib.sha256(Path(__file__).with_name("guest").joinpath("hostnet.py").read_bytes()).hexdigest(),
                    self._wasi_env(),
                    self.preopen_dev,
                    [isatty(fd) for fd in (0, 1, 2)],  # the guest decides buffering at init
                    # the time module read the host's zone at init (tzname, timezone, daylight, as _tzset_js gives them)
                    [time.localtime().tm_year, *self._year_minutes(time.localtime().tm_year)],
                ]
            ).encode()
        ).hexdigest()
        return _engine.cache_dir() / f"snapshot-{self.flavor}-{key[:16]}.mem"

    def _boot(self, slots: tuple[int, int]) -> None:
        """Start CPython (or restore a snapshot of it after the preload) and run the preload."""
        store = self.store
        self._net_slots = slots
        self.restored = False
        path = None
        # with site= or mounts= the preload may need them, and the snapshot is taken without: no snapshot then
        if (
            self.preload is not None
            and not self.site
            and not self.mounts
            and os.environ.get("PYODIDE_WASMTIME_SNAPSHOT") != "0"
        ):
            path = self._snapshot_path()
            if self._restore(path, slots):
                self.restored = self._started = True
                # the hash seed and `random`'s state are the snapshot's: a fresh seed, as a normal start has
                self.run('import sys; "random" in sys.modules and __import__("random").seed()')
                return
        self.ex["emscripten_stack_init"](store)
        self.ex["__wasm_call_ctors"](store)
        self.ex["Py_Initialize"](store)
        self._started = True
        if self.preload is not None and self.run(self.preload) == 0 and path is not None:
            self._save(path)

    def _restore(self, path: Path, slots: tuple[int, int]) -> bool:
        store = self.store
        try:
            data = path.read_bytes()
            nl = data.index(b"\n")
            hdr = json.loads(data[:nl])
            pages = hdr["pages"]
            have = self.memory.size(store)
            if (
                hdr["version"] != SNAPSHOT_VERSION
                or hdr["slots"] != list(slots)
                or pages < have
                or len(data) - nl - 1 != pages * 65536
            ):
                return False
        except (OSError, ValueError, KeyError, TypeError):
            return False
        # all of the file is checked: from here on the memory is written once
        self.ex["emscripten_stack_init"](store)
        if pages > have:
            self.memory.grow(store, pages - have)
        src = ctypes.cast(ctypes.c_char_p(data), ctypes.c_void_p).value
        assert src is not None
        ctypes.memmove(ctypes.addressof(self.memory.data_ptr(store).contents), src + nl + 1, pages * 65536)
        if hdr["table"] > self.table.size(store):
            self.table.grow(store, hdr["table"] - self.table.size(store), self._wt.Val.funcref(None))
        return True

    _PROBE = (
        "def _p():\n    import os\n    r = []\n    for i in range(64):\n        try: os.fstat(i); r.append(i)\n"
        "        except OSError: pass\n    open('/_probe', 'w').write(repr((r, os.getcwd())))\n_p(); del _p\n"
    )

    def _probe(self) -> tuple[str, list[tuple[str, int]]]:
        """What a snapshot does not hold: the guest's open fds and cwd, and the files under its root."""
        self.run(self._PROBE)
        assert self.root is not None
        state = (self.root / "_probe").read_text()
        files = [
            (str(p.relative_to(self.root)), p.stat().st_size)
            for p in sorted(self.root.rglob("*"))
            if p.is_file() and not p.name.startswith(("_pw_", "_probe"))
        ]
        return state, files

    def _save(self, path: Path) -> None:
        """Write the snapshot from a throwaway interpreter (no site, no mounts), unless the preload changed what a
        snapshot does not hold: dlopen, table slots, closures, signals, open fds, the cwd, files."""
        with Pyodide(self.flavor, preopen_dev=self.preopen_dev, env=self.env, data=self.data) as fresh:
            before = fresh._probe()
            rc = fresh.run(self.preload or "")
            if rc != 0 or len(fresh.instances) != 1 or fresh.slots or fresh.host_state or fresh._probe() != before:
                return
            st = fresh.store
            pages = fresh.memory.size(st)
            hdr = {
                "version": SNAPSHOT_VERSION,
                "pages": pages,
                "table": fresh.table.size(st),
                "slots": list(fresh._net_slots),
            }
            buf = (ctypes.c_char * (pages * 65536)).from_address(ctypes.addressof(fresh.memory.data_ptr(st).contents))
            tmp = path.with_suffix(f".tmp{os.getpid()}")
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(tmp, "wb") as f:
                    f.write(json.dumps(hdr).encode() + b"\n")
                    f.write(buf)
                os.replace(tmp, path)
                for old in path.parent.glob(f"snapshot-{self.flavor}-*.mem"):
                    if old != path:
                        old.unlink(missing_ok=True)
            except OSError:
                pass
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass

    # ------------------------------------------------------------------ public
    def run(self, code: str, argv: list[str] | None = None) -> int:
        """Run Python source in the guest, in its ``__main__``: 0 if it ran, 1 if it raised (the traceback is on
        stderr), N for ``sys.exit(N)`` (a message or None-like code as CPython's: text -> 1, None -> 0)."""
        if not self._started:
            self._start()
        assert self.root is not None
        self._runs += 1
        pre = f"import sys; sys.argv = {list(argv)!r}\n" if argv is not None else ""
        (self.root / f"_pw_{self._runs}.py").write_text(pre + code)
        rc_file = f"/_pw_{self._runs}.rc"
        wrapper = _WRAPPER.format(src=f"/_pw_{self._runs}.py", rc=rc_file)
        src = wrapper.encode() + b"\0"
        store = self.store
        p = self.ex["PyMem_Malloc"](store, len(src))
        self._wr(p, src)
        try:
            rc = self.ex["PyRun_SimpleString"](store, p)
        except self._wt.ExitTrap as e:  # the process ended (exit(), os._exit()): this interpreter is gone
            self._exited = e.code
            rc = e.code
        except self._wt.Trap as e:  # abort(), a failed assert, an unreachable: the guest is dead
            first = str(e).strip().splitlines()[0] if str(e).strip() else "trap"
            print(f"pyodide-wasmtime: the guest trapped: {first}", file=sys.stderr)
            self._exited = 134  # 128 + SIGABRT, as a process that aborts
            rc = 134
        except (
            Exception
        ) as e:  # a host function failed on purpose (JavaScript's TypeError, a pointer outside the memory)
            print(
                f"pyodide-wasmtime: a host function failed, the guest is dead: {type(e).__name__}: {e}", file=sys.stderr
            )
            self._exited = 134  # as for a trap
            rc = 134
        rc_path = self.root / rc_file.lstrip("/")
        if self._exited is not None:
            self.close()  # a next run() starts a new interpreter
            self._exited = None
        elif rc_path.exists():
            rc = int(rc_path.read_text())
        if self.lazy:
            log.info("[loader] imports bound lazily (no definition at load): %s", ", ".join(sorted(set(self.lazy))))
        for line in self.netlog:
            log.info("[net] %s", line)
        self.netlog.clear()
        return rc

    def close(self) -> None:
        for s in self.socks.values():
            s.close()
        self.socks.clear()
        self.protoents.clear()  # guest addresses, and the guest is gone: so are the table slots and instances
        self.slots.clear()
        self.instances = [None]
        if self.root is not None:
            shutil.rmtree(self.root, ignore_errors=True)
            self.root = None
        self.free_slots.clear()
        self.host_state = False
        self.functions.clear()
        self.func_pool.clear()
        self.live_funcs.clear()
        self._cell = self._pending = 0
        self._started = False

    def __enter__(self) -> Pyodide:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
