# HTTPS made by the guest itself: its sockets (the adapter over the host's socket operations) and its TLS
# (Pyodide's OpenSSL 1.1.1w and the _ssl module of CPython 3.15 built here). No host fetch.
import socket
import ssl
import urllib.request

print("ssl", ssl.OPENSSL_VERSION, "| _ssl from", ssl._ssl.__file__.rsplit("/", 1)[-1])
ctx = ssl.create_default_context()
with socket.create_connection(("pypi.org", 443), timeout=20) as raw:
    with ctx.wrap_socket(raw, server_hostname="pypi.org") as s:
        print(
            "handshake",
            s.version(),
            s.cipher()[0],
            "| peer cert subject CN:",
            dict(x[0] for x in s.getpeercert()["subject"]).get("commonName"),
        )
        s.sendall(b"HEAD /simple/ HTTP/1.1\r\nHost: pypi.org\r\nConnection: close\r\n\r\n")
        print("raw response:", s.recv(64).split(b"\r\n")[0].decode())
r = urllib.request.urlopen("https://pypi.org/pypi/six/json", timeout=30)
import json

print("urllib", r.status, json.loads(r.read())["info"]["name"])
try:
    ssl.create_default_context().wrap_socket(
        socket.create_connection(("pypi.org", 443), timeout=20), server_hostname="wrong.example"
    )
except ssl.SSLCertVerificationError as e:
    print("hostname check works:", e.verify_message)
