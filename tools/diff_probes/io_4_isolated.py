# ruff: noqa
# type: ignore
# isolate
# Cases that hang or kill the guest on one side: each in a fresh interpreter (the harness gives an isolated case 60 s).
import os
import sys

case("os-read-stdin-0", lambda: os.read(0, 0))
case("os-readv-stdin", lambda: os.readv(0, [bytearray(4)]))
case("os-readv-stdin-empty-buffer", lambda: os.readv(0, [bytearray(0)]))
case("os-readv-stdin-two", lambda: os.readv(0, [bytearray(2), bytearray(2)]))
case("os-readv-stdin-no-buffers", lambda: os.readv(0, []))
case("os-read-stdin-1", lambda: os.read(0, 1))
case("os-read-stdin-big", lambda: os.read(0, 2**20))
case("os-read-stdin-2gb", lambda: len(os.read(0, 2**31)))
case("os-read-stdin-huge", lambda: os.read(0, 2**40))
case("os-read-file-0", lambda: os.read(os.open(B + "/z", os.O_RDWR | os.O_CREAT), 0))
case("sys-stdin-read-0", lambda: sys.stdin.read(0))
case("sys-stdin-buffer-read-0", lambda: sys.stdin.buffer.read(0))
case("sys-stdin-buffer-read1-0", lambda: sys.stdin.buffer.read1(0))
case("sys-stdin-buffer-raw-read-0", lambda: sys.stdin.buffer.raw.read(0))
case("sys-stdin-buffer-raw-readinto-empty", lambda: sys.stdin.buffer.raw.readinto(bytearray(0)))
case("sys-stdin-readline-0", lambda: sys.stdin.readline(0))
case("sys-stdin-fd-open-read-0", lambda: open(0, "rb", buffering=0, closefd=False).read(0))
case("os-write-stdout-0", lambda: os.write(1, b""))
case("os-writev-stdout-empty", lambda: os.writev(1, [b""]))
case("os-writev-stdout-none", lambda: os.writev(1, []))
case("os-write-stderr-0", lambda: os.write(2, b""))
case("sys-stdout-close-then-print", lambda: (sys.stdout.close(), print("x"))[1])
case("os-close-1-then-print", lambda: (os.close(1), print("x"), sys.stdout.flush())[2])
case("os-close-1-then-write-2", lambda: (os.close(1), os.write(2, b"[after close 1]\n"))[1])
case("os-close-0-then-input", lambda: (os.close(0), input())[1])
case("os-close-0-then-read", lambda: (os.close(0), os.read(0, 1))[1])
case("os-close-2-then-stderr", lambda: (os.close(2), print("x", file=sys.stderr), sys.stderr.flush())[2])
case("os-dup2-devnull-stdout", lambda: (os.dup2(os.open("/dev/null", os.O_WRONLY), 1), os.write(1, b"x"))[1])
case(
    "os-dup2-file-to-stdout",
    lambda: (os.dup2(os.open(B + "/o", os.O_WRONLY | os.O_CREAT), 1), os.write(1, b"x"), open(B + "/o", "rb").read())[
        2
    ],
)
case("os-dup2-stdout-to-0", lambda: (os.dup2(1, 0), os.write(0, b"[to0]\n"))[1])
case("print-to-closed-fd-flush", lambda: (os.close(1), sys.stdout.write("x"), sys.stdout.flush())[2])
case("sys-stdout-none-print", lambda: (setattr(sys, "stdout", None), print("x"))[1])
case("libc-close-1-then-write", lambda: (__import__("ctypes").CDLL(None).close(1), os.write(1, b"x"))[1])
case("sys-exit-in-case", lambda: sys.exit(3))
case("os-exit-in-case", lambda: os._exit(4))
case("raise-SystemExit-str", lambda: (_ for _ in ()).throw(SystemExit("msg")))
case("os-abort", lambda: os.abort())
case("os-kill-self-SIGTERM", lambda: os.kill(os.getpid(), 15))
case("os-kill-self-SIGKILL", lambda: os.kill(os.getpid(), 9))
case("os-kill-self-SIGSEGV", lambda: os.kill(os.getpid(), 11))
case("ctypes-null-deref", lambda: __import__("ctypes").c_int.from_address(0).value)
case("ctypes-bad-deref", lambda: __import__("ctypes").c_int.from_address(2**31 + 1000).value)
case("ctypes-bad-deref-big", lambda: __import__("ctypes").c_int.from_address(2**32 - 4).value)
case("ctypes-call-null-fn", lambda: __import__("ctypes").CFUNCTYPE(None)(0)())
case("ctypes-call-bad-fn-index", lambda: __import__("ctypes").CFUNCTYPE(None)(99999999)())
case("ctypes-call-fn-index-1", lambda: __import__("ctypes").CFUNCTYPE(None)(1)())
case("fd-first-open", lambda: os.open(B + "/fd1", os.O_RDWR | os.O_CREAT))
case("fd-second-open", lambda: (os.open(B + "/fd1", os.O_RDWR | os.O_CREAT), os.open(B + "/fd1", os.O_RDWR))[1])
case(
    "fd-reuse-after-close",
    lambda: (lambda a: (os.close(a), os.open(B + "/fd1", os.O_RDWR | os.O_CREAT) == a)[1])(
        os.open(B + "/fd1", os.O_RDWR | os.O_CREAT)
    ),
)
case("fd-dup-of-file", lambda: (lambda a: os.dup(a) - a)(os.open(B + "/fd1", os.O_RDWR | os.O_CREAT)))
case("fd-open-dir", lambda: os.open(B, os.O_RDONLY))
case("fd-open-many-250", lambda: [os.open(B + "/fd1", os.O_RDWR | os.O_CREAT) for _ in range(250)][-1])
case("fd-open-1100", lambda: [os.open(B + "/fd1", os.O_RDWR | os.O_CREAT) for _ in range(1100)][-1])
case("fd-open-5000", lambda: [os.open(B + "/fd1", os.O_RDWR | os.O_CREAT) for _ in range(5000)][-1])
case("fd-rlimit-nofile", lambda: __import__("resource").getrlimit(__import__("resource").RLIMIT_NOFILE))
case("fd-fstat-3", lambda: os.fstat(3).st_mode & 0o170000)
case("fd-fstat-4", lambda: os.fstat(4).st_mode & 0o170000)
case("fd-fstat-5", lambda: os.fstat(5).st_mode & 0o170000)
case("fd-fstat-6", lambda: os.fstat(6).st_mode & 0o170000)
case("fd-close-3", lambda: os.close(3))
case("fd-close-4", lambda: os.close(4))
case("fd-write-3", lambda: os.write(3, b"x"))
