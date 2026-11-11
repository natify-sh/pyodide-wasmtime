"""libffi's `ffi_cif` and `ffi_type` records of the guest (the Emscripten port: `ffi_call_js`,
`ffi_prep_closure_loc_js`) read and written as the JavaScript of pyodide.asm.mjs does: the arguments of a call, the
signature of a closure, the result. Functions of the guest's memory, which they are given as `rd` and `wr`; the
host's calls into the guest stay in `Pyodide`."""

from __future__ import annotations

import struct
from typing import Any

from ._consts import Big, GuestFault, Reader, Writer, num, to_wasm


# ------------------------------------------------------------------ libffi's emscripten port: calls and closures
# What pyodide.asm.mjs does in ffi_call_js / ffi_prep_closure_loc_js, with the type of the function from the wasm
# table (a JavaScript call tolerates any signature: extra arguments are dropped, missing ones are undefined).
def down(cur: int, size: int, align: int) -> int:
    """cur - size, aligned down, on the guest's stack: GuestFault if a size from the guest takes it below 0."""
    new = (cur - size) & ~(max(align, 1) - 1)
    if size < 0 or new < 0:
        raise GuestFault(f"{size:#x} bytes do not fit on the stack")
    return new


def u32(rd: Reader, a: int) -> int:
    return struct.unpack("<I", rd(a, 4))[0]


def unbox(rd: Reader, t: int) -> tuple[int, int]:
    """A struct of one member is that member (libffi's JS `unbox_small_structs`): (type pointer, type id)."""
    for _depth in range(64):
        tid = struct.unpack("<H", rd(t + 6, 2))[0]
        if tid != 13:
            return t, tid
        first, second = struct.unpack("<II", rd(u32(rd, t + 8), 8))
        if first == 0:
            return t, 0
        if second != 0:
            return t, 13
        t = first
    raise RuntimeError("an ffi_type of structs inside structs, too deep")


def call_args(rd: Reader, wr: Writer, cif: int, rvalue: int, avalue: int, cur: int) -> tuple[list[Any], int, int]:
    """`ffi_call`'s arguments of the callee from the cif and `avalue` (the by-value ones are put on the guest's stack
    below `cur`, its pointer) -> (the arguments, the new stack pointer, the id of the return type)"""
    _abi, nargs, atp, rtp, _bytes, _flags, nfixed = struct.unpack("<7I", rd(cif, 28))
    if nargs > 1000:  # a wasm function has at most 1000 parameters
        raise RuntimeError(f"a cif of {nargs} arguments")
    _rp, rid = unbox(rd, rtp)
    if rid == 15:
        raise RuntimeError("complex ret marshalling nyi")
    if rid > 15:
        raise RuntimeError(f"Unexpected rtype {rid}")
    args: list = []
    ret_by_arg = rid in (4, 13)
    if ret_by_arg:
        args.append(rvalue)
    aptrs = struct.unpack(f"<{nargs}I", rd(avalue, 4 * nargs)) if nargs else ()
    atypes = struct.unpack(f"<{nargs}I", rd(atp, 4 * nargs)) if nargs else ()
    for i in range(nfixed):
        ap = aptrs[i]
        tp, tid = unbox(rd, atypes[i])
        if tid in (1, 9, 10, 14):
            args.append(u32(rd, ap))
        elif tid == 2:
            args.append(struct.unpack("<f", rd(ap, 4))[0])
        elif tid == 3:
            args.append(struct.unpack("<d", rd(ap, 8))[0])
        elif tid in (5, 6):
            args.append(struct.unpack("<B" if tid == 5 else "<b", rd(ap, 1))[0])
        elif tid in (7, 8):
            args.append(struct.unpack("<H" if tid == 7 else "<h", rd(ap, 2))[0])
        elif tid in (11, 12):
            args.append(Big(struct.unpack("<Q", rd(ap, 8))[0]))
        elif tid == 4:
            args.extend(Big(x) for x in struct.unpack("<QQ", rd(ap, 16)))
        elif tid == 13:
            size, align = struct.unpack("<IH", rd(tp, 6))
            cur = down(cur, size, align)
            wr(cur, rd(ap, size))
            args.append(cur)
        else:
            raise RuntimeError("complex marshalling nyi" if tid == 15 else f"Unexpected type {tid}")
    if nfixed != nargs:  # the variadic part: a block on the stack, its address the last argument
        structs = []
        for i in range(nargs - 1, nfixed - 1, -1):
            ap = aptrs[i]
            tp, tid = unbox(rd, atypes[i])
            if tid in (5, 6):
                cur = down(cur, 1, 1)
                wr(cur, rd(ap, 1))
            elif tid in (7, 8):
                cur = down(cur, 2, 2)
                wr(cur, rd(ap, 2))
            elif tid in (1, 9, 10, 14, 2):
                cur = down(cur, 4, 4)
                wr(cur, rd(ap, 4))
            elif tid in (3, 11, 12):
                cur = down(cur, 8, 8)
                wr(cur, rd(ap, 8))
            elif tid == 4:
                cur = down(cur, 16, 8)
                wr(cur, rd(ap, 16))
            elif tid == 13:
                cur = down(cur, 4, 4)
                structs.append((cur, ap, *struct.unpack("<IH", rd(tp, 6))))
            else:
                raise RuntimeError("complex arg marshalling nyi" if tid == 15 else f"Unexpected argtype {tid}")
        args.append(cur)
        for target, ap, size, align in structs:
            cur = down(cur, size, align)
            wr(cur, rd(ap, size))
            wr(target, struct.pack("<I", cur))
    return args, cur, rid


def store_result(wr: Writer, rvalue: int, rid: int, res: Any) -> None:
    """The callee's result `res` (a JavaScript value) into the guest's `rvalue`, by the id of the return type."""
    ret_by_arg = rid in (4, 13)
    if ret_by_arg:
        return
    if rid in (1, 9, 10, 14):
        wr(rvalue, struct.pack("<I", num(res, 32)))
    elif rid in (5, 6):
        wr(rvalue, struct.pack("<B", num(res, 8)))
    elif rid in (7, 8):
        wr(rvalue, struct.pack("<H", num(res, 16)))
    elif rid in (2, 3):
        if isinstance(res, Big):
            raise TypeError("Cannot mix BigInt and other types")
        x = float("nan") if res is None else float(res)
        try:
            wr(rvalue, struct.pack("<f" if rid == 2 else "<d", x))
        except OverflowError:  # a float32 too large for it is an infinity
            wr(rvalue, struct.pack("<f", float("inf") if x > 0 else float("-inf")))
    elif rid in (11, 12):
        if not isinstance(res, Big):
            raise TypeError(f"Cannot convert {res} to a BigInt")
        wr(rvalue, struct.pack("<Q", res & 0xFFFFFFFFFFFFFFFF))


def closure_signature(
    rd: Reader, wt: Any, cif: int
) -> tuple[list[Any], list[Any], str, list[tuple[int, int, int]], bool, int, int]:
    """The wasm signature of a closure of the cif and what its trampoline needs of it -> (the parameters, the results,
    the kind of result, (type id, size, alignment) of each argument, whether the result is returned by argument,
    nargs, nfixed). `wt` is the wasmtime module."""
    _abi, nargs, atp, rtp, _bytes, _flags, nfixed = struct.unpack("<7I", rd(cif, 28))
    if nargs > 1000:  # a wasm function has at most 1000 parameters
        raise RuntimeError(f"a cif of {nargs} arguments")
    _rp, rid = unbox(rd, rtp)
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
    atypes = struct.unpack(f"<{nargs}I", rd(atp, 4 * nargs)) if nargs else ()
    info = []  # (type id, size, alignment) of each argument
    for t in atypes:
        tp, tid = unbox(rd, t)
        size, align = struct.unpack("<IH", rd(tp, 6))
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
    return params, results, rk, info, ret_by_arg, nargs, nfixed


def closure_frame(rd: Reader, wr: Writer, state: list, a: tuple, cur: int) -> tuple[int, int, int, int, int, int]:
    """A closure's call as libffi's `avalue` on the guest's stack below `cur`, from the wasm arguments `a` and the
    closure's `state` -> (cif, fun, user_data, the return pointer, the arguments' pointer, the new stack pointer)"""
    closure, nargs, nfixed, info, ret_by_arg, rk = state
    _index, cif, fun, user_data = struct.unpack("<IIII", rd(closure, 16))
    j = 0
    if ret_by_arg:
        ret_ptr = a[0] & 0xFFFFFFFF
        j = 1
    else:
        cur = down(cur, 8, 8)
        ret_ptr = cur
    cur = down(cur, 4 * nargs, 1)
    args_ptr = cur
    slots: dict[int, int] = {}

    def put(c: int, size: int, align: int, data: bytes) -> None:
        nonlocal cur
        cur = down(cur, size, align)
        slots[c] = cur
        wr(cur, data)

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
            put(c, size, align, rd(v & 0xFFFFFFFF, size))
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
            put(c, size, align, rd(u32(rd, varargs), size))
        else:
            slots[c] = varargs
        varargs += 4
    if nargs:
        wr(args_ptr, struct.pack(f"<{nargs}I", *(slots[c] for c in range(nargs))))
    return cif, fun, user_data, ret_ptr, args_ptr, cur


def closure_result(rd: Reader, rk: str, ret_ptr: int) -> Any:
    """What the closure returns to the guest, read from `ret_ptr` by the kind of result."""
    if rk == "v":
        return None
    raw = rd(ret_ptr, 8)
    if rk == "i":
        return to_wasm(struct.unpack("<I", raw[:4])[0], "i32")
    if rk == "j":
        return to_wasm(Big(struct.unpack("<Q", raw)[0]), "i64")
    if rk == "d":
        return struct.unpack("<d", raw)[0]
    if rk == "f":
        return struct.unpack("<f", raw[:4])[0]
    return None
