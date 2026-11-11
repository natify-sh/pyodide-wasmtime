# type: ignore
# ruff: noqa
# fmt: off
import ctypes
L = ctypes.CDLL(None, use_errno=True)
i, ll, cp, vp, ui = ctypes.c_int, ctypes.c_longlong, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_uint
def C(name, *args, ret=i):
    f = getattr(L, name); f.restype = ret
    ctypes.set_errno(0)
    r = f(*args)
    if ret in (i, ll, ctypes.c_long) and r < 0:
        return 'ERR ' + errno.errorcode.get(ctypes.get_errno(), str(ctypes.get_errno()))
    return r
def b(n): return (B + '/' + n).encode()
class TS(ctypes.Structure): _fields_ = [('sec', ctypes.c_longlong), ('nsec', ctypes.c_long)]
UTIME_NOW, UTIME_OMIT = (1 << 30) - 1, (1 << 30) - 2
AT_FDCWD, AT_SYMLINK_NOFOLLOW, AT_REMOVEDIR, AT_EACCESS = -100, 0x100, 0x200, 0x200
tree()
# posix_fallocate returns the error number itself
def pfa(fn, off, ln, flags=os.O_RDWR):
    fd = os.open(B + '/' + fn, flags)
    try: r = L.posix_fallocate(fd, ctypes.c_longlong(off), ctypes.c_longlong(ln))
    except Exception as e: return 'EXC ' + type(e).__name__
    return ('ERR ' + errno.errorcode.get(r, str(r)) if r else 'ok', os.fstat(fd).st_size)
L.posix_fallocate.argtypes = [i, ll, ll]
for off in (0, 5, 10, 100, 4096, 2 ** 20, 2 ** 31, -1, 2 ** 62):
    for ln in (0, 1, 5, 100, 4096, 2 ** 20, -1, 2 ** 31):
        if off >= 2 ** 31 and ln >= 2 ** 20: continue
        w(B + '/f')
        case('posix_fallocate off=%d len=%d' % (off, ln), lambda: pfa('f', off, ln))
case('posix_fallocate rdonly', lambda: pfa('f', 0, 5, os.O_RDONLY))
case('posix_fallocate wronly', lambda: pfa('f', 0, 5, os.O_WRONLY))
case('posix_fallocate dir', lambda: (lambda fd: L.posix_fallocate(fd, ll(0), ll(5)))(os.open(B + '/d', 0)))
case('posix_fallocate bad fd', lambda: L.posix_fallocate(999, ll(0), ll(5)))
case('posix_fallocate append', lambda: pfa('f', 0, 20, os.O_WRONLY | os.O_APPEND))
case('posix_fallocate stdout', lambda: L.posix_fallocate(1, ll(0), ll(5)))
case('posix_fallocate keeps content', lambda: (pfa('f', 0, 20), open(B + '/f').read())[1])
# mknod / mkfifo
for tn, mode in (('reg', 0o100644), ('fifo', 0o010644), ('chr', 0o020644), ('blk', 0o060644), ('sock', 0o140644), ('dir', 0o040755), ('zero-type', 0o644), ('lnk', 0o120777), ('bad', 0o030000)):
    for nn in ('new_' + tn, 'f', 'missing/x', 'dro/x', 'ln', 'bl', 'd', ''):
        case('mknod %s -> %s' % (tn, nn or 'empty'), lambda: (C('mknod', b(nn) if nn else b'', i(mode), i(0)), os.path.lexists(B + '/' + nn) and ty(os.lstat(B + '/' + nn).st_mode)))
case('mknod chr with dev', lambda: (C('mknod', b('chr1'), i(0o020666), i(0x0103)), ty(os.stat(B + '/chr1').st_mode)))
case('mkfifo', lambda: (C('mkfifo', b('fifo1'), i(0o600)), ty(os.stat(B + '/fifo1').st_mode)))
case('mkfifo mode', lambda: oct(stat.S_IMODE(os.stat(B + '/fifo1').st_mode)))
case('mkfifo exists', lambda: C('mkfifo', b('f'), i(0o600)))
case('fifo open ro nonblock', lambda: os.close(os.open(B + '/fifo1', os.O_RDONLY | os.O_NONBLOCK)))
case('mknodat dirfd', lambda: (C('mknodat', os.open(B + '/d', 0), b'nn', i(0o100644), i(0)), os.path.exists(B + '/d/nn')))
case('mkfifoat dirfd', lambda: (C('mkfifoat', os.open(B + '/d', 0), b'ff', i(0o600)), os.path.exists(B + '/d/ff')))
case('mknod unlink fifo', lambda: (os.unlink(B + '/fifo1'), os.path.exists(B + '/fifo1')))
# utimensat / futimens
def ts(a, b_=None): return (TS * 2)(a, b_ or TS(0, UTIME_NOW))
def st(n): s = os.stat(B + '/' + n); return (s.st_atime_ns, s.st_mtime_ns)
NOWISH = ('now now', 'now a', 'now m', 'now with sec', 'omit omit', 'omit with sec')
def shown(nm, tgt, arr_a, arr_m):
    if not os.path.lexists(B + '/' + tgt): return None
    s = os.stat(B + '/' + tgt)
    # a field set to a real time is shown, a field set to NOW or left alone only as "recent or not"
    def f(ns, spec):
        if spec.nsec == UTIME_NOW: return 'now' if abs(ns / 1e9 - __import__('time').time()) < 100 else 'old'
        if spec.nsec == UTIME_OMIT: return 'kept(%s)' % (ns == 1)
        return ns
    return (f(s.st_atime_ns, arr_a), f(s.st_mtime_ns, arr_m))
for nm, a, m in (('both set', TS(100, 5), TS(200, 6)), ('now now', TS(0, UTIME_NOW), TS(0, UTIME_NOW)), ('omit omit', TS(0, UTIME_OMIT), TS(0, UTIME_OMIT)), ('omit a', TS(0, UTIME_OMIT), TS(300, 7)), ('omit m', TS(300, 7), TS(0, UTIME_OMIT)),
                 ('now a', TS(0, UTIME_NOW), TS(300, 7)), ('now m', TS(300, 7), TS(0, UTIME_NOW)), ('nsec 999999999', TS(10, 999999999), TS(10, 999999999)),
                 ('now with sec', TS(55, UTIME_NOW), TS(55, UTIME_NOW)), ('omit with sec', TS(55, UTIME_OMIT), TS(66, UTIME_OMIT)), ('zero', TS(0, 0), TS(0, 0)), ('nsec 1', TS(0, 1), TS(0, 2))):
    arr = (TS * 2)(a, m)
    for tgt in ('f', 'd', 'ln', 'ro', 'missing'):
        case('utimensat %s on %s' % (nm, tgt), lambda: (os.utime(B + '/f', ns=(1, 1)) if os.path.exists(B + '/f') else 0, os.utime(B + '/' + tgt, ns=(1, 1)) if os.path.exists(B + '/' + tgt) else 0, C('utimensat', i(AT_FDCWD), b(tgt), arr, i(0)), shown(nm, tgt, a, m))[2:])
    fd = os.open(B + '/f', os.O_RDWR)
    case('futimens %s' % nm, lambda: (os.utime(B + '/f', ns=(1, 1)), C('futimens', i(fd), arr), shown(nm, 'f', a, m))[1:])
    os.close(fd)
    case('utimensat nofollow %s' % nm, lambda: (os.utime(B + '/f', ns=(1, 1)), C('utimensat', i(AT_FDCWD), b('ln'), arr, i(AT_SYMLINK_NOFOLLOW)), shown(nm, 'f', a, m), ty(os.lstat(B + '/ln').st_mode))[1:])
case('utimensat NULL times = now', lambda: (os.utime(B + '/f', ns=(1, 1)), C('utimensat', i(AT_FDCWD), b('f'), None, i(0)), abs(st('f')[1] / 1e9 - __import__('time').time()) < 100)[1:])
case('utimensat bad flags', lambda: C('utimensat', i(AT_FDCWD), b('f'), None, i(0x1000)))
case('utimensat bad flags 2', lambda: C('utimensat', i(AT_FDCWD), b('f'), None, i(0x400)))
case('utimensat AT_EMPTY_PATH', lambda: C('utimensat', os.open(B + '/f', 0), b'', None, i(0x1000)))
case('utimensat dirfd rel', lambda: (os.utime(B + '/d/in', ns=(1, 1)), C('utimensat', os.open(B + '/d', 0), b'in', (TS * 2)(TS(5, 0), TS(6, 0)), i(0)), st('d/in'))[1:])
case('utimensat dirfd bad', lambda: C('utimensat', i(999), b'in', None, i(0)))
case('utimensat dirfd file', lambda: C('utimensat', os.open(B + '/f', 0), b'in', None, i(0)))
case('futimens bad fd', lambda: C('futimens', i(999), None))
case('futimens dir', lambda: C('futimens', os.open(B + '/d', 0), None))
case('futimens rdonly fd', lambda: C('futimens', os.open(B + '/f', os.O_RDONLY), (TS * 2)(TS(5, 0), TS(6, 0))))
case('futimens stdout', lambda: C('futimens', i(1), None))
case('utimes', lambda: (lambda tv: (C('utimes', b('f'), tv), st('f')))((TS * 2)(TS(10, 500000), TS(20, 250000)))[1])
# fchmodat / faccessat / fchownat / unlinkat / mkdirat / readlinkat / renameat
for tgt in ('f', 'ln', 'bl', 'd', 'missing', 'ro'):
    for fl in (0, AT_SYMLINK_NOFOLLOW, 0x1000, 0x200, 0xffff):
        fresh()
        case('fchmodat %s flags=%x' % (tgt, fl), lambda: (C('fchmodat', i(AT_FDCWD), b(tgt), i(0o600), i(fl)), oct(stat.S_IMODE(os.lstat(B + '/' + tgt).st_mode)) if os.path.lexists(B + '/' + tgt) else None))
        case('faccessat %s flags=%x' % (tgt, fl), lambda: C('faccessat', i(AT_FDCWD), b(tgt), i(0), i(fl)))
        case('fchownat %s flags=%x' % (tgt, fl), lambda: C('fchownat', i(AT_FDCWD), b(tgt), ui(-1), ui(-1), i(fl)))
        case('unlinkat %s flags=%x' % (tgt, fl), lambda: (tree() if False else 0, C('unlinkat', i(AT_FDCWD), b(tgt + '__x' if tgt == 'missing' else tgt), i(fl)), os.path.lexists(B + '/' + tgt))[1:])
case('faccessat AT_EACCESS', lambda: C('faccessat', i(AT_FDCWD), b('f'), i(4), i(AT_EACCESS)))
case('mkdirat dirfd', lambda: (C('mkdirat', os.open(B + '/d', 0), b'md', i(0o700)), oct(stat.S_IMODE(os.stat(B + '/d/md').st_mode))))
case('mkdirat bad fd', lambda: C('mkdirat', i(999), b'x', i(0o700)))
case('mkdirat dirfd=file', lambda: C('mkdirat', os.open(B + '/f', 0), b'x', i(0o700)))
case('readlinkat dirfd', lambda: (lambda buf: (C('readlinkat', os.open(B, 0), b'abs', buf, ctypes.c_size_t(100), ret=ctypes.c_long), buf.value[:3]))(ctypes.create_string_buffer(100)))
case('readlinkat small buf', lambda: (lambda buf: (C('readlinkat', i(AT_FDCWD), b('ln'), buf, ctypes.c_size_t(0), ret=ctypes.c_long), 'z'))(ctypes.create_string_buffer(100)))
case('readlink buf 1', lambda: (lambda buf: (C('readlink', b('ln'), buf, ctypes.c_size_t(1), ret=ctypes.c_long), buf.raw[:2]))(ctypes.create_string_buffer(100)))
case('readlink buf long target', lambda: (lambda buf: (os.symlink('t' * 300, B + '/lng'), C('readlink', b('lng'), buf, ctypes.c_size_t(100), ret=ctypes.c_long)))(ctypes.create_string_buffer(100))[1])
case('readlink file', lambda: C('readlink', b('f'), ctypes.create_string_buffer(10), ctypes.c_size_t(10), ret=ctypes.c_long))
case('readlink missing', lambda: C('readlink', b('nonex'), ctypes.create_string_buffer(10), ctypes.c_size_t(10), ret=ctypes.c_long))
case('renameat dirfds', lambda: (C('renameat', os.open(B + '/d', 0), b'in', os.open(B, 0), b'moved_in'), os.path.exists(B + '/moved_in')))
case('renameat bad fd', lambda: C('renameat', i(999), b'a', i(998), b'b'))
case('renameat2 present', lambda: hasattr(L, 'renameat2'))
case('linkat flags', lambda: (C('linkat', i(AT_FDCWD), b('ln'), i(AT_FDCWD), b('lk1'), i(0x400)), ty(os.lstat(B + '/lk1').st_mode) if os.path.lexists(B + '/lk1') else None))
case('linkat nofollow', lambda: (C('linkat', i(AT_FDCWD), b('ln'), i(AT_FDCWD), b('lk2'), i(0)), ty(os.lstat(B + '/lk2').st_mode) if os.path.lexists(B + '/lk2') else None))
case('linkat empty path', lambda: C('linkat', os.open(B + '/f', 0), b'', i(AT_FDCWD), b('lk3'), i(0x1000)))
case('symlinkat dirfd', lambda: (C('symlinkat', b'tg', os.open(B + '/d', 0), b'sl'), os.readlink(B + '/d/sl')))
case('symlinkat bad fd', lambda: C('symlinkat', b'tg', i(999), b'sl'))
# openat / fstatat / statx
for dn in ('AT_FDCWD', 'dirfd', 'filefd', 'badfd', 'stdout'):
    dfd = {'AT_FDCWD': AT_FDCWD, 'dirfd': os.open(B, 0), 'filefd': os.open(B + '/f', 0), 'badfd': 999, 'stdout': 1}[dn]
    for pn, pp in (('rel f', b'f'), ('abs f', b(('f'))), ('empty', b''), ('dot', b'.'), ('dotdot', b'..'), ('missing', b'zz')):
        case('openat %s %s' % (dn, pn), lambda: (lambda r: (os.close(r), 'ok')[1] if isinstance(r, int) and r >= 0 else r)(C('openat', i(dfd), pp, i(0))))
        buf = ctypes.create_string_buffer(256)
        case('fstatat %s %s' % (dn, pn), lambda: C('fstatat', i(dfd), pp, buf, i(0)) if hasattr(L, 'fstatat') else 'n/a')
        case('fstatat nofollow %s %s' % (dn, pn), lambda: C('fstatat', i(dfd), pp, buf, i(AT_SYMLINK_NOFOLLOW)))
        case('fstatat empty_path %s %s' % (dn, pn), lambda: C('fstatat', i(dfd), pp, buf, i(0x1000)))
        case('fstatat bad flags %s %s' % (dn, pn), lambda: C('fstatat', i(dfd), pp, buf, i(0x8000)))
case('statx basic', lambda: (lambda buf: (C('statx', i(AT_FDCWD), b('f'), i(0), ui(0xfff), buf), int.from_bytes(buf.raw[40:48], 'little')))(ctypes.create_string_buffer(256)))
case('statx missing', lambda: C('statx', i(AT_FDCWD), b('nonex'), i(0), ui(0xfff), ctypes.create_string_buffer(256)))
case('statx mask/flags bad', lambda: C('statx', i(AT_FDCWD), b('f'), i(0x8000), ui(0xfff), ctypes.create_string_buffer(256)))
# preadv/pwritev with libc
class IOV(ctypes.Structure): _fields_ = [('base', vp), ('len', ctypes.c_size_t)]
def iov(*bufs): return (IOV * len(bufs))(*[IOV(ctypes.cast(x, vp), len(x)) for x in bufs])
case('preadv 2 bufs', lambda: (lambda a, c_: (w(B + '/io', b'0123456789'), C('preadv', os.open(B + '/io', 0), iov(a, c_), i(2), ll(2), ret=ctypes.c_long), a.raw, c_.raw)[1:])(ctypes.create_string_buffer(3), ctypes.create_string_buffer(4)))
case('pwritev 2 bufs', lambda: (w(B + '/io', b'0123456789'), C('pwritev', os.open(B + '/io', os.O_RDWR), iov(ctypes.create_string_buffer(b'ab', 2), ctypes.create_string_buffer(b'cd', 2)), i(2), ll(3), ret=ctypes.c_long), open(B + '/io', 'rb').read())[1:])
case('pwritev iovcnt 0', lambda: C('pwritev', os.open(B + '/io', os.O_RDWR), None, i(0), ll(0), ret=ctypes.c_long))
case('pwritev iovcnt 2000', lambda: C('pwritev', os.open(B + '/io', os.O_RDWR), iov(*[ctypes.create_string_buffer(b'x', 1)] * 2000), i(2000), ll(0), ret=ctypes.c_long))
case('preadv offset -1', lambda: C('preadv', os.open(B + '/io', 0), iov(ctypes.create_string_buffer(3)), i(1), ll(-1), ret=ctypes.c_long))
case('pwritev 2 bufs total', lambda: (w(B + '/io', b''), C('pwritev', os.open(B + '/io', os.O_RDWR), iov(ctypes.create_string_buffer(b'ab', 2), ctypes.create_string_buffer(b'cd', 2)), i(2), ll(0), ret=ctypes.c_long))[1])
case('dup3 flags', lambda: (lambda fd: (C('dup3', i(fd), i(77), i(0o2000000)), os.close(77))[0])(os.open(B + '/f', 0)))
case('dup3 bad flags', lambda: C('dup3', os.open(B + '/f', 0), i(78), i(1)))
case('dup3 same fd', lambda: (lambda fd: C('dup3', i(fd), i(fd), i(0)))(os.open(B + '/f', 0)))
case('dup3 target 1', lambda: 'skip')
case('umask libc', lambda: (C('umask', i(0o77)), C('umask', i(0o22))))
case('getcwd small buf', lambda: (lambda buf: (os.chdir(B), L.getcwd(buf, ctypes.c_size_t(2)), ctypes.get_errno(), os.chdir('/'))[2])(ctypes.create_string_buffer(2)))
case('getcwd null buf', lambda: (lambda: (L.getcwd.__setattr__('restype', ctypes.c_char_p), os.chdir(B), L.getcwd(None, 0).replace(B.encode(), b'B') if True else 0, os.chdir('/'))[2])())
case('chroot libc', lambda: C('chroot', b(('d'))))
case('statfs libc', lambda: (lambda buf: (C('statfs', b('f'), buf), int.from_bytes(buf.raw[8:16], 'little') > 0, int.from_bytes(buf.raw[56:64], 'little')))(ctypes.create_string_buffer(256)))
case('statfs missing', lambda: C('statfs', b('nonex'), ctypes.create_string_buffer(256)))
case('fstatfs bad fd', lambda: C('fstatfs', i(999), ctypes.create_string_buffer(256)))
case('fstatfs file', lambda: (lambda buf: (C('fstatfs', os.open(B + '/f', 0), buf), int.from_bytes(buf.raw[8:16], 'little') > 0))(ctypes.create_string_buffer(256)))
case('truncate libc neg', lambda: C('truncate', b('f'), ll(-5)))
case('truncate libc big', lambda: C('truncate', b('f'), ll(2 ** 62)))
case('fsync libc bad', lambda: C('fsync', i(999)))
case('fdatasync libc bad', lambda: C('fdatasync', i(999)))
case('sync libc', lambda: C('sync'))
case('flock libc', lambda: C('flock', os.open(B + '/f', 0), i(2)))
case('creat libc', lambda: (lambda r: (os.close(r), os.stat(B + '/cr').st_size)[1])(C('creat', b('cr'), i(0o644))))
case('mkstemp libc', lambda: (lambda t: (C('mkstemp', t), t.value[-6:] != b'XXXXXX'))(ctypes.create_string_buffer(B.encode() + b'/tmpXXXXXX')))
case('mkdtemp libc', lambda: (lambda t: (L.mkdtemp.__setattr__('restype', ctypes.c_char_p), L.mkdtemp(t) is not None)[1])(ctypes.create_string_buffer(B.encode() + b'/dXXXXXX')))
case('mkstemp bad template', lambda: C('mkstemp', ctypes.create_string_buffer(B.encode() + b'/tmpXX')))
case('realpath libc', lambda: (lambda buf: (L.realpath.__setattr__('restype', ctypes.c_char_p), L.realpath(b('d/../f'), None).replace(B.encode(), b'B'))[1])(0))
case('realpath libc missing', lambda: (L.realpath.__setattr__('restype', ctypes.c_char_p), (L.realpath(b('nonex/x'), None), ctypes.get_errno()))[1])
