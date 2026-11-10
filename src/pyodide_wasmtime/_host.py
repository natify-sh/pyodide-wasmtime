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
        self.slots: dict = {}  # (instance, export name) -> table slot
        self.scopes: dict[int, list[int]] = {}  # a dlopen call's scope -> the instances loaded in it
        self._tfuncs: dict[bytes, int] = {}  # the table's functions (by engine handle) -> first slot
        self._tscanned = 0
        self._wasi_linker: Any = None  # wasmtime's WASI functions, for the side modules that import them
        self._dlreason = ""  # why the last instantiate failed
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
                exports.pop(name, None)

    # ------------------------------------------------------------------ the loader's host interface
    # Five operations a wasm module cannot do itself, because the host holds the instances and their exports by
    # name: instantiate, scope, got_set, sym, call. The rest of `_dlopen_js` (the file, dylink.0 and its bounds, memory
    # from calloc, the GOT, relocations, constructors, dlerror) runs in the adapter.
    #
    # What a module's `env` imports see, as in Emscripten's glue: the main module (in the dynamic build with the
    # adapter's exports), then the libraries loaded RTLD_GLOBAL, and, when the function is first called (the glue's
    # lazy stubs), the libraries of the dlopen call's own scope (its NEEDED libraries; the last one wins) and last
    # the module's own exports.
    def _rd(self, a: int, n: int) -> bytes:
        return bytes(self.memory.read(self.cur[-1], a, a + n))

    def _wr(self, a: int, data: bytes) -> None:
        self.memory.write(self.cur[-1], bytes(data), a)

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
            "instantiate": (self._dl_instantiate, ft(5)),
            "scope": (self._dl_scope, ft(2, 0)),
            "got_set": (self._dl_got_set, ft(3, 0)),
            "sym": (self._dl_sym, ft(4)),
            "call": (self._dl_call, ft(3)),
            "error": (self._dl_error, ft(5, 0)),
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
            self.instances[0]["exports"].update({n: adapter[n] for n in adapter_names})
            self.instances[0]["exports"][_wasm.TRAMP] = tramp[_wasm.TRAMP]
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
        self._started = False

    def __enter__(self) -> Pyodide:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
