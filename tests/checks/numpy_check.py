import sys
import time

import numpy as np

print("python", sys.version.split()[0], "numpy", np.__version__)
a = np.arange(1_000_000, dtype=np.float64)
t = time.time()
print("sum", a.sum(), "mean", a.mean(), "std", round(float(a.std()), 3))
b = np.arange(12).reshape(3, 4)
print("matmul", (b @ b.T).tolist())
print("linalg inv", np.linalg.inv(np.array([[2.0, 1.0], [1.0, 3.0]])).round(4).tolist())
print("sort", np.sort(np.array([5, 3, 9, 1, 7])).tolist())
print("fft", np.abs(np.fft.fft(np.arange(8))).round(3).tolist())
r = np.random.default_rng(42)
print("random", r.integers(0, 100, 5).tolist(), round(float(r.random()), 6))
print(
    "dtype/cast", np.array([1, 2, 3], dtype=np.int8).astype(np.float32).tolist(), np.sqrt(np.array([4.0, 9.0])).tolist()
)
print(
    "lstsq",
    np.linalg.lstsq(np.array([[1.0, 1.0], [1.0, 2.0], [1.0, 3.0]]), np.array([1.0, 2.0, 2.0]), rcond=None)[0]
    .round(4)
    .tolist(),
)
