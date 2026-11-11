# ruff: noqa
# type: ignore
# Standard streams, isatty, terminal size, ioctl/termios/fcntl on the std fds, files and pipes.
import ctypes
import fcntl
import io
import os
import select
import selectors
import stat
import sys
import termios

libc = ctypes.CDLL(None, use_errno=True)

# sys.std*
for nm in ("stdin", "stdout", "stderr", "__stdin__", "__stdout__", "__stderr__"):
    s = getattr(sys, nm)
    case("sys-%s-class" % nm, lambda s=s: type(s).__name__)
    case("sys-%s-isatty" % nm, lambda s=s: s.isatty())
    case("sys-%s-fileno" % nm, lambda s=s: s.fileno())
    case("sys-%s-encoding" % nm, lambda s=s: (s.encoding, s.errors))
    case("sys-%s-name" % nm, lambda s=s: s.name)
    case("sys-%s-mode" % nm, lambda s=s: s.mode)
    case("sys-%s-linebuf" % nm, lambda s=s: (s.line_buffering, getattr(s, "write_through", None)))
    case("sys-%s-newlines" % nm, lambda s=s: s.newlines)
    case("sys-%s-buffer-class" % nm, lambda s=s: type(getattr(s, "buffer", None)).__name__)
    case("sys-%s-closed" % nm, lambda s=s: s.closed)
    case("sys-%s-readable-writable-seekable" % nm, lambda s=s: (s.readable(), s.writable(), s.seekable()))
    case("sys-%s-tell" % nm, lambda s=s: s.tell())
    case("sys-%s-seek" % nm, lambda s=s: s.seek(0))
    case("sys-%s-raw-class" % nm, lambda s=s: type(getattr(getattr(s, "buffer", None), "raw", None)).__name__)
    case("sys-%s-raw-name" % nm, lambda s=s: getattr(getattr(getattr(s, "buffer", None), "raw", None), "name", None))
    case("sys-%s-blocking" % nm, lambda s=s: os.get_blocking(s.fileno()))
    case("sys-%s-fstat-mode" % nm, lambda s=s: stat.filemode(os.fstat(s.fileno()).st_mode)[0])
    case(
        "sys-%s-fstat-ischr-isfifo-isreg" % nm,
        lambda s=s: (lambda m: (stat.S_ISCHR(m), stat.S_ISFIFO(m), stat.S_ISREG(m), stat.S_ISSOCK(m)))(
            os.fstat(s.fileno()).st_mode
        ),
    )
case("sys-stdin-readline", lambda: sys.stdin.readline())
case("sys-stdin-read", lambda: sys.stdin.read())
case("sys-stdin-read1", lambda: sys.stdin.read(1))
case("sys-stdin-readlines", lambda: sys.stdin.readlines())
case("sys-stdin-iter", lambda: list(sys.stdin))
case("sys-stdin-buffer-read", lambda: sys.stdin.buffer.read())
case("sys-stdin-buffer-readline", lambda: sys.stdin.buffer.readline())
case("sys-stdin-buffer-peek", lambda: sys.stdin.buffer.peek())
case("input-eof", lambda: input())
case("input-prompt-eof", lambda: input("prompt> "))
case("os-read-stdin", lambda: os.read(0, 10))
case("os-read-stdin-neg", lambda: os.read(0, -1))
case("os-pread-stdin", lambda: os.pread(0, 4, 0))
case("os-lseek-stdin", lambda: os.lseek(0, 0, 0))
case("os-write-stdin", lambda: os.write(0, b"x"))
case("os-read-stdout", lambda: os.read(1, 10))
case("os-read-stderr", lambda: os.read(2, 10))
case("os-write-stdout-empty", lambda: os.write(1, b""))
case("os-write-stdout", lambda: os.write(1, b"[write1]\n"))
case("os-write-stderr", lambda: os.write(2, b"[write2]\n"))
case("os-write-stdout-no-newline", lambda: os.write(1, b"[nonl]"))
case("os-write-stdout-nl-after", lambda: os.write(1, b"\n"))
case("os-write-stdout-binary", lambda: os.write(1, b"\x00\x01\xff[bin]\n"))
case("os-write-stdout-utf8", lambda: os.write(1, "[ключ]\n".encode()))
case("os-write-stdout-invalid-utf8", lambda: os.write(1, b"[\xff\xfe]\n"))
case("os-write-stdout-big", lambda: os.write(1, b"x" * 100000 + b"\n") > 0)
case("os-write-stdout-crlf", lambda: os.write(1, b"[a\r\nb]\n"))
case("os-writev-stdout", lambda: os.writev(1, [b"[wv", b"1]\n"]))
case("os-pwrite-stdout", lambda: os.pwrite(1, b"x", 0))
case("os-lseek-stdout", lambda: os.lseek(1, 0, 0))
case("os-fsync-stdout", lambda: os.fsync(1))
case("os-fsync-stdin", lambda: os.fsync(0))
case("os-ftruncate-stdout", lambda: os.ftruncate(1, 0))
case("os-dup-stdout-write", lambda: (lambda fd: (os.write(fd, b"[dup]\n"), os.close(fd))[0])(os.dup(1)))
case("os-dup-stdout-fd-number", lambda: (lambda fd: (os.close(fd), fd)[1])(os.dup(1)))
case("os-dup2-stdout-to-9", lambda: (os.dup2(1, 9), os.write(9, b"[dup2]\n"), os.close(9))[1])
case("os-dup-stdin-isatty", lambda: (lambda fd: (os.isatty(fd), os.close(fd))[0])(os.dup(0)))
case("os-fdopen-1-write", lambda: (lambda f: (f.write("[fdopen]\n"), f.flush())[0])(os.fdopen(os.dup(1), "w")))
case("open-fd-1-write", lambda: (lambda f: (f.write("[open1]\n"), f.flush())[0])(open(1, "w", closefd=False)))
case("open-fd-0-read", lambda: open(0, "rb", closefd=False).read())
case("print-stdout", lambda: print("[print]"))
case("print-stderr", lambda: print("[print-err]", file=sys.stderr))
case("print-no-newline-then-case", lambda: print("[nonl2]", end=""))
case("print-flush", lambda: print("[flush]", flush=True))
case("print-nonascii", lambda: print("[ключ € \U0001f600]"))
case("print-surrogate", lambda: print("[\udcff]"))
case("print-nul", lambda: print("[a\0b]"))
case("print-big-line", lambda: print("x" * 100000) and 0)
case("sys-stdout-write-return", lambda: sys.stdout.write("[sw]\n"))
case("sys-stdout-write-bytes", lambda: sys.stdout.write(b"x"))
case("sys-stdout-buffer-write", lambda: (sys.stdout.buffer.write(b"[bw]\n"), sys.stdout.flush())[0])
case(
    "sys-stdout-buffer-write-partial-utf8",
    lambda: (sys.stdout.buffer.write(b"[\xd0"), sys.stdout.buffer.write(b"\xba]\n"), sys.stdout.flush())[0],
)
case("sys-stdout-flush", lambda: sys.stdout.flush())
case("sys-stderr-write", lambda: sys.stderr.write("[se]\n"))
case("sys-stdout-writelines", lambda: sys.stdout.writelines(["[wl1]", "[wl2]\n"]))
case("sys-stdout-reconfigure", lambda: sys.stdout.reconfigure(encoding="latin-1") or sys.stdout.encoding)
case("sys-stdout-reconfigure-back", lambda: sys.stdout.reconfigure(encoding="utf-8") or sys.stdout.encoding)
case("sys-stdout-reconfigure-linebuf", lambda: sys.stdout.reconfigure(line_buffering=True))
case("sys-stdout-detach", lambda: type(io.TextIOWrapper(io.BytesIO()).detach()).__name__)
case("sys-stdout-truncate", lambda: sys.stdout.truncate())
case("sys-stdout-isatty-fd-0-1-2", lambda: [os.isatty(i) for i in (0, 1, 2)])
case("sys-stdout-fileno-eq", lambda: [sys.stdin.fileno(), sys.stdout.fileno(), sys.stderr.fileno()])
case("sys-excepthook-name", lambda: sys.excepthook.__module__)
case("sys-displayhook-name", lambda: sys.displayhook.__module__)
case(
    "sys-flags",
    lambda: (sys.flags.interactive, sys.flags.isolated, sys.flags.utf8_mode, sys.flags.unbuffered, sys.flags.dev_mode),
)
case(
    "sys-getdefaultencoding",
    lambda: (sys.getdefaultencoding(), sys.getfilesystemencoding(), sys.getfilesystemencodeerrors()),
)
case("sys-platform", lambda: (sys.platform, os.name, sys.byteorder, sys.maxsize))
case("sys-orig-argv", lambda: sys.orig_argv[:1] if hasattr(sys, "orig_argv") else None)
case("sys-argv", lambda: sys.argv)
case("sys-executable", lambda: sys.executable)
case("sys-prefix", lambda: (sys.prefix, sys.exec_prefix, sys.base_prefix))
case("locale-preferred", lambda: __import__("locale").getpreferredencoding(False))
case("locale-getlocale", lambda: __import__("locale").getlocale())

# os.isatty / ttyname / terminal size
for i in (0, 1, 2, 3, 100, 2**31 - 1, 2**31, 2**32, 2**63 - 1, -1):
    case("isatty-%d" % i, os.isatty, i)
for i in (0, 1, 2, 3, -1):
    case("ttyname-%d" % i, os.ttyname, i)
case("isatty-file", lambda: os.isatty(os.open(B + "/ttyfile", os.O_RDWR | os.O_CREAT)))
case("isatty-devnull", lambda: os.isatty(os.open("/dev/null", os.O_RDWR)))
case("isatty-dir", lambda: os.isatty(os.open(B, os.O_RDONLY)))
case("isatty-pipe", lambda: [os.isatty(i) for i in os.pipe()])
case("isatty-str", lambda: os.isatty("x"))
case("isatty-float", lambda: os.isatty(1.5))
case("get_terminal_size", lambda: os.get_terminal_size())
case("get_terminal_size-0", lambda: os.get_terminal_size(0))
case("get_terminal_size-file", lambda: os.get_terminal_size(os.open(B + "/ttyfile", os.O_RDWR)))
case("get_terminal_size-bad", lambda: os.get_terminal_size(99))
case("shutil-get_terminal_size", lambda: tuple(__import__("shutil").get_terminal_size()))
case("openpty", lambda: os.openpty())
case("pty-fork", lambda: os.forkpty())
case("ctermid", lambda: os.ctermid())
case("tcgetpgrp", lambda: os.tcgetpgrp(0))
case("getpgrp", lambda: os.getpgrp() >= 0)
case("setsid", lambda: os.setsid())
case("getsid", lambda: os.getsid(0))

# ioctl and termios
buf = b"\0" * 8
FILE_FD = os.open(B + "/ttyfile", os.O_RDWR | os.O_CREAT)
os.write(FILE_FD, b"abcdef")
try:
    PR, PW = os.pipe()
    os.write(PW, b"123")
except OSError:
    PR, PW = 90, 91  # the pipe cases below then show the same error as the call itself
for nm, fd in (
    ("0", 0),
    ("1", 1),
    ("2", 2),
    ("file", FILE_FD),
    ("pipe-r", PR),
    ("pipe-w", PW),
    ("closed", 77),
    ("neg", -1),
    ("devnull", None),
    ("dir", None),
):
    fdv = fd
    if nm == "devnull":
        try:
            fdv = os.open("/dev/null", os.O_RDWR)
        except OSError:
            fdv = 95  # no /dev/null: the cases below show the missing descriptor
    if nm == "dir":
        fdv = os.open(B, os.O_RDONLY)
    for rn in (
        "TIOCGWINSZ",
        "TIOCSWINSZ",
        "TIOCGPGRP",
        "TIOCSPGRP",
        "TCGETS",
        "TCSETS",
        "TIOCOUTQ",
        "TIOCINQ",
        "TIOCNOTTY",
        "TIOCSCTTY",
        "TIOCEXCL",
        "TIOCNXCL",
    ):
        if hasattr(termios, rn):
            case("ioctl-%s-%s" % (rn, nm), lambda fdv=fdv, rn=rn: fcntl.ioctl(fdv, getattr(termios, rn), buf))
    case("ioctl-FIONREAD-%s" % nm, lambda fdv=fdv: fcntl.ioctl(fdv, termios.FIONREAD, b"\0\0\0\0"))
    case("ioctl-FIONREAD-int-%s" % nm, lambda fdv=fdv: fcntl.ioctl(fdv, termios.FIONREAD, 0))
    case(
        "ioctl-FIONREAD-mutate-%s" % nm,
        lambda fdv=fdv: (lambda b: (fcntl.ioctl(fdv, termios.FIONREAD, b, True), bytes(b))[1])(bytearray(4)),
    )
    case("ioctl-FIONBIO-%s" % nm, lambda fdv=fdv: fcntl.ioctl(fdv, termios.FIONBIO, b"\1\0\0\0"))
    case("ioctl-FIOCLEX-%s" % nm, lambda fdv=fdv: fcntl.ioctl(fdv, termios.FIOCLEX))
    case("ioctl-0x5555-%s" % nm, lambda fdv=fdv: fcntl.ioctl(fdv, 0x5555, buf))
    case("ioctl-0-%s" % nm, lambda fdv=fdv: fcntl.ioctl(fdv, 0, buf))
    case("tcgetattr-%s" % nm, lambda fdv=fdv: termios.tcgetattr(fdv))
    case("tcsetattr-%s" % nm, lambda fdv=fdv: termios.tcsetattr(fdv, termios.TCSANOW, [0, 0, 0, 0, 0, 0, [b"\0"] * 32]))
    case("tcflush-%s" % nm, lambda fdv=fdv: termios.tcflush(fdv, termios.TCIFLUSH))
    case("tcdrain-%s" % nm, lambda fdv=fdv: termios.tcdrain(fdv))
    case("tcsendbreak-%s" % nm, lambda fdv=fdv: termios.tcsendbreak(fdv, 0))
    case("tcflow-%s" % nm, lambda fdv=fdv: termios.tcflow(fdv, termios.TCOON))
    case("tcgetwinsize-%s" % nm, lambda fdv=fdv: termios.tcgetwinsize(fdv))
    case("fcntl-GETFL-%s" % nm, lambda fdv=fdv: fcntl.fcntl(fdv, fcntl.F_GETFL) & 3)
    case("fcntl-GETFD-%s" % nm, lambda fdv=fdv: fcntl.fcntl(fdv, fcntl.F_GETFD))
    case(
        "fcntl-SETFL-nonblock-%s" % nm,
        lambda fdv=fdv: (
            fcntl.fcntl(fdv, fcntl.F_SETFL, os.O_NONBLOCK),
            fcntl.fcntl(fdv, fcntl.F_GETFL) & os.O_NONBLOCK,
        )[1],
    )
    case("fcntl-DUPFD-%s" % nm, lambda fdv=fdv: fcntl.fcntl(fdv, fcntl.F_DUPFD, 50) >= 50)
    case("fcntl-flock-%s" % nm, lambda fdv=fdv: fcntl.flock(fdv, fcntl.LOCK_SH | fcntl.LOCK_NB))
    case("os-get-blocking-%s" % nm, lambda fdv=fdv: os.get_blocking(fdv))
    case("os-set-blocking-%s" % nm, lambda fdv=fdv: os.set_blocking(fdv, False))
    case("os-fstat-%s" % nm, lambda fdv=fdv: stat.filemode(os.fstat(fdv).st_mode)[0])
    case("os-lseek-%s" % nm, lambda fdv=fdv: os.lseek(fdv, 0, 1))
    case("os-fstatvfs-%s" % nm, lambda fdv=fdv: os.fstatvfs(fdv).f_bsize > 0)
    case("os-fpathconf-%s" % nm, lambda fdv=fdv: os.fpathconf(fdv, "PC_NAME_MAX"))
    case("os-fsync-%s" % nm, lambda fdv=fdv: os.fsync(fdv))
    case("os-sendfile-%s" % nm, lambda fdv=fdv: os.sendfile(1, fdv, 0, 0))
