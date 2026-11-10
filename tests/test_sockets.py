"""Sockets in the guest against a server on the host: non-blocking mode, poll and select with several sockets and a
timeout, descriptor numbers, and the answers to recvmsg. The peer answers `ping` with `pong` after 0.3 s and `echo:X`
with `X` at once, so a test can tell "nothing yet" from "data" without sleeping blindly."""

from __future__ import annotations

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
