# type: ignore
# ruff: noqa
# fmt: off
# standalone (no prelude)
# ours HANGS forever on os.read(0, 0) (stdin at EOF or not); Pyodide returns b"" at once
import os
print('before')
print(os.read(0, 0))
print('after')
