# type: ignore
# ruff: noqa
# fmt: off
# standalone (no prelude)
import os, ctypes
B = '/tmp/dp_' + str(os.getpid()); os.makedirs(B)
open(B + '/f', 'w').write('x')
L = ctypes.CDLL(None, use_errno=True)
class TS(ctypes.Structure): _fields_ = [('sec', ctypes.c_longlong), ('nsec', ctypes.c_long)]
# Pyodide: an invalid timespec is stored as NaN and the next stat of the file is a fatal RangeError (BigInt(NaN)); ours: EINVAL
arr = (TS * 2)(TS(10, 10 ** 9), TS(10, 0))
print('utimensat nsec=1e9 ->', L.utimensat(-100, (B + '/f').encode(), arr, 0), ctypes.get_errno())
print('stat ->', os.stat(B + '/f').st_mtime)
