"""asyncio in the guest: its default selector loop (a socketpair, poll), a client of a server on the host, and a server
and its client in the same guest, all non-blocking, no threads."""

from __future__ import annotations

import socketserver
import threading
from collections.abc import Iterator

import pytest
from conftest import Guest


class LineEcho(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        for line in self.rfile:
            self.wfile.write(b"echo:" + line)


@pytest.fixture(scope="module")
def port() -> Iterator[int]:
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = Server(("127.0.0.1", 0), LineEcho)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()


def run(guest: Guest, code: str) -> list[str]:
    p = guest.run("import asyncio, time\n" + code, timeout=120)
    assert p.returncode == 0, p.stderr[-1500:]
    return p.stdout.split("\n")[:-1]


def test_asyncio_run_sleeps_and_talks_to_a_server_on_the_host(guest: Guest, port: int):
    out = run(
        guest,
        f"""
async def main():
    t = time.time()
    await asyncio.sleep(0.3)
    print('slept:', 0.25 < time.time() - t < 5)
    r, w = await asyncio.open_connection('127.0.0.1', {port})
    for i in range(3):
        w.write(b'line %d\\n' % i)
        await w.drain()
        print((await r.readline()).decode().strip())
    w.close()
    await w.wait_closed()
    print(type(asyncio.get_running_loop()).__name__)
asyncio.run(main())
""",
    )
    assert out == ["slept: True", "echo:line 0", "echo:line 1", "echo:line 2", "_UnixSelectorEventLoop"]


def test_an_asyncio_server_and_its_clients_in_one_guest(guest: Guest):
    out = run(
        guest,
        """
async def handle(r, w):
    while line := await r.readline():
        w.write(line.upper())
        await w.drain()
    w.close()

async def client(port, n):
    r, w = await asyncio.open_connection('127.0.0.1', port)
    w.write(b'client %d\\n' % n)
    got = await r.readline()
    w.close()
    await w.wait_closed()
    return got

async def main():
    srv = await asyncio.start_server(handle, '127.0.0.1', 0)
    port = srv.sockets[0].getsockname()[1]
    print(sorted(await asyncio.gather(*(client(port, n) for n in range(5)))))
    srv.close()
    await srv.wait_closed()
asyncio.run(main())
""",
    )
    assert out == ["[b'CLIENT 0\\n', b'CLIENT 1\\n', b'CLIENT 2\\n', b'CLIENT 3\\n', b'CLIENT 4\\n']"]


def test_a_selectors_echo_server_and_client_without_asyncio(guest: Guest):
    out = run(
        guest,
        """
import selectors, socket
sel = selectors.DefaultSelector()
srv = socket.socket(); srv.bind(('127.0.0.1', 0)); srv.listen(); srv.setblocking(False)
sel.register(srv, selectors.EVENT_READ, 'accept')
cli = socket.socket(); cli.setblocking(False)
try: cli.connect(srv.getsockname())
except BlockingIOError: pass
sel.register(cli, selectors.EVENT_WRITE, 'client')
got = b''
done = False
while not done:
    for key, ev in sel.select(5):
        if key.data == 'accept':
            conn, _ = srv.accept(); conn.setblocking(False); sel.register(conn, selectors.EVENT_READ, 'conn')
        elif key.data == 'client':
            if ev & selectors.EVENT_WRITE:
                cli.send(b'ping'); sel.modify(cli, selectors.EVENT_READ, 'client')
            else:
                got = cli.recv(10); done = True
        else:
            conn = key.fileobj; conn.send(conn.recv(10) + b'!')
print(got, type(sel).__name__)
""",
    )
    assert out == ["b'ping!' PollSelector"]


def test_an_asyncio_write_larger_than_the_socket_buffer(guest: Guest):
    """The writer's send must not block the interpreter while the reader (in the same guest) is not running."""
    out = run(
        guest,
        """
N = 8_000_000

async def handle(r, w):
    data = await r.readexactly(N)
    w.write(b'got %d' % len(data))
    await w.drain()
    w.close()

async def main():
    srv = await asyncio.start_server(handle, '127.0.0.1', 0)
    port = srv.sockets[0].getsockname()[1]
    r, w = await asyncio.open_connection('127.0.0.1', port)
    w.write(b'x' * N)
    await w.drain()
    print((await r.read(100)).decode())
    w.close()
    srv.close()
asyncio.run(main())
""",
    )
    assert out == ["got 8000000"]
