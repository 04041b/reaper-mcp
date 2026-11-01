"""The bridge between this server and REAPER, replacing reapy's distant API.

reapy's own server (``reapy.config.enable_dist_api`` / ``configure_reaper``)
listens on every network interface, port 2306, without authentication, and
calls whatever function a request names: any module, any attribute, so
``os.system`` too. Alongside it, reapy adds a REAPER web interface on port
2307 with no password. Anyone who can reach the machine can run code as the
user running REAPER.

This module keeps reapy's wire protocol and object model, and changes how a
connection is made:

- it listens on 127.0.0.1 only, on its own port, so reapy's server is never
  mistaken for it;
- a connection is served only after a challenge-response handshake proving
  both ends hold the token in ``~/.reaper-mcp/bridge.json`` (mode 0600), so
  other users of the machine cannot use it, and the token itself never
  crosses the socket, so a process impersonating either end cannot learn it;
- there is no web interface: REAPER starts the bridge from
  ``Scripts/__startup.lua``, which ``reaper-mcp-server --setup-reaper`` writes.

Run by REAPER, this file is a ReaScript: it starts the bridge. It must then
import nothing but the standard library and reapy (REAPER's Python does not
have this package's dependencies), which is why it, too, imports reapy.
"""

import hashlib
import hmac
import json
import os
import secrets
import socket
import sys
import time
from pathlib import Path

HOST = "127.0.0.1"
PORT = 2316
CONFIG = Path.home() / ".reaper-mcp" / "bridge.json"
NONCE_BYTES = 32
# How long a connecting client may take over the handshake. REAPER's main
# thread waits meanwhile, so it is short: the real client answers at once.
HANDSHAKE_SECONDS = 0.5


def write_config(path: Path = CONFIG, *, sys_path: list[str], port: int = PORT) -> dict:
    """Write the bridge's settings, readable by this user only. An existing
    token is kept, so a client that is already set up keeps working."""
    token = secrets.token_hex(32)
    if path.is_file():
        token = load_config(path).get("token", token)
    config = {"port": port, "token": token, "sys_path": sys_path}
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(config, f)
    os.chmod(path, 0o600)  # O_CREAT's mode does not apply to an existing file
    return config


def load_config(path: Path = CONFIG) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _import_reapy():
    """reapy, from the environment the bridge was set up from if REAPER's
    Python does not have it on its path."""
    try:
        import reapy
    except ImportError:
        sys.path.extend(load_config().get("sys_path", []))
        import reapy
    return reapy


_import_reapy()

from reapy.tools.network.client import Client  # noqa: E402 -- after the path fix above
from reapy.tools.network.server import Server  # noqa: E402
from reapy.tools.network.socket import Socket  # noqa: E402


def _proof(token: bytes, role: bytes, nonces: bytes) -> bytes:
    """HMAC of both nonces under the token; role keeps the two proofs distinct."""
    return hmac.new(token, role + nonces, hashlib.sha256).digest()


def _send(sock: socket.socket, data: bytes) -> None:
    """One message in reapy's framing: an 8-byte little-endian length, then the data."""
    sock.sendall(len(data).to_bytes(8, "little") + data)


def _recv(sock: socket.socket, size: int, deadline: float) -> bytes:
    """One message of exactly size bytes, by deadline. A peer that announces
    any other length, goes quiet or hangs up raises, so nothing it sends can
    make the reader allocate or wait without bound."""
    if int.from_bytes(_recv_exact(sock, 8, deadline), "little") != size:
        raise ConnectionError("unexpected handshake message")
    return _recv_exact(sock, size, deadline)


def _recv_exact(sock: socket.socket, size: int, deadline: float) -> bytes:
    data = b""
    while len(data) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("handshake timed out")
        sock.settimeout(remaining)
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("peer closed the connection during the handshake")
        data += chunk
    return data


class BridgeServer(Server):
    """reapy's server, on 127.0.0.1, serving only clients that prove the token."""

    def __init__(self, port: int, token: bytes, host: str = HOST):
        Socket.__init__(self)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: no other socket may share the port
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.bind((host, port))
        self.listen()
        self.connections = {}
        self.token = token
        self.settimeout(0.0001)

    def accept(self, *args, **kwargs):
        try:
            connection, address = self._socket.accept()
        except (socket.timeout, BlockingIOError):
            return None
        try:
            self._handshake(connection)
        except (OSError, ValueError):  # timeouts and resets are OSErrors
            connection.close()
            return None
        connection.settimeout(None)
        wrapped = Socket(connection)
        self.connections[address] = wrapped
        return wrapped, address

    def _handshake(self, connection: socket.socket) -> None:
        deadline = time.monotonic() + HANDSHAKE_SECONDS
        server_nonce = secrets.token_bytes(NONCE_BYTES)
        _send(connection, server_nonce)
        reply = _recv(connection, NONCE_BYTES + 32, deadline)
        client_nonce, proof = reply[:NONCE_BYTES], reply[NONCE_BYTES:]
        expected = _proof(self.token, b"client", server_nonce + client_nonce)
        if not hmac.compare_digest(proof, expected):
            raise ValueError("bad token")
        _send(connection, _proof(self.token, b"server", server_nonce + client_nonce))

    def get_requests(self):
        # Copied: a client hanging up removes itself from connections.
        requests = {}
        for address, connection in list(self.connections.items()):
            request = self._get_request(connection, address)
            if request is not None:
                requests[address] = request
        return requests


class BridgeClient(Client):
    """reapy's client, for a BridgeServer: it proves the token, and checks the
    server's proof before sending anything, so an impostor gets no request."""

    def __init__(self, port: int, token: bytes, *, host: str = HOST, timeout: float = 5.0):
        Socket.__init__(self)
        self.port, self.host = port, host
        self.address = ""
        self._socket.settimeout(timeout)
        self._socket.connect((host, port))
        deadline = time.monotonic() + timeout
        server_nonce = _recv(self._socket, NONCE_BYTES, deadline)
        client_nonce = secrets.token_bytes(NONCE_BYTES)
        _send(self._socket, client_nonce + _proof(token, b"client", server_nonce + client_nonce))
        try:
            proof = _recv(self._socket, 32, deadline)
        except ConnectionError as e:
            raise ConnectionError(
                f"the REAPER bridge refused this client's token ({CONFIG}); "
                "restart REAPER after running reaper-mcp-server --setup-reaper"
            ) from e
        if not hmac.compare_digest(proof, _proof(token, b"server", server_nonce + client_nonce)):
            raise ConnectionError(f"the process on port {port} is not the REAPER bridge")
        self._socket.settimeout(None)


def _serve() -> None:
    reapy = _import_reapy()
    config = load_config()
    server = BridgeServer(int(config["port"]), bytes.fromhex(config["token"]))

    def loop():
        server.accept()
        server.send_results(server.process_requests(server.get_requests()))
        reapy.defer(loop)

    loop()


if __name__ == "__main__":
    _serve()
