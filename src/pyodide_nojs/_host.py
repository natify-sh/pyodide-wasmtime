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

import ctypes
import errno
import hashlib
import json
import logging
import os
import select
import shutil
import socket
import struct
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
import weakref
from pathlib import Path
from typing import Any

from . import _cif, _engine, _timecalc, _wasm
from ._consts import (
    _GLOBAL_WHY,
    _JS_MODULES,
    _U32,
    BASE_ENV,
    EOPNOTSUPP,
    ESOCKTNOSUPPORT,
    FLAVORS,
    GUEST,
    GUEST_ERRNO,
    GUEST_OWN_ENV,
    GUEST_SUFFIXES,
    MAX_MEMORY,
    MAX_TABLE,
    PYVER,
    SERVICE_EXPORTS,
    SERVICES,
    SNAPSHOT_VERSION,
    TESTENV_HINT,
    WASI_ERRNO,
    GuestExit,
    GuestFault,
    MainExports,
    _from_wasm,
    _override,
    _s32,
    _to_wasm,
    available_flavors,
    data_dir,
    guest_errno,
    override_warnings,
)
from ._sockaddr import (
    BOOL_OPTIONS,
    ca_bundle,
    msg_flags,
    msghdr,
    nameinfo,
    nonblocking,
    option,
    recv,
    resolve_addrinfo,
    send,
    sockaddr,
    sockaddr_out,
    werr,
)

log = logging.getLogger("pyodide_nojs")

# what the package, its tools and its tests import from here
__all__ = [
    "BASE_ENV",
    "FLAVORS",
    "PYVER",
    "TESTENV_HINT",
    "GuestExit",
    "GuestFault",
    "Pyodide",
    "available_flavors",
    "data_dir",
    "guest_errno",
    "override_warnings",
]


class Pyodide:
    """One Python (Pyodide's CPython) in wasm, run by wasmtime.

    >>> py = Pyodide()                       # the dynamic build from the package's data (fused if only that is there)
    >>> py.run("print(1 + 1)")               # 0 if the code ran, -1 if it raised (the traceback is on stderr)

    ``site``: a folder (or several) copied into the guest's ``site-packages`` (a wheel unpacked, ``micropip``...);
    ``mounts``: ``{guest path: host folder}`` preopened as they are (the guest can write there);
    ``preopen_dev``: the host's ``/dev`` (OpenSSL reads ``/dev/urandom``); ``env``: more environment variables.
    The guest is isolated: its environment is Pyodide's minimal one (``BASE_ENV``) plus ``env``, never the host's,
    unless ``inherit_env`` passes the host's variables too, secrets included (``env`` wins; no snapshot then).
    The guest's ``/`` is a temporary folder (stdlib zip, site-packages); it is not a sandbox against the host's own
    network: ``socket`` and the host's fetch are real.

    ``preload``: Python source run once at start (as ``run(preload)``). The memory after it is cached in a snapshot file
    in the cache dir, so a next start with the same preload and settings restores it instead of booting Python
    (``$PYODIDE_NOJS_SNAPSHOT=0`` turns that off). The preload must only import and compute: it must not print (it
    prints at snapshot time only); opening files or sockets, ``chdir``, writing files, ``dlopen``, ``ctypes`` symbol
    lookups or callbacks, and signals or timers make the snapshot be skipped (a normal start,
    the preload run once); with ``site=`` or ``mounts=`` or ``inherit_env`` there is no snapshot at all.
    """

    def __init__(
        self,
        flavor: str | None = None,
        *,
        site: str | os.PathLike[str] | list[str | os.PathLike[str]] | None = None,
        mounts: dict[str, str | os.PathLike[str]] | None = None,
        preopen_dev: bool | None = None,
        env: dict[str, str] | None = None,
        inherit_env: bool = False,
        data: str | os.PathLike[str] | None = None,
        wasm_opt: str | os.PathLike[str] | None = None,
        preload: str | None = None,
        asm_wasm: str | os.PathLike[str] | None = None,
        stdlib: str | os.PathLike[str] | None = None,
    ) -> None:
        wt = _engine.require_wasmtime()
        self._wt = wt
        self.data = data_dir(data)
        self.asm_wasm = _override(asm_wasm, "PYODIDE_NOJS_ASM_WASM")
        self.stdlib = _override(stdlib, "PYODIDE_NOJS_STDLIB")
        self._override_checked = False
        have = available_flavors(self.data)
        overridden = self.asm_wasm is not None or self.stdlib is not None
        if self.asm_wasm is not None and "dynamic" not in have and (self.data / "adapter.wasm").exists():
            have.append("dynamic")  # the adapter is the package's, the main module is the given one
        if flavor is None:
            flavor = _engine.env("PYODIDE_NOJS_FLAVOR") or (
                "dynamic" if overridden or "dynamic" in have else (have[0] if have else "dynamic")
            )
        if flavor == "fused" and overridden:
            raise ValueError(
                "asm_wasm/stdlib replace files of the dynamic build: "
                "the fused module is built for one Pyodide (use dynamic)"
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
        for what, folders in (("site", self.site), ("mount", self.mounts.values())):
            for f in folders:
                if not os.path.isdir(f):
                    raise FileNotFoundError(f"{what} folder not found: {f}{TESTENV_HINT}")
        self.preopen_dev = bool(os.environ.get("PREOPEN_DEV")) if preopen_dev is None else preopen_dev
        self.env = dict(env or {})
        self.inherit_env = inherit_env
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
        self._gseq = 0  # libraries made RTLD_GLOBAL so far
        self._wasi_linker: Any = None  # wasmtime's WASI functions, for the side modules that import them
        self._dlreason = ""  # why the last instantiate failed
        self.socks: dict = {}
        self.netlog: list[str] = []
        self._shut_both: weakref.WeakSet[socket.socket] = weakref.WeakSet()  # shutdown(RDWR) was called: poll's HUP
        self._listening: set[socket.socket] = set()  # listen() was called: SO_ACCEPTCONN (macOS refuses to say it)
        self._connecting: set[socket.socket] = set()  # a non-blocking connect that has not been looked at yet
        self._pending_err: dict[socket.socket, int] = {}  # SO_ERROR read by poll for POLLERR, kept for the guest's read
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
        self.closures_out = 0  # closures the guest holds (allocated, not yet freed): their slots are the host's
        self.live_funcs: dict[int, tuple] = {}  # table slot -> (signature, Func, state) of a closure in use
        self._svc_ex: Any = (
            None  # where the host's own exports of the adapter are: the main module (fused), the adapter
        )
        self.memory: Any = None
        self.store: Any = None

    # ------------------------------------------------------------------ the guest's root
    def _setup_root(self) -> None:
        self.root = root = Path(tempfile.mkdtemp(prefix="pyodide_nojs_"))
        (root / "lib" / f"python{PYVER}" / "lib-dynload").mkdir(parents=True)  # CPython looks for it at start
        shutil.copy(
            self.stdlib or self.data / "python_stdlib.zip", root / "lib" / f"python{PYVER.replace('.', '')}.zip"
        )
        sp = root / "lib" / f"python{PYVER}" / "site-packages"
        sp.mkdir()
        guest_files = sorted(g for g in GUEST.iterdir() if g.suffix in GUEST_SUFFIXES)
        for g in guest_files:  # before the site= folders: a file of the same name there wins (but not the run protocol)
            if g.name != "pyodide_nojs_run.py":
                shutil.copy(g, sp)
        lock = self.data / "pyodide-lock.json"  # Pyodide's package lock, for micropip (guest/pyodide_lock.py)
        if lock.exists():
            shutil.copy(lock, sp / "pyodide-lock.json")
        for s in self.site:  # inside the preopen: WASI does not follow a link out of it
            shutil.copytree(s, sp, dirs_exist_ok=True)
        shutil.copy(GUEST / "pyodide_nojs_run.py", sp)  # the host's own protocol: ours always wins
        for guest in self.mounts:  # a placeholder, so that a directory listing of the parent shows the mount
            (root / guest.lstrip("/")).mkdir(parents=True, exist_ok=True)
        (root / "home" / "pyodide").mkdir(parents=True, exist_ok=True)  # HOME
        (root / "tmp").mkdir(exist_ok=True)  # Pyodide has /tmp (mode 0o777, set at start by _boot): tempfile's default
        (root / "etc" / "ssl").mkdir(parents=True)
        (root / "etc" / "ssl" / "cert.pem").write_bytes(ca_bundle())
        (root / "etc" / "services").write_text("".join(f"{n} {p}/{pr}\n" for (n, pr), p in SERVICES.items()))

    def _drop_stubs(self) -> None:
        """The fused module exports the zero/null stubs of the JavaScript bridge (the merge made them functions);
        the glue marks them `stub` and dlsym and the GOT do not see them: nor do we. Needs the pyodide.asm.wasm
        and adapter.wasm of the package (without them every export stays)."""
        main_path, adapter_path = self.data / "pyodide.asm.wasm", self.data / "adapter.wasm"
        if not (main_path.exists() and adapter_path.exists()):
            return
        # the names are read from 10 MB of wasm: kept in the cache dir, keyed by the two files' size and mtime
        key = hashlib.sha256(b"|".join(_engine._stamp(p) for p in (main_path, adapter_path))).hexdigest()[:16]
        cached = _engine.cache_dir() / f"stubs-{key}.json"
        try:
            names = json.loads(cached.read_text())
        except (OSError, ValueError):
            wasm = main_path.read_bytes()
            answered = set(_wasm.export_names(adapter_path.read_bytes())) | set(_wasm.export_names(wasm))
            answered.add(_wasm.TRAMP)
            names = [n for mod, n, kind in _wasm.import_names(wasm) if mod == "env" and kind == 0 and n not in answered]
            try:
                _engine.private_dir(cached.parent)
                cached.write_text(json.dumps(names))
            except OSError:
                pass
        self.instances[0]["exports"].hidden.update(names)

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
        # the main module, then the libraries in the order they became RTLD_GLOBAL (the glue's mergeLibSymbols)
        glob = sorted(
            (self.instances[i]["global"], i) for i in range(1, len(self.instances)) if self.instances[i]["global"]
        )
        ids = [0] + [i for _, i in glob]
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

    def _dl_reason(self, text: str) -> int:
        """A failed load whose reason is the JS API's own text (a link error the engine would word differently)."""
        self._dlreason = text
        log.info("[loader] instantiate failed: %s", text)
        return -1

    def _link_error(self, i: int, imp: Any, item: Any, number: bool) -> str | None:
        """What V8 says when the glue's import object gives `item` for import `imp` (#i) and it does not fit, else
        None. `number`: the glue gives a plain number (__memory_base, __table_base); item None: a JS function."""
        wt, c = self._wt, self.cur[-1]
        ty = imp.type
        pre = f'LinkError: WebAssembly.Instance(): Import #{i} module="{imp.module}" function="{imp.name}": '
        if isinstance(ty, wt.FuncType):
            if not isinstance(item, wt.Func):
                return pre + "function import requires a callable"
            if imp.module == "env":  # the glue's own functions are JavaScript, which takes any signature: not checked
                have = item.type(c)
                if [str(t) for t in have.params] != [str(t) for t in ty.params] or [str(t) for t in have.results] != [
                    str(t) for t in ty.results
                ]:
                    return pre + "imported function does not match the expected type"
        elif isinstance(ty, wt.GlobalType):
            if number:
                if ty.mutable:
                    return pre + "imported mutable global must be a WebAssembly.Global object"
                if str(ty.content) not in ("i32", "f32", "f64"):
                    return pre + _GLOBAL_WHY
            elif not isinstance(item, wt.Global):
                return pre + _GLOBAL_WHY
            else:
                have = item.type(c)
                if have.mutable != ty.mutable:
                    return pre + "imported global does not match the expected mutability"
                if str(have.content) != str(ty.content):
                    return pre + "imported global does not match the expected type"
        elif isinstance(ty, wt.MemoryType):
            if not isinstance(item, wt.Memory):
                return pre + "memory import must be a WebAssembly.Memory object"
            lim, mt, pages = ty.limits, item.type(c), item.size(c)
            if pages < lim.min:
                return pre + f"memory import has {pages} pages which is smaller than the declared initial of {lim.min}"
            if lim.max is not None:
                have_max = mt.limits.max
                if have_max is None:
                    return pre + f"memory import has no maximum limit, expected at most {lim.max}"
                if have_max > lim.max:
                    why = f"memory import has a larger maximum size {have_max} than the module's declared maximum"
                    return pre + f"{why} {lim.max}"
            if ty.is_shared != mt.is_shared:
                declared, imported = int(ty.is_shared), int(mt.is_shared)
                return pre + f"mismatch in shared state of memory, declared = {declared}, imported = {imported}"
        elif isinstance(ty, wt.TableType):
            if not isinstance(item, wt.Table):
                return pre + "table import requires a WebAssembly.Table"
            if str(item.type(c).element) != str(ty.element):
                return pre + "imported table does not match the expected type"
            size, lim = item.size(c), ty.limits
            if size < lim.min:
                return (
                    f"LinkError: WebAssembly.Instance(): table import {i} is smaller than initial {lim.min}, got {size}"
                )
            if lim.max is not None and item.type(c).limits.max is None:
                return f"LinkError: WebAssembly.Instance(): table import {i} has no maximum length, expected {lim.max}"
        elif isinstance(ty, wt.TagType):
            if not isinstance(item, wt.Tag):
                return pre + "tag import requires a WebAssembly.Tag"
            ft = ty.functype  # the glue's tags carry one i32
            if [str(t) for t in ft.params] != ["i32"] or list(ft.results):
                return pre + "imported tag does not match the expected type"
        return None

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
        10: "RangeError: Maximum call stack size exceeded",
    }

    def _dl_error(self, code: int, np_: int, nn: int, ap: int, an: int) -> None:
        """dlerror's text: the glue's own, set through the main module's __dl_seterr."""
        name = self._rd(np_, nn).decode("utf-8", "replace") if np_ else "__main__"
        arg = self._rd(ap, an).decode("utf-8", "replace") if ap and an else ""
        if code == 12:
            text = f'Tried to lookup unknown symbol "{arg}" in dynamic lib: {name}'
        else:
            why = self._dlreason if code & 255 == 11 else self._DL_WHY.get(code & 255, "Error").format(arg=arg)
            text = ("'Could not" if code & 256 else "could not") + f" load dynamic lib: {name}\n{why}"
        c = self.cur[-1]
        ex = self.instances[0]["exports"]
        msg = text.encode("utf-8", "replace")
        blk = ex["malloc"](c, 8 + len(msg) + 1) & 0xFFFFFFFF  # [the %s argument][the format "%s"][the text]
        if not blk:  # no memory even for the message: dlerror stays what it was
            return
        self._wr(blk, struct.pack("<I", blk + 8) + b"%s\0\0" + msg + b"\0")
        ex["__dl_seterr"](c, _s32(blk + 4), _s32(blk))  # the format and the pointer to its arguments
        ex["free"](c, _s32(blk))

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
                data = _engine.translate_to_exnref(data, self.wasm_opt)
                module = wt.Module(_engine.engine(), data)
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
            imports = list(module.imports)
            for i, imp in enumerate(imports):  # V8 looks at every module object before it checks any import
                if imp.module not in _JS_MODULES:
                    return self._dl_reason(
                        f'TypeError: WebAssembly.Instance(): Import #{i} module="{imp.module}": '
                        "module is not an object or function"
                    )
            for i, imp in enumerate(imports):
                m, nm, ty = imp.module, imp.name, imp.type
                number = m == "env" and nm in ("__memory_base", "__table_base")  # a number in the glue
                if isinstance(ty, wt.TableType) and ty.limits.min > 10_000_000:
                    return self._dl_reason(
                        f"RangeError: WebAssembly.Instance(): initial table size ({ty.limits.min} elements) is "
                        "larger than implementation limit (10000000 elements)"
                    )
                item: Any = None  # None: what the glue's import object gives is a JavaScript function
                if m == "env" and nm == "memory":
                    item = self.memory
                elif m == "env" and nm == "__indirect_function_table":
                    item = self.table
                elif number:
                    item = wt.Global(c, wt.GlobalType(i32, False), wt.Val.i32(mb if nm == "__memory_base" else tb))
                elif m == "env" and nm == "__stack_pointer":
                    item = main["__stack_pointer"]
                elif m == "env" and nm in ("__cpp_exception", "__c_longjmp"):
                    item = main.get(nm) or (wt.Tag(c, ty) if isinstance(ty, wt.TagType) else None)
                elif m in ("GOT.mem", "GOT.func"):
                    item = wt.Global(c, wt.GlobalType(i32, True), wt.Val.i32(0))
                elif isinstance(ty, wt.FuncType):  # env or WASI (the other modules are handled above)
                    if m == "env":
                        item = self._env_func(nm)
                    else:  # the glue gives a side module the main module's WASI imports: the adapter's or wasmtime's
                        item = self._env_func(nm) if nm in _wasm.WASI_ROUTED else None
                        try:
                            item = item or self._wasi_func(nm)
                        except Exception:  # not a WASI function: the lazy stub below, as for env
                            pass
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
                why = self._link_error(i, imp, item, number)
                if why:
                    return self._dl_reason(why)
                if m in ("GOT.mem", "GOT.func"):
                    got.append(item)
                linker.define(c, m, nm, item)
            inst = linker.instantiate(c, module)
            ex = inst.exports(c)
            exports = {e.name: ex[e.name] for e in module.exports}
            for e in module.exports:  # relocateExports: ToInt32 of `value + memoryBase`, which a BigInt cannot do
                t = e.type
                if isinstance(t, wt.GlobalType) and str(t.content) == "i64" and not t.mutable:
                    return self._dl_reason("TypeError: Cannot mix BigInt and other types, use explicit conversions")
            own.update(exports)
            self.instances.append({"exports": exports, "got": got, "global": False, "base": mb & 0xFFFFFFFF})
            return len(self.instances) - 1
        except Exception as exc:
            return self._dl_fail("LinkError: WebAssembly.Instance()", exc)

    def _define_exit(self, linker: Any) -> None:
        """proc_exit as a process has it: any status, masked to 8 bits (wasmtime's own refuses 126 and above)."""
        wt = self._wt
        linker.allow_shadowing = True

        def proc_exit(code: int) -> None:
            raise GuestExit(code & 255)

        linker.define_func("wasi_snapshot_preview1", "proc_exit", wt.FuncType([wt.ValType.i32()], []), proc_exit)

    def _wasi_func(self, name: str) -> Any:
        wt = self._wt
        if self._wasi_linker is None:
            self._wasi_linker = wt.Linker(_engine.engine())
            self._wasi_linker.define_wasi()
            self._define_exit(self._wasi_linker)
        return self._wasi_linker.get(self.cur[-1], "wasi_snapshot_preview1", name)

    def _dl_scope(self, id_: int, scope: int) -> None:
        """The module is loaded: its exports join the global namespace (scope 0) or the dlopen call's scope."""
        if scope:
            self.scopes.setdefault(scope, []).append(id_)
        else:
            self._gseq += 1
            self.instances[id_]["global"] = self._gseq

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
            ty = e.type(c)
            kind, val = str(ty.content), e.value(c)
            base = self.instances[id_].get("base", 0)  # the glue's relocateExports: an immutable global + memoryBase
            if kind in ("i32", "f32", "f64"):
                # ToInt32 of the number, NaN and infinity are 0 (the sum of a float and the base is a float too)
                v = val if ty.mutable else val + base
                v = int(v) if v == v and abs(v) != float("inf") else 0
                self._wr(out, struct.pack("<II", 1, 0))
                return _s32(v & 0xFFFFFFFF)
            if ty.mutable:  # a reference (ToNumber: 0) or an i64 (ToInt32 throws) is no GOT symbol
                if struct.unpack("<I", self._rd(out + 4, 4))[0] == 0:  # the GOT asks (out[1] = 0)
                    return 0
                if kind == "i64":
                    raise RuntimeError("TypeError: Cannot convert a BigInt value to a number")
                self._wr(out, struct.pack("<II", 1, 0))
                return 0
            if kind != "i64":  # an immutable reference: null + base is the base, a function + base is NaN
                self._wr(out, struct.pack("<II", 1, 0))
                return _s32((base if getattr(val, "value", 1) is None else 0) & 0xFFFFFFFF)
            self._wr(out, struct.pack("<II", 0, 0))
            return 0
        if isinstance(e, wt.Func):
            if (id_, name) in self.slots:
                slot, new = self.slots[(id_, name)], False
            else:
                slot, new = self._table_slot(e)
                self.slots[(id_, name)] = slot
            # kind 3: a slot made by this lookup, with the export's index (the glue's symbolIndex)
            self._wr(out, struct.pack("<II", 3 if new else 2, list(exports).index(name) if new else 0))
            return _s32(slot)
        self._wr(out, struct.pack("<II", 0, 0))
        return 0

    def _dl_call(self, id_: int, p: int, n: int) -> int:
        e = self.instances[id_]["exports"].get(self._rd(p, n).decode())
        if isinstance(e, self._wt.Func):
            try:
                e(self.cur[-1])
            except GuestExit:  # exit() in a constructor: the glue's catch makes it a failed load (text: JS's `${e}`)
                return self._dl_reason("[object Object]")
            except (
                Exception
            ) as exc:  # a trap, an uncaught wasm exception: the glue's catch(e) makes any of them a failed load
                return self._dl_fail("RuntimeError", exc)
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
            return werr(e)
        return self._new_handle(s)

    def _n_bind(self, h: int, sa: int, n: int) -> int:
        s = self.socks[h]
        try:
            s.bind(sockaddr(self._rd, s, sa, n))
        except OSError as e:
            return werr(e)
        return 0

    def _n_listen(self, h: int, backlog: int) -> int:
        try:
            self.socks[h].listen(backlog if backlog >= 0 else socket.SOMAXCONN)
        except OSError as e:
            return werr(e)
        self._listening.add(self.socks[h])
        return 0

    def _n_accept(self, h: int, sa: int, lenp: int, nb: int) -> int:
        try:
            with nonblocking(self.socks[h], nb):
                conn, addr = self.socks[h].accept()
            conn.setblocking(True)
        except OSError as e:
            return werr(e)
        sockaddr_out(self._rd, self._wr, sa, lenp, addr)
        return self._new_handle(conn)

    def _n_connect(self, h: int, sa: int, n: int, nb: int) -> int:
        """A non-blocking socket starts the connection and answers EINPROGRESS; it completes in the background (poll
        for POLLOUT, then SO_ERROR), as in the kernel. The host socket itself stays blocking."""
        s = self.socks[h]
        try:
            addr = sockaddr(self._rd, s, sa, n)
            if nb:
                s.setblocking(False)
                try:
                    err = s.connect_ex(addr)
                finally:
                    s.setblocking(True)
                if err:
                    if err in (errno.EINPROGRESS, 10035):  # Windows: WSAEWOULDBLOCK
                        self._connecting.add(s)
                    raise OSError(errno.EINPROGRESS if err == 10035 else err, "connect")
            else:
                s.connect(addr)
        except OSError as e:
            self.netlog.append(f"socket connect -> {e}")
            return werr(e)
        self.netlog.append(f"socket connect {addr[0]}:{addr[1]}")
        return 0

    def _n_sendto(self, h: int, p: int, n: int, flags: int, sa: int, salen: int) -> int:
        s = self.socks[h]
        try:
            hf = msg_flags(flags)
            data = self._rd(p, n)
            with nonblocking(s, flags & 0x40):  # a partial count, or EAGAIN when nothing fits
                if sa:
                    return s.sendto(data, hf, sockaddr(self._rd, s, sa, salen))
                return send(s, data, hf)
        except OSError as e:
            return werr(e)

    def _n_recvfrom(self, h: int, p: int, n: int, flags: int, sa: int, lenp: int) -> int:
        try:
            data, addr, ret, _ = recv(self.socks[h], n, flags)
        except OSError as e:
            return werr(e)
        self._wr(p, data)
        sockaddr_out(self._rd, self._wr, sa, lenp, addr)
        return ret

    def _n_sendmsg(self, h: int, msg: int, flags: int) -> int:
        s = self.socks[h]
        try:
            name, namelen, iovs, ctllen = msghdr(self._rd, msg)
            if ctllen:  # SCM_RIGHTS, SCM_CREDENTIALS...: nothing can carry them to the host
                return -EOPNOTSUPP
            hf = msg_flags(flags)
            data = b"".join(self._rd(b, n) for b, n in iovs)
            with nonblocking(s, flags & 0x40):
                if name:
                    return s.sendto(data, hf, sockaddr(self._rd, s, name, namelen))
                return send(s, data, hf)
        except OSError as e:
            return werr(e)

    def _n_recvmsg(self, h: int, msg: int, flags: int) -> int:
        name, _namelen, iovs, _ctllen = msghdr(self._rd, msg)
        try:
            data, addr, ret, mflags = recv(self.socks[h], sum(n for _, n in iovs), flags)
        except OSError as e:
            return werr(e)
        pos = 0
        for b, n in iovs:  # every buffer, in order
            self._wr(b, data[pos : pos + n])
            pos += n
        if name:
            sockaddr_out(self._rd, self._wr, name, msg + 4, addr)
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
            hup = [s in self._shut_both for _, s in live]  # select has no hang-up: shut down both ways is the one known
            rd, wr, ex = select.select(
                [s for i, s in live if events[i] & 1],
                [s for i, s in live if events[i] & 4],
                [s for _, s in live],
                0 if any(hup) else t,
            )
            for (i, s), h in zip(live, hup, strict=True):
                out[i] = (1 if s in rd else 0) | (4 if s in wr else 0) | (8 if s in ex else 0) | (16 if h else 0)
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
            if s in self._pending_err:
                g |= 8
            elif s in self._connecting and g & 20 and not g & 1:
                # a refused connect: Linux says POLLERR|POLLHUP|POLLOUT, macOS only POLLHUP. SO_ERROR is cleared by the
                # read, so it is kept for the guest's own getsockopt(SO_ERROR), once, as the kernel would give it
                self._connecting.discard(s)
                if err := s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR):
                    self._pending_err[s] = err
                    g |= 8
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
            self._listening.discard(s)
            self._connecting.discard(s)
            self._pending_err.pop(s, None)
            s.close()
        return 0

    def _n_shutdown(self, h: int, how: int) -> int:
        try:
            self.socks[h].shutdown(how)
        except OSError as e:
            return werr(e)
        if how == socket.SHUT_RDWR:
            self._shut_both.add(self.socks[h])
        return 0

    def _n_name(self, h: int, peer: int, sa: int, lenp: int) -> int:
        s = self.socks[h]
        try:
            addr = s.getpeername() if peer else s.getsockname()
        except OSError as e:
            return werr(e)
        sockaddr_out(self._rd, self._wr, sa, lenp, addr)
        return 0

    def _n_setopt(self, h: int, level: int, opt: int, valp: int, ln: int) -> int:
        """setsockopt (the import patched into the main module, tools/patch_main.mjs): applied to the host's socket."""
        s = self.socks[h]
        hl, ho = option(level, opt)
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
            return werr(e)
        return 0

    def _n_getopt(self, h: int, level: int, opt: int, valp: int, lenp: int) -> int:
        """getsockopt: the option is found by name in the host's socket module; an unknown one is ENOPROTOOPT."""
        s = self.socks[h]
        cap = int.from_bytes(self._rd(lenp, 4), "little")
        if level == 1 and opt in (3, 30, 38, 39):  # SO_TYPE, SO_ACCEPTCONN, SO_PROTOCOL, SO_DOMAIN: musl's numbers
            stream = s.type == socket.SOCK_STREAM
            val = {
                3: 1 if stream else 2,
                30: int(s in self._listening),
                38: s.proto or (6 if stream else 17),
                39: 2 if s.family == socket.AF_INET else 10,
            }
            raw = val[opt].to_bytes(4, "little")
        else:
            hl, ho = option(level, opt)
            if hl is None or ho is None:
                self.netlog.append(f"getsockopt {level}/{opt}: the host's socket module has no such option")
                return -GUEST_ERRNO["NOPROTOOPT"]
            try:
                if (level, opt) == (1, 4):
                    self._connecting.discard(s)
                if (level, opt) == (1, 4) and s in self._pending_err:
                    raw = self._pending_err.pop(s).to_bytes(4, "little")
                else:
                    raw = s.getsockopt(hl, ho, min(max(cap, 4), 1024))
            except OSError as e:
                self.netlog.append(f"getsockopt {level}/{opt} -> {e}")
                return werr(e)
            if (level, opt) in BOOL_OPTIONS and len(raw) == 4:
                raw = int(any(raw)).to_bytes(4, "little")
            if (level, opt) == (1, 4) and (
                err := int.from_bytes(raw[:4], "little")
            ):  # SO_ERROR: an errno, in the guest's numbers
                raw = (-werr(OSError(err, ""))).to_bytes(4, "little")
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
                return werr(e)
            finally:
                s.setblocking(True)
        except OSError as e:
            return werr(e)
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
        sp = self.ex["__stack_pointer"]
        orig = sp.value(ctx)
        args, cur, rid = _cif.call_args(self._rd, self._wr, cif, rvalue, avalue, orig)
        cur &= ~15  # the stack pointer stays 16-aligned (WASI wants out structures aligned to 8)
        if cur == orig:  # nothing on the stack: stackRestore(cur) is a no-op
            res = self._js_call(fn, args)
        else:
            sp.set_value(ctx, cur)
            try:
                res = self._js_call(fn, args)
            finally:
                sp.set_value(ctx, orig)
        _cif.store_result(self._wr, rvalue, rid, res)

    def _ffi_slot(self) -> int:
        """getEmptyTableSlot(): a freed slot (the last freed first), else the table grown by one."""
        self.closures_out += 1
        if self.free_slots:
            return self.free_slots.pop()
        return self.table.grow(self.cur[-1], 1, self._wt.Val.funcref(None))

    def _ffi_free(self, index: int) -> None:
        index &= _U32
        self.closures_out -= 1
        self.functions.pop(index, None)
        self._ffi_release(index)
        self.table.set(self.cur[-1], index, self._wt.Val.funcref(None))
        self.free_slots.append(index)

    def _ffi_prep(self, closure: int, cif: int, fun: int, user_data: int, codeloc: int) -> int:
        """Puts a host function of the closure's signature into table slot `codeloc`; when the guest calls it, the
        arguments are written to the stack as libffi's `avalue` and `fun(cif, ret, args, user_data)` is called."""
        wt = self._wt
        closure, cif, fun, user_data, codeloc = (x & _U32 for x in (closure, cif, fun, user_data, codeloc))
        params, results, rk, info, ret_by_arg, nargs, nfixed = _cif.closure_signature(self._rd, wt, cif)

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
        rk = state[5]  # the closure's own entry may be released while it runs (`state` is then cleared)
        ctx = self.cur[-1]
        sp = self.ex["__stack_pointer"]
        orig = sp.value(ctx)
        cif, fun, user_data, ret_ptr, args_ptr, cur = _cif.closure_frame(self._rd, self._wr, state, a, orig)
        sp.set_value(ctx, cur & ~15)  # 16-aligned, as the compiled code expects
        try:
            self._table_func(fun)(ctx, *(_to_wasm(x, "i32") for x in (cif, ret_ptr, args_ptr, user_data)))
        finally:
            sp.set_value(ctx, orig)
        return _cif.closure_result(self._rd, rk, ret_ptr)

    # ------------------------------------------------------------------ local time (_timecalc)
    def _t_localtime(self, t: int, tm: int) -> int:
        return _timecalc.t_localtime(self._wr, t, tm)

    def _t_mktime(self, tm: int) -> int:
        return _timecalc.t_mktime(self._rd, self._wr, tm)

    def _t_tzset(self, timezone: int, daylight: int, std_name: int, dst_name: int) -> None:
        _timecalc.t_tzset(self._wr, timezone, daylight, std_name, dst_name)

    # ------------------------------------------------------------------ signals and the runtime's name
    def _set_runtime(self) -> None:
        """`sys._emscripten_info.runtime`: the name goes into a block of the adapter's, once per start (after a
        restore too: the adapter's global is new, the string in the restored memory is not referenced again)"""
        from . import __version__

        b = f"pyodide-nojs {__version__}".encode() + b"\0"
        p = self._svc_ex["__nojs_set_runtime"](self.store, len(b)) & 0xFFFFFFFF
        if p:  # out of memory: no name is set, and the adapter's _Py_emscripten_runtime answers NULL
            self._wr(p, b)

    def _dl_depth(self) -> int:
        """How many NEEDED libraries the adapter may nest: what the wasm stack in force allows."""
        _engine.engine()
        return _engine.depth_cap(_engine._STATE["wasm_stack"])

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
        cell = self._svc_ex["__nojs_sigcell_addr"](self.cur[-1]) & 0xFFFFFFFF  # the adapter's, made on first call
        if not cell:
            raise RuntimeError("the guest is out of memory: no word for the signal")
        self._wr(cell, struct.pack("<I", signum))

    def _cpu_clock(self, cid: int, res: int, out: int) -> int:
        return _timecalc.cpu_clock(self._wr, cid, res, out)

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
            return werr(e)
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
        found = resolve_addrinfo(node, service, flags, family, type_, proto)
        if isinstance(found, int):
            return found
        entries, canon, type_, proto = found
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
        found = nameinfo(raw, flags)
        if isinstance(found, int):
            return found
        host, service = found
        for ptr, cap, text in ((node, nodelen, host), (serv, servlen, service)):
            if ptr and cap:
                b = text.encode()
                if len(b) >= cap:
                    return -12  # EAI_OVERFLOW
                self._wr(ptr, b + b"\0")
        return 0

    # what a net operation answers when the guest gave it a pointer outside its memory, or the host failed in a way
    # nobody foresaw: -EFAULT and -EIO, but the name functions answer in EAI_* (or a NULL pointer)
    NET_FAILS = {"getaddrinfo": (-11, -4), "getnameinfo": (-11, -4)}

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
                return other if name in self.NET_FAILS else werr(e)
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
            "depth",
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
            "depth": (self._dl_depth, ft(0)),
            "cpuclock": (self._cpu_clock, ft(3)),
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
        }
        fs = {"statvfs": (self._fs_statvfs, ft(2))}
        return loader, net, fs

    # ------------------------------------------------------------------ start
    def _start(self) -> None:
        wt = self._wt
        engine = _engine.engine()
        if not self._override_checked:
            self._override_checked = True
            warn, detail = override_warnings(self.asm_wasm, self.stdlib, self.data)
            for w in warn:
                log.warning("pyodide-nojs: %s", w)
            for d in detail:
                log.info("pyodide-nojs: %s", d)
        self._setup_root()
        assert self.root is not None
        self.store = store = wt.Store(engine)
        # growth that Pyodide's glue gets as a RangeError (a dylink table of 2^31 slots, memory beyond 4 GiB) fails
        # here as -1 from memory.grow / table.grow, which the loader turns into a dlerror (not an error of the host)
        store.set_limits(memory_size=MAX_MEMORY, table_elements=MAX_TABLE)
        wasi = wt.WasiConfig()
        wasi.env = self._wasi_env()
        wasi.preopen_dir(str(self.root), "/")
        for guest, host in self.mounts.items():
            wasi.preopen_dir(host, guest)
        if self.preopen_dev:  # the entropy device OpenSSL reads (/dev/urandom)
            if not os.path.isdir("/dev"):
                raise FileNotFoundError("preopen_dev: the host has no /dev (a POSIX host has the entropy device)")
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
            self._define_exit(linker)
            define_ops(linker)
            self.ex = _engine.LazyExports(store, linker.instantiate(store, main_mod), main_mod)
            self.memory, self.table = self.ex["memory"], self.ex["__indirect_function_table"]
            self.instances[0] = {"exports": MainExports(self.ex), "got": []}
            self._svc_ex = self.ex
            self.instances[0]["exports"].hidden.update(SERVICE_EXPORTS)
            self._drop_stubs()
            mods: dict[str, int] = {}
            for i in main_mod.imports:
                mods[i.module] = mods.get(i.module, 0) + 1
            self.summary = "fused: one module; its imports: " + ", ".join(f"{k} ({v})" for k, v in mods.items())
        else:
            main_path = self.asm_wasm or self.data / "pyodide.asm.wasm"
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
            done: list[Path] = []
            main_mod = _engine.load_module(main_path, wasm_opt=self.wasm_opt if self.asm_wasm else None, converted=done)
            if done:
                log.warning("pyodide-nojs: %s: converted from legacy exceptions at start; cached", main_path)
            imports = _wasm.func_imports(main_mod)
            got = [i.name for i in main_mod.imports if i.module == "GOT.func"]
            shim_mod = wt.Module(engine, wt.wat2wasm(_wasm.shim_wat(imports, fwd, got)))
            shim = wt.Linker(engine).instantiate(store, shim_mod).exports(store)

            linker = wt.Linker(engine)
            linker.define_wasi()
            self._define_exit(linker)
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
            self._define_exit(al)
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
            self._svc_ex = adapter
            self.instances[0]["exports"].hidden.update(SERVICE_EXPORTS)
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
        env = dict(BASE_ENV)
        if self.inherit_env:
            for k, v in os.environ.items():
                if not k or "=" in k or k in GUEST_OWN_ENV:
                    continue
                try:
                    k.encode()
                    v.encode()
                except UnicodeEncodeError:  # not UTF-8 (a surrogate-escaped byte): WASI's environment is text
                    log.warning("--inherit-env: %r is not valid UTF-8 and is not passed to the guest", k)
                    continue
                env[k] = v
        env.update(SSL_CERT_FILE="/etc/ssl/cert.pem", REQUESTS_CA_BUNDLE="/etc/ssl/cert.pem")
        env.update(self.env)
        return list(env.items())

    def _at_start(self) -> str:
        return f"__import__('pyodide_nojs_run').start({bool(self.site)!r})\n"

    def _guest_cstr(self, b: bytes) -> int:
        store = self.store
        p = self.ex["malloc"](store, len(b) + 1) & 0xFFFFFFFF
        self.memory.write(store, b + b"\0", p)
        return p

    def _chdir_home(self) -> None:
        """Pyodide's JavaScript starts the guest in HOME (the cwd is not in a snapshot: this is run after a restore)."""
        p = self._guest_cstr(b"/home/pyodide")
        rc = self.ex["chdir"](self.store, p)
        self.ex["free"](self.store, p)
        if rc != 0:  # not an assert: it must hold under python -O too
            raise RuntimeError("chdir to /home/pyodide failed (does a mount= replace /home?)")

    # ------------------------------------------------------------------ snapshot of the memory after `preload`
    def _snapshot_path(self) -> Path:
        files = [
            self.stdlib or self.data / "python_stdlib.zip",
            *(
                [self.data / "pyodide_fused.wasm"]
                if self.flavor == "fused"
                else [self.asm_wasm or self.data / "pyodide.asm.wasm", self.data / "adapter.wasm"]
            ),
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
                    [_engine._stamp(f.resolve()).decode() for f in files],
                    PYVER,
                    self.preload,
                    hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    hashlib.sha256(
                        b"".join(
                            g.name.encode() + b"\0" + g.read_bytes()
                            for g in sorted(GUEST.iterdir())
                            if g.suffix in GUEST_SUFFIXES
                        )
                    ).hexdigest(),
                    hashlib.sha256(f.read_bytes()).hexdigest()
                    if (f := self.data / "pyodide-lock.json").exists()
                    else None,
                    self._wasi_env(),
                    self.preopen_dev,
                    [isatty(fd) for fd in (0, 1, 2)],  # the guest decides buffering at init
                    # the time module read the host's zone at init (tzname, timezone, daylight, as _tzset_js gives them)
                    [time.localtime().tm_year, *_timecalc.year_minutes(time.localtime().tm_year)],
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
            and not self.inherit_env  # the snapshot is a file: the host's variables (secrets) must not get into it
            and _engine.env("PYODIDE_NOJS_SNAPSHOT") != "0"
        ):
            path = self._snapshot_path()
            if self._restore(path, slots):
                self.restored = self._started = True
                self._set_runtime()
                self._chdir_home()
                # the hash seed and `random`'s state are the snapshot's: a fresh seed, as a normal start has
                self.run(self._at_start() + 'import sys; "random" in sys.modules and __import__("random").seed()')
                return
        self.ex["emscripten_stack_init"](store)
        self.ex["__wasm_call_ctors"](store)
        self._set_runtime()
        self._chdir_home()
        # Pyodide's own main(): PyConfig (home "/", stdlib_dir the zip, no bytecode, argv), Py_InitializeFromConfig; its
        # argv[0] is Emscripten's thisProgram, "./this.program", which CPython resolves against the cwd
        # (argv and its string stay allocated: 23 bytes, as the stack copies of Emscripten's callMain would be)
        argv = self.ex["malloc"](store, 8) & 0xFFFFFFFF
        self.memory.write(store, self._guest_cstr(b"./this.program").to_bytes(4, "little") + bytes(4), argv)
        rc = self.ex["__main_argc_argv"](store, 1, argv)
        if rc:
            raise RuntimeError(f"Pyodide's main() returned {rc}: CPython did not start")
        self._started = True
        self.run(self._at_start())
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
        fresh = Pyodide(
            self.flavor,
            preopen_dev=self.preopen_dev,
            env=self.env,
            inherit_env=self.inherit_env,
            data=self.data,
            asm_wasm=self.asm_wasm,
            stdlib=self.stdlib,
        )
        fresh._override_checked = True  # the warnings were given at this interpreter's start
        with fresh:
            before = fresh._probe()
            rc = fresh.run(self.preload or "")
            if (
                rc != 0
                or len(fresh.instances) != 1
                or fresh.slots
                or fresh.host_state
                or fresh.closures_out
                or fresh._probe() != before
            ):
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
                _engine.private_dir(path.parent)
                with _engine.open_private(tmp) as f:
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
        wrapper = f"__import__('pyodide_nojs_run').run({f'/_pw_{self._runs}.py'!r}, {rc_file!r})\n"
        src = wrapper.encode() + b"\0"
        store = self.store
        p = self.ex["PyMem_Malloc"](store, len(src))
        self._wr(p, src)
        try:
            rc = self.ex["PyRun_SimpleString"](store, p)
        except (
            GuestExit
        ) as e:  # the process ended (exit(), os._exit(), a signal's default action): this interpreter is gone
            self._exited = rc = e.status
        except self._wt.Trap as e:  # abort(), a failed assert, an unreachable: the guest is dead
            first = str(e).strip().splitlines()[0] if str(e).strip() else "trap"
            print(f"pyodide-nojs: the guest trapped: {first}", file=sys.stderr)
            self._exited = 134  # 128 + SIGABRT, as a process that aborts
            rc = 134
        except (
            Exception
        ) as e:  # a host function failed on purpose (JavaScript's TypeError, a pointer outside the memory)
            tb = traceback.extract_tb(e.__traceback__)[-1]  # where, for a host that can not be reached to debug
            print(
                f"pyodide-nojs: a host function failed, the guest is dead: {type(e).__name__}: {e}"
                f" (at {Path(tb.filename).name}:{tb.lineno}, in {tb.name})",
                file=sys.stderr,
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
        self.slots.clear()
        self.instances = [None]
        if self.root is not None:
            shutil.rmtree(self.root, ignore_errors=True)
            self.root = None
        self.free_slots.clear()
        self.host_state = False
        self.closures_out = 0
        self.functions.clear()
        self.func_pool.clear()
        self.live_funcs.clear()
        self._started = False

    def __enter__(self) -> Pyodide:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
