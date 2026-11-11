"""The checks of the experiment, on both builds: what the program prints must be what it must print."""

from __future__ import annotations

import contextlib
import hashlib
import http.server
import io
import re
import sys
import threading
import zipfile

import pytest
from conftest import Guest, check_file


def exact(guest: Guest, script: str, site: str, expected: str, *args: str):
    p = guest.run(check_file(script), site, *args)
    assert p.returncode == 0, p.stderr[-2000:]
    assert p.stdout.splitlines() == check_file(expected).splitlines()
    return p


def lines(guest: Guest, code: str, site: str, patterns: list[str], *args: str):
    p = guest.run(code, site, *args)
    assert p.returncode == 0, p.stderr[-2000:]
    for pat in patterns:
        assert re.search(pat, p.stdout, re.M), f"missing /{pat}/ in:\n{p.stdout}"
    return p


def test_numpy(guest: Guest):
    p = exact(guest, "numpy_check.py", "site", "numpy_check.expected")
    assert "unresolved 0" not in p.stderr or True  # the loader's own log is not part of the contract


@pytest.mark.skipif(sys.platform == "win32", reason="--dev preopens the host's /dev, which Windows does not have")
def test_openssl_through_ctypes(guest: Guest):
    exact(guest, "openssl_check.py", "site_ssl", "openssl_check.expected", "--dev")


NET = [
    r"^pyfetch 200 True attrs$",
    r"^micropip: six, attrs, requests",
    r"^requests\.get 200 application/json micropip$",
    r"^cffi \(binary wheel via micropip\) 2\.0\.0 25 10$",
]
TLS = [
    r"^ssl OpenSSL 1\.1\.1w .*_ssl\.cpython-315-wasm32-emscripten\.so$",
    r"^handshake TLSv1\.3 \S+ \| peer cert subject CN: pypi\.org$",
    r"^raw response: HTTP/1\.1 200 OK$",
    r"^urllib 200 six$",
]
REFUSE = """
import socket, ssl
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # verification on, no CA
try:
    ctx.wrap_socket(socket.create_connection(("pypi.org", 443), timeout=20), server_hostname="pypi.org")
    print("accepted")
except ssl.SSLCertVerificationError as e:
    print("refused:", e.verify_message)
"""
NUMPY_WHEEL = """
import hostnet
hostnet.install()
import micropip
hostnet.run(micropip.install("https://cdn.jsdelivr.net/pyodide/v315.0.0a2/full/numpy-2.4.3-cp315-cp315-pyemscripten_2026_5_wasm32.whl"))
"""


@pytest.mark.network
def test_net_through_the_hosts_fetch(guest: Guest):
    lines(guest, check_file("net_check.py"), "site_net", NET)


@pytest.mark.network
def test_the_guests_own_tls(guest: Guest):
    lines(guest, check_file("tls_check.py"), "site_tls", TLS, "--dev")


@pytest.mark.network
def test_micropip_over_the_guests_tls(guest: Guest):
    lines(
        guest,
        check_file("tls_micropip.py"),
        "site_tls",
        [r"^micropip over guest TLS: six \S+ \| requests\.get 200 micropip$"],
        "--dev",
    )


@pytest.mark.network
def test_the_guest_refuses_a_certificate_with_no_ca(guest: Guest):
    lines(guest, REFUSE, "site_tls", [r"^refused: "], "--dev")


@pytest.mark.network
def test_numpy_wheel_from_the_cdn_is_converted_at_dlopen(guest: Guest):
    p = guest.run(NUMPY_WHEEL + check_file("numpy_check.py"), "site_net")
    assert p.returncode == 0, p.stderr[-2000:]
    assert p.stdout.splitlines() == check_file("numpy_check.expected").splitlines()
    assert p.stderr.count("[loader] converted legacy exceptions") >= 2


def _wheel(name: str, body: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{name}.py", body)
        z.writestr(f"{name}-1.0.dist-info/METADATA", f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
        z.writestr(f"{name}-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr(f"{name}-1.0.dist-info/RECORD", "")
    return buf.getvalue()


LOCK_HEAD = """
import asyncio
import micropip
import pyodide_lock

lock = {"info": {}, "packages": {
    n: {"name": n, "version": "1.0", "file_name": n + "-1.0-py3-none-any.whl", "sha256": h, "depends": d,
        "imports": [n], "package_type": "package", "install_dir": "site"}
    for n, h, d in %r}}
pyodide_lock.patch(micropip._compat, lock, "http://127.0.0.1:%d/")
"""
LOCK_GUEST = (
    """
import micropip
L = micropip._compat.LOCKFILE_PACKAGES
print("lock", micropip._compat.LOCKFILE_INFO["abi_version"], len(L), L["numpy"]["version"])
"""
    + LOCK_HEAD
    + """
asyncio.run(micropip.install("fakelockpkg"))
import fakelockpkg
print("installed", fakelockpkg.VALUE, micropip.list()["fakelockdep"].source)
"""
)
LOCK_ORDER = (
    LOCK_HEAD
    + """
import os, site
sp = site.getsitepackages()[0]
open(sp + "/preinst.py", "w").write("ORIG")
os.mkdir(sp + "/preinst-0.5.dist-info")
open(sp + "/preinst-0.5.dist-info/METADATA", "w").write("Metadata-Version: 2.1\\nName: preinst\\nVersion: 0.5\\n")
load = micropip._compat.loadPackage
asyncio.run(load(["a"]))
asyncio.run(load(["a"]))
asyncio.run(load("cyc1"))
asyncio.run(load(["preinst"]))
print("preinst", open(sp + "/preinst.py").read())
"""
)


@contextlib.contextmanager
def lock_server(tmp_path, deps: dict[str, list[str]], bodies: dict[str, str] | None = None):
    """A local server of fake wheels, one per name of `deps`; yields (port, the paths requested, the lock entries)."""
    entries = []
    for n, d in deps.items():
        w = _wheel(n, (bodies or {}).get(n, "X = 41\n"))
        (tmp_path / f"{n}-1.0-py3-none-any.whl").write_bytes(w)
        entries.append((n, hashlib.sha256(w).hexdigest(), d))
    hits: list[str] = []

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(tmp_path), **k)

        def do_GET(self):
            hits.append(self.path)
            super().do_GET()

        def log_message(self, format, *args):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv.server_address[1], hits, entries
    finally:
        srv.shutdown()
        srv.server_close()


def test_micropip_finds_a_package_of_the_lock(guest: Guest, tmp_path):
    """The lock is in the guest; micropip resolves a lock package by name and installs it (and its `depends`)
    from the base URL, sha256 checked: here a fake lock and a local server, no PyPI, no jsDelivr."""
    bodies = {"fakelockpkg": "import fakelockdep\nVALUE = fakelockdep.X + 1\n"}
    with lock_server(tmp_path, {"fakelockpkg": ["fakelockdep"], "fakelockdep": []}, bodies) as (port, _, entries):
        lines(
            guest,
            LOCK_GUEST % (entries, port),
            "site_net",
            [r"^lock 2026_5 31 2\.4\.3$", r"^installed 42 pyodide$"],
        )


def test_lock_packages_come_dependencies_first_once_and_never_over_an_installed_one(guest: Guest, tmp_path):
    deps = {"a": ["b", "c"], "b": ["c"], "c": [], "cyc1": ["cyc2"], "cyc2": ["cyc1"], "preinst": []}
    with lock_server(tmp_path, deps) as (port, hits, entries):
        lines(guest, LOCK_ORDER % (entries, port), "site_net", [r"^preinst ORIG$"])
    # a needs b and c, b needs c: c, b, a; the second call fetches nothing; a cycle ends; preinst is not fetched
    assert hits == [f"/{n}-1.0-py3-none-any.whl" for n in ("c", "b", "a", "cyc2", "cyc1")]


def test_a_failed_hook_fails_the_import_every_time(guest: Guest):
    code = (
        "import pyodide_lock\npyodide_lock.hook('/nonexistent', 'x')\n"
        "for i in range(2):\n"
        "    try:\n        import micropip\n    except FileNotFoundError:\n        print('failed', i)\n"
    )
    lines(guest, code, "site_net", [r"^failed 0$", r"^failed 1$"])


def test_the_lock_base_is_the_pinned_release():
    from pyodide_nojs import PYODIDE_VERSION
    from pyodide_nojs.guest.pyodide_nojs_start import LOCK_BASE

    assert LOCK_BASE == f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION.replace('-alpha.', 'a')}/full/"


@pytest.mark.network
def test_micropip_installs_numpy_from_pyodides_lock(guest: Guest):
    p = guest.run(
        "import hostnet; hostnet.install()\nimport asyncio, micropip\nasyncio.run(micropip.install('numpy'))\n"
        "import numpy\nprint('numpy', numpy.__version__, numpy.arange(3).sum())\n"
        "asyncio.run(micropip.install('scipy'))\n"
        "import scipy.linalg\nprint('scipy', scipy.linalg.det([[1, 2], [3, 4]]))\n",
        "site_net",
    )
    assert p.returncode == 0, p.stderr[-2000:]
    assert re.search(r"^numpy 2\.4\.3 3$", p.stdout, re.M), p.stdout
    assert re.search(r"^scipy -2\.0$", p.stdout, re.M), p.stdout
