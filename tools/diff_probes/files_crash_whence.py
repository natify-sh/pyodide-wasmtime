# type: ignore
# ruff: noqa
# fmt: off
# standalone (no prelude)
import os, errno, sys
B = '/tmp/dp_' + str(os.getpid()); os.makedirs(B)
open(B + '/f', 'w').write('0123456789')
fd = os.open(B + '/f', os.O_RDWR)
# argv-less: the case is chosen by the WHENCE below (edit and rerun); ours traps in fd_seek ("Invalid enum value Whence")
WHENCE = int(os.environ.get('WHENCE', '3')) if hasattr(os, 'environ') else 3
try: r = os.lseek(fd, 0, WHENCE)
except OSError as e: r = 'ERR ' + errno.errorcode.get(e.errno, str(e.errno))
print('lseek whence=%d | %s' % (WHENCE, r))
