"""Append `memory` (the imported memory 0) to a module's export section: add_memory_export.py IN.wasm OUT.wasm"""

import sys


def leb(b, i):
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if not c & 0x80:
            return r, i


def enc(n):
    out = bytearray()
    while True:
        c = n & 0x7F
        n >>= 7
        out.append(c | (0x80 if n else 0))
        if not n:
            return bytes(out)


b = bytearray(open(sys.argv[1], "rb").read())
i = 8
while i < len(b):
    sid = b[i]
    size, j = leb(b, i + 1)
    if sid == 7:
        cnt, k = leb(b, j)
        body = enc(cnt + 1) + bytes(b[k : j + size]) + enc(6) + b"memory" + b"\x02\x00"
        b[i : j + size] = bytes([7]) + enc(len(body)) + body
        break
    i = j + size
open(sys.argv[2], "wb").write(b)
