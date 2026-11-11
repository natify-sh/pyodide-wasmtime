# ruff: noqa
# type: ignore
# select, poll, selectors, epoll and friends (ENOSYS expected), pipes.
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
try:
    PR, PW = os.pipe()
    os.write(PW, b"123")
except OSError:
    PR, PW = 90, 91  # the pipe cases below then show the same error as the call itself
buf = b"\0" * 8
# select / poll / selectors
case("select-has-epoll", lambda: hasattr(select, "epoll"))
case("select-has-kqueue", lambda: hasattr(select, "kqueue"))
case("select-has-poll", lambda: hasattr(select, "poll"))
case("select-has-devpoll", lambda: hasattr(select, "devpoll"))
case("select-consts", lambda: sorted(n for n in dir(select) if n.isupper()))
case("select-PIPE_BUF", lambda: select.PIPE_BUF)
case("selectors-default", lambda: selectors.DefaultSelector.__name__)
case("selectors-names", lambda: sorted(n for n in dir(selectors) if n.endswith("Selector")))
case("select-empty-0", lambda: select.select([], [], [], 0))
case("select-empty-timeout", lambda: select.select([], [], [], 0.01))
case("select-stdin-r", lambda: select.select([0], [], [], 0))
case("select-stdin-r-timeout", lambda: select.select([0], [], [], 0.01))
case("select-stdout-w", lambda: select.select([], [1], [], 0))
case("select-stderr-w", lambda: select.select([], [2], [], 0))
case("select-stdout-r", lambda: select.select([1], [], [], 0))
case("select-stdin-x", lambda: select.select([], [], [0], 0))
case("select-file-rwx", lambda: select.select([FILE_FD], [FILE_FD], [FILE_FD], 0))
case("select-pipe-r", lambda: select.select([PR], [], [], 0))
case("select-pipe-w", lambda: select.select([], [PW], [], 0))
case("select-pipe-empty-r", lambda: (lambda p: select.select([p[0]], [], [], 0))(os.pipe()))
case("select-devnull", lambda: (lambda fd: select.select([fd], [fd], [], 0))(os.open("/dev/null", os.O_RDWR)))
case("select-devzero", lambda: (lambda fd: select.select([fd], [fd], [], 0))(os.open("/dev/zero", os.O_RDWR)))
case("select-dir", lambda: select.select([os.open(B, os.O_RDONLY)], [], [], 0))
case("select-closed-fd", lambda: select.select([77], [], [], 0))
case("select-neg-fd", lambda: select.select([-1], [], [], 0))
case("select-fd-1024", lambda: select.select([1024], [], [], 0))
case("select-fd-big", lambda: select.select([2**31], [], [], 0))
case("select-fileobj", lambda: select.select([sys.stdin], [sys.stdout], [], 0))
case("select-non-int", lambda: select.select(["x"], [], [], 0))
case("select-neg-timeout", lambda: select.select([], [], [], -1))
case("select-nan-timeout", lambda: select.select([], [], [], float("nan")))
case("select-huge-timeout", lambda: select.select([1], [], [], 1e300))
case("select-None-timeout-ready", lambda: select.select([], [1], [], None))
case("select-dup-fds", lambda: select.select([], [1, 1, 2], [], 0))
case("select-many-fds", lambda: len(select.select([], [1] * 500, [], 0)[1]))
case(
    "select-timeout-elapsed",
    lambda: (lambda t0: (select.select([], [], [], 0.2), __import__("time").time() - t0 >= 0.19)[1])(
        __import__("time").time()
    ),
)
case(
    "select-sleep-precision",
    lambda: (lambda t0: (select.select([], [], [], 0.05), 0.04 < __import__("time").time() - t0 < 0.5)[1])(
        __import__("time").time()
    ),
)
case(
    "time-sleep-small",
    lambda: (lambda t0: (__import__("time").sleep(0.05), 0.04 < __import__("time").time() - t0 < 0.5)[1])(
        __import__("time").time()
    ),
)
case("time-sleep-zero", lambda: __import__("time").sleep(0))
case("time-sleep-neg", lambda: __import__("time").sleep(-1))
case("time-sleep-inf", lambda: __import__("time").sleep(float("inf")) if False else "skipped")


def pollcase(fd, ev, timeout=0):
    p = select.poll()
    p.register(fd, ev)
    return p.poll(timeout)


try:
    DN = os.open("/dev/null", os.O_RDWR)
except OSError:
    DN = 95  # no /dev/null: the cases that use it show the missing descriptor
ALL = select.POLLIN | select.POLLOUT | select.POLLPRI | select.POLLERR | select.POLLHUP | select.POLLNVAL
for nm, fd in (
    ("0", 0),
    ("1", 1),
    ("2", 2),
    ("file", FILE_FD),
    ("pipe-r", PR),
    ("pipe-w", PW),
    ("closed", 77),
    ("dir", os.open(B, os.O_RDONLY)),
    ("devnull", DN),
):
    for en, ev in (("IN", select.POLLIN), ("OUT", select.POLLOUT), ("PRI", select.POLLPRI), ("ALL", ALL), ("none", 0)):
        case("poll-%s-%s" % (nm, en), lambda fd=fd, ev=ev: pollcase(fd, ev))
case("poll-register-neg", lambda: select.poll().register(-1))
case("poll-register-str", lambda: select.poll().register("x"))
case("poll-register-twice", lambda: (lambda p: (p.register(1), p.register(1), p.poll(0))[2])(select.poll()))
case("poll-unregister-missing", lambda: select.poll().unregister(1))
case("poll-modify-missing", lambda: select.poll().modify(1, select.POLLIN))
case("poll-empty", lambda: select.poll().poll(0))
case("poll-empty-timeout", lambda: select.poll().poll(10))
case("poll-neg-timeout-ready", lambda: pollcase(1, select.POLLOUT, -1))
case("poll-None-timeout-ready", lambda: pollcase(1, select.POLLOUT, None))
case("poll-float-timeout", lambda: pollcase(1, select.POLLOUT, 0.5))
case("poll-huge-timeout", lambda: pollcase(1, select.POLLOUT, 2**40))
case("poll-bad-events", lambda: pollcase(1, 2**20))
case("poll-bad-events-neg", lambda: pollcase(1, -1))
case("poll-fileobj", lambda: (lambda p: (p.register(sys.stdout, select.POLLOUT), p.poll(0))[1])(select.poll()))
case(
    "poll-many",
    lambda: (
        lambda p: (
            [p.register(i, select.POLLOUT) for i in range(1, 300) if False],
            [p.register(os.dup(1), select.POLLOUT) for _ in range(100)],
            len(p.poll(0)),
        )[2]
    )(select.poll()),
)


def elapsed(fn):
    import time

    t0 = time.time()
    r = fn()
    return (r, 0.15 < time.time() - t0 < 1.0)


case("select-empty-0.2-elapsed", lambda: elapsed(lambda: select.select([], [], [], 0.2)))
case("select-stdin-0.2-elapsed", lambda: elapsed(lambda: select.select([0], [], [], 0.2)))
case("select-file-x-0.2-elapsed", lambda: elapsed(lambda: select.select([], [], [FILE_FD], 0.2)))
case("select-stdout-x-0.2-elapsed", lambda: elapsed(lambda: select.select([], [], [1], 0.2)))
case("poll-empty-0.2-elapsed", lambda: elapsed(lambda: select.poll().poll(200)))
case("poll-stdin-IN-0.2-elapsed", lambda: elapsed(lambda: pollcase(0, select.POLLIN, 200)))
case("poll-file-PRI-0.2-elapsed", lambda: elapsed(lambda: pollcase(FILE_FD, select.POLLPRI, 200)))
case("poll-stdout-PRI-0.2-elapsed", lambda: elapsed(lambda: pollcase(1, select.POLLPRI, 200)))
case("poll-no-events-0.2-elapsed", lambda: elapsed(lambda: pollcase(1, 0, 200)))
case("selectors-select-0.2-elapsed", lambda: elapsed(lambda: selectors.DefaultSelector().select(0.2)))
