# ruff: noqa
# type: ignore
# isolate
# libc poll/epoll/pipe entry points and the rest of the poll family, one case per interpreter (Pyodide dies on some).
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

FILE_FD = os.open(B + "/ttyfile", os.O_RDWR | os.O_CREAT)
os.write(FILE_FD, b"abcdef")
import selectors
import select
import stat
import termios
import fcntl

try:
    PR, PW = os.pipe()
    os.write(PW, b"123")
except OSError:
    PR, PW = 90, 91  # the pipe cases below then show the same error as the call itself
buf = b"\0" * 8


def pollcase(fd, ev, timeout=0):
    p = select.poll()
    p.register(fd, ev)
    return p.poll(timeout)


case("os-poll-sym", lambda: libc.poll.__class__.__name__)
case("libc-poll-NULL-0", lambda: libc.poll(None, 0, 0))
case("libc-poll-NULL-1", lambda: libc.poll(None, 1, 0))
case("libc-poll-huge-nfds", lambda: libc.poll(None, 2**30, 0))
case("libc-poll-neg-timeout-empty", lambda: libc.poll(None, 0, -1) if False else "skipped")
case("libc-select-0", lambda: libc.select(0, None, None, None, ctypes.byref(ctypes.c_long(0))) if False else "skipped")
case(
    "sel-register-stdout",
    lambda: (lambda s: (s.register(1, selectors.EVENT_WRITE), [(k.fd, e) for k, e in s.select(0)])[1])(
        selectors.DefaultSelector()
    ),
)
case(
    "sel-register-file",
    lambda: (lambda s: (s.register(FILE_FD, selectors.EVENT_READ), [(k.fd, e) for k, e in s.select(0)])[1])(
        selectors.DefaultSelector()
    ),
)
case(
    "sel-register-stdin",
    lambda: (lambda s: (s.register(0, selectors.EVENT_READ), [(k.fd, e) for k, e in s.select(0)])[1])(
        selectors.DefaultSelector()
    ),
)
case(
    "sel-register-pipe",
    lambda: (lambda s: (s.register(PR, selectors.EVENT_READ), [(k.fd, e) for k, e in s.select(0)])[1])(
        selectors.DefaultSelector()
    ),
)
case("sel-register-closed", lambda: selectors.DefaultSelector().register(77, selectors.EVENT_READ))
case("sel-select-class", lambda: type(selectors.DefaultSelector()).__name__)
case(
    "sel-SelectSelector",
    lambda: (lambda s: (s.register(1, selectors.EVENT_WRITE), [(k.fd, e) for k, e in s.select(0)])[1])(
        selectors.SelectSelector()
    ),
)
case(
    "sel-PollSelector",
    lambda: (lambda s: (s.register(1, selectors.EVENT_WRITE), [(k.fd, e) for k, e in s.select(0)])[1])(
        selectors.PollSelector()
    ),
)
case("sel-EpollSelector", lambda: selectors.EpollSelector())
case("epoll-create", lambda: select.epoll())
case("epoll-sym-libc", lambda: libc.epoll_create1(0))
case("epoll-sym-libc-ctl", lambda: libc.epoll_ctl(5, 1, 1, None))
case("epoll-sym-libc-wait", lambda: libc.epoll_wait(5, None, 1, 0))
case("eventfd", lambda: os.eventfd(0))
case("eventfd-libc", lambda: libc.eventfd(0, 0))
case("signalfd-libc", lambda: libc.signalfd(-1, None, 0))
case("timerfd-libc", lambda: libc.timerfd_create(1, 0))
case("inotify-libc", lambda: libc.inotify_init())
case("pipe2-nonblock", lambda: (lambda p: (os.get_blocking(p[0]), p))(os.pipe2(os.O_NONBLOCK))[0])
case("pipe-read-empty-nonblock", lambda: (lambda p: os.read(p[0], 1))(os.pipe2(os.O_NONBLOCK)))
case("pipe-write-read", lambda: (lambda p: (os.write(p[1], b"abc"), os.read(p[0], 10))[1])(os.pipe()))
case("pipe-write-closed-reader", lambda: (lambda p: (os.close(p[0]), os.write(p[1], b"x"))[1])(os.pipe()))
case("pipe-read-closed-writer", lambda: (lambda p: (os.close(p[1]), os.read(p[0], 10))[1])(os.pipe()))
case("pipe-fstat", lambda: stat.S_ISFIFO(os.fstat(os.pipe()[0]).st_mode))
case("pipe-lseek", lambda: os.lseek(os.pipe()[0], 0, 0))
case("pipe-big-write", lambda: (lambda p: os.write(p[1], b"x" * 100000))(os.pipe()))
case("pipe-poll-after-write", lambda: (lambda p: (os.write(p[1], b"a"), pollcase(p[0], select.POLLIN))[1])(os.pipe()))
case(
    "pipe-select-after-write",
    lambda: (lambda p: (os.write(p[1], b"a"), select.select([p[0]], [], [], 0)[0] == [p[0]])[1])(os.pipe()),
)
case("pipe-poll-after-close-writer", lambda: (lambda p: (os.close(p[1]), pollcase(p[0], select.POLLIN))[1])(os.pipe()))
case(
    "pipe-fionread",
    lambda: (lambda p: (os.write(p[1], b"abc"), fcntl.ioctl(p[0], termios.FIONREAD, b"\0\0\0\0"))[1])(os.pipe()),
)
case("socketpair", lambda: __import__("socket").socketpair())
