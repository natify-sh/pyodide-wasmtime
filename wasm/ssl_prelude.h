/* clang 18 lacks the __*_C helper macros that Emscripten 6's musl stdint.h uses (newer clang has them) */
#ifndef __INT8_C
#define __INT8_C(c) c
#define __INT16_C(c) c
#define __INT32_C(c) c
#define __INT64_C(c) c##LL
#define __UINT8_C(c) c
#define __UINT16_C(c) c
#define __UINT32_C(c) c##U
#define __UINT64_C(c) c##ULL
#define __INTMAX_C(c) c##LL
#define __UINTMAX_C(c) c##ULL
#endif
