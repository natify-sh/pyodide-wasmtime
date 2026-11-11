# type: ignore
# ruff: noqa
# fmt: off
# standalone (no prelude)
import os
B = '/tmp/dp_' + str(os.getpid()); os.makedirs(B)
open(B + '/f', 'w').write('x')
# Pyodide: utime(2**40) is accepted and then os.stat of the file is a fatal RangeError (BigInt(NaN)) when the time is beyond Date's range; ours: EINVAL (a known gap)
for t in (2 ** 40, 2 ** 53):
    try:
        os.utime(B + '/f', (t, t)); print('utime', t, 'ok', flush=True); print('stat', os.stat(B + '/f').st_mtime, flush=True)
    except OSError as e: print('utime', t, 'ERR', e.errno, flush=True)
