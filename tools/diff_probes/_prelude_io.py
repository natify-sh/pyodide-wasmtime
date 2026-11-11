# ruff: noqa
# type: ignore
# Put in front of every probe by tools/diff_pyodide.py, after `SIDES = {name: hex of a side module}` and
# `ONLY = None | k | -1` (the k-th case only; -1: list the case ids, run nothing).
import errno
import os
import time

B = "/tmp/dp_%09d" % (time.time_ns() % 10**9)
_cnt = [0]
os.makedirs(B + "/so", exist_ok=True)
for _nm, _h in SIDES.items():
    _p = B + "/so/" + _nm
    os.makedirs(os.path.dirname(_p), exist_ok=True)
    with open(_p, "wb") as _f:
        _f.write(bytes.fromhex(_h))


def show(v):
    return repr(v)[:300].replace("\n", "\\n")


def case(cid, fn, *a, **kw):
    _cnt[0] += 1
    if ONLY is not None and ONLY != _cnt[0] - 1:
        if ONLY == -1:
            print("%s | dry" % cid)
        return
    try:
        r = show(fn(*a, **kw))
    except OSError as e:
        r = "ERR " + errno.errorcode.get(e.errno, str(e.errno)) if e.errno else "ERR OSError " + show(str(e))
    except BaseException as e:
        r = "EXC %s: %s" % (type(e).__name__, show(str(e))[1:-1])
    print("%s | %s" % (cid, r), flush=True)
