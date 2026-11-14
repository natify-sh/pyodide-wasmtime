"""What the host runs in the guest: the start (`start`) and one `run` of the user's code."""

# pyright: reportAttributeAccessIssue=false
import errno
import signal
import sys
import traceback


def start(site_first):
    """Run at every start, also after a snapshot restore (so it is idempotent). /tmp and /home/pyodide are 0o777 in
    Pyodide, and the guest's modes are the adapter's own records, not the host's; stdout is line buffered, as
    Pyodide's (a line printed before a trap or os._exit is kept); '' first in sys.path as Pyodide's JavaScript puts
    it after the init (not with PYTHONSAFEPATH); with site= the user's packages come before the stdlib zip (a real
    _ssl over the zip's stub, as before)."""
    import os

    for d in ("/tmp", "/home/pyodide"):
        os.chmod(d, 0o777)
    sys.stdout.reconfigure(line_buffering=True)
    if not sys.flags.safe_path and sys.path[:1] != [""]:
        sys.path.insert(0, "")
    sp = f"/lib/python{sys.version_info[0]}.{sys.version_info[1]}/site-packages"
    if site_first and sp in sys.path:
        sys.path.remove(sp)
        sys.path.insert(0 if sys.flags.safe_path else 1, sp)


def _drop(signum, frame):
    pass


def _finish(err):
    """The status of a run and the report of how it ended: the SystemExit's code or message, the traceback of an
    uncaught error (130 for a KeyboardInterrupt, a shell's 128 + SIGINT, else 1), the flush of the standard streams."""
    rc = 0
    if err is None:
        pass
    elif isinstance(err, SystemExit):
        c = err.code
        if c is None:
            rc = 0
        elif isinstance(c, int):
            rc = int(c) & 255 if -(2**63) <= c < 2**63 else 255
        else:
            print(c, file=sys.stderr)
            rc = 1
    else:
        e = err
        rc = 130 if isinstance(e, KeyboardInterrupt) else 1
        e.__traceback__ = e.__traceback__.tb_next if e.__traceback__ else None  # not our frame (a SyntaxError has none)
        try:  # (OSError: the program closed descriptor 2, so there is nowhere to say it; Pyodide's runPython throws it)
            if sys.excepthook is sys.__excepthook__:
                traceback.print_exception(e)
            else:
                try:
                    sys.excepthook(type(e), e, e.__traceback__)
                except BaseException as e2:
                    e2.__traceback__ = e2.__traceback__.tb_next if e2.__traceback__ else None
                    traceback.print_exception(e2)
        except OSError as e3:
            if e3.errno != errno.EBADF:
                raise
    for s in (sys.stdout, sys.stderr):  # a stream whose descriptor the program closed: Pyodide never flushes at the end
        try:
            s.flush()
        except OSError as e4:
            if e4.errno != errno.EBADF:  # as CPython's shutdown: a message, status 120 (the program's own status stays)
                rc = rc or 120
                try:
                    print(f"Exception ignored in: {s!r}\n{type(e4).__name__}: {e4}", file=sys.__stderr__)
                except OSError:
                    pass
    return rc


def run(src_path, rc_path):
    """One `run()` of the host: the user's code in __main__, SystemExit as an exit status (the interpreter must
    survive it: Emscripten's exit() ends in `unreachable`), an uncaught KeyboardInterrupt as a traceback and status 130
    (a shell's 128 + SIGINT), any other error as a traceback and status 1.

    The host's Ctrl-C (`Pyodide.interrupt`) can come at any look for signals, also in this wrapper: once the user's code
    is over, SIGINT is given to a handler that does nothing until the status is written, so that a late signal can not
    cut the traceback, the flush or the status file (the host drops a signal that came late for the run anyway)."""
    err = None
    try:
        import __main__

        with open(src_path) as f:
            code = compile(f.read(), "<string>", "exec")
        exec(code, __main__.__dict__)
    except BaseException as e:
        err = e
    saved = None
    while True:  # a signal can still come between the end of the code and this handler
        try:
            if saved is None:
                saved = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, _drop)
            break
        except KeyboardInterrupt:
            if err is None:
                err = KeyboardInterrupt()
    rc = _finish(err)
    with open(rc_path, "w") as f:  # one write of the whole text
        f.write(str(rc))
    # the user's handler is back (a program that had none has Python's own)
    signal.signal(signal.SIGINT, signal.default_int_handler if saved is None else saved)
