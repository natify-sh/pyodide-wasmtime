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
import errno
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


class Pyodide:
    """One Python (Pyodide's CPython) in wasm, run by wasmtime.

    >>> py = Pyodide()                       # the fused build from the package's data
    >>> py.run("print(1 + 1)")               # 0 if the code ran, -1 if it raised (the traceback is on stderr)

    ``site``: a folder (or several) copied into the guest's ``site-packages`` (a wheel unpacked, ``micropip``...);
    ``mounts``: ``{guest path: host folder}`` preopened as they are (the guest can write there);
    ``preopen_dev``: the host's ``/dev`` (OpenSSL reads ``/dev/urandom``); ``env``: more environment variables.
    The guest's ``/`` is a temporary folder (stdlib zip, site-packages); it is not a sandbox against the host's own
    network: ``socket`` and the host's fetch are real.
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
    ) -> None:
        wt = _engine.require_wasmtime()
        self._wt = wt
        self.data = data_dir(data)
        have = available_flavors(self.data)
        if flavor is None:
            flavor = os.environ.get("PYODIDE_WASMTIME_FLAVOR") or (have[0] if have else "fused")
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
        opt = os.environ.get("WASM_OPT") or wasm_opt or self.data / "wasm-opt.wasm"
        self.wasm_opt = str(opt) if (os.environ.get("WASM_OPT") or wasm_opt or Path(opt).exists()) else None
        # state of the running guest
        self.root: Path | None = None
        self.cur: list = []  # the Caller (or the Store) of the running host function
        self.instances: list = [None]  # id -> {exports (name -> extern, in export order), got (GOT globals)}
        self.slots: dict = {}
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

    # ------------------------------------------------------------------ the loader's host interface
    # Four operations a wasm module cannot do itself, because the host holds the instances and their exports by
    # name: instantiate, sym, got_set, call. The rest of `_dlopen_js` (the file, dylink.0, memory from calloc, the
    # GOT, relocations, constructors) runs in the adapter.
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

    def _env_func(self, name: str) -> Any:
        wt = self._wt
        for inst in self.instances:
            e = inst["exports"].get(name)
            if isinstance(e, wt.Func):
                return e
        return None

    def _dl_instantiate(self, p: int, n: int, mb: int, tb: int) -> int:
        wt = self._wt
        c = self.cur[-1]
        try:
            data = self._rd(p, n)
            try:
                module = wt.Module(_engine.engine(), data)
            except Exception as exc:  # legacy exceptions (a wheel micropip just installed): Binaryen's wasm-opt, here
                if "legacy_exceptions" not in str(exc) or not self.wasm_opt:
                    raise
                module = wt.Module(_engine.engine(), _engine.translate_to_exnref(data, self.wasm_opt))
                self.converted += 1
                log.info("[loader] converted legacy exceptions to exnref (%d bytes)", n)
            linker = wt.Linker(_engine.engine())
            own = {e.name for e in module.exports}
            cell: list = []
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
                    if item is None and nm in own:  # its own function, reached through its export once it exists

                        def tramp(caller, *args, _n=nm, _cell=cell):
                            return _cell[0][_n](caller, *args)

                        item = wt.Func(self.store, ty, tramp, access_caller=True)
                    if item is None:  # as Emscripten's glue: resolved when called, an error only if still missing then

                        def lazy(caller, *args, _n=nm):
                            f = self._env_func(_n)
                            if f is None:
                                raise RuntimeError(f"missing function: {_n}")
                            return f(caller, *args)

                        item = wt.Func(self.store, ty, lazy, access_caller=True)
                        self.lazy.append(nm)
                elif m in ("GOT.mem", "GOT.func"):
                    item = wt.Global(c, wt.GlobalType(i32, True), wt.Val.i32(0))
                    got.append(item)
                else:
                    raise RuntimeError(f"unresolved import {m}.{nm}")
                linker.define(c, m, nm, item)
            inst = linker.instantiate(c, module)
            ex = inst.exports(c)
            exports = {e.name: ex[e.name] for e in module.exports}
            cell.append(exports)
            self.instances.append({"exports": exports, "got": got})
            return len(self.instances) - 1
        except Exception as exc:
            log.error("[loader] instantiate failed: %s: %s", type(exc).__name__, exc)
            print(f"[loader] instantiate failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return -1

    def _dl_got_set(self, id_: int, i: int, v: int) -> None:
        self.instances[id_]["got"][i].set_value(self.cur[-1], v)

    def _dl_sym(self, id_: int, p: int, n: int, out: int) -> int:
        wt = self._wt
        c = self.cur[-1]
        name = self._rd(p, n).decode()
        exports = self.instances[id_]["exports"]
        e = exports.get(name)
        if isinstance(e, wt.Global):
            self._wr(out, struct.pack("<II", 1, list(exports).index(name)))
            return e.value(c) & 0xFFFFFFFF
        if isinstance(e, wt.Func):
            if (id_, name) not in self.slots:
                self.slots[(id_, name)] = self.table.grow(c, 1, wt.Val.funcref(e))
            self._wr(out, struct.pack("<II", 2, list(exports).index(name)))
            return self.slots[(id_, name)]
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

    def _wrap(self, fn, nres: int):
        def f(caller, *args):
            self.cur.append(caller)
            try:
                r = fn(*args)
            finally:
                self.cur.pop()
            return r if nres else None

        return f

    def _ops(self) -> tuple[dict, dict]:
        wt = self._wt
        i32 = wt.ValType.i32()

        def ft(n, r=1):
            return wt.FuncType([i32] * n, [i32] * r)

        loader = {
            "instantiate": (self._dl_instantiate, ft(4)),
            "got_set": (self._dl_got_set, ft(3, 0)),
            "sym": (self._dl_sym, ft(4)),
            "call": (self._dl_call, ft(3)),
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
        return loader, net

    # ------------------------------------------------------------------ start
    def _start(self) -> None:
        wt = self._wt
        engine = _engine.engine()
        self._setup_root()
        assert self.root is not None
        self.store = store = wt.Store(engine)
        wasi = wt.WasiConfig()
        wasi.env = [
            *BASE_ENV,
            ("SSL_CERT_FILE", "/etc/ssl/cert.pem"),
            ("REQUESTS_CA_BUNDLE", "/etc/ssl/cert.pem"),
        ] + list(self.env.items())
        wasi.preopen_dir(str(self.root), "/")
        for guest, host in self.mounts.items():
            wasi.preopen_dir(host, guest)
        if self.preopen_dev:  # the entropy device OpenSSL reads (/dev/urandom)
            wasi.preopen_dir("/dev", "/dev")
        wasi.inherit_stdin()
        wasi.inherit_stdout()
        wasi.inherit_stderr()
        store.set_wasi(wasi)
        loader_ops, net_ops = self._ops()
        I32 = wt.ValType.i32()  # noqa: N806

        def define_ops(linker):
            for name, (fn, ty) in loader_ops.items():
                linker.define_func("loader", name, ty, self._wrap(fn, len(ty.results)), access_caller=True)
            for name, (fn, ty) in net_ops.items():
                linker.define_func("net", name, ty, self._wrap_net(name, fn), access_caller=True)

        if self.flavor == "fused":
            main_mod = _engine.load_module(self.data / "pyodide_fused.wasm")
            linker = wt.Linker(engine)
            linker.define_wasi()
            define_ops(linker)
            self.ex = _engine.LazyExports(store, linker.instantiate(store, main_mod), main_mod)
            self.memory, self.table = self.ex["memory"], self.ex["__indirect_function_table"]
            self.instances[0] = {"exports": self.ex, "got": []}
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
            }
            for i in adapter_mod.imports:
                assert i.module in ("wasi_snapshot_preview1", "loader", "aux", "net") or (
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
            self.instances[0] = {"exports": self.ex, "got": []}

            tl = wt.Linker(engine)
            tl.define(store, "env", "__indirect_function_table", self.table)
            tramp = tl.instantiate(store, wt.Module(engine, wt.wat2wasm(_wasm.TRAMP_WAT))).exports(store)

            al = wt.Linker(engine)
            al.define_wasi()
            al.define(store, "env", "memory", self.memory)
            al.define(store, "env", "__indirect_function_table", self.table)
            al.define(store, "env", "__stack_pointer", self.ex["__stack_pointer"])
            al.define(store, "env", "__memory_base", wt.Global(store, wt.GlobalType(I32, False), wt.Val.i32(0)))
            al.define(store, "env", "__table_base", wt.Global(store, wt.GlobalType(I32, False), wt.Val.i32(0)))
            for f in ("malloc", "calloc", "free"):
                al.define(store, "env", f, self.ex[f])
            al.define(store, "aux", "table_grow", tramp["table_grow"])
            define_ops(al)
            adapter = al.instantiate(store, adapter_mod).exports(store)
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
        self.ex["emscripten_stack_init"](store)
        self.ex["__wasm_call_ctors"](store)
        self.ex["Py_Initialize"](store)
        self._started = True

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
        self._started = False

    def __enter__(self) -> Pyodide:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
