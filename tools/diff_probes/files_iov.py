# type: ignore
# ruff: noqa
# fmt: off
# readv, writev, preadv, pwritev with several buffers, and pread/pwrite above 64 KiB
def new(data=b'0123456789', flags=os.O_RDWR):
    w(B + '/io', data)
    return os.open(B + '/io', flags)
def content(): return open(B + '/io', 'rb').read()
def rv(data, sizes, off=None):
    fd = new(data); bs = [bytearray(s) for s in sizes]
    n = os.readv(fd, bs) if off is None else os.preadv(fd, bs, off)
    return (n, [bytes(b) for b in bs], os.lseek(fd, 0, 1))
def wv(bufs, off=None):
    fd = new(b''); n = os.writev(fd, bufs) if off is None else os.pwritev(fd, bufs, off)
    return (n, content(), os.lseek(fd, 0, 1))
for name, sizes in (('2x4', (4, 4)), ('3 uneven', (1, 5, 2)), ('past the end', (6, 6)), ('empty in the middle', (3, 0, 3)), ('empty first', (0, 4)), ('all empty', (0, 0))):
    case('readv ' + name, lambda: rv(b'0123456789', sizes))
    case('preadv ' + name, lambda: rv(b'0123456789', sizes, 2))
    case('writev ' + name, lambda: wv([b'ab' * s for s in sizes]))
    case('pwritev ' + name, lambda: wv([b'ab' * s for s in sizes], 3))
case('readv short file', lambda: rv(b'abc', (2, 2, 2)))
case('readv at the end', lambda: (lambda fd: (os.lseek(fd, 0, 2), os.readv(fd, [bytearray(2), bytearray(2)]))[1])(new()))
case('preadv at the end', lambda: rv(b'abc', (2, 2), 3))
case('readv 1000 one-byte', lambda: (lambda fd, bs: (os.readv(fd, bs), b''.join(bs)[:5], len(set(map(bytes, bs)))))(new(bytes(range(256)) * 4), [bytearray(1) for _ in range(1000)]))
case('preadv 1000 one-byte', lambda: (lambda fd, bs: (os.preadv(fd, bs, 7), bytes(b''.join(bs)[:3]), os.lseek(fd, 0, 1)))(new(bytes(range(256)) * 4), [bytearray(1) for _ in range(1000)]))
case('writev 1000 one-byte', lambda: (lambda fd: (os.writev(fd, [bytes([i % 256]) for i in range(1000)]), len(content()), content()[999]))(new(b'')))
case('pwritev 1000 one-byte', lambda: (lambda fd: (os.pwritev(fd, [bytes([i % 256]) for i in range(1000)], 5), len(content()), content()[1004]))(new(b'')))
case('readv 2000 buffers', lambda: (lambda fd, bs: os.readv(fd, bs))(new(b'x' * 3000), [bytearray(1) for _ in range(2000)]))
case('readv bad fd', lambda: os.readv(999, [bytearray(1), bytearray(1)]))
case('writev bad fd', lambda: os.writev(999, [b'a', b'b']))
case('preadv bad fd', lambda: os.preadv(999, [bytearray(1), bytearray(1)], 0))
case('pwritev write-only reading', lambda: os.preadv(new(flags=os.O_WRONLY), [bytearray(1), bytearray(1)], 0))
case('readv on a write-only fd', lambda: os.readv(new(flags=os.O_WRONLY), [bytearray(1), bytearray(1)]))
case('writev on a read-only fd', lambda: os.writev(new(flags=os.O_RDONLY), [b'a', b'b']))
case('writev second buffer large', lambda: wv([b'a', b'b' * 200000])[0])
case('readv second buffer large', lambda: rv(b'c' * 300000, (1, 200000))[0])
case('pread 5 MB of 10 MB', lambda: len(os.pread(new(b'x' * 10 ** 7), 5000000, 0)))
case('pread 10 MB all', lambda: len(os.pread(new(b'x' * 10 ** 7), 10 ** 7, 0)))
case('pread 200000 at 5', lambda: (lambda d: (len(d), d[:3]))(os.pread(new(bytes(range(256)) * 1000), 200000, 5)))
case('pread past the end of a 100 KB file', lambda: len(os.pread(new(b'x' * 100000), 200000, 50000)))
case('pread 70000 of a 65536 file', lambda: len(os.pread(new(b'x' * 65536), 70000, 0)))
case('pread at the end', lambda: os.pread(new(b'x' * 100), 70000, 100))
case('pwrite 300000', lambda: (lambda fd: (os.pwrite(fd, b'z' * 300000, 10), len(content()), content()[300009:300010]))(new()))
case('pwrite 5 MB', lambda: (lambda fd: (os.pwrite(fd, b'z' * 5000000, 0), len(content())))(new(b'')))
case('pread leaves the position', lambda: (lambda fd: (len(os.pread(fd, 100000, 0)), os.lseek(fd, 0, 1)))(new(b'x' * 200000)))
case('os.read 5 MB', lambda: len(os.read(new(b'x' * 10 ** 7), 5000000)))
