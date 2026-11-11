# ruff: noqa
# type: ignore
# Extension modules of a wheel: numpy (unzipped from /dist) and some submodules, imported by path; a broken extension module.
import glob
import importlib
import importlib.machinery
import importlib.util
import sys
import zipfile

W = glob.glob("/dist/numpy-*.whl")[0]
ND = B + "/np"
zipfile.ZipFile(W).extractall(ND)
sys.path.insert(0, ND)
case("numpy-wheel-found", lambda: W.rsplit("/", 1)[1])
case("numpy-so-count", lambda: len(glob.glob(ND + "/numpy/**/*.so", recursive=True)))
case("import-numpy", lambda: importlib.import_module("numpy").__version__)
import numpy as np  # noqa: E402

for sub in (
    "numpy.core",
    "numpy._core",
    "numpy._core._multiarray_umath",
    "numpy._core._multiarray_tests",
    "numpy.linalg",
    "numpy.linalg._umath_linalg",
    "numpy.fft",
    "numpy.fft._pocketfft_umath",
    "numpy.random",
    "numpy.random.mtrand",
    "numpy.random._generator",
    "numpy.random._bounded_integers",
    "numpy.random._common",
    "numpy.random._mt19937",
    "numpy.random._pcg64",
    "numpy.random._philox",
    "numpy.random._sfc64",
    "numpy.random.bit_generator",
    "numpy.polynomial",
    "numpy.polynomial.polynomial",
    "numpy.ma",
    "numpy.testing",
    "numpy.lib",
    "numpy.lib.stride_tricks",
    "numpy.f2py",
    "numpy.ctypeslib",
    "numpy.typing",
    "numpy.matlib",
    "numpy._core._rational_tests",
    "numpy._core._struct_ufunc_tests",
    "numpy._core._simd",
    "numpy._core._operand_flag_tests",
    "numpy._core._umath_tests",
    "numpy.nope",
):
    case("import-" + sub, lambda sub=sub: importlib.import_module(sub).__name__)
case("np-sum", lambda: int(np.arange(1000).sum()))
case("np-dot", lambda: float(np.dot(np.arange(10.0), np.arange(10.0))))
case("np-matmul", lambda: np.matmul(np.eye(3), np.arange(9.0).reshape(3, 3)).tolist())
case("np-linalg-inv", lambda: np.linalg.inv(np.array([[2.0, 0], [0, 4.0]])).tolist())
case("np-linalg-det", lambda: round(float(np.linalg.det(np.array([[1.0, 2], [3, 4]]))), 6))
case("np-linalg-svd", lambda: [round(float(x), 6) for x in np.linalg.svd(np.array([[1.0, 2], [3, 4]]))[1]])
case("np-linalg-eig", lambda: sorted(round(float(x), 6) for x in np.linalg.eig(np.array([[2.0, 0], [0, 3.0]]))[0]))
case("np-linalg-solve", lambda: np.linalg.solve(np.array([[3.0, 1], [1, 2]]), np.array([9.0, 8])).tolist())
case("np-linalg-solve-singular", lambda: np.linalg.solve(np.zeros((2, 2)), np.zeros(2)))
case("np-fft", lambda: [round(abs(x), 6) for x in np.fft.fft(np.arange(8.0))])
case("np-random-seed", lambda: (np.random.seed(1), float(np.random.rand()))[1])
case("np-random-gen", lambda: float(np.random.default_rng(1).random()))
case("np-random-int", lambda: np.random.default_rng(5).integers(0, 100, 5).tolist())
case("np-sort", lambda: np.sort(np.array([3, 1, 2])).tolist())
case("np-str", lambda: str(np.arange(5)))
case("np-float16", lambda: float(np.float16(1.5) * np.float16(2)))
case("np-complex", lambda: complex(np.complex128(1 + 2j) * 2))
case("np-datetime", lambda: str(np.datetime64("2020-01-01") + 1))
case("np-einsum", lambda: np.einsum("ij,jk->ik", np.eye(2), np.ones((2, 2))).tolist())
case("np-unique", lambda: np.unique(np.array([3, 1, 1, 2])).tolist())
case("np-ma", lambda: float(np.ma.masked_array([1.0, 2, 3], mask=[0, 1, 0]).sum()))
case("np-poly", lambda: np.polynomial.Polynomial([1, 2, 3])(2.0))
case(
    "np-memmap",
    lambda: (
        np.arange(10, dtype="u1").tofile(B + "/mm.bin"),
        np.memmap(B + "/mm.bin", dtype="u1", mode="r")[:4].tolist(),
    )[1],
)
case("np-fromfile", lambda: np.fromfile(B + "/mm.bin", dtype="u1")[:3].tolist())
case("np-save-load", lambda: (np.save(B + "/a.npy", np.arange(4)), np.load(B + "/a.npy").tolist())[1])
case("np-load-mmap", lambda: np.load(B + "/a.npy", mmap_mode="r")[:2].tolist())
case("np-ctypes-data", lambda: np.arange(3, dtype="i4").ctypes.data > 0)
case("np-ctypeslib-load", lambda: np.ctypeslib.load_library("nope", ND))
case("np-testing", lambda: np.testing.assert_allclose(1.0, 1.0 + 1e-12))
case("np-test-fail", lambda: np.testing.assert_equal(1, 2))
case("np-error-state", lambda: (np.seterr(all="raise"), np.float64(1) / np.float64(0))[1])
case("np-big-alloc", lambda: np.zeros(2**28, dtype="u1").nbytes)
case("np-huge-alloc", lambda: np.zeros(2**33, dtype="u1").nbytes)
case(
    "np-modules-loaded-so",
    lambda: sorted(
        m
        for m, mod in sys.modules.items()
        if m.startswith("numpy") and str(getattr(mod, "__file__", "")).endswith(".so")
    )[:60],
)
case("so-file-suffixes", lambda: importlib.machinery.EXTENSION_SUFFIXES)
case("so-spec-numpy-core", lambda: importlib.util.find_spec("numpy._core._multiarray_umath").origin.replace(ND, "<ND>"))
# a broken extension module and a side module that is not a Python extension
SUF = importlib.machinery.EXTENSION_SUFFIXES[0]
open(ND + "/badext" + SUF, "wb").write(b"junk")
open(ND + "/emptyext" + SUF, "wb").write(b"")
open(ND + "/noinit" + SUF, "wb").write(open(B + "/so/ok.so", "rb").read())
open(ND + "/cyc" + SUF, "wb").write(open(B + "/so/cyc_a.so", "rb").read())
case("import-badext", lambda: importlib.import_module("badext"))
case("import-emptyext", lambda: importlib.import_module("emptyext"))
case("import-side-without-PyInit", lambda: importlib.import_module("noinit"))
case("import-side-without-PyInit-twice", lambda: importlib.import_module("noinit"))
case("import-missing-ext", lambda: importlib.import_module("numpy.nosuch"))
