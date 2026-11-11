# ruff: noqa
# type: ignore
# mmap: length x offset x access, prot x flags, anonymous, operations on a mapping, file changes under a mapping.
import mmap
import os

PAT = bytes(i % 251 for i in range(100000))
F = B + "/f"
with open(F, "wb") as _f:
    _f.write(PAT)
with open(B + "/empty", "wb"):
    pass
with open(B + "/small", "wb") as _f:
    _f.write(b"0123456789")
os.makedirs(B + "/d")
open(B + "/wo", "wb").write(PAT)
os.chmod(B + "/wo", 0o200)


def view(m):
    try:
        n = len(m)
        return (n, bytes(m[:4]), bytes(m[n - 2 :]) if n >= 2 else b"")
    finally:
        m.close()


def mk(path, flags=os.O_RDWR, **kw):
    fd = os.open(path, flags)
    try:
        return view(mmap.mmap(fd, **kw))
    finally:
        os.close(fd)


case("const-allocgran", lambda: mmap.ALLOCATIONGRANULARITY)
case("const-pagesize", lambda: mmap.PAGESIZE)
case(
    "const-flags",
    lambda: (
        mmap.MAP_SHARED,
        mmap.MAP_PRIVATE,
        mmap.MAP_ANON,
        mmap.MAP_ANONYMOUS,
        mmap.PROT_READ,
        mmap.PROT_WRITE,
        mmap.PROT_EXEC,
    ),
)
case("const-madv", lambda: sorted(n for n in dir(mmap) if n.startswith("MADV_")))
case("const-names", lambda: sorted(n for n in dir(mmap) if n.isupper()))

LENS = [
    0,
    1,
    100,
    4095,
    4096,
    4097,
    65536,
    100000,
    100001,
    2**20,
    2**31 - 1,
    2**31,
    2**32,
    2**40,
    2**62,
    2**63 - 1,
    2**63,
    -1,
]
OFFS = [
    0,
    1,
    4095,
    4096,
    65535,
    65536,
    65537,
    100000,
    100001,
    2**20,
    2**31,
    2**32,
    2**32 + 65536,
    2**40,
    2**63 - 1,
    2**63,
    -1,
    -4096,
]

for ln in LENS:
    for acc in ("default", "READ", "WRITE", "COPY"):
        kw = {} if acc == "default" else {"access": getattr(mmap, "ACCESS_" + acc)}
        case("len-%d-%s" % (ln, acc), mk, F, os.O_RDWR, length=ln, **kw)
for off in OFFS:
    for ln in (0, 1, 4096, 30000):
        case("off-%d-len%d" % (off, ln), mk, F, os.O_RDWR, length=ln, access=mmap.ACCESS_READ, offset=off)
    case("off-%d-write" % off, mk, F, os.O_RDWR, length=100, access=mmap.ACCESS_WRITE, offset=off)
    case("off-%d-copy" % off, mk, F, os.O_RDWR, length=100, access=mmap.ACCESS_COPY, offset=off)

# flags x prot x open mode
for fl in ("SHARED", "PRIVATE", 0, 3, 4, "SHARED|PRIVATE"):
    for pr in (0, 1, 2, 3, 4, 5, 7, 8, -1):
        for om, on in ((os.O_RDONLY, "ro"), (os.O_WRONLY, "wo"), (os.O_RDWR, "rw")):
            if isinstance(fl, str):
                flv = 0
                for part in fl.split("|"):
                    flv |= getattr(mmap, "MAP_" + part)
            else:
                flv = fl
            case("fp-%s-prot%d-%s" % (fl, pr, on), mk, F, om, length=4096, flags=flv, prot=pr)
for acc in (0, 1, 2, 3, 4, -1, 99):
    case("access-%d" % acc, mk, F, os.O_RDWR, length=100, access=acc)
case("access-and-flags", mk, F, os.O_RDWR, length=100, access=mmap.ACCESS_READ, flags=mmap.MAP_SHARED)
case("access-and-prot", mk, F, os.O_RDWR, length=100, access=mmap.ACCESS_READ, prot=3)
case("tagname", mk, F, os.O_RDWR, length=100, tagname="x")

# the file argument
case("fd-empty-length0", mk, B + "/empty", os.O_RDWR, length=0)
case("fd-empty-length1", mk, B + "/empty", os.O_RDWR, length=1)
case("fd-empty-length1-read", mk, B + "/empty", os.O_RDONLY, length=1, access=mmap.ACCESS_READ)
case("fd-empty-length4096-write", mk, B + "/empty", os.O_RDWR, length=4096, access=mmap.ACCESS_WRITE)
case("fd-dir", lambda: mmap.mmap(os.open(B + "/d", os.O_RDONLY), 100, access=mmap.ACCESS_READ))
case("fd-dir-length0", lambda: mmap.mmap(os.open(B + "/d", os.O_RDONLY), 0, access=mmap.ACCESS_READ))
case("fd-wo-file-shared-write", mk, B + "/f", os.O_WRONLY, length=100, access=mmap.ACCESS_WRITE)
case("fd-wo-file-read", mk, B + "/f", os.O_WRONLY, length=100, access=mmap.ACCESS_READ)
case("fd-wo-file-copy", mk, B + "/f", os.O_WRONLY, length=100, access=mmap.ACCESS_COPY)
case("fd-ro-write", mk, B + "/f", os.O_RDONLY, length=100, access=mmap.ACCESS_WRITE)
case("fd-ro-copy", mk, B + "/f", os.O_RDONLY, length=100, access=mmap.ACCESS_COPY)
case("fd-closed", lambda: mmap.mmap(999, 100))
case("fd-neg-2", lambda: mmap.mmap(-2, 100))
case("fd-neg-1-len0", lambda: mmap.mmap(-1, 0))
case("fd-str", lambda: mmap.mmap("x", 100))
case("fd-None", lambda: mmap.mmap(None, 100))
case("fd-float", lambda: mmap.mmap(1.5, 100))
case("fd-stdin", lambda: mmap.mmap(0, 100, access=mmap.ACCESS_READ))
case("fd-stdout", lambda: mmap.mmap(1, 100, access=mmap.ACCESS_READ))
case("fd-pipe", lambda: (lambda p: mmap.mmap(p[0], 100, access=mmap.ACCESS_READ))(os.pipe()))
case("fd-fileobj-fileno", lambda: view(mmap.mmap(open(F, "r+b").fileno(), 100)))
case("fd-devnull", lambda: mmap.mmap(os.open("/dev/null", os.O_RDWR), 100))
case("fd-devzero", lambda: mmap.mmap(os.open("/dev/zero", os.O_RDWR), 100))
case("fd-dup", lambda: view(mmap.mmap(os.dup(os.open(F, os.O_RDWR)), 100)))
case("fd-kwarg-fileno", lambda: view(mmap.mmap(fileno=os.open(F, os.O_RDWR), length=10)))
case("fd-no-args", lambda: mmap.mmap())
case("fd-extra-args", lambda: mmap.mmap(-1, 10, 1, 2, 3, 4, 5, 6))

# anonymous
for ln in (0, 1, 100, 4096, 65536, 65537, 2**20, 2**31, 2**32, 2**40, 2**63 - 1, -1):
    case("anon-len-%d" % ln, lambda ln=ln: view(mmap.mmap(-1, ln)))
for fl in (mmap.MAP_SHARED, mmap.MAP_PRIVATE, 0, mmap.MAP_SHARED | mmap.MAP_PRIVATE):
    for pr in (0, 1, 2, 3, 7):
        case("anon-flags%d-prot%d" % (fl, pr), lambda fl=fl, pr=pr: view(mmap.mmap(-1, 4096, flags=fl, prot=pr)))
for acc in (0, 1, 2, 3):
    case("anon-access-%d" % acc, lambda acc=acc: view(mmap.mmap(-1, 4096, access=acc)))
case("anon-offset", lambda: view(mmap.mmap(-1, 4096, offset=4096)))
case("anon-offset0", lambda: view(mmap.mmap(-1, 4096, offset=0)))
case("anon-zeroed", lambda: bytes(mmap.mmap(-1, 70000)[:]).count(0))
case("anon-flag-ANON-fd--1", lambda: view(mmap.mmap(-1, 100, flags=mmap.MAP_ANONYMOUS | mmap.MAP_PRIVATE)))
case(
    "anon-flag-ANON-fd-file",
    lambda: view(mmap.mmap(os.open(F, os.O_RDWR), 100, flags=mmap.MAP_ANONYMOUS | mmap.MAP_PRIVATE)),
)


# operations
def fresh():
    try:
        os.chmod(F, 0o644)
    except OSError:
        pass
    with open(F, "wb") as f:
        f.write(PAT)


def rw(fn, length=10000, offset=0, access=mmap.ACCESS_WRITE, closefd=False):
    fresh()
    fd = os.open(F, os.O_RDWR)
    m = mmap.mmap(fd, length, access=access, offset=offset)
    if closefd:
        os.close(fd)
    try:
        return fn(m, fd)
    finally:
        try:
            m.close()
        except Exception:
            pass
        if not closefd:
            os.close(fd)


def contents():
    with open(F, "rb") as f:
        return f.read()


case(
    "op-write-flush-close",
    lambda: rw(lambda m, fd: (m.__setitem__(slice(0, 4), b"ZZZZ"), m.flush(), m.close(), contents()[:6])[3]),
)
case(
    "op-write-close-noflush",
    lambda: rw(lambda m, fd: (m.__setitem__(slice(0, 4), b"ZZZZ"), m.close(), contents()[:6])[2]),
)
case("op-write-noclose-read-file", lambda: rw(lambda m, fd: (m.__setitem__(slice(0, 4), b"ZZZZ"), contents()[:6])[1]))
case(
    "op-write-flush-noclose-read-file",
    lambda: rw(lambda m, fd: (m.__setitem__(slice(0, 4), b"ZZZZ"), m.flush(), contents()[:6])[2]),
)
case(
    "op-write-flush-range",
    lambda: rw(lambda m, fd: (m.__setitem__(slice(5, 9), b"ZZZZ"), m.flush(0, 4096), m.close(), contents()[3:11])[3]),
)
case("op-flush-offset-unaligned", lambda: rw(lambda m, fd: m.flush(1, 10)))
case("op-flush-offset-aligned", lambda: rw(lambda m, fd: m.flush(4096, 10)))
case("op-flush-beyond", lambda: rw(lambda m, fd: m.flush(0, 10**6)))
case("op-flush-neg", lambda: rw(lambda m, fd: m.flush(-1, 1)))
case("op-flush-readonly", lambda: rw(lambda m, fd: m.flush(), access=mmap.ACCESS_READ))
case("op-flush-copy", lambda: rw(lambda m, fd: m.flush(), access=mmap.ACCESS_COPY))
case("op-flush-after-close", lambda: rw(lambda m, fd: (m.close(), m.flush())))
case("op-flush-after-fdclose", lambda: rw(lambda m, fd: (m.__setitem__(0, 1), m.flush()), closefd=True))
case(
    "op-close-after-fdclose-data",
    lambda: rw(lambda m, fd: (m.__setitem__(0, 9), m.close(), contents()[:2])[2], closefd=True),
)
case("op-write-ro", lambda: rw(lambda m, fd: m.__setitem__(0, 1), access=mmap.ACCESS_READ))
case(
    "op-write-copy-private",
    lambda: rw(lambda m, fd: (m.__setitem__(0, 1), m.flush(), m.close(), contents()[:2])[3], access=mmap.ACCESS_COPY),
)
case("op-write-copy-read-back", lambda: rw(lambda m, fd: (m.__setitem__(0, 1), m[:3])[1], access=mmap.ACCESS_COPY))
case("op-write-method", lambda: rw(lambda m, fd: (m.write(b"abc"), m.tell(), m[:5])[1:]))
case("op-write-byte", lambda: rw(lambda m, fd: (m.write_byte(7), m.tell(), m[:3])[1:]))
case("op-write-ro-method", lambda: rw(lambda m, fd: m.write(b"abc"), access=mmap.ACCESS_READ))
case("op-write-beyond", lambda: rw(lambda m, fd: m.write(b"x" * 20000)))
case("op-set-beyond", lambda: rw(lambda m, fd: m.__setitem__(10000, 1)))
case("op-get-beyond", lambda: rw(lambda m, fd: m[10000]))
case("op-get-neg", lambda: rw(lambda m, fd: m[-1]))
case("op-slice-step", lambda: rw(lambda m, fd: bytes(m[:20:5])))
case("op-slice-neg-step", lambda: rw(lambda m, fd: bytes(m[20:0:-5])))
case("op-slice-assign-wrong-size", lambda: rw(lambda m, fd: m.__setitem__(slice(0, 4), b"ab")))
case("op-slice-assign-step", lambda: rw(lambda m, fd: (m.__setitem__(slice(0, 8, 2), b"abcd"), m[:8])[1]))
case(
    "op-find",
    lambda: rw(
        lambda m, fd: (
            m.find(b"\x05\x06\x07"),
            m.find(b"nope"),
            m.find(b"\x05", 10),
            m.find(b"\x05", -100, -1),
            m.rfind(b"\x05"),
        )
    ),
)
case("op-find-int", lambda: rw(lambda m, fd: m.find(5)))
case("op-find-empty", lambda: rw(lambda m, fd: (m.find(b""), m.find(b"", 5), m.find(b"", 99999))))
case("op-readline", lambda: rw(lambda m, fd: (m.readline(), m.tell())))
case(
    "op-readline-newline",
    lambda: rw(lambda m, fd: (m.__setitem__(slice(0, 4), b"ab\ncd"[:4]), m.readline(), m.tell())[1:]),
)
case(
    "op-read-methods",
    lambda: rw(lambda m, fd: (m.read(3), m.read(0), m.read(-1)[:3], m.tell(), m.read(5), m.seek(0), m.read_byte())),
)
case("op-seek", lambda: rw(lambda m, fd: (m.seek(5), m.seek(5, 1), m.seek(-1, 2), m.tell())))
case("op-seek-bad", lambda: rw(lambda m, fd: m.seek(20000)))
case("op-seek-bad-whence", lambda: rw(lambda m, fd: m.seek(0, 9)))
case("op-size", lambda: rw(lambda m, fd: m.size()))
case("op-size-after-close", lambda: rw(lambda m, fd: (m.close(), m.size())))
case("op-size-anon", lambda: mmap.mmap(-1, 100).size())
case("op-size-after-truncate", lambda: rw(lambda m, fd: (os.truncate(F, 100), m.size())[1]))
case("op-resize-grow", lambda: rw(lambda m, fd: m.resize(20000)))
case("op-resize-shrink", lambda: rw(lambda m, fd: m.resize(100)))
case("op-resize-same", lambda: rw(lambda m, fd: m.resize(10000)))
case("op-resize-zero", lambda: rw(lambda m, fd: m.resize(0)))
case("op-resize-ro", lambda: rw(lambda m, fd: m.resize(100), access=mmap.ACCESS_READ))
case("op-resize-copy", lambda: rw(lambda m, fd: m.resize(100), access=mmap.ACCESS_COPY))
case("op-resize-anon", lambda: mmap.mmap(-1, 100).resize(200))
case("op-resize-after-fdclose", lambda: rw(lambda m, fd: m.resize(20000), closefd=True))
case("op-move", lambda: rw(lambda m, fd: (m.move(0, 100, 10), m[:3])[1]))
case("op-move-beyond", lambda: rw(lambda m, fd: m.move(0, 9999, 10)))
case("op-move-ro", lambda: rw(lambda m, fd: m.move(0, 100, 10), access=mmap.ACCESS_READ))
for adv in (
    "NORMAL",
    "RANDOM",
    "SEQUENTIAL",
    "WILLNEED",
    "DONTNEED",
    "FREE",
    "REMOVE",
    "DONTFORK",
    "DOFORK",
    "MERGEABLE",
    "UNMERGEABLE",
    "HUGEPAGE",
    "NOHUGEPAGE",
    "DONTDUMP",
    "DODUMP",
    "HWPOISON",
):
    case("op-madvise-" + adv, lambda adv=adv: rw(lambda m, fd: m.madvise(getattr(mmap, "MADV_" + adv))))
case("op-madvise-0", lambda: rw(lambda m, fd: m.madvise(0)))
case("op-madvise-99", lambda: rw(lambda m, fd: m.madvise(99)))
case("op-madvise-range", lambda: rw(lambda m, fd: m.madvise(mmap.MADV_NORMAL, 0, 100)))
case("op-madvise-range-unaligned", lambda: rw(lambda m, fd: m.madvise(mmap.MADV_NORMAL, 1, 100)))
case("op-madvise-range-beyond", lambda: rw(lambda m, fd: m.madvise(mmap.MADV_NORMAL, 0, 10**6)))
case("op-madvise-anon", lambda: mmap.mmap(-1, 100).madvise(mmap.MADV_NORMAL))
case("op-closed-attr", lambda: rw(lambda m, fd: (m.closed, m.close(), m.closed)))
case("op-close-twice", lambda: rw(lambda m, fd: (m.close(), m.close())))
case("op-len-after-close", lambda: rw(lambda m, fd: (m.close(), len(m))))
case("op-getitem-after-close", lambda: rw(lambda m, fd: (m.close(), m[0])))
case("op-with", lambda: rw(lambda m, fd: (m.__enter__().__class__.__name__, m.__exit__(None, None, None), m.closed)))
case("op-memoryview", lambda: rw(lambda m, fd: bytes(memoryview(m)[:3])))
case("op-memoryview-close-with-export", lambda: rw(lambda m, fd: (lambda mv: m.close())(memoryview(m))))
case("op-memoryview-write", lambda: rw(lambda m, fd: (lambda mv: (mv.__setitem__(0, 9), m[0])[1])(memoryview(m))))
case(
    "op-memoryview-ro",
    lambda: rw(lambda m, fd: (lambda mv: mv.__setitem__(0, 9))(memoryview(m)), access=mmap.ACCESS_READ),
)
case("op-bytes-from-mm", lambda: rw(lambda m, fd: bytes(m)[:4]))
case("op-iter", lambda: rw(lambda m, fd: list(m)[:3]))
case("op-in", lambda: rw(lambda m, fd: (b"\x01\x02" in m, b"zz" in m)))
case("op-re", lambda: rw(lambda m, fd: __import__("re").search(rb"\x05\x06", m).span()))
case("op-pickle", lambda: rw(lambda m, fd: __import__("pickle").dumps(m)))
case("op-copy", lambda: rw(lambda m, fd: __import__("copy").copy(m)))
case("op-repr-class", lambda: rw(lambda m, fd: type(m).__name__))
case("op-fileno", lambda: rw(lambda m, fd: hasattr(m, "fileno")))
case("op-trackfd", lambda: mmap.mmap(os.open(F, os.O_RDONLY), 100, access=mmap.ACCESS_READ, trackfd=False).closed)
case("op-trackfd-size", lambda: mmap.mmap(os.open(F, os.O_RDONLY), 100, access=mmap.ACCESS_READ, trackfd=False).size())
case("op-trackfd-resize", lambda: mmap.mmap(os.open(F, os.O_RDWR), 100, trackfd=False).resize(200))
case("op-trackfd-len0", lambda: mmap.mmap(os.open(F, os.O_RDWR), 0, trackfd=False))
case(
    "op-trackfd-fdclosed-write",
    lambda: (
        lambda fd: (lambda m: (os.close(fd), m.__setitem__(0, 5), m.flush(), m.close(), contents()[:2])[4])(
            mmap.mmap(fd, 100, trackfd=False)
        )
    )(os.open(F, os.O_RDWR)),
)


# two mappings, file changes under a mapping
def two(fn):
    fresh()
    fd = os.open(F, os.O_RDWR)
    a = mmap.mmap(fd, 8192)
    b = mmap.mmap(fd, 8192)
    c = mmap.mmap(fd, 8192, access=mmap.ACCESS_COPY)
    try:
        return fn(a, b, c, fd)
    finally:
        for m in (a, b, c):
            m.close()
        os.close(fd)


case("two-shared-visible", lambda: two(lambda a, b, c, fd: (a.__setitem__(0, 77), b[0], c[0])))
case(
    "two-shared-visible-after-flush",
    lambda: two(lambda a, b, c, fd: (a.__setitem__(0, 77), a.flush(), b[0], c[0], contents()[0])),
)
case(
    "two-shared-both-close",
    lambda: two(
        lambda a, b, c, fd: (a.__setitem__(0, 77), b.__setitem__(1, 78), a.close(), b.close(), contents()[:3])[4]
    ),
)
case(
    "two-private-then-flush",
    lambda: two(lambda a, b, c, fd: (c.__setitem__(0, 66), c.flush(), c.close(), contents()[0])[3]),
)
case("two-pwrite-after-map-visible", lambda: two(lambda a, b, c, fd: (os.pwrite(fd, b"QQ", 0), a[:2], c[:2])[1:]))
case("two-write-file-after-map-visible", lambda: two(lambda a, b, c, fd: (open(F, "r+b").write(b"RR"), a[:2])[1]))
case("two-ftruncate-grow-visible", lambda: two(lambda a, b, c, fd: (os.ftruncate(fd, 200000), a.size(), b.size())[1:]))
case("two-ftruncate-smaller-then-read", lambda: two(lambda a, b, c, fd: (os.ftruncate(fd, 10), bytes(a[:4]))[1]))
case(
    "two-ftruncate-smaller-then-read-beyond",
    lambda: two(lambda a, b, c, fd: (os.ftruncate(fd, 10), bytes(a[4000:4004]))[1]),
)
case(
    "two-ftruncate-smaller-write-flush",
    lambda: two(lambda a, b, c, fd: (os.ftruncate(fd, 10), a.__setitem__(0, 5), a.flush(), os.path.getsize(F))[3]),
)
case("two-ftruncate-zero-then-new-map", lambda: two(lambda a, b, c, fd: (os.ftruncate(fd, 0), mmap.mmap(fd, 0))))
case("two-ftruncate-zero-then-read", lambda: two(lambda a, b, c, fd: (os.ftruncate(fd, 0), a[:2])[1]))
case(
    "two-ftruncate-zero-flush-size",
    lambda: two(lambda a, b, c, fd: (os.ftruncate(fd, 0), a.flush(), os.path.getsize(F))[2]),
)
case("two-unlink-then-read", lambda: two(lambda a, b, c, fd: (os.unlink(F), bytes(a[:3]))[1]))
case(
    "two-unlink-then-write-flush",
    lambda: two(lambda a, b, c, fd: (os.unlink(F), a.__setitem__(0, 3), a.flush(), os.path.exists(F))[3]),
)
case(
    "two-unlink-then-close-write-exists",
    lambda: two(lambda a, b, c, fd: (os.unlink(F), a.__setitem__(0, 3), a.close(), os.path.exists(F))[3]),
)
case(
    "two-rename-then-write-flush",
    lambda: two(
        lambda a, b, c, fd: (
            os.rename(F, F + ".r"),
            a.__setitem__(0, 3),
            a.flush(),
            os.path.exists(F),
            open(F + ".r", "rb").read(2),
        )[3:]
    ),
)
case(
    "two-rename-then-close-fd-flush",
    lambda: two(
        lambda a, b, c, fd: (
            os.rename(F, F + ".r2"),
            os.close(fd),
            a.__setitem__(0, 3),
            a.flush(),
            open(F + ".r2", "rb").read(2),
        )[4]
    ),
)
case(
    "two-unlink-then-close-fd-flush",
    lambda: two(lambda a, b, c, fd: (os.unlink(F), os.close(fd), a.__setitem__(0, 3), a.flush(), "ok")[4]),
)
case(
    "two-chmod-0-then-flush", lambda: two(lambda a, b, c, fd: (os.chmod(F, 0), a.__setitem__(0, 3), a.flush(), "ok")[3])
)
case(
    "two-chmod-ro-then-flush",
    lambda: two(lambda a, b, c, fd: (os.chmod(F, 0o444), a.__setitem__(0, 3), a.flush(), contents()[:1])[3]),
)
case(
    "two-mtime-after-flush",
    lambda: two(
        lambda a, b, c, fd: (os.utime(F, (1, 1)), a.__setitem__(0, 3), a.flush(), os.stat(F).st_mtime > 1000)[3]
    ),
)
case(
    "two-mtime-after-close",
    lambda: two(
        lambda a, b, c, fd: (os.utime(F, (1, 1)), a.__setitem__(0, 3), a.close(), os.stat(F).st_mtime > 1000)[3]
    ),
)
case(
    "two-mtime-private-close",
    lambda: two(lambda a, b, c, fd: (os.utime(F, (1, 1)), c.__setitem__(0, 3), c.close(), os.stat(F).st_mtime)[3]),
)
case(
    "two-mtime-read-only-map-close",
    lambda: two(
        lambda a, b, c, fd: (
            os.utime(F, (1, 1)),
            mmap.mmap(fd, 100, access=mmap.ACCESS_READ).close(),
            os.stat(F).st_mtime,
        )[2]
    ),
)
case(
    "two-size-after-write-extends",
    lambda: two(lambda a, b, c, fd: (a.__setitem__(8191, 1), a.flush(), os.path.getsize(F))[2]),
)


# a mapping of a file that is shorter than the length asked
def short(fn):
    with open(B + "/short", "wb") as f:
        f.write(b"abcdef")
    fd = os.open(B + "/short", os.O_RDWR)
    try:
        return fn(fd)
    finally:
        os.close(fd)


case("short-len0-size", lambda: short(lambda fd: view(mmap.mmap(fd, 0))))
case("short-len10", lambda: short(lambda fd: view(mmap.mmap(fd, 10))))
case("short-len4096", lambda: short(lambda fd: view(mmap.mmap(fd, 4096))))
case(
    "short-len10-write-file-size",
    lambda: short(
        lambda fd: (lambda m: (m.__setitem__(8, 1), m.flush(), os.path.getsize(B + "/short"))[2])(mmap.mmap(fd, 10))
    ),
)
case("short-off3", lambda: short(lambda fd: view(mmap.mmap(fd, 0, offset=3))))
case("short-off6", lambda: short(lambda fd: view(mmap.mmap(fd, 0, offset=6))))
case("short-off7", lambda: short(lambda fd: view(mmap.mmap(fd, 0, offset=7))))
case("short-off65536", lambda: short(lambda fd: view(mmap.mmap(fd, 0, offset=65536))))
case("short-len0-off0-size-readonly", lambda: short(lambda fd: view(mmap.mmap(fd, 0, access=mmap.ACCESS_READ))))
case(
    "short-read-tail-bytes", lambda: short(lambda fd: bytes(mmap.mmap(fd, 100, access=mmap.ACCESS_READ)[:100]).count(0))
)
case("small-whole", mk, B + "/small", os.O_RDWR, length=0)
case(
    "small-whole-content",
    lambda: (lambda m: m[:])(mmap.mmap(os.open(B + "/small", os.O_RDONLY), 0, access=mmap.ACCESS_READ)),
)
case("wo-0200-open-rw", lambda: os.open(B + "/wo", os.O_RDWR))
case(
    "big-offset-file-sparse",
    lambda: (lambda fd: (os.ftruncate(fd, 2**32 + 10), view(mmap.mmap(fd, 10, offset=2**32)))[1])(
        os.open(B + "/sparse", os.O_RDWR | os.O_CREAT)
    ),
)
case(
    "big-file-len0",
    lambda: (lambda fd: (os.ftruncate(fd, 2**31 + 10), mmap.mmap(fd, 0).size())[1])(
        os.open(B + "/sparse2", os.O_RDWR | os.O_CREAT)
    ),
)
case(
    "big-file-len-1-off-big",
    lambda: (lambda fd: (os.ftruncate(fd, 2**33), view(mmap.mmap(fd, 1, offset=2**33 - 65536)))[1])(
        os.open(B + "/sparse3", os.O_RDWR | os.O_CREAT)
    ),
)
