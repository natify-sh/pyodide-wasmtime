# type: ignore
# ruff: noqa
# fmt: off
import os, errno, stat, sys
B = '/tmp/dp_' + str(os.getpid()); os.makedirs(B)
def case(cid, fn):
    try: r = fn()
    except OSError as e: r = 'ERR ' + errno.errorcode.get(e.errno, str(e.errno))
    except Exception as e: r = 'EXC ' + type(e).__name__
    print(cid, '|', r)
def w(p, d=b'hello'):
    with open(p, 'wb') as f: f.write(d)
w(B + '/f'); w(B + '/ro'); os.chmod(B + '/ro', 0o444); w(B + '/wo'); os.chmod(B + '/wo', 0o222); w(B + '/none'); os.chmod(B + '/none', 0)
os.mkdir(B + '/d'); os.mkdir(B + '/dro'); os.chmod(B + '/dro', 0o555); os.mkdir(B + '/dnone'); os.chmod(B + '/dnone', 0)
os.symlink('f', B + '/ln'); os.symlink('nothing', B + '/bl'); os.symlink('d', B + '/lnd'); os.symlink('ln', B + '/ln2'); os.symlink('loop2', B + '/loop1'); os.symlink('loop1', B + '/loop2')
w(B + '/empty', b'')
KEEP = ('f', 'ro', 'wo', 'none', 'd', 'dro', 'dnone', 'ln', 'bl', 'lnd', 'ln2', 'loop1', 'loop2', 'empty')
paths = {'f': 'f', 'ro': 'ro', 'wo': 'wo', 'none': 'none', 'd': 'd', 'dslash': 'd/', 'dro': 'dro', 'dnone': 'dnone', 'ln': 'ln', 'lnd': 'lnd', 'lndslash': 'lnd/', 'bl': 'bl', 'ln2': 'ln2', 'loop': 'loop1',
         'missing': 'missing', 'missing_in_missing': 'nodir/x', 'fslash': 'f/', 'f_dot': 'f/.', 'in_f': 'f/x', 'dot': '.', 'dotdot': '..', 'empty_name': '', 'in_dro': 'dro/new', 'in_dnone': 'dnone/x', 'dd_missing': 'd/../missing',
         'dotdot_f': 'd/../f', 'dot_f': './f', 'dblslash': 'd//x', 'trail_dots': 'f/..', 'n255': 'a' * 255, 'n256': 'a' * 256, 'nonascii': 'héllo中', 'emoji': '\U0001f600', 'surrogate': 'sur\udcff', 'space': ' sp ace ', 'nl': 'a\nb', 'empty_file': 'empty'}
flags = {'RDONLY': os.O_RDONLY, 'WRONLY': os.O_WRONLY, 'RDWR': os.O_RDWR, 'RDONLY|CREAT': os.O_RDONLY | os.O_CREAT, 'WRONLY|CREAT': os.O_WRONLY | os.O_CREAT,
         'WRONLY|CREAT|EXCL': os.O_WRONLY | os.O_CREAT | os.O_EXCL, 'RDWR|CREAT|EXCL': os.O_RDWR | os.O_CREAT | os.O_EXCL, 'WRONLY|TRUNC': os.O_WRONLY | os.O_TRUNC, 'RDWR|TRUNC': os.O_RDWR | os.O_TRUNC,
         'RDONLY|TRUNC': os.O_RDONLY | os.O_TRUNC, 'WRONLY|APPEND': os.O_WRONLY | os.O_APPEND, 'RDWR|APPEND': os.O_RDWR | os.O_APPEND, 'RDONLY|DIRECTORY': os.O_RDONLY | os.O_DIRECTORY,
         'WRONLY|DIRECTORY': os.O_WRONLY | os.O_DIRECTORY, 'RDONLY|NOFOLLOW': os.O_RDONLY | os.O_NOFOLLOW, 'RDONLY|CLOEXEC': os.O_RDONLY | os.O_CLOEXEC, 'RDONLY|NONBLOCK': os.O_RDONLY | os.O_NONBLOCK,
         'CREAT|EXCL|NOFOLLOW': os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 'CREAT|DIRECTORY': os.O_RDONLY | os.O_CREAT | os.O_DIRECTORY, 'RDONLY|SYNC': os.O_RDONLY | os.O_SYNC,
         'RDWR|CREAT|TRUNC': os.O_RDWR | os.O_CREAT | os.O_TRUNC, 'RDWR|CREAT|APPEND': os.O_RDWR | os.O_CREAT | os.O_APPEND}
def doopen(p, fl, mode=None):
    fd = os.open(B + '/' + p, fl, *([mode] if mode is not None else []))
    try:
        st = os.fstat(fd); t = 'dir' if stat.S_ISDIR(st.st_mode) else 'file' if stat.S_ISREG(st.st_mode) else oct(stat.S_IFMT(st.st_mode))
        return 'OK ' + t + ' size=%d' % st.st_size
    finally: os.close(fd)
for pn, p in paths.items():
    for fn, fl in flags.items():
        w(B + '/f')
        for stale in os.listdir(B):
            if stale in KEEP: continue
            try: os.remove(B + '/' + stale)
            except OSError: pass
        case('open %s %s' % (pn, fn), lambda: doopen(p, fl, 0o644))
for um in (0o022, 0o077, 0o000):
    os.umask(um)
    for m in (0o666, 0o644, 0o400, 0o7777, 0o000, 0o111):
        n = 'cm_%o_%o' % (um, m)
        case('create mode umask=%o mode=%o' % (um, m), lambda: (os.close(os.open(B + '/' + n, os.O_CREAT | os.O_WRONLY, m)), oct(stat.S_IMODE(os.stat(B + '/' + n).st_mode)))[1])
os.umask(0o022)
case('open default mode', lambda: (os.close(os.open(B + '/dm', os.O_CREAT | os.O_WRONLY)), oct(stat.S_IMODE(os.stat(B + '/dm').st_mode)))[1])
case('open bytes path', lambda: (os.close(os.open(os.fsencode(B + '/f'), os.O_RDONLY)), 'OK')[1])
case('open path with NUL', lambda: os.open(B + '/f\0x', os.O_RDONLY))
dfd = os.open(B + '/d', os.O_RDONLY | os.O_DIRECTORY)
case('openat dir_fd rel', lambda: (os.close(os.open('../f', os.O_RDONLY, dir_fd=dfd)), 'OK')[1])
case('openat dir_fd create', lambda: (os.close(os.open('newx', os.O_CREAT | os.O_WRONLY, 0o600, dir_fd=dfd)), os.path.exists(B + '/d/newx'))[1])
case('openat dir_fd abs path', lambda: (os.close(os.open(B + '/f', os.O_RDONLY, dir_fd=dfd)), 'OK')[1])
case('openat dir_fd empty path', lambda: os.open('', os.O_RDONLY, dir_fd=dfd))
case('openat dir_fd .', lambda: (os.close(os.open('.', os.O_RDONLY, dir_fd=dfd)), 'OK')[1])
ffd = os.open(B + '/f', os.O_RDONLY)
case('openat dir_fd=file fd', lambda: os.open('x', os.O_RDONLY, dir_fd=ffd))
case('openat dir_fd=bad', lambda: os.open('f', os.O_RDONLY, dir_fd=9999))
case('openat dir_fd=-1', lambda: os.open('f', os.O_RDONLY, dir_fd=-1))
case('open fd numbers ascending', lambda: (lambda a, b: (os.close(a), os.close(b), b - a)[2])(os.open(B + '/f', 0), os.open(B + '/f', 0)))
case('open reuse lowest fd', lambda: (lambda a: (os.close(a), os.open(B + '/f', 0) == a)[1])(os.open(B + '/f', 0)))
def rw(fl, op):
    fd = os.open(B + '/f', fl)
    try:
        if op == 'r': return os.read(fd, 10)
        return os.write(fd, b'XY')
    finally: os.close(fd)
for fn in ('RDONLY', 'WRONLY', 'RDWR', 'WRONLY|APPEND', 'RDWR|APPEND'):
    for op in 'rw':
        w(B + '/f')
        case('rw %s %s' % (fn, op), lambda: rw(flags[fn], op))
w(B + '/f')
case('append write goes to end', lambda: (lambda fd: (os.lseek(fd, 0, 0), os.write(fd, b'ZZ'), os.lseek(fd, 0, 1), os.close(fd), open(B + '/f', 'rb').read())[2:])(os.open(B + '/f', os.O_WRONLY | os.O_APPEND)))
w(B + '/f')
case('append pos after write', lambda: (lambda fd: (os.write(fd, b'ZZ'), os.lseek(fd, 0, 1), os.close(fd))[1])(os.open(B + '/f', os.O_RDWR | os.O_APPEND)))
case('open dir read', lambda: (lambda fd: os.read(fd, 10))(os.open(B + '/d', 0)))
case('open dir write via fd', lambda: (lambda fd: os.write(fd, b'x'))(os.open(B + '/d', 0)))
case('python open w on dir', lambda: open(B + '/d', 'w'))
case('python open r on dir', lambda: open(B + '/d', 'r'))
case('python open x existing', lambda: open(B + '/f', 'x'))
case('python open r+ missing', lambda: open(B + '/zz_missing', 'r+'))
case('python open a+ then read', lambda: (lambda f: (f.seek(0), f.read(), f.close())[1])(open(B + '/f', 'a+')))
case('python open w+ truncates', lambda: (lambda f: (f.close(), os.path.getsize(B + '/f'))[1])(open(B + '/f', 'w+')))
