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
def ty(m): return {stat.S_IFDIR: 'dir', stat.S_IFREG: 'file', stat.S_IFLNK: 'lnk', stat.S_IFCHR: 'chr', stat.S_IFIFO: 'fifo', stat.S_IFSOCK: 'sock', stat.S_IFBLK: 'blk'}.get(stat.S_IFMT(m), '?')
def tree():
    """the common tree under B: files, modes, dirs, links."""
    w(B + '/f'); w(B + '/ro'); os.chmod(B + '/ro', 0o444); w(B + '/wo'); os.chmod(B + '/wo', 0o222); w(B + '/none'); os.chmod(B + '/none', 0); w(B + '/empty', b'')
    os.mkdir(B + '/d'); w(B + '/d/in'); os.mkdir(B + '/dro'); os.chmod(B + '/dro', 0o555); os.mkdir(B + '/dnone'); os.chmod(B + '/dnone', 0); os.mkdir(B + '/emptyd')
    os.symlink('f', B + '/ln'); os.symlink('nothing', B + '/bl'); os.symlink('d', B + '/lnd'); os.symlink('ln', B + '/ln2'); os.symlink('loop2', B + '/loop1'); os.symlink('loop1', B + '/loop2')
    os.symlink(B + '/f', B + '/abs')
NAMES = {'f': 'f', 'ro': 'ro', 'wo': 'wo', 'none': 'none', 'empty': 'empty', 'd': 'd', 'dslash': 'd/', 'dro': 'dro', 'dnone': 'dnone', 'emptyd': 'emptyd', 'ln': 'ln', 'lnd': 'lnd', 'lndslash': 'lnd/', 'bl': 'bl', 'ln2': 'ln2', 'loop': 'loop1', 'abs': 'abs',
         'missing': 'missing', 'missing_in_missing': 'nodir/x', 'fslash': 'f/', 'f_dot': 'f/.', 'in_f': 'f/x', 'dot': '.', 'dotdot': '..', 'empty_name': '', 'in_dro': 'dro/new', 'in_dnone': 'dnone/x', 'dd': 'd/../f', 'dotf': './f', 'dbl': 'd//in',
         'n255': 'a' * 255, 'n256': 'a' * 256, 'nonascii': 'héllo中', 'surrogate': 'sur\udcff', 'space': ' sp ace ', 'rootdir': '/', 'bslash': 'a\\b', 'trailing_dot_name': 'x.'}
def P(n): return n if n.startswith('/') else B + '/' + n
import shutil
def fresh():
    os.chdir('/')
    for n in os.listdir(B):
        p = B + '/' + n
        try:
            os.chmod(p, 0o755) if not os.path.islink(p) else None
        except OSError: pass
        try:
            shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)
        except OSError: pass
    tree()
def state():
    out = []
    for n in sorted(os.listdir(B)):
        p = B + '/' + n
        out.append(n[:12] + ':' + ('l' if os.path.islink(p) else 'd' if os.path.isdir(p) else 'f'))
    return ' '.join(out)
def op(cid, fn, show=False):
    fresh()
    case(cid, lambda: (lambda r: r if not show else (r, state()))(fn()))
SAFE = {k: v for k, v in NAMES.items() if k not in ('rootdir', 'dotdot', 'empty_name', 'dot')}
