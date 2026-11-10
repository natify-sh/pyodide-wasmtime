"""Networking for Pyodide without JavaScript (guest side).

Pyodide's `_ssl` is a stub (its browser build has no OpenSSL in the main module), so TLS cannot run in the
guest; as in a browser (`fetch`) or with WASI 0.2 (`wasi:http`), the host does HTTP(S). The guest reaches the
host's `fetch` through ctypes (a table slot the host wrote to `_hostnet_slots`; `ffi_call_js` is in the
adapter). On top of it:

* `fetch(url, method, headers, body)`: the call itself;
* `pyfetch`: `pyodide.http.pyfetch` with its FetchResponse API (`status`, `ok`, `headers`, `url`,
  `bytes()`, `string()`, `text()`, `json()`, `memoryview()`, `raise_for_status()`), and `open_url`;
* a urllib handler for http and https, installed globally, so `urllib.request.urlopen` works (micropip
  outside the browser fetches with it);
* `run(coro)`: an asyncio loop with no I/O (the default loop needs a socketpair, which the guest has not).

`install()` puts the first three in place; `fetch` and `run` work without it.
"""

import asyncio
import asyncio.base_events
import ctypes
import email.message
import io
import json
import time
import urllib.error
import urllib.request
from urllib.response import addinfourl

from _hostnet_slots import FETCH, FREE

_fetch = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)(
    FETCH
)
_free = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(FREE)


def fetch(url, method="GET", headers=None, body=None):
    """-> (status, reason, [(header, value)], body bytes, final url). Errors of the network are OSError."""
    req = json.dumps({"url": url, "method": method, "headers": dict(headers or {})}).encode()
    if isinstance(body, str):
        body = body.encode()
    body = bytes(body or b"")
    out = (ctypes.c_uint32 * 4)()
    _fetch(req, len(req), body, len(body), ctypes.addressof(out))
    meta = json.loads(ctypes.string_at(out[0], out[1]))
    data = ctypes.string_at(out[2], out[3]) if out[3] else b""
    for p in (out[0], out[2]):
        if p:
            _free(p)
    if "error" in meta:
        raise OSError(meta["error"])
    return meta["status"], meta["reason"], meta["headers"], data, meta["url"]


# ---------------------------------------------------------------- pyodide.http.pyfetch
class FetchResponse:
    def __init__(self, url, status, reason, headers, data):
        self.url, self.status, self.status_text, self._data = url, status, reason, data
        self.headers = {k.lower(): v for k, v in headers}
        self.ok = 200 <= status < 300
        self.redirected = False
        self.type = "basic"
        self.body_used = False

    async def bytes(self):
        return self._data

    async def string(self):
        return self._data.decode()

    async def text(self):
        return self._data.decode()

    async def json(self, **kwargs):
        return json.loads(self._data, **kwargs)

    async def memoryview(self):
        return memoryview(self._data)

    def raise_for_status(self):
        if 400 <= self.status < 600:
            raise OSError(f"{self.status} {self.status_text}: {self.url}")

    def clone(self):
        return FetchResponse(self.url, self.status, self.status_text, list(self.headers.items()), self._data)


async def pyfetch(url, **kwargs):
    st, reason, hdrs, data, final = fetch(url, kwargs.get("method", "GET"), kwargs.get("headers"), kwargs.get("body"))
    return FetchResponse(final, st, reason, hdrs, data)


def open_url(url):
    return io.StringIO(fetch(url)[3].decode())


# ---------------------------------------------------------------- urllib
class HostHandler(urllib.request.BaseHandler):
    handler_order = 100  # before the default HTTP(S)Handler

    def _open(self, req):
        st, reason, hdrs, data, final = fetch(req.full_url, req.get_method(), dict(req.header_items()), req.data)
        msg = email.message.Message()
        for k, v in hdrs:
            msg[k] = v
        resp = addinfourl(io.BytesIO(data), msg, final, st)
        resp.msg = reason
        return resp

    http_open = https_open = _open


# ---------------------------------------------------------------- asyncio with no I/O
class _NoSelector:
    def select(self, timeout=None):
        if timeout:
            time.sleep(min(timeout, 0.01))
        return []


class Loop(asyncio.base_events.BaseEventLoop):
    def __init__(self):
        super().__init__()
        self._selector = _NoSelector()

    def _process_events(self, event_list):
        pass

    def _write_to_self(self):
        pass


def run(coro):
    loop = Loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)


# ---------------------------------------------------------------- urllib3 (and so requests)
# On sys.platform == "emscripten" urllib3 sends through `urllib3.contrib.emscripten.fetch`, which needs
# JavaScript (XMLHttpRequest / JSPI). This module takes its place before urllib3 is imported: the same
# names, the request sent by the host's fetch. Compressed bodies are not asked for, as in a browser where
# the decoding is done before Python sees the body.
import sys as _sys
import types as _types


class _RequestError(Exception):
    def __init__(self, message=None, *, request=None, response=None):
        self.request, self.response, self.message = request, response, message
        super().__init__(message)


class _StreamingError(_RequestError):
    pass


class _TimeoutError(_RequestError):
    pass


def _u3_send_request(request):
    from urllib3.contrib.emscripten.response import EmscriptenResponse

    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("accept-encoding", "connection", "host")}
    try:
        st, _reason, hdrs, data, _url = fetch(request.url, request.method, headers, request.body)
    except OSError as e:
        raise _RequestError(str(e), request=request) from None
    return EmscriptenResponse(status_code=st, headers=dict(hdrs), body=data, request=request)


_u3 = _types.ModuleType("urllib3.contrib.emscripten.fetch")
_u3._RequestError, _u3._StreamingError, _u3._TimeoutError = _RequestError, _StreamingError, _TimeoutError
_u3.send_request = _u3_send_request
_u3.send_streaming_request = lambda request: None  # not streaming: urllib3 falls back to send_request
_u3.streaming_ready = lambda: False
_u3.has_jspi = lambda: False


def install():
    """Route pyfetch, urllib and urllib3 through the host's fetch (HTTP and TLS by the host). Without it, urllib
    and http.client use the guest's own sockets and, with a real `_ssl`, the guest's own TLS."""
    try:
        import pyodide.http as ph

        ph.pyfetch, ph.open_url, ph.FetchResponse = pyfetch, open_url, FetchResponse
    except ImportError:
        pass
    urllib.request.install_opener(urllib.request.build_opener(HostHandler))
    _sys.modules.setdefault("urllib3.contrib.emscripten.fetch", _u3)


def native():
    """The guest's own sockets and TLS (a real `_ssl`): urllib3 keeps its socket backend instead of the
    emscripten one (which needs JavaScript); urllib and http.client need nothing."""
    m = _types.ModuleType("urllib3.contrib.emscripten")
    m.inject_into_urllib3 = lambda: None
    _sys.modules.setdefault("urllib3.contrib.emscripten", m)
