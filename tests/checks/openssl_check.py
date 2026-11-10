# Pyodide's own OpenSSL (the shared library package libopenssl 1.1.1w of the lock) in the guest, through
# ctypes and the adapter's loader. Needs the host's /dev preopened (PREOPEN_DEV=1): OpenSSL reads its
# entropy from /dev/urandom. SITE_DIR/openssl/ holds the unpacked libopenssl-1.1.1w.zip.
import ctypes
import hashlib

P = "/lib/python3.15/site-packages/openssl/"
crypto = ctypes.CDLL(P + "libcrypto.so")
ssl = ctypes.CDLL(P + "libssl.so")
for f, r, a in [
    (crypto.OpenSSL_version, ctypes.c_char_p, [ctypes.c_int]),
    (crypto.SHA256, ctypes.c_void_p, [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p]),
    (crypto.ERR_get_error, ctypes.c_ulong, []),
    (ssl.TLS_client_method, ctypes.c_void_p, []),
    (ssl.SSL_CTX_new, ctypes.c_void_p, [ctypes.c_void_p]),
    (ssl.SSL_new, ctypes.c_void_p, [ctypes.c_void_p]),
]:
    f.restype, f.argtypes = r, a
print("libcrypto", crypto.OpenSSL_version(0).decode())
buf = ctypes.create_string_buffer(32)
crypto.SHA256(b"abc", 3, buf)
print("SHA256(abc) equal to hashlib:", buf.raw == hashlib.sha256(b"abc").digest())
ctx = ssl.SSL_CTX_new(ssl.TLS_client_method())
print("SSL_CTX_new", bool(ctx), "SSL_new", bool(ssl.SSL_new(ctx)), "ERR_get_error", crypto.ERR_get_error())
