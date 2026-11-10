"""Checks of the component build (tools/wasip2/build.sh): Python, files and sockets under stock `wasmtime run`.

    python tools/wasip2/check.py WORKDIR

A local HTTP server on 127.0.0.1 is the peer, so no external network is needed.
"""

import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

work = Path(sys.argv[1]).resolve() / "p2"
wasmtime = work / "wasmtime-v50.0.1-x86_64-linux" / "wasmtime"
component = work / "pyodide.component.wasm"


def guest(code: str) -> subprocess.CompletedProcess[str]:
    cmd = [str(wasmtime), "run", "-W", "all-proposals=y", "-S", "inherit-network=y", "-S", "allow-ip-name-lookup=y"]
    cmd += [
        "--dir",
        f"{work / 'root'}::/",
        "--env",
        "PYTHONHOME=/",
        "--env",
        "PYTHONPATH=/lib/python3.15/site-packages",
    ]
    return subprocess.run([*cmd, str(component), "-c", code], capture_output=True, text=True, timeout=300)


with TemporaryDirectory() as td:
    Path(td, "index.txt").write_text("hello from the host server\n")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=td))
    server.RequestHandlerClass.log_message = lambda *a: None  # type: ignore[method-assign]
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    checks = {
        "python": ("import sys; print(sys.platform, sum(range(10)))", "emscripten 45"),
        "files": ("import os; print(sorted(os.listdir('/')))", "['lib']"),
        "tcp": (
            f"import socket\ns = socket.create_connection(('127.0.0.1', {port}), timeout=10)\n"
            "s.sendall(b'GET /index.txt HTTP/1.0\\r\\n\\r\\n')\nd = b''\n"
            "while True:\n    c = s.recv(4096)\n    if not c: break\n    d += c\n"
            f"print(d.split(b'\\r\\n')[0].decode(), d.split(b'\\r\\n\\r\\n')[1].decode().strip(), s.getpeername()[1] == {port})",
            "HTTP/1.0 200 OK hello from the host server True",
        ),
        "dns+urllib": (
            f"import socket, urllib.request\nprint(socket.gethostbyname('localhost'), urllib.request.urlopen('http://localhost:{port}/index.txt', timeout=10).status)",
            "127.0.0.1 200",
        ),
        "refused": (
            "import socket\ntry: socket.create_connection(('127.0.0.1', 1), timeout=5)\nexcept ConnectionRefusedError: print('refused')",
            "refused",
        ),
        "unresolvable": (
            "import socket\ntry: socket.gethostbyname('no-such-host.invalid')\nexcept socket.gaierror: print('gaierror')",
            "gaierror",
        ),
    }
    bad = 0
    for name, (code, want) in checks.items():
        p = guest(code)
        ok = p.returncode == 0 and p.stdout.strip() == want
        bad += not ok
        print(
            ("ok  " if ok else "FAIL"),
            name,
            "" if ok else f"-> rc={p.returncode} out={p.stdout.strip()!r} err={p.stderr.strip()[-300:]!r}",
        )
    server.shutdown()
sys.exit(1 if bad else 0)
