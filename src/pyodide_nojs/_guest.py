"""The guest facilities that several components of the host share: the wasm store, the main module's exports, memory and
table, the stack of call contexts, and the accessors of the guest's memory.

One `Guest` per `Pyodide`; components hold it as a read-only handle. Only `bind` sets the wasm objects, and the stack of
contexts (`cur`) is changed only here: `wrap` pushes the Caller of a running host function and pops it again."""

from __future__ import annotations

import logging
from typing import Any

from ._consts import GUEST_ERRNO, GuestFault
from ._sockaddr import werr

log = logging.getLogger("pyodide_nojs")


class Guest:
    def __init__(self) -> None:
        self.store: Any = None
        self.ex: Any = None
        self.memory: Any = None
        self.table: Any = None
        self.cur: list = []  # the Caller (or the Store) of the running host function

    def bind(self, store: Any, ex: Any) -> None:
        """A new guest: its store and the main module's exports (the memory and the table are two of them); the
        context stack is the store alone."""
        self.store, self.ex = store, ex
        self.memory, self.table = ex["memory"], ex["__indirect_function_table"]
        self.cur[:] = [store]

    def wrap(self, fn, handle=None, void: bool = False):
        """A host function for the wasm: the Caller is `cur[-1]` while `fn(*args)` runs, popped on every way out (the
        push and pop are inline: this is the path of every host call). An `Exception` goes to `handle(exc)`, whose
        result is the answer (none: it goes on); `void`: the answer is None whatever `fn` returns."""

        def f(caller, *args):
            cur = self.cur
            cur.append(caller)
            try:
                r = fn(*args)
            except Exception as e:
                if handle is None:
                    raise
                r = handle(e)
            finally:
                cur.pop()
            return None if void else r

        return f

    def _span(self, a: int, n: int) -> int:
        """The guest address a (wasmtime passes i32 as SIGNED: -1 is 0xFFFFFFFF) after checking that [a, a+n) lies in
        the memory; n is a size_t, so a negative one is a huge one. GuestFault (EFAULT) otherwise."""
        a = a + (1 << 32) if a < 0 else a
        n = n + (1 << 32) if n < 0 else n
        if a >> 32 or n >> 32 or a + n > self.memory.data_len(self.cur[-1]):
            raise GuestFault(f"{a:#x}+{n:#x} is outside the memory")
        return a

    def rd(self, a: int, n: int) -> bytes:
        a = self._span(a, n)
        return bytes(self.memory.read(self.cur[-1], a, a + (n + (1 << 32) if n < 0 else n)))

    def wr(self, a: int, data: bytes) -> None:
        data = bytes(data)
        self.memory.write(self.cur[-1], data, self._span(a, len(data)))

    def cstr(self, p: int) -> str | None:
        """The NUL-terminated string at p (at most 4096 bytes: GuestFault if there is no end inside the memory)."""
        if not p:
            return None
        out = bytearray()
        for i in range(4096):
            b = self.rd(p + i, 1)  # GuestFault past the end of memory
            if b == b"\0":
                return out.decode("utf-8", "replace")
            out += b
        raise GuestFault("string too long")

    def malloc(self, n: int) -> int:
        """The guest's malloc: its address as an unsigned number (0: no memory)."""
        return self.ex["malloc"](self.cur[-1], n) & 0xFFFFFFFF

    def free(self, p: int) -> None:
        self.ex["free"](self.cur[-1], p)

    def guest_cstr(self, b: bytes) -> int:
        """`b` and a NUL in a new block (outside any host function: the store is the context)."""
        store = self.store
        p = self.ex["malloc"](store, len(b) + 1) & 0xFFFFFFFF
        self.memory.write(store, b + b"\0", p)
        return p

    # what a net operation answers when the guest gave it a pointer outside its memory, or the host failed in a way
    # nobody foresaw: -EFAULT and -EIO, but the name functions answer in EAI_* (or a NULL pointer)
    NET_FAILS = {"getaddrinfo": (-11, -4), "getnameinfo": (-11, -4)}

    def wrap_net(self, name: str, fn):
        """No exception of a net operation reaches the wasm (it would be a trap that ends the interpreter): a pointer
        outside the memory is EFAULT, a host error is its errno, anything else is logged and EIO."""
        fault, other = self.NET_FAILS.get(name, (-GUEST_ERRNO["FAULT"], -GUEST_ERRNO["IO"]))

        def handle(e: Exception) -> int:
            if isinstance(e, GuestFault):
                return fault
            if isinstance(e, OSError):
                return other if name in self.NET_FAILS else werr(e)
            log.exception("[net] %s failed", name)
            return other

        return self.wrap(fn, handle)
