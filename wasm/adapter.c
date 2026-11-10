// Emscripten `env` imports of pyodide.asm.wasm answered over WASI preview1, as a wasm module.
//
// Shape (after Wasmtime's wasi-preview1-component-adapter): built as an Emscripten-style side module
// (-fPIC -shared) with NO data section and no stack of its own: it imports the main module's memory,
// table and __stack_pointer and works on the main module's pointers directly. Its only state (directory
// cookies) is one block from the main module's malloc, kept in a wasm global.
//
// Paths: every absolute path and every path relative to AT_FDCWD (the cwd is always "/") goes to the
// first preopen (fd 3), which the host maps to the guest's "/". Emscripten's errno values are WASI's,
// so a WASI error is returned as is (negated, as a syscall does).

#include "adapter/common.h"
#include "adapter/state.h"
#include "adapter/cwd.h"
#include "adapter/metadata.h"
#include "adapter/openfiles.h"
#include "adapter/loader.h"
#include "adapter/mmap.h"
#include "adapter/log.h"
#include "adapter/ffi.h"
#include "adapter/writes.h"
#include "adapter/sockets.h"
#include "adapter/time.h"
#include "adapter/owners.h"
#include "adapter/signals.h"
