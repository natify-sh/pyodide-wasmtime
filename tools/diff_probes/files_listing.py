# type: ignore
# ruff: noqa
# fmt: off
# the listing of a directory: read once per descriptor (a snapshot), served by the position
import ctypes
libc = ctypes.CDLL(None, use_errno=True)
libc.fdopendir.restype = libc.readdir.restype = libc.opendir.restype = ctypes.c_void_p
libc.fdopendir.argtypes = [ctypes.c_int]; libc.opendir.argtypes = [ctypes.c_char_p]
libc.readdir.argtypes = [ctypes.c_void_p]; libc.telldir.argtypes = [ctypes.c_void_p]; libc.rewinddir.argtypes = [ctypes.c_void_p]
libc.seekdir.argtypes = [ctypes.c_void_p, ctypes.c_long]; libc.telldir.restype = ctypes.c_long; libc.closedir.argtypes = [ctypes.c_void_p]
def names(d):
    out = []
    while True:
        e = libc.readdir(d)
        if not e: return out
        out.append(ctypes.string_at(e + 19).decode())
def mk(n, d='/L'):
    shutil.rmtree(B + d, ignore_errors=True); os.makedirs(B + d)
    for i in range(n): w(B + d + '/f%04d' % i, b'')
    return B + d
p = mk(3000)
case('3000 listdir', lambda: (lambda l: (len(l), len(set(l)), sorted(l) == ['f%04d' % i for i in range(3000)]))(os.listdir(p)))
case('3000 scandir', lambda: (lambda l: (len(l), len(set(l))))([e.name for e in os.scandir(p)]))
case('3000 walk', lambda: sum(len(f) for _, _, f in os.walk(p)))
case('3000 listdir by fd', lambda: (lambda fd: (len(os.listdir(fd)), len(os.listdir(fd)), os.close(fd))[:2])(os.open(p, os.O_RDONLY)))
case('3000 scandir by fd twice', lambda: (lambda fd: (len(list(os.scandir(fd))), len(list(os.scandir(fd)))))(os.open(p, os.O_RDONLY)))
def tell():
    d = libc.opendir(p.encode()); a = len(names(d)); libc.rewinddir(d); b = len(names(d)); libc.closedir(d); return (a, b)
case('3000 readdir, rewinddir, readdir', tell)
def seek():
    d = libc.opendir(p.encode()); first = [ctypes.string_at(libc.readdir(d) + 19).decode() for _ in range(5)]
    t = libc.telldir(d); nxt = names(d); libc.seekdir(d, t); again = names(d); libc.closedir(d)
    return (len(first), again == nxt, len(nxt), len(set(first) & set(nxt)))
case('3000 telldir, seekdir', seek)
def pos():
    fd = os.open(p, os.O_RDONLY | os.O_DIRECTORY); a = os.lseek(fd, 0, 1); os.listdir(fd); b = os.lseek(fd, 0, 1); d = libc.fdopendir(os.dup(fd)); n = len(names(d)); c = os.lseek(fd, 0, 1)
    return (a, b, n, c)
case('3000 positions (lseek CUR)', pos)
def dup():
    fd = os.open(p, os.O_RDONLY | os.O_DIRECTORY); fd2 = os.dup(fd); d1 = libc.fdopendir(fd); d2 = libc.fdopendir(fd2)
    a = len(names(d1)); b = len(names(d2)); return (a, b)
case('3000 dup shares the position', dup)
# created during the loop, removed during the loop
def modlist(kind, n=25):
    q = mk(n, '/M'); got = []
    for k, e in enumerate(os.scandir(q)):
        got.append(e.name)
        if k == 3 and kind == 'create': [w(q + '/new%02d' % i) for i in range(5)]
        if k == 3 and kind == 'create_all': [w(q + '/new%02d' % i) for i in range(500)]
    return (len(got), len(set(got)), len(set(got) - set('f%04d' % i for i in range(n))))
case('scandir while creating 5', lambda: modlist('create'))
case('scandir while creating 500', lambda: modlist('create_all'))
case('scandir while creating 500 (3000)', lambda: modlist('create_all', 3000))
def rew():
    q = mk(5, '/R'); fd = os.open(q, os.O_RDONLY); a = sorted(os.listdir(fd)); w(q + '/added'); os.rename(q + '/f0000', q + '/renamed'); b = sorted(os.listdir(fd)); os.close(fd)
    return (len(a), len(b), [x for x in b if x not in a], [x for x in a if x not in b])
case('listdir(fd) twice sees the change (rewinddir)', rew)
def libc_rew():
    q = mk(5, '/R'); d = libc.opendir(q.encode()); a = sorted(names(d)); w(q + '/added'); libc.rewinddir(d); b = sorted(names(d)); libc.closedir(d)
    return (len(a), len(b), [x for x in b if x not in a])
case('rewinddir sees the change', libc_rew)
def same_pos():
    q = mk(5, '/R'); fd = os.open(q, os.O_RDONLY | os.O_DIRECTORY); n1 = len(os.listdir(fd)); w(q + '/added'); return (n1, len(os.listdir(fd)), len(os.listdir(q)))
case('listdir path after a change', same_pos)
case('empty dir', lambda: (os.makedirs(B + '/E'), os.listdir(B + '/E'), len(list(os.scandir(B + '/E'))))[1:])
case('long names', lambda: (lambda q: (len(os.listdir(q)), len(set(os.listdir(q)))))(mk(0, '/N') and None or [os.makedirs(B + '/N2') , [w(B + '/N2/' + ('n%03d_' % i) + 'x' * 240) for i in range(300)], B + '/N2'][2]))
case('rmtree of 3000', lambda: (shutil.rmtree(p), os.path.exists(p))[1])
