// Ffi closures and ffi_call_js. Included only by adapter.c.
#ifndef ADAPTER_FFI_H
#define ADAPTER_FFI_H

#include "common.h"

// A closure is a block from malloc whose first word is its table slot; the host reuses freed slots (getEmptyTableSlot)
EXPORT("ffi_closure_alloc_js") u32 ffi_closure_alloc_js(u32 size, u32 *code) {
    u32 *closure = (u32 *)malloc(size);
    if (!closure) {
        *code = 0;
        return 0;
    }
    u32 slot = host_ffi_slot();
    *code = slot;
    *closure = slot;
    return (u32)closure;
}

EXPORT("ffi_closure_free_js") void ffi_closure_free_js(u32 *closure) {
    host_ffi_free(*closure);
    free(closure);
}

EXPORT("ffi_prep_closure_loc_js") i32 ffi_prep_closure_loc_js(void *closure, const void *cif, u32 fun, u32 user_data, u32 codeloc) {
    return host_ffi_prep(closure, cif, fun, user_data, codeloc);
}

// ================================================================== ffi_call_js: ctypes calls
// libffi's emscripten port calls through JavaScript (`wasmTable.get(fn)(...args)`), which takes any callee type. The host
// does the same (loader.ffi_call: any arity, 64-bit, floats, structs, variadic calls).
EXPORT("ffi_call_js") void ffi_call_js(const void *cif, u32 fn, void *rvalue, void **avalue) { host_ffi_call(cif, fn, rvalue, avalue); }

#endif
