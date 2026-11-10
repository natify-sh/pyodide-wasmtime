# cffi's callback() (ffi_prep_closure): the wheel's own, loaded by dlopen (the .expected file is what Pyodide prints)
import cffi

ffi = cffi.FFI()
cb = ffi.callback("int(int,int)", lambda a, b: a + b)
print("int", cb(3, 4))
print("double", ffi.callback("double(double)", lambda x: x * 2)(1.25))
print("int64", ffi.callback("long long(long long,long long)", lambda a, b: a * b)(1 << 33, 3))
ffi.cdef("void qsort(void*, size_t, size_t, int(*)(const void*, const void*));")
lib = ffi.dlopen(None)
arr = ffi.new("int[]", [5, 3, 9, 1, 4])


@ffi.callback("int(const void*, const void*)")
def cmp(a, b):
    return ffi.cast("int*", a)[0] - ffi.cast("int*", b)[0]


lib.qsort(arr, 5, 4, cmp)
print("qsort", list(arr))
