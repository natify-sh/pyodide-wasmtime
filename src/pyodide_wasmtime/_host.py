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

import errno
import importlib.metadata
import json
import logging
import os
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
        shutil.copy(Path(__file__).with_name("guest") / "hostnet.py", sp)
        # the frozen `encodings` package looks in /lib/python3.15/encodings, which does not exist: the stdlib is the
        # zip (Pyodide's JavaScript sets this up); without it every codec but the frozen ones is missing
        (sp / "sitecustomize.py").write_text(
            f"import encodings\nencodings.__path__.append('/lib/python{PYVER.replace('.', '')}.zip/encodings')\n"
        )

    # ------------------------------------------------------------------ the loader's host interface
    # Four operations a wasm module cannot do itself, because the host holds the instances and their exports by
    # name: instantiate, sym, got_set, call. The rest of `_dlopen_js` (the file, dylink.0, memory from calloc, the
    # GOT, relocations, constructors) runs in the adapter.
    def _rd(self, a: int, n: int) -> bytes:
        return bytes(self.memory.read(self.cur[-1], a, a + n))

    def _wr(self, a: int, data: bytes) -> None:
        self.memory.write(self.cur[-1], bytes(data), a)

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
    @staticmethod
    def _werr(exc: OSError) -> int:
        """A host OSError -> -errno in WASI's (= Emscripten's) numbering."""
        name = errno.errorcode.get(getattr(exc, "errno", None) or 0, "EIO")[1:]
        return -WASI_ERRNO.get(name, WASI_ERRNO["IO"])

    def _n_socket(self, domain: int, type_: int, proto: int) -> int:
        try:
            s = socket.socket(
                {2: socket.AF_INET, 10: socket.AF_INET6}[domain], {1: socket.SOCK_STREAM, 2: socket.SOCK_DGRAM}[type_]
            )
        except (KeyError, OSError) as e:
            return self._werr(e) if isinstance(e, OSError) else -WASI_ERRNO["AFNOSUPPORT"]
        h = max(self.socks, default=0) + 1
        self.socks[h] = s
        return h

    def _n_connect(self, h: int, family: int, port: int, ap: int) -> int:
        ip = socket.inet_ntop(
            socket.AF_INET6 if family == 10 else socket.AF_INET, self._rd(ap, 16 if family == 10 else 4)
        )
        try:
            self.socks[h].connect((ip, port))
        except OSError as e:
            self.netlog.append(f"socket connect {ip}:{port} -> {e}")
            return self._werr(e)
        self.netlog.append(f"socket connect {ip}:{port}")
        return 0

    def _n_send(self, h: int, p: int, n: int) -> int:
        try:
            return self.socks[h].send(self._rd(p, n))
        except OSError as e:
            return self._werr(e)

    def _n_recv(self, h: int, p: int, n: int, peek: int) -> int:
        try:
            data = self.socks[h].recv(n, socket.MSG_PEEK if peek else 0)
        except OSError as e:
            return self._werr(e)
        self._wr(p, data)
        return len(data)

    def _n_poll(self, h: int, events: int, timeout_ms: int) -> int:
        s = self.socks[h]
        r, w, _ = select.select(
            [s] if events & 1 else [], [s] if events & 4 else [], [], None if timeout_ms < 0 else timeout_ms / 1000
        )
        return (1 if r else 0) | (4 if w else 0)

    def _n_pollv(self, n: int, hp: int, evp: int, timeout_ms: int, revp: int) -> int:
        """Several sockets at once (poll): handles and events are arrays of i32 in the guest's memory, the revents are
        written back. With no sockets it is a sleep. Returns how many are ready."""
        if n == 0:
            if timeout_ms > 0:
                time.sleep(timeout_ms / 1000)
            return 0
        handles = struct.unpack(f"<{n}i", self._rd(hp, 4 * n))
        events = struct.unpack(f"<{n}i", self._rd(evp, 4 * n))
        socks = [self.socks.get(h) for h in handles]
        r, w, _ = select.select(
            [s for s, e in zip(socks, events, strict=True) if s and e & 1],
            [s for s, e in zip(socks, events, strict=True) if s and e & 4],
            [],
            None if timeout_ms < 0 else timeout_ms / 1000,
        )
        revents = [
            ((1 if s in r else 0) | (4 if s in w else 0)) if s else 32 for s in socks
        ]  # a closed handle: POLLNVAL
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

    def _n_name(self, h: int, peer: int, ap: int, portp: int) -> int:
        try:
            ip, port = (self.socks[h].getpeername() if peer else self.socks[h].getsockname())[:2]
        except OSError as e:
            return self._werr(e)
        self._wr(ap, socket.inet_aton(ip))
        self._wr(portp, struct.pack("<i", port))
        return 0

    def _n_resolve(self, np_: int, n: int, ap: int) -> int:
        name = self._rd(np_, n).decode()
        try:
            ip = socket.gethostbyname(name)
        except OSError:
            return -WASI_ERRNO["NOENT"]
        self.netlog.append(f"resolve {name} -> {ip}")
        self._wr(ap, socket.inet_aton(ip))
        return 0

    # ------------------------------------------------------------------ libffi's emscripten port: calls and closures
    # What pyodide.asm.mjs does in ffi_call_js / ffi_prep_closure_loc_js, with the type of the function from the wasm
    # table (a JavaScript call tolerates any signature: extra arguments are dropped, missing ones are undefined).
    def _u32(self, a: int) -> int:
        return struct.unpack("<I", self._rd(a, 4))[0]

    def _unbox(self, t: int) -> tuple[int, int]:
        """A struct of one member is that member (libffi's JS `unbox_small_structs`): (type pointer, type id)."""
        while True:
            tid = struct.unpack("<H", self._rd(t + 6, 2))[0]
            if tid != 13:
                return t, tid
            first, second = struct.unpack("<II", self._rd(self._u32(t + 8), 8))
            if first == 0:
                return t, 0
            if second != 0:
                return t, 13
            t = first

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
        """`_PyEM_TrampolineCall_JS` for a table entry whose type the WAT trampoline does not know."""
        return _to_wasm(self._js_call(fn, [a, b, c]), "i32")

    def _ffi_call(self, cif: int, fn: int, rvalue: int, avalue: int) -> None:
        ctx = self.cur[-1]
        _abi, nargs, atp, rtp, _bytes, _flags, nfixed = struct.unpack("<7I", self._rd(cif, 28))
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
                cur = (cur - size) & ~(align - 1)
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
                    cur -= 1
                    self._wr(cur, self._rd(ap, 1))
                elif tid in (7, 8):
                    cur = (cur - 2) & ~1
                    self._wr(cur, self._rd(ap, 2))
                elif tid in (1, 9, 10, 14, 2):
                    cur = (cur - 4) & ~3
                    self._wr(cur, self._rd(ap, 4))
                elif tid in (3, 11, 12):
                    cur = (cur - 8) & ~7
                    self._wr(cur, self._rd(ap, 8))
                elif tid == 4:
                    cur = (cur - 16) & ~7
                    self._wr(cur, self._rd(ap, 16))
                elif tid == 13:
                    cur = (cur - 4) & ~3
                    structs.append((cur, ap, *struct.unpack("<IH", self._rd(tp, 6))))
                else:
                    raise RuntimeError("complex arg marshalling nyi" if tid == 15 else f"Unexpected argtype {tid}")
            args.append(cur)
            for target, ap, size, align in structs:
                cur = (cur - size) & ~(align - 1)
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
        if self.free_slots:
            return self.free_slots.pop()
        return self.table.grow(self.cur[-1], 1, self._wt.Val.funcref(None))

    def _ffi_free(self, index: int) -> None:
        self.functions.pop(index, None)
        self.table.set(self.cur[-1], index, self._wt.Val.funcref(None))
        self.free_slots.append(index)

    def _ffi_prep(self, closure: int, cif: int, fun: int, user_data: int, codeloc: int) -> int:
        """Puts a host function of the closure's signature into table slot `codeloc`; when the guest calls it, the
        arguments are written to the stack as libffi's `avalue` and `fun(cif, ret, args, user_data)` is called."""
        wt = self._wt
        _abi, nargs, atp, rtp, _bytes, _flags, nfixed = struct.unpack("<7I", self._rd(cif, 28))
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

        def trampoline(caller: Any, *a: Any) -> Any:
            self.cur.append(caller)
            try:
                return self._ffi_closure(closure, nargs, nfixed, info, ret_by_arg, rk, a)
            finally:
                self.cur.pop()

        try:
            func = wt.Func(self.store, wt.FuncType(params, results), trampoline, access_caller=True)
        except Exception:  # JavaScript: convertJsFunctionToWasm failed
            return 1
        self.functions.pop(codeloc, None)
        self.table.set(self.cur[-1], codeloc, func)
        self._wr(closure + 4, struct.pack("<III", cif, fun, user_data))
        return 0

    def _ffi_closure(
        self, closure: int, nargs: int, nfixed: int, info: list, ret_by_arg: bool, rk: str, a: tuple
    ) -> Any:
        ctx = self.cur[-1]
        sp = self.ex["__stack_pointer"]
        orig = cur = sp.value(ctx)
        _index, cif, fun, user_data = struct.unpack("<IIII", self._rd(closure, 16))
        j = 0
        if ret_by_arg:
            ret_ptr = a[0] & 0xFFFFFFFF
            j = 1
        else:
            cur = (cur - 8) & ~7
            ret_ptr = cur
        cur -= 4 * nargs
        args_ptr = cur
        slots: dict[int, int] = {}

        def put(c: int, size: int, align: int, data: bytes) -> None:
            nonlocal cur
            cur = (cur - size) & ~(align - 1)
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
        }
        net = {
            "socket": (self._n_socket, ft(3)),
            "connect": (self._n_connect, ft(4)),
            "send": (self._n_send, ft(3)),
            "recv": (self._n_recv, ft(4)),
            "poll": (self._n_poll, ft(3)),
            "pollv": (self._n_pollv, ft(5)),
            "close": (self._n_close, ft(1)),
            "shutdown": (self._n_shutdown, ft(2)),
            "name": (self._n_name, ft(4)),
            "resolve": (self._n_resolve, ft(3)),
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
                linker.define_func("net", name, ty, self._wrap(fn, len(ty.results)), access_caller=True)

        if self.flavor == "fused":
            main_mod = _engine.load_module(self.data / "pyodide_fused.wasm")
            linker = wt.Linker(engine)
            linker.define_wasi()
            define_ops(linker)
            self.ex = linker.instantiate(store, main_mod).exports(store)
            self.memory, self.table = self.ex["memory"], self.ex["__indirect_function_table"]
            self.instances[0] = {"exports": {e.name: self.ex[e.name] for e in main_mod.exports}, "got": []}
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
            self.ex = linker.instantiate(store, main_mod).exports(store)
            self.memory, self.table = self.ex["memory"], self.ex["__indirect_function_table"]
            self.instances[0] = {"exports": {e.name: self.ex[e.name] for e in main_mod.exports}, "got": []}

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
            for f in ("malloc", "calloc", "free"):
                al.define(store, "env", f, self.ex[f])
            al.define(store, "aux", "table_grow", tramp["table_grow"])
            define_ops(al)
            adapter = al.instantiate(store, adapter_mod).exports(store)
            for n, e in {
                **adapter,
                _wasm.TRAMP: tramp[_wasm.TRAMP],
            }.items():  # dlsym finds them too, as in the fused module
                if isinstance(e, wt.Func) and not n.startswith("__wasm") and n not in self.instances[0]["exports"]:
                    self.instances[0]["exports"][n] = e
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
        if self.root is not None:
            shutil.rmtree(self.root, ignore_errors=True)
            self.root = None
        self.free_slots.clear()
        self.functions.clear()
        self._cell = self._pending = 0
        self._started = False

    def __enter__(self) -> Pyodide:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
