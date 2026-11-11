# type: ignore
# ruff: noqa
# fmt: off
# standalone (no prelude)
import os, errno
def c(n, f):
    try: r = f()
    except OSError as e: r = 'ERR ' + errno.errorcode[e.errno]
    print(n, '|', r)
for fd in (3, 4, 5, 6, 7, 8, 9):
    c('fstat %d' % fd, lambda: os.fstat(fd).st_mode)
fd = os.open('/tmp', 0)
print('first free fd |', fd)
os.close(fd)
c('close 3', lambda: os.close(3))
c('open after', lambda: os.close(os.open('/tmp', 0)))
c('listdir /', lambda: len(os.listdir('/')) > 0)
c('open /etc', lambda: os.close(os.open('/etc', 0)))
c('exists', lambda: os.path.exists('/lib/python3.15/site-packages'))
