# type: ignore
# ruff: noqa
# fmt: off
# standalone (no prelude)
import os, errno
B = '/tmp/dp_' + str(os.getpid()); os.makedirs(B)
fd = os.open(B + '/f', os.O_RDWR | os.O_CREAT)
# Pyodide (MEMFS grows one array): pwrite far beyond the end is a fatal RangeError (Array buffer allocation failed); ours: a sparse host file
for n in (2 ** 20, 2 ** 28, 2 ** 31, 2 ** 32, 2 ** 40):
    try: print('pwrite', n, os.pwrite(fd, b'x', n), os.fstat(fd).st_size, flush=True)
    except OSError as e: print('pwrite', n, 'ERR', errno.errorcode[e.errno], flush=True)
