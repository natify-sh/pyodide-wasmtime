# type: ignore
# ruff: noqa
# fmt: off
# standalone (no prelude)
import os, errno
B = '/tmp/dp_' + str(os.getpid()); os.makedirs(B)
open(B + '/f', 'w').write('0123456789')
fd = os.open(B + '/f', os.O_RDWR)
def c(n, f):
    try: r = f()
    except OSError as e: r = 'ERR ' + str(errno.errorcode.get(e.errno, e.errno))
    except BaseException as e: r = 'EXC ' + type(e).__name__
    print(n, '|', r)
c('lseek SET 2**63-1', lambda: os.lseek(fd, 2 ** 63 - 1, 0))
c('lseek CUR 1 from there', lambda: os.lseek(fd, 1, 1))
c('lseek CUR 2**62 twice', lambda: (os.lseek(fd, 0, 0), os.lseek(fd, 2 ** 62, 1), os.lseek(fd, 2 ** 62, 1), os.lseek(fd, 2 ** 62, 1)))
c('lseek END 2**63-1', lambda: (os.lseek(fd, 0, 0), os.lseek(fd, 2 ** 63 - 1, 2)))
c('lseek END 2**63-10', lambda: (os.lseek(fd, 0, 0), os.lseek(fd, 2 ** 63 - 10, 2)))
c('lseek after', lambda: os.lseek(fd, 0, 1))
c('print after', lambda: print('alive'))
