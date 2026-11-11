# type: ignore
# ruff: noqa
# fmt: off
# standalone (no prelude)
import os, errno, sys
B = '/tmp/dp_' + str(os.getpid()); os.makedirs(B)
open(B + '/f', 'w').write('abc')
# the results go to stderr (stdout is closed in the middle)
out = sys.stderr
def c(n, f):
    try: r = f()
    except OSError as e: r = 'ERR ' + errno.errorcode.get(e.errno, str(e.errno))
    except BaseException as e: r = 'EXC ' + type(e).__name__
    out.write('%s | %s\n' % (n, r)); out.flush()
c('close(1)', lambda: os.close(1))
c('write(1) closed', lambda: os.write(1, b'x'))
c('fstat(1) closed', lambda: os.fstat(1))
c('lseek(1) closed', lambda: os.lseek(1, 0, 1))
c('isatty(1) closed', lambda: os.isatty(1))
c('open gets fd 1?', lambda: (lambda fd: (os.close(fd), fd)[1])(os.open(B + '/f', 0)))
c('open keeps fd 1 and write(1) goes to the file', lambda: (lambda fd: (os.write(fd, b'Z') if fd == 1 else 'fd=%d' % (fd if fd != 1 else 0), os.close(fd))[0])(os.open(B + '/f', os.O_WRONLY)))
c('print after close(1)', lambda: print('hello'))
c('sys.stdout.write', lambda: sys.stdout.write('x'))
c('sys.stdout.flush', lambda: sys.stdout.flush())
