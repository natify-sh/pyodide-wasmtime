"""The host's sockets without state: the guest's sockaddr, msghdr and addrinfo structures against the host's, the
option, flag and error numbers by NAME (the guest's are musl's, the host's differ), and the host's CA certificates.
The guest's memory is given as `rd(ptr, n)` and `wr(ptr, data)`."""

from __future__ import annotations

import contextlib
import errno
import os
import re
import socket
import ssl
import struct
from pathlib import Path

from ._consts import SERVICES, Reader, Writer, guest_errno

MSG_FLAGS = {
    1: "MSG_OOB",
    2: "MSG_PEEK",
    4: "MSG_DONTROUTE",
    0x20: "MSG_TRUNC",
    0x40: "MSG_DONTWAIT",
    0x80: "MSG_EOR",
    0x100: "MSG_WAITALL",
    0x4000: "MSG_NOSIGNAL",
    0x8000: "MSG_MORE",
}
SOCK_LEVELS = {1: "SOL_SOCKET", 0: "IPPROTO_IP", 6: "IPPROTO_TCP", 41: "IPPROTO_IPV6"}
SOCK_OPTIONS = {
    **{
        (1, n): v
        for n, v in enumerate(
            "SO_DEBUG SO_REUSEADDR SO_TYPE SO_ERROR SO_DONTROUTE SO_BROADCAST SO_SNDBUF SO_RCVBUF SO_KEEPALIVE "
            "SO_OOBINLINE".split(),
            1,
        )
    },
    (1, 13): "SO_LINGER",
    (1, 15): "SO_REUSEPORT",
    (1, 18): "SO_RCVLOWAT",
    (1, 19): "SO_SNDLOWAT",
    (1, 30): "SO_ACCEPTCONN",
    (0, 1): "IP_TOS",
    (0, 2): "IP_TTL",
    (0, 33): "IP_MULTICAST_TTL",
    (0, 34): "IP_MULTICAST_LOOP",
    **{
        (6, n): v
        for n, v in enumerate("TCP_NODELAY TCP_MAXSEG TCP_CORK TCP_KEEPIDLE TCP_KEEPINTVL TCP_KEEPCNT".split(), 1)
    },
    (41, 16): "IPV6_UNICAST_HOPS",
    (41, 18): "IPV6_MULTICAST_HOPS",
    (41, 19): "IPV6_MULTICAST_LOOP",
    (41, 26): "IPV6_V6ONLY",
}
# on/off options: BSD (macOS) answers getsockopt with the option's bit (SO_KEEPALIVE 8, TCP_NODELAY 4), Linux with 1
BOOL_OPTIONS = {(1, 1), (1, 2), (1, 5), (1, 6), (1, 9), (1, 10), (1, 15), (6, 1), (6, 3), (41, 26)}
AI_FLAGS = {
    1: "AI_PASSIVE",
    2: "AI_CANONNAME",
    4: "AI_NUMERICHOST",
    8: "AI_V4MAPPED",
    16: "AI_ALL",
    32: "AI_ADDRCONFIG",
    1024: "AI_NUMERICSERV",
}
NI_FLAGS = {1: "NI_NUMERICHOST", 2: "NI_NUMERICSERV", 4: "NI_NOFQDN", 8: "NI_NAMEREQD", 16: "NI_DGRAM"}
EAI_CODES = {
    getattr(socket, "EAI_" + n): code
    for n, code in (
        ("BADFLAGS", -1),
        ("NONAME", -2),
        ("AGAIN", -3),
        ("FAIL", -4),
        ("FAMILY", -6),
        ("SOCKTYPE", -7),
        ("SERVICE", -8),
        ("MEMORY", -10),
        ("SYSTEM", -11),
        ("OVERFLOW", -12),
        ("ADDRFAMILY", -2),
        ("NODATA", -2),
    )  # fmt: skip
    if hasattr(socket, "EAI_" + n)
}


def ca_bundle() -> bytes:
    """The host's CA certificates for the guest's OpenSSL (`SSL_CERT_FILE`): the environment's, Python's, system's."""
    files = [
        os.environ.get("SSL_CERT_FILE"),
        ssl.get_default_verify_paths().cafile,
        "/etc/ssl/certs/ca-certificates.crt",
    ]
    try:
        import certifi  # type: ignore[import-not-found,unused-ignore]

        files.append(certifi.where())
    except ImportError:
        pass
    out, seen = b"", set()
    for f in files:
        if f and f not in seen and os.path.exists(f):
            seen.add(f)
            out += Path(f).read_bytes() + b"\n"
    return out


# ------------------------------------------------------------------ the host's sockets
# The guest passes its own structures (sockaddr, msghdr, addrinfo, option values) as pointers and the host reads
# and writes them, so the adapter stays small. The numbers are musl's (Linux's); the host's differ (macOS,
# Windows), so options, flags and error codes are translated by NAME.
def werr(exc: OSError) -> int:
    """A host OSError -> -errno in the guest's (Emscripten's) numbering."""
    return -guest_errno(getattr(exc, "errno", None))


def sockaddr(rd: Reader, s: socket.socket, p: int, n: int) -> tuple:
    """The sockaddr at p (n bytes) as the host's address tuple for socket s."""
    want = 2 if s.family == socket.AF_INET else 10
    raw = rd(p, min(n, 128)) if p and n >= 2 else b""
    if len(raw) < 2:
        raise OSError(errno.EINVAL, "bad sockaddr")
    if int.from_bytes(raw[:2], "little") != want:
        raise OSError(errno.EAFNOSUPPORT, "address family")
    if len(raw) < (16 if want == 2 else 28):
        raise OSError(errno.EINVAL, "short sockaddr")
    return sockaddr_tuple(raw)


def sockaddr_tuple(raw: bytes) -> tuple:
    port = int.from_bytes(raw[2:4], "big")
    if raw[0] == 2:
        return socket.inet_ntop(socket.AF_INET, raw[4:8]), port
    return (
        socket.inet_ntop(socket.AF_INET6, raw[8:24]),
        port,
        int.from_bytes(raw[4:8], "big") & 0xFFFFF,  # the flow label is 20 bits
        int.from_bytes(raw[24:28], "little"),
    )


def sockaddr_bytes(addr: tuple) -> bytes:
    """The host's address tuple as a sockaddr_in (an IPv4 address) or sockaddr_in6 (an IPv6 one, with the flow
    label and scope id if the tuple has them); ValueError for any other shape."""
    if not isinstance(addr, tuple) or len(addr) not in (2, 4) or not isinstance(addr[0], str):
        raise ValueError(f"not an internet address: {addr!r}")
    port = int(addr[1]).to_bytes(2, "big")
    if len(addr) == 2 and ":" not in addr[0]:
        return b"\2\0" + port + socket.inet_aton(addr[0]) + bytes(8)
    flow, scope = (int(addr[2]), int(addr[3])) if len(addr) == 4 else (0, 0)
    ip = socket.inet_pton(socket.AF_INET6, addr[0].split("%")[0])
    return b"\x0a\0" + port + (flow & 0xFFFFF).to_bytes(4, "big") + ip + (scope & 0xFFFFFFFF).to_bytes(4, "little")


def sockaddr_out(rd: Reader, wr: Writer, sa: int, lenp: int, addr: tuple | None) -> None:
    """Write an address to the caller's buffer (sa, *lenp = its size); *lenp becomes the real size (0: none)."""
    if not sa or not lenp:
        return
    try:
        raw = sockaddr_bytes(addr) if addr else b""
    except (ValueError, OSError):  # a shape no internet address has (a host that answers oddly): no address
        raw = b""
    cap = int.from_bytes(rd(lenp, 4), "little")
    wr(sa, raw[:cap])
    wr(lenp, len(raw).to_bytes(4, "little"))


def msg_flags(flags: int) -> int:
    """musl's MSG_* bits -> the host's. DONTWAIT is the adapter's business, NOSIGNAL is moot (no SIGPIPE here)."""
    out = 0
    for bit, name in MSG_FLAGS.items():
        if flags & bit:
            if name == "MSG_DONTWAIT":  # the call is made non-blocking instead (_nonblocking)
                flags &= ~bit
                continue
            v = getattr(socket, name, None)
            if v is None and name != "MSG_NOSIGNAL":
                raise OSError(errno.EOPNOTSUPP, name)
            out |= v or 0
            flags &= ~bit
    if flags:
        raise OSError(errno.EOPNOTSUPP, "flags")
    return out


@contextlib.contextmanager
def nonblocking(s: socket.socket, on: int):
    """The guest asked for a call that must not wait (a non-blocking socket, MSG_DONTWAIT): the host socket, which
    is blocking otherwise, is not for the length of the call."""
    if on:
        s.setblocking(False)
    try:
        yield
    finally:
        if on:
            s.setblocking(True)


def send(s: socket.socket, data: bytes, flags: int) -> int:
    """send() without an address: a datagram socket with no peer is EDESTADDRREQ (Windows says WSAENOTCONN)."""
    try:
        return s.send(data, flags)
    except OSError as e:
        if e.errno == 10057 and s.type == socket.SOCK_DGRAM:
            raise OSError(10039, "WSAEDESTADDRREQ") from e
        raise


def recv(s: socket.socket, n: int, flags: int) -> tuple[bytes, tuple | None, int, int]:
    """-> (data cut to n, source address, the size to return, msg_flags). A datagram is read whole, so that a
    short buffer truncates it (MSG_TRUNC in the flags, and in the result if asked) as the kernel does."""
    hf = msg_flags(flags & ~0x20)  # MSG_TRUNC is applied here
    n = min(n + (1 << 32) if n < 0 else n, 1 << 20)  # a size_t; a stream read may return less than asked
    with nonblocking(s, flags & 0x40):
        if s.type == socket.SOCK_DGRAM:
            data, addr = s.recvfrom(65536, hf)
            return data[:n], addr, (len(data) if flags & 0x20 else min(n, len(data))), 0x20 if len(data) > n else 0
        data, addr = s.recvfrom(n, hf)
    return data, addr, len(data), 0


def msghdr(rd: Reader, msg: int) -> tuple[int, int, list[tuple[int, int]], int]:
    """struct msghdr of wasm32 (name, namelen, iov, iovlen, control, controllen, flags) -> name, namelen, the
    iovecs as (base, len), controllen"""
    name, namelen, iov, iovlen, _ctl, ctllen, _fl = struct.unpack("<7I", rd(msg, 28))
    if iovlen > 1024:  # IOV_MAX: refused before anything is read
        raise OSError(errno.EMSGSIZE, "iovlen")
    return name, namelen, list(struct.iter_unpack("<II", rd(iov, 8 * iovlen))), ctllen


def option(level: int, opt: int) -> tuple[int | None, int | None]:
    """musl's (level, option) numbers -> the host's, found by the NAME of the constant; None: the host has none."""
    return (
        getattr(socket, SOCK_LEVELS.get(level, ""), None),
        getattr(socket, SOCK_OPTIONS.get((level, opt), ""), None),
    )


def resolve_addrinfo(
    node: str | None, service: str | None, flags: int, family: int, type_: int, proto: int
) -> int | tuple[list[tuple[int, str, bytes]], bytes, int, int]:
    """getaddrinfo's validation (Pyodide's JavaScript: EAI codes; the defaults stream/6, dgram/17) and the host's
    resolver: a negative EAI_* code, or (entries as (family, canonical name, sockaddr), the canonical name as bytes,
    the type, the protocol)."""
    if type_ and not proto:
        proto = 17 if type_ == 2 else 6
    if not type_ and proto:
        type_ = 2 if proto == 17 else 1
    proto = proto or 6
    type_ = type_ or 1
    if node is None and service is None:
        return -2
    if flags & ~(1 | 2 | 4 | 8 | 16 | 32 | 1024):
        return -1
    if flags & 2 and node is None:
        return -1
    if type_ not in (1, 2):
        return -7
    if family not in (0, 2, 10):
        return -6
    port = 0
    if service is not None:
        m = re.match(r"\s*[+-]?\d+", service)  # parseInt(service, 10)
        proto_name = "tcp" if type_ == 1 else "udp"
        if m:
            port = int(m.group()) & 0xFFFF
        elif flags & 1024:
            return -2
        else:
            try:
                port = socket.getservbyname(service, proto_name)
            except OSError:
                port = SERVICES.get((service, proto_name), 0)
                if not port:
                    return -8
    hflags = 0
    for bit, name in AI_FLAGS.items():
        if flags & bit:
            hflags |= getattr(socket, name, 0)
    try:
        found = socket.getaddrinfo(
            node,
            port,
            {0: socket.AF_UNSPEC, 2: socket.AF_INET, 10: socket.AF_INET6}[family],
            socket.SOCK_STREAM if type_ == 1 else socket.SOCK_DGRAM,
            0,
            hflags,
        )
    except socket.gaierror as e:
        return EAI_CODES.get(e.args[0], -4)
    except UnicodeError:
        return -2
    entries = [(2 if f == socket.AF_INET else 10, c, sockaddr_bytes(a)) for f, _t, _p, c, a in found]
    if not entries:
        return -2
    canon = ((entries[0][1] or node or "").encode() + b"\0") if flags & 2 else b""
    return entries, canon, type_, proto


def nameinfo(raw: bytes, flags: int) -> int | tuple[str, str]:
    """getnameinfo of a sockaddr (`raw`): a negative EAI_* code, or (host, service)."""
    need = {2: 16, 10: 28}.get(int.from_bytes(raw[:2], "little"))
    if need is None or len(raw) < need:
        return -6  # EAI_FAMILY
    hflags = 0
    for bit, name in NI_FLAGS.items():
        if flags & bit:
            hflags |= getattr(socket, name, 0)
    try:
        host, service = socket.getnameinfo(sockaddr_tuple(raw), hflags)
    except socket.gaierror as e:
        return EAI_CODES.get(e.args[0], -4)
    except OSError:
        return -4
    return host, service
