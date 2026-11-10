# Networking without JavaScript: the host's fetch under pyfetch, urllib, micropip and requests, and a
# binary Pyodide wheel installed by micropip and loaded by the adapter's loader.
import hostnet

hostnet.install()  # first: pyfetch, the urllib handler and urllib3's fetch go to the host
import micropip
from pyodide.http import pyfetch


async def pyfetch_check():
    r = await pyfetch("https://pypi.org/pypi/attrs/json")
    d = await r.json()
    print("pyfetch", r.status, r.ok, d["info"]["name"])


hostnet.run(pyfetch_check())

hostnet.run(micropip.install(["six", "attrs", "requests"]))
import requests  # noqa: E401, E402

print("micropip: six, attrs, requests (+ urllib3, idna, certifi, charset-normalizer) imported")
r = requests.get("https://pypi.org/pypi/micropip/json")
print("requests.get", r.status_code, r.headers.get("content-type"), r.json()["info"]["name"])

B = "https://cdn.jsdelivr.net/pyodide/v315.0.0a2/full/"
hostnet.run(micropip.install(["pycparser", B + "cffi-2.0.0-cp315-cp315-pyemscripten_2026_5_wasm32.whl"]))
import cffi  # noqa: E402

ffi = cffi.FFI()
ffi.cdef("struct pt { int x, y; };")
p = ffi.new("struct pt *", {"x": 3, "y": 4})
print("cffi (binary wheel via micropip)", cffi.__version__, p.x * p.x + p.y * p.y, sum(ffi.new("int[4]", [1, 2, 3, 4])))
print("installed", sorted(micropip.list()))
