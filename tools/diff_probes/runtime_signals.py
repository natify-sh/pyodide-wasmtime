# ruff: noqa
# type: ignore
# SIGNALS: signal module, raise_signal, os.kill(getpid()), alarm/setitimer via ctypes, KeyboardInterrupt, safe points.
import ctypes
import errno
import os
import signal
import time

libc = ctypes.CDLL(None)


N = 0


def c(cid, f):
    global N
    N += 1
    if N <= globals().get("SKIP", 0):
        return
    print(">> " + cid, flush=True)
    try:
        r = f()
        print(cid, "|", r, flush=True)
    except OSError as e:
        print(cid, "| ERR", errno.errorcode.get(e.errno, e.errno), flush=True)
    except BaseException as e:
        print(cid, "| EXC", type(e).__name__, str(e)[:80], flush=True)


got = []


def h(n, fr):
    got.append(n)


c("valid_signals", lambda: sorted(int(s) for s in signal.valid_signals()))
c("Signals names", lambda: sorted((s.name, int(s)) for s in signal.Signals))
for n in list(range(-1, 70)) + [2**31, 2**32, 2**63]:
    c("strsignal %d" % n, lambda: signal.strsignal(n))
    c("getsignal %d" % n, lambda: signal.getsignal(n))
    c(
        "default_int? signal.signal-bad %d" % n,
        lambda: signal.signal(n, signal.SIG_IGN) and 0 if n not in range(1, 65) else "inrange",
    )
for n in range(1, 66):

    def one(n=n):
        old = signal.signal(n, h)
        got.clear()
        signal.raise_signal(n)
        r = list(got)
        signal.signal(n, old)
        return (str(old), r)

    c("signal+raise %d" % n, one)

    def kill(n=n):
        old = signal.signal(n, h)
        got.clear()
        os.kill(os.getpid(), n)
        r = list(got)
        signal.signal(n, old)
        return r

    c("os.kill(getpid) %d" % n, kill)

    def ign(n=n):
        old = signal.signal(n, signal.SIG_IGN)
        signal.raise_signal(n)
        r = signal.getsignal(n)
        signal.signal(n, old)
        return str(r)

    c("ignored raise %d" % n, ign)

    def pk(n=n):
        old = signal.signal(n, h)
        got.clear()
        signal.pthread_kill(__import__("threading").get_ident(), n)
        r = list(got)
        signal.signal(n, old)
        return r

    c("pthread_kill %d" % n, pk)
    c("siginterrupt %d" % n, lambda: signal.siginterrupt(n, True))
c("kill 0 sig0", lambda: os.kill(os.getpid(), 0))
c("kill pid 99999 sig0", lambda: os.kill(99999, 0))
c("kill pid 1 sig0", lambda: os.kill(1, 0))
c("kill ppid sig0", lambda: os.kill(os.getppid(), 0))
c("kill -1 0", lambda: os.kill(-1, 0))
c("killpg 0", lambda: os.killpg(0, 0))
c("kill bad sig", lambda: os.kill(os.getpid(), 999))
c("kill neg sig", lambda: os.kill(os.getpid(), -1))
c("signal bad handler", lambda: signal.signal(signal.SIGUSR1, 5))
c("signal SIGKILL", lambda: signal.signal(signal.SIGKILL, h))
c("signal SIGSTOP", lambda: signal.signal(signal.SIGSTOP, h))
c("signal SIG_DFL SIGINT", lambda: str(signal.signal(signal.SIGINT, signal.SIG_DFL)))
c("signal restore SIGINT", lambda: str(signal.signal(signal.SIGINT, signal.default_int_handler)))
c("default getsignal SIGINT", lambda: signal.getsignal(signal.SIGINT))
c("default getsignal SIGTERM", lambda: signal.getsignal(signal.SIGTERM))
c("default getsignal SIGPIPE", lambda: signal.getsignal(signal.SIGPIPE))
c("default getsignal SIGUSR1", lambda: signal.getsignal(signal.SIGUSR1))
c("sigmask", lambda: signal.pthread_sigmask(signal.SIG_BLOCK, []))
c("sigpending", lambda: signal.sigpending())
c("sigwait-less set_wakeup_fd", lambda: signal.set_wakeup_fd(-1))
c("set_wakeup_fd bad", lambda: signal.set_wakeup_fd(999))
c("signal.alarm", lambda: signal.alarm(0))
c("signal.setitimer", lambda: signal.setitimer(signal.ITIMER_REAL, 0))
c("signal.getitimer", lambda: signal.getitimer(signal.ITIMER_REAL))
c("signal.pause", lambda: hasattr(signal, "pause"))
c(
    "signal has",
    lambda: [
        x
        for x in (
            "alarm",
            "setitimer",
            "getitimer",
            "pause",
            "sigwait",
            "sigtimedwait",
            "pidfd_send_signal",
            "sigwaitinfo",
            "pthread_sigmask",
            "siginterrupt",
            "set_wakeup_fd",
            "pthread_kill",
            "raise_signal",
        )
        if hasattr(signal, x)
    ],
)


class ITV(ctypes.Structure):
    _fields_ = [
        ("isec", ctypes.c_int64),
        ("iusec", ctypes.c_int64),
        ("vsec", ctypes.c_int64),
        ("vusec", ctypes.c_int64),
    ]


def busy(secs, cond):
    t0 = time.monotonic()
    n = 0
    while time.monotonic() - t0 < secs and not cond():
        n += 1
    return n


def alarm_busy():
    got.clear()
    old = signal.signal(signal.SIGALRM, h)
    libc.alarm.restype = ctypes.c_uint
    r = libc.alarm(1)
    busy(3, lambda: got)
    left = libc.alarm(0)
    signal.signal(signal.SIGALRM, old)
    return (r, list(got), left)


c("alarm(1) in busy loop (handler runs?)", alarm_busy)


def itimer(which, sig, interval):
    got.clear()
    old = signal.signal(sig, h)
    v = ITV(0, 200000 if interval else 0, 0, 100000)
    r = libc.setitimer(which, ctypes.byref(v), None)
    busy(1.0, lambda: len(got) >= 2)
    z = ITV()
    cur = ITV(9, 9, 9, 9)
    libc.setitimer(which, ctypes.byref(z), ctypes.byref(cur))
    signal.signal(sig, old)
    return (r, len(got) >= (2 if interval else 1), cur.vsec == 0)


c("setitimer REAL oneshot busy", lambda: itimer(0, signal.SIGALRM, False))
c("setitimer REAL interval busy", lambda: itimer(0, signal.SIGALRM, True))
c("setitimer VIRTUAL busy", lambda: itimer(1, signal.SIGVTALRM, False))
c("setitimer PROF busy", lambda: itimer(2, signal.SIGPROF, False))
c("setitimer bad which", lambda: (libc.setitimer(7, ctypes.byref(ITV()), None), ctypes.get_errno()))
c("getitimer REAL", lambda: (libc.getitimer(0, ctypes.byref(ITV())), ctypes.get_errno()))


def itimer_sleep():
    got.clear()
    old = signal.signal(signal.SIGALRM, h)
    libc.alarm(1)
    time.sleep(0.2)
    r = list(got)
    libc.alarm(0)
    signal.signal(signal.SIGALRM, old)
    return r


c("alarm then sleep(0.2) (not due)", itimer_sleep)


def itimer_sleep2():
    got.clear()
    old = signal.signal(signal.SIGALRM, h)
    v = ITV(0, 0, 0, 50000)
    libc.setitimer(0, ctypes.byref(v), None)
    t0 = time.monotonic()
    time.sleep(0.3)
    r = (list(got), time.monotonic() - t0 < 1)
    libc.alarm(0)
    signal.signal(signal.SIGALRM, old)
    return r


c("setitimer 50ms then sleep(0.3) (handler runs during/after sleep?)", itimer_sleep2)


def ki(how):
    try:
        if how == "raise":
            signal.raise_signal(signal.SIGINT)
        elif how == "kill":
            os.kill(os.getpid(), signal.SIGINT)
        elif how == "libc":
            libc.raise_(signal.SIGINT) if hasattr(libc, "raise_") else libc.kill(os.getpid(), signal.SIGINT)
        for _ in range(100):
            pass
        return "no KeyboardInterrupt"
    except KeyboardInterrupt:
        return "KeyboardInterrupt"


for how in ["raise", "kill", "libc"]:
    c("SIGINT %s" % how, lambda: ki(how))
c(
    "SIGINT with SIG_IGN",
    lambda: (
        signal.signal(signal.SIGINT, signal.SIG_IGN),
        signal.raise_signal(2),
        signal.signal(2, signal.default_int_handler),
    )[1:2],
)
c("SIGINT custom handler raising", lambda: (lambda: (signal.signal(2, lambda n, f: 1 / 0), ki("raise"))[1])())
signal.signal(2, signal.default_int_handler)
c(
    "handler exception propagates",
    lambda: (
        signal.signal(signal.SIGUSR1, lambda n, f: (_ for _ in ()).throw(ValueError("boom"))),
        signal.raise_signal(signal.SIGUSR1),
    )[1],
)
signal.signal(signal.SIGUSR1, signal.SIG_DFL)
c(
    "handler args",
    lambda: (
        signal.signal(signal.SIGUSR1, lambda n, f: got.append((n, type(f).__name__))),
        got.clear(),
        signal.raise_signal(signal.SIGUSR1),
        got,
    )[3],
)
c("handler runs before next stmt", lambda: (got.clear(), signal.raise_signal(signal.SIGUSR1), len(got))[2])
c(
    "handler within busy loop (raise from C)",
    lambda: (got.clear(), [libc.raise_(10) if False else libc.kill(os.getpid(), 10) for _ in range(3)], len(got))[2],
)
c("libc signal() install", lambda: ctypes.CFUNCTYPE(None, ctypes.c_int))
c("libc sigaction missing?", lambda: hasattr(libc, "sigaction"))
c("libc raise", lambda: (got.clear(), getattr(libc, "raise")(10), list(got))[2])
c("libc raise bad", lambda: (getattr(libc, "raise")(999), ctypes.get_errno())[0])
c("libc kill bad", lambda: libc.kill(os.getpid(), 999))
c("libc kill pid-1 sig0", lambda: libc.kill(1, 0))
c("libc sigprocmask", lambda: libc.sigprocmask(0, None, None))
c("libc sigemptyset", lambda: libc.sigemptyset(ctypes.create_string_buffer(128)))
c("libc pause nodeadlock-less", lambda: hasattr(libc, "pause"))
c("libc alarm now 0", lambda: libc.alarm(0))
c("libc ualarm", lambda: libc.ualarm(0, 0))
c("libc sigsuspend exists", lambda: hasattr(libc, "sigsuspend"))
c(
    "libc strsignal",
    lambda: ctypes.c_char_p(ctypes.CFUNCTYPE(ctypes.c_char_p, ctypes.c_int)(("strsignal", libc))(11)).value,
)
