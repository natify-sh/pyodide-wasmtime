"""Run by `site` at every start of the guest (`pyodide_nojs.pth`), so that the user's own sitecustomize.py is free."""

import os
import sys

# where the wheels of Pyodide's lock are (bump with the release)
LOCK_BASE = "https://cdn.jsdelivr.net/pyodide/v315.0.0a2/full/"
LOCK = f"/lib/python{sys.version_info[0]}.{sys.version_info[1]}/site-packages/pyodide-lock.json"

# Pyodide's _socket was built without the constant SO_REUSEADDR (musl's value is 2), which asyncio and
# socketserver look up; setsockopt itself is real (tools/patch_main.mjs)
import _socket

_socket.SO_REUSEADDR = 2  # pyright: ignore[reportAttributeAccessIssue]

if os.path.exists(LOCK):
    import pyodide_lock  # pyright: ignore[reportMissingImports]  # its sibling file in the guest

    pyodide_lock.hook(LOCK, LOCK_BASE)
