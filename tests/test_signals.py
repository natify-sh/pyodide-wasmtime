"""Offline: signals (`__call_sighandler`, `_Py_CheckEmscriptenSignals_Helper`, `Pyodide.interrupt`), the interval timers
(`_setitimer_js`) and the runtime's name (`_Py_emscripten_runtime`), on both packagings."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import Guest

from pyodide_nojs import Pyodide

RAISE = """
import signal, os, time
got = []
signal.signal(signal.SIGUSR1, lambda s, f: got.append(("usr1", s)))
signal.signal(signal.SIGUSR2, lambda s, f: got.append(("usr2", s)))
signal.raise_signal(signal.SIGUSR1); print(got)
os.kill(os.getpid(), signal.SIGUSR2); print(got)
try:
    signal.raise_signal(signal.SIGINT); print("no KeyboardInterrupt")
except KeyboardInterrupt:
    print("KeyboardInterrupt")
try:
    os.kill(os.getpid(), signal.SIGINT); time.sleep(0); print("no KeyboardInterrupt (kill)")
except KeyboardInterrupt:
    print("KeyboardInterrupt (kill)")
"""


def test_raise_and_kill_call_the_handlers(guest: Guest) -> None:
    """What the real Pyodide prints: [('usr1', 10)] ... KeyboardInterrupt; it was nothing at all (__call_sighandler)."""
    r = guest.run(RAISE)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "[('usr1', 10)]",
        "[('usr1', 10), ('usr2', 12)]",
        "KeyboardInterrupt",
        "KeyboardInterrupt (kill)",
    ]


LOOP = """
import select, signal
got = []
def handler(s, f):
    got.append(s)
    if s == 10:
        raise ValueError("from the handler")
signal.signal(signal.SIGUSR1, handler)
n = 0
try:
    select.poll().poll(1)  # the host function that posts the signal (a sleep: no descriptors)
    while n < 3_000_000:
        n += 1
    print("not interrupted", n)
except BaseException as e:
    print("raised", type(e).__name__, n > 0 and n < 1000, got)
"""


@pytest.mark.parametrize(
    ("signum", "expected"), [(2, "raised KeyboardInterrupt True []"), (10, "raised ValueError True [10]")]
)
def test_interrupt_from_a_host_function(flavor: str, signum: int, expected: str, capfd: Any) -> None:
    """`Pyodide.interrupt(signum)` posts a signal that Python takes between bytecodes (JavaScript's
    Py_EmscriptenSignalBuffer): SIGINT is a KeyboardInterrupt in a running loop, another signal runs its handler."""
    with Pyodide(flavor) as py:
        original = py.net._n_pollv  # the host function the guest calls (poll with no descriptors is a sleep)

        def pollv(*args: int) -> int:
            py.interrupt(signum)
            return original(*args)

        py.net._n_pollv = pollv  # type: ignore[method-assign]
        assert py.run(LOOP) == 0
    assert capfd.readouterr().out.strip() == expected


def test_interrupt_needs_a_running_guest(flavor: str) -> None:
    with pytest.raises(RuntimeError, match="not running"):
        Pyodide(flavor).interrupt()


ITIMER = """
import ctypes as c, signal, time
got = []
signal.signal(signal.SIGALRM, lambda s, f: got.append(s))
libc = c.CDLL(None)
class tv(c.Structure): _fields_ = [("s", c.c_int64), ("us", c.c_int64)]
class itv(c.Structure): _fields_ = [("interval", tv), ("value", tv)]
libc.setitimer.argtypes = [c.c_int, c.POINTER(itv), c.c_void_p]
print("setitimer", libc.setitimer(0, c.byref(itv(tv(0, 0), tv(0, 100_000))), None))
t = time.time()
while time.time() - t < 5 and not got:
    pass
print("one-shot", got, time.time() - t < 5)
print("alarm", libc.alarm(1))
t = time.time()
while time.time() - t < 5 and len(got) < 2:
    pass
print("alarm", got)
libc.setitimer(0, c.byref(itv(tv(0, 20_000), tv(0, 20_000))), None)  # an interval timer
t = time.time()
while time.time() - t < 5 and len(got) < 5:
    pass
print("interval", len(got) >= 5)
libc.setitimer(0, c.byref(itv(tv(0, 0), tv(0, 0))), None)
"""


def test_itimer_delivers_sigalrm_when_python_looks_for_signals(guest: Guest) -> None:
    """ctypes setitimer/alarm reach `_setitimer_js`. JavaScript fires the timer from its event loop, after the run; here
    the deadline is checked whenever Python looks for signals, so a busy loop sees SIGALRM (the interval re-arms)."""
    r = guest.run(ITIMER)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["setitimer 0", "one-shot [14] True", "alarm 0", "alarm [14, 14]", "interval True"]


def test_the_runtime_is_named(guest: Guest) -> None:
    """`sys._emscripten_info.runtime`: Pyodide on Node says 'node v22...'; here this package."""
    r = guest.run("import sys; print(sys._emscripten_info.runtime)")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("pyodide-nojs ")
