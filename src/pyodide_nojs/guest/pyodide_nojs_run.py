"""What the host runs in the guest: the start (`start`) and one `run` of the user's code."""

# pyright: reportAttributeAccessIssue=false
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


def run(src_path, rc_path):
    """One `run()` of the host: the user's code in __main__, SystemExit as an exit status (the interpreter must
    survive it: Emscripten's exit() ends in `unreachable`), any other error as a traceback and status 1."""
    import __main__

    rc = 0
    try:
        with open(src_path) as f:
            code = compile(f.read(), "<string>", "exec")
        exec(code, __main__.__dict__)
    except SystemExit as e:
        c = e.code
        if c is None:
            rc = 0
        elif isinstance(c, int):
            rc = int(c) & 255 if -(2**63) <= c < 2**63 else 255
        else:
            print(c, file=sys.stderr)
            rc = 1
    except BaseException as e:
        rc = 1
        e.__traceback__ = e.__traceback__.tb_next if e.__traceback__ else None  # not our frame (a SyntaxError has none)
        if sys.excepthook is sys.__excepthook__:
            traceback.print_exception(e)
        else:
            try:
                sys.excepthook(type(e), e, e.__traceback__)
            except BaseException as e2:
                e2.__traceback__ = e2.__traceback__.tb_next if e2.__traceback__ else None
                traceback.print_exception(e2)
    sys.stdout.flush()
    sys.stderr.flush()
    with open(rc_path, "w") as f:
        f.write(str(rc))
