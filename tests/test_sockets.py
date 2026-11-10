"""Sockets in the guest against a server on the host: non-blocking mode, poll and select with several sockets and a
timeout, descriptor numbers, and the answers to recvmsg. The peer answers `ping` with `pong` after 0.3 s and `echo:X`
with `X` at once, so a test can tell "nothing yet" from "data" without sleeping blindly."""

from __future__ import annotations

import errno
import socket
import socketserver
import threading
import time
from collections.abc import Iterator

import pytest
from conftest import Guest


class Peer(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        buf = b""
        while True:
            try:
                chunk = self.request.recv(1024)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while buf:
                if buf.startswith(b"ping"):
                    buf = buf[4:]
                    time.sleep(0.3)
                    self.request.sendall(b"pong")
                elif buf.startswith(b"echo:") and len(buf) >= 7:
                    self.request.sendall(buf[5:7])
                    buf = buf[7:]
                else:
                    break


@pytest.fixture(scope="module")
def port() -> Iterator[int]:
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = Server(("127.0.0.1", 0), Peer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()


def run(guest: Guest, port: int, code: str) -> list[str]:
    # a guest that hangs is a failure of the test, not minutes of waiting
    p = guest.run(f"import socket, select, time, errno, fcntl, os\nPORT = {port}\n" + code, timeout=90)
    assert p.returncode == 0, p.stderr[-1500:]
    return p.stdout.split("\n")[:-1]


def test_a_non_blocking_socket_does_not_block(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "s = socket.create_connection(('127.0.0.1', PORT)); s.setblocking(False)\n"
        "try: s.recv(10)\nexcept BlockingIOError: print('recv: EAGAIN')\n"
        "s.sendall(b'echo:hi'); time.sleep(0.2)\n"
        "print('recv:', s.recv(10))\n"
        "try: s.recv(10)\nexcept BlockingIOError: print('again: EAGAIN')\n",
    )
    assert out == ["recv: EAGAIN", "recv: b'hi'", "again: EAGAIN"]


def test_msg_dontwait(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "s = socket.create_connection(('127.0.0.1', PORT))\n"
        "try: s.recv(10, socket.MSG_DONTWAIT)\nexcept BlockingIOError: print('DONTWAIT: EAGAIN')\n"
        "s.settimeout(2); s.sendall(b'echo:ok'); print('blocking recv:', s.recv(10))\n",
    )
    assert out == ["DONTWAIT: EAGAIN", "blocking recv: b'ok'"]


def test_the_flag_is_visible_through_fcntl_and_the_constructor(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "s = socket.create_connection(('127.0.0.1', PORT))\n"
        "print('blocking:', bool(fcntl.fcntl(s, fcntl.F_GETFL) & os.O_NONBLOCK))\n"
        "s.setblocking(False)\n"
        "print('after setblocking(False):', bool(fcntl.fcntl(s, fcntl.F_GETFL) & os.O_NONBLOCK))\n"
        "t = socket.socket(socket.AF_INET, socket.SOCK_STREAM | socket.SOCK_NONBLOCK)\n"
        "print('SOCK_NONBLOCK:', t.gettimeout())\n",
    )
    assert out == ["blocking: False", "after setblocking(False): True", "SOCK_NONBLOCK: 0.0"]


def test_poll_waits_for_the_socket_that_gets_data(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "a = socket.create_connection(('127.0.0.1', PORT)); b = socket.create_connection(('127.0.0.1', PORT))\n"
        "p = select.poll(); p.register(a, select.POLLIN); p.register(b, select.POLLIN)\n"
        "b.sendall(b'ping')\n"
        "t = time.time(); r = p.poll(3000); dt = time.time() - t\n"
        "print('ready:', [fd == b.fileno() for fd, ev in r], 'waited between 0.2 and 2.5 s:', 0.2 < dt < 2.5)\n"
        "print('data:', b.recv(10))\n",
    )
    assert out == ["ready: [True] waited between 0.2 and 2.5 s: True", "data: b'pong'"]


def test_poll_times_out_on_idle_sockets(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "a = socket.create_connection(('127.0.0.1', PORT)); b = socket.create_connection(('127.0.0.1', PORT))\n"
        "p = select.poll(); p.register(a, select.POLLIN); p.register(b, select.POLLIN)\n"
        "t = time.time(); r = p.poll(400); dt = time.time() - t\n"
        "print(r, 'waited the timeout:', 0.3 < dt < 2.0)\n",
    )
    assert out == ["[] waited the timeout: True"]


def test_a_ready_file_does_not_wait_for_an_idle_socket(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "a = socket.create_connection(('127.0.0.1', PORT))\n"
        "f = open('/etc/ssl/cert.pem', 'rb')\n"
        "p = select.poll(); p.register(a, select.POLLIN); p.register(f, select.POLLIN)\n"
        "t = time.time(); r = p.poll(5000); dt = time.time() - t\n"
        "print([fd == f.fileno() for fd, ev in r], 'did not wait:', dt < 2.0)\n",
    )
    assert out == ["[True] did not wait: True"]


def test_poll_reports_an_invalid_descriptor(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "p = select.poll(); p.register(777, select.POLLIN); print(p.poll(0))\n",
    )
    assert out == [f"[(777, {32})]"]


def test_select_works_and_descriptors_are_small(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "a = socket.create_connection(('127.0.0.1', PORT)); b = socket.create_connection(('127.0.0.1', PORT))\n"
        "print('small numbers:', a.fileno() < 1024 and b.fileno() < 1024)\n"
        "b.sendall(b'ping')\n"
        "r, w, x = select.select([a, b], [], [], 3)\n"
        "print('select:', [s is b for s in r])\n"
        "print('writable:', len(select.select([], [a], [], 1)[1]))\n",
    )
    assert out == ["small numbers: True", "select: [True]", "writable: 1"]


def test_many_sockets_can_be_opened_and_closed(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "for i in range(300):\n    s = socket.create_connection(('127.0.0.1', PORT)); s.close()\n"
        "print('ok', socket.socket().fileno() < 1024)\n",
    )
    assert out == ["ok True"]


def test_recvmsg_returns_no_control_data(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "s = socket.create_connection(('127.0.0.1', PORT)); s.settimeout(3)\n"
        "s.sendall(b'echo:zz')\n"
        "data, anc, flags, addr = s.recvmsg(100, 64)\n"
        "print(data, anc)\n",
    )
    assert out == ["b'zz' []"]


def test_a_server_socket_binds_listens_and_accepts(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "l = socket.socket(); l.bind(('127.0.0.1', 0)); l.listen(5); la = l.getsockname()\n"
        "print('type/acceptconn:', l.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE),"
        " l.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN))\n"
        "c = socket.create_connection(la); s, peer = l.accept()\n"
        "print('addresses:', peer == c.getsockname(), s.getsockname() == la, s.getpeername() == peer)\n"
        "c.sendall(b'hi'); print('data:', s.recv(10))\n"
        "l.setblocking(False)\n"
        "try: l.accept()\nexcept BlockingIOError: print('accept: EAGAIN')\n"
        "c2 = socket.create_connection(la); time.sleep(0.1); s2, _ = l.accept()\n"
        "print('accepted is blocking:', s2.getblocking())\n"
        "try: socket.socket().bind(la)\nexcept OSError as e: print('bind in use:', e.errno == errno.EADDRINUSE)\n"
        "try: l.getsockopt(socket.SOL_SOCKET, 9999)\n"
        "except OSError as e: print('unknown option:', e.errno == errno.ENOPROTOOPT)\n"
        "print('option values are the host:', l.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF) > 0)\n",
    )
    assert out == [
        "type/acceptconn: 1 1",
        "addresses: True True True",
        "data: b'hi'",
        "accept: EAGAIN",
        "accepted is blocking: True",
        "bind in use: True",
        "unknown option: True",
        "option values are the host: True",
    ]


def test_a_non_blocking_connect_is_in_progress_then_completes(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "c = socket.socket(); c.setblocking(False)\n"
        "try: c.connect(('127.0.0.1', PORT))\n"
        "except BlockingIOError as e: print('connect:', e.errno == errno.EINPROGRESS)\n"
        "p = select.poll(); p.register(c, select.POLLOUT)\n"
        "print('POLLOUT:', [ev & select.POLLOUT != 0 for _, ev in p.poll(3000)])\n"
        "print('SO_ERROR:', c.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR), c.getpeername()[1] == PORT)\n"
        "t = socket.socket(); t.bind(('127.0.0.1', 0)); dead = t.getsockname(); t.close()\n"
        "r = socket.socket(); r.setblocking(False)\n"
        "try: r.connect(dead)\nexcept BlockingIOError: pass\n"
        "p = select.poll(); p.register(r, select.POLLOUT)\n"
        "print('POLLERR:', [ev & select.POLLERR != 0 for _, ev in p.poll(3000)])\n"
        "print('SO_ERROR:', r.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == errno.ECONNREFUSED)\n"
        "k = socket.socket(); k.settimeout(3)\n"
        "try: k.connect(dead)\nexcept ConnectionRefusedError: print('timeout connect: refused')\n"
        "k = socket.socket(); k.settimeout(3); k.connect(('127.0.0.1', PORT))\n"
        "print('timeout connect:', k.getpeername()[1] == PORT)\n",
    )
    assert out == [
        "connect: True",
        "POLLOUT: [True]",
        "SO_ERROR: 0 True",
        "POLLERR: [True]",
        "SO_ERROR: True",
        "timeout connect: refused",
        "timeout connect: True",
    ]


def test_poll_reports_a_hang_up(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "l = socket.socket(); l.bind(('127.0.0.1', 0)); l.listen(1)\n"
        "c = socket.create_connection(l.getsockname()); s, _ = l.accept(); c.close(); time.sleep(0.1)\n"
        "p = select.poll(); p.register(s, select.POLLIN | select.POLLOUT)\n"
        "print([(ev & select.POLLIN != 0, ev & select.POLLHUP != 0) for _, ev in p.poll(1000)], s.recv(5))\n"
        "s.shutdown(socket.SHUT_RDWR)\n"
        "print([ev & select.POLLHUP != 0 for _, ev in p.poll(1000)])\n",
    )
    assert out == ["[(True, False)] b''", "[True]"]


def test_udp_has_addresses_in_both_directions(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.bind(('127.0.0.1', 0)); ua = u.getsockname()\n"
        "c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
        "print('SO_TYPE:', u.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE))\n"
        "c.sendto(b'one', ua); d, a = u.recvfrom(100); print(d, a[0], a[1] == c.getsockname()[1])\n"
        "u.sendto(b'two', a); print(c.recvfrom(100)[0])\n"
        "c.connect(ua); c.send(b'three'); print(u.recv(100), c.getpeername() == ua)\n"
        "print('sendmsg:', c.sendmsg([b'ab', b'cd', b'ef']))\n"
        "b1, b2, b3 = bytearray(2), bytearray(3), bytearray(10)\n"
        "n, anc, fl, a = u.recvmsg_into([b1, b2, b3])\n"
        "print(n, bytes(b1), bytes(b2), bytes(b3[:1]), anc, fl, a == c.getsockname())\n"
        "c.send(b'0123456789'); print('peek:', u.recvfrom(4, socket.MSG_PEEK)[0])\n"
        "d, anc, fl, a = u.recvmsg(4); print('truncated:', d, bool(fl & socket.MSG_TRUNC))\n"
        "try: c.sendmsg([b'x'], [(socket.SOL_SOCKET, 1, bytes(4))])\n"
        "except OSError as e: print('SCM_RIGHTS:', e.errno == errno.EOPNOTSUPP)\n"
        "try: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).send(b'x')\n"
        "except OSError as e: print('no address:', e.errno == errno.EDESTADDRREQ)\n",
    )
    assert out == [
        "SO_TYPE: 2",
        "b'one' 127.0.0.1 True",
        "b'two'",
        "b'three' True",
        "sendmsg: 6",
        "6 b'ab' b'cde' b'f' [] 0 True",
        "peek: b'0123'",
        "truncated: b'0123' True",
        "SCM_RIGHTS: True",
        "no address: True",
    ]


def test_socketpair_works_both_ways(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "a, b = socket.socketpair(); a.sendall(b'x'); print(b.recv(5)); b.sendall(b'yy'); print(a.recv(5))\n"
        "a.close(); print(b.recv(5))\n",
    )
    assert out == ["b'x'", "b'yy'", "b''"]


def test_ioctl_answers_as_pyodide(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "import termios\n"
        "def io(fd, op):\n"
        "    try: return fcntl.ioctl(fd, op, bytes(4))\n"
        "    except OSError as e: return e.errno\n"
        "a, b = socket.socketpair(); a.sendall(b'12345'); time.sleep(0.1)\n"
        "print('FIONREAD:', int.from_bytes(io(b, termios.FIONREAD), 'little'),"
        " io(999, termios.FIONREAD) == errno.EBADF)\n"
        "f = open('/etc/ssl/cert.pem', 'rb')\n"
        "print('file:', io(f, termios.FIONREAD) == errno.ENOTTY, io(f, termios.TCGETS) == errno.ENOTTY,"
        " io(f, 0x5555) == errno.EINVAL)\n",
    )
    assert out == ["FIONREAD: 5 True", "file: True True True"]


def test_getaddrinfo_lists_the_hosts_addresses(guest: Guest, port: int):
    try:
        host = socket.getaddrinfo("localhost", 80, 0, socket.SOCK_STREAM)
    except OSError:
        pytest.skip("the host cannot resolve localhost")
    families = {"v6" if r[0] == socket.AF_INET6 else "v4" for r in host}
    out = run(
        guest,
        port,
        "r = socket.getaddrinfo('localhost', 80, 0, socket.SOCK_STREAM)\n"
        "print(sorted({'v6' if int(x[0]) == 10 else 'v4' for x in r}), {(int(x[1]), x[2]) for x in r})\n"
        "print(socket.getaddrinfo('127.0.0.1', 'domain', type=socket.SOCK_DGRAM)[0][2:], end=' ')\n"
        "print(socket.getaddrinfo('localhost', 80, flags=socket.AI_CANONNAME)[0][3], end=' ')\n"
        "print([x[4] for x in socket.getaddrinfo(None, 8080, socket.AF_INET, flags=socket.AI_PASSIVE)])\n"
        "for kw in ({'flags': 0x4000}, {'type': socket.SOCK_RAW}, {'family': 99}, {'flags': socket.AI_NUMERICHOST}):\n"
        "    try: socket.getaddrinfo('localhost', 80, **kw)\n"
        "    except socket.gaierror as e: print(e.errno, end=' ')\n"
        "for a in ((None, None), ('127.0.0.1', 'nosuchservice')):\n"
        "    try: socket.getaddrinfo(*a)\n"
        "    except socket.gaierror as e: print(e.errno, end=' ')\n"
        "print()\n",
    )
    assert out[0] == f"{sorted(families)} {{(1, 6)}}"  # the host's families, stream, protocol 6
    assert out[1] == "(17, '', ('127.0.0.1', 53)) localhost [('0.0.0.0', 8080)]"
    assert out[2] == "-1 -7 -6 -2 -2 -8 "


@pytest.mark.network  # a sandbox without DNS answers EAI_AGAIN
def test_an_unknown_host_name_is_not_found(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "try: socket.getaddrinfo('nosuch.invalid', 80)\nexcept socket.gaierror as e: print(e.errno)\n",
    )
    assert out == ["-2"]


def test_services_protocols_and_numeric_names(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "print(socket.getprotobyname('tcp'), socket.getprotobyname('udp'), socket.getprotobyname('icmp'))\n"
        "print(socket.getprotobyname('udp'), socket.getprotobyname('tcp'))\n"
        "try: socket.getprotobyname('nosuchproto')\nexcept OSError: print('unknown protocol')\n"
        "print(socket.getservbyname('http'), socket.getservbyname('domain', 'udp'), socket.getservbyport(443))\n"
        "print(socket.getnameinfo(('127.0.0.1', 80), socket.NI_NUMERICHOST | socket.NI_NUMERICSERV))\n"
        "print(socket.gethostbyname('localhost'))\n",
    )
    assert out == ["6 17 1", "17 6", "unknown protocol", "80 53 https", "('127.0.0.1', '80')", "127.0.0.1"]


@pytest.mark.network  # the reverse lookups and NI_NAMEREQD ask a resolver
def test_reverse_lookups(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "print(socket.getnameinfo(('127.0.0.1', 80), 0)[1])\n"
        "try: socket.getnameinfo(('10.255.255.1', 80), socket.NI_NAMEREQD)\n"
        "except socket.gaierror as e: print('NAMEREQD:', e.errno)\n"
        "print(socket.gethostbyaddr('127.0.0.1')[2])\n",
    )
    assert out == ["http", "NAMEREQD: -2", "['127.0.0.1']"]


def test_ipv6_structures_are_written_and_read_right(guest: Guest, port: int):
    """This CPython has no IPv6 sockets (socket.has_ipv6 is False): the sockaddr is seen through getaddrinfo's raw
    data, and, where libc's own calls can be reached through ctypes (fused only: the dynamic build gets them as
    imports), whole."""
    out = run(
        guest,
        port,
        "af, st, pr, cn, sa = socket.getaddrinfo('::1', 8080, type=socket.SOCK_STREAM)[0]\n"
        "print(int(af), st, pr, sa[0], sa[1][:6].hex())\n"
        "import ctypes, struct\n"
        "libc = ctypes.CDLL(None)\n"
        "if hasattr(libc, 'getnameinfo'):\n"
        "    libc.freeaddrinfo.restype = None\n"
        "    res = ctypes.c_void_p()\n"
        "    libc.getaddrinfo(b'::1', b'8080', None, ctypes.byref(res))\n"
        "    ai = struct.unpack('<8I', ctypes.string_at(res.value, 32))\n"
        "    print(ai[1:5], ctypes.string_at(ai[5], 28).hex())\n"
        "    libc.freeaddrinfo(ctypes.c_void_p(res.value))\n"
        "    sa = bytes([10, 0, 0x1f, 0x90, 0, 0, 0, 7]) + bytes(15) + b'\\1' + bytes(4)\n"
        "    host, serv = ctypes.create_string_buffer(64), ctypes.create_string_buffer(16)\n"
        "    print(libc.getnameinfo(sa, 28, host, 64, serv, 16, 3), host.value, serv.value)\n"
        "    print(libc.getnameinfo(sa, 28, host, 2, serv, 16, 3))\n",
    )
    assert out[0] == "10 1 6 10 1f9000000000"
    if guest.flavor == "fused":
        assert out[1:] == [
            "(10, 1, 6, 28) 0a001f90000000000000000000000000000000000000000100000000",
            "0 b'::1' b'8080'",
            "-12",
        ]


def test_sockaddr_translation_round_trips():
    from pyodide_wasmtime._host import Pyodide

    v6 = ("fe80::1", 8080, 7, 3)
    raw = Pyodide._sockaddr_bytes(v6)
    assert len(raw) == 28 and raw[:2] == b"\x0a\x00" and raw[2:4] == b"\x1f\x90" and raw[24:] == b"\x03\0\0\0"
    assert Pyodide._sockaddr_tuple(raw) == v6
    v4 = ("10.1.2.3", 80)
    raw = Pyodide._sockaddr_bytes(v4)
    assert raw == b"\x02\x00\x00\x50\x0a\x01\x02\x03" + bytes(8)
    assert Pyodide._sockaddr_tuple(raw) == v4


def test_a_non_blocking_send_never_waits(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "a, b = socket.socketpair(); a.setblocking(False)\n"
        "t = time.time(); n = a.send(b'x' * 10_000_000)\n"
        "print('partial:', 0 < n < 10_000_000, 'quick:', time.time() - t < 20)\n"
        "try:\n    while True: a.send(b'x' * 1_000_000)\nexcept BlockingIOError: print('full: EAGAIN')\n"
        "a.setblocking(True)\n"
        "try: a.send(b'y' * 10_000_000, socket.MSG_DONTWAIT)\nexcept BlockingIOError: print('MSG_DONTWAIT: EAGAIN')\n"
        "try: a.sendmsg([b'y' * 100], [], socket.MSG_DONTWAIT)\nexcept BlockingIOError: print('sendmsg: EAGAIN')\n"
        "b.setblocking(False)\n"
        "got = 0\n"
        "try:\n    while True: got += len(b.recv(1 << 20))\nexcept BlockingIOError: print('drained:', got > 0)\n",
    )
    assert out == [
        "partial: True quick: True",
        "full: EAGAIN",
        "MSG_DONTWAIT: EAGAIN",
        "sendmsg: EAGAIN",
        "drained: True",
    ]


def test_setsockopt_is_real(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "s = socket.socket()\n"
        "print(s.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY))\n"
        "s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)\n"
        "s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)\n"
        "print(s.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY),"
        " s.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE))\n"
        "try: s.setsockopt(socket.SOL_SOCKET, 9999, 1)\nexcept OSError as e: print(e.errno == errno.ENOPROTOOPT)\n"
        "try: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)\n"
        "except OSError as e: print('udp:', e.errno)\n",
    )
    assert out[:3] == ["0", "1 1", "True"]
    assert out[3].startswith("udp: ")


def test_errors_are_emscriptens_numbers(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "print(errno.EOPNOTSUPP == errno.ENOTSUP == 138)\n"
        "u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
        "try: u.listen(1)\nexcept OSError as e: print('listen on UDP:', e.errno == errno.EOPNOTSUPP)\n"
        "try: u.sendto(b'x', socket.MSG_OOB, ('127.0.0.1', 9))\n"
        "except OSError as e: print('MSG_OOB on UDP:', e.errno == errno.EOPNOTSUPP)\n",
    )
    assert out == ["True", "listen on UDP: True", "MSG_OOB on UDP: True"]


def test_bad_guest_pointers_and_sizes_are_errors_not_traps(guest: Guest, port: int):
    out = run(
        guest,
        port,
        "import ctypes, struct\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "a, b = socket.socketpair(); a.sendall(b'hello'); time.sleep(0.1)\n"
        "buf = ctypes.create_string_buffer(64)\n"
        "print('huge length:', libc.recv(b.fileno(), buf, ctypes.c_size_t(2**32 - 1), 0x40) in (5, -1))\n"
        "def msg(iov, iovlen):\n"
        "    return ctypes.create_string_buffer(struct.pack('<7I', 0, 0, iov, iovlen, 0, 0, 0))\n"
        "ctypes.set_errno(0)\n"
        "print('iovlen:', libc.recvmsg(b.fileno(), msg(ctypes.addressof(buf), 0x10000), 0),"
        " ctypes.get_errno() == errno.EMSGSIZE)\n"
        "a.sendall(b'again'); time.sleep(0.1)\n"
        "print('wild iov:', libc.recvmsg(b.fileno(), msg(0x7FFFFFF0, 3), 0), ctypes.get_errno() == errno.EFAULT)\n"
        "print('wild buffer:', libc.send(a.fileno(), 0x7FFFFFF0, 10, 0), ctypes.get_errno() == errno.EFAULT)\n"
        "print('negative length:', libc.send(a.fileno(), buf, -5, 0), ctypes.get_errno() == errno.EFAULT)\n"
        "print('alive:', socket.gethostbyname('127.0.0.1'))\n",
    )
    assert out == [
        "huge length: True",
        "iovlen: -1 True",
        "wild iov: -1 True",
        "wild buffer: -1 True",
        "negative length: -1 True",
        "alive: 127.0.0.1",
    ]


def test_a_wild_string_pointer_is_a_name_error(guest: Guest, port: int):
    """libc's getaddrinfo is reached through ctypes (the dynamic build gets it as an import, not an export)."""
    out = run(
        guest,
        port,
        "import ctypes, struct\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "res = ctypes.c_void_p()\n"
        "print('past the end:', libc.getaddrinfo(ctypes.c_void_p(0x7FFFFF00), None, None, ctypes.byref(res)))\n"
        "sa = bytes([10, 0, 0, 80]) + (0x7FFFFFFF).to_bytes(4, 'big') + bytes(15) + b'\\1' + bytes(4)\n"
        "host, serv = ctypes.create_string_buffer(64), ctypes.create_string_buffer(16)\n"
        "print('flow label:', libc.getnameinfo(sa, 28, host, 64, serv, 16, 3), host.value)\n",
    )
    assert out == ["past the end: -11", "flow label: 0 b'::1'"]


def test_a_second_run_on_one_object_sees_a_fresh_guest(flavor: str, capfd: pytest.CaptureFixture[str]):
    from pyodide_wasmtime import Pyodide

    code = "import socket; print(socket.getprotobyname('udp'), socket.getprotobyname('tcp'))"
    with Pyodide(flavor) as py:
        for _ in range(2):
            assert py.run(code) == 0
            py.close()  # everything the host remembers of the guest goes
    assert capfd.readouterr().out == "17 6\n17 6\n"


def test_the_accessors_check_the_memory():
    from pyodide_wasmtime._host import GuestFault, Pyodide

    class Memory:
        def __init__(self) -> None:
            self.data = bytearray(100)

        def data_len(self, _store: object) -> int:
            return len(self.data)

        def read(self, _store: object, start: int, stop: int) -> bytes:
            return bytes(self.data[start:stop])

        def write(self, _store: object, data: bytes, start: int) -> None:
            self.data[start : start + len(data)] = data

    py = Pyodide.__new__(Pyodide)
    py.cur, py.memory = [None], Memory()
    py._wr(10, b"abc\0")
    assert py._rd(10, 3) == b"abc" and py._cstr(10) == "abc"
    for a, n in [(-1, 4), (98, 3), (0, -1), (1 << 32, 1), (-(1 << 31), 1), (2**31, 0 + 1)]:
        with pytest.raises(GuestFault):
            py._rd(a, n)
    with pytest.raises(GuestFault):
        py._wr(99, b"ab")
    py.memory.data[96:100] = b"abcd"  # no NUL before the end of the memory
    with pytest.raises(GuestFault):
        py._cstr(96)
    py.memory.data[:] = b"x" * 100
    with pytest.raises(GuestFault):
        py._cstr(1)  # no NUL at all


def test_the_net_wrapper_turns_every_exception_into_an_errno():
    from pyodide_wasmtime._host import GuestFault, Pyodide

    py = Pyodide.__new__(Pyodide)
    py.cur = []

    def boom(kind: type[BaseException]):
        def f(*_a: object) -> int:
            raise kind("x")

        return f

    call = lambda name, kind: py._wrap_net(name, boom(kind))(None)  # noqa: E731
    assert call("bind", GuestFault) == -21
    assert call("bind", ValueError) == -29
    assert call("bind", OverflowError) == -29
    assert call("bind", IndexError) == -29
    assert call("bind", OSError) == -29  # an OSError without an errno is EIO
    assert call("getaddrinfo", GuestFault) == -11 and call("getaddrinfo", KeyError) == -4
    assert call("protobyname", GuestFault) == 0
    assert py.cur == []


def test_host_errors_are_translated_by_name_on_every_os():
    from pyodide_wasmtime._host import guest_errno

    expect = {10035: "EAGAIN", 10036: "EINPROGRESS", 10061: "ECONNREFUSED", 10054: "ECONNRESET", 10053: "ECONNABORTED",
              10060: "ETIMEDOUT", 10048: "EADDRINUSE", 10049: "EADDRNOTAVAIL", 10051: "ENETUNREACH",
              10065: "EHOSTUNREACH", 10057: "ENOTCONN", 10056: "EISCONN", 10040: "EMSGSIZE", 10047: "EAFNOSUPPORT",
              10045: "EOPNOTSUPP"}  # fmt: skip
    for wsa, name in expect.items():
        assert guest_errno(wsa) == guest_errno(getattr(errno, name)), name
    assert guest_errno(10045) == guest_errno(errno.ENOTSUP) == 138
    assert guest_errno(errno.EWOULDBLOCK) == guest_errno(errno.EAGAIN) == 6
    assert guest_errno(errno.ECONNREFUSED) == 14 and guest_errno(errno.EINPROGRESS) == 26
    assert guest_errno(999999) == guest_errno(None) == 29  # unknown: EIO
