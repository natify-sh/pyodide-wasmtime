# type: ignore
# ruff: noqa
# fmt: off
import mmap
w(B + '/io', b'0123456789')
fds = []
def op(n):
    while len(fds) < n: fds.append(os.open(B + '/io', 0))
op(10)
case('first fd', lambda: fds[0])
case('contiguous 10', lambda: fds == list(range(fds[0], fds[0] + 10)))
for n in (500, 1020, 1030, 1100, 2000):
    op(n)
    last = fds[-1]
    case('fd count %d: contiguous' % n, lambda: fds == list(range(fds[0], fds[0] + len(fds))))
    case('fd count %d: last read' % n, lambda: os.read(last, 3))
    case('fd count %d: last fstat' % n, lambda: os.fstat(last).st_size)
    case('fd count %d: last lseek' % n, lambda: os.lseek(last, 2, 0))
    case('fd count %d: last pread' % n, lambda: os.pread(last, 3, 1))
    case('fd count %d: last dup' % n, lambda: (lambda d: (os.close(d), 'ok')[1])(os.dup(last)))
    case('fd count %d: last mmap' % n, lambda: mmap.mmap(last, 0, access=mmap.ACCESS_READ)[:3])
    case('fd count %d: last fcntl' % n, lambda: __import__('fcntl').fcntl(last, 1))
    case('fd count %d: last close' % n, lambda: (os.close(last), fds.pop())[0])
    case('fd count %d: reopen gets %s' % (n, 'last'), lambda: (lambda x: (fds.append(x), x == last)[1])(os.open(B + '/io', 0)))
for fd in fds: os.close(fd)
case('after closing all: first fd is lowest', lambda: (lambda x: (os.close(x), x)[1])(os.open(B + '/io', 0)))
a, b, c = [os.open(B + '/io', 0) for _ in range(3)]
os.close(b); os.close(a)
case('close a,b: next open is lowest (a)', lambda: (lambda x: (os.close(x), x == a)[1])(os.open(B + '/io', 0)))
os.close(c)
a, b, c = [os.open(B + '/io', 0) for _ in range(3)]
os.close(a); os.close(c)
case('close a,c then open twice -> a, c', lambda: (lambda x, y: (os.close(x), os.close(y), (x == a, y == c))[2])(os.open(B + '/io', 0), os.open(B + '/io', 0)))
os.close(b)
