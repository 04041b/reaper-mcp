"""The bridge that replaces reapy's distant API: it listens on 127.0.0.1 only,
serves only clients that prove the token, and never sends the token itself.
Both ends run here for real, over a loopback socket; REAPER is not needed."""

import contextlib
import json
import operator
import os
import socket
import stat
import sys
import threading
import time

import pytest

from reaper_mcp import reaper_bridge
from reaper_mcp.reaper_bridge import BridgeClient, BridgeServer

TOKEN = bytes.fromhex("11" * 32)


@contextlib.contextmanager
def _pumped(token: bytes):
    """A BridgeServer on a free port, pumped as REAPER's defer loop would."""
    bridge = BridgeServer(0, token)
    stop = threading.Event()

    def pump():
        while not stop.is_set():
            bridge.accept()
            bridge.send_results(bridge.process_requests(bridge.get_requests()))

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    yield bridge
    stop.set()
    thread.join()
    bridge.close()


@pytest.fixture
def server():
    with _pumped(TOKEN) as bridge:
        yield bridge


def _port(bridge) -> int:
    return bridge._socket.getsockname()[1]


def test_listens_on_loopback_only(server):
    assert server._socket.getsockname()[0] == "127.0.0.1"


def test_a_client_with_the_token_is_served(server):
    client = BridgeClient(_port(server), TOKEN)
    assert client.request(operator.add, {"args": (2, 3), "kwargs": {}}) == 5


def test_a_client_without_the_token_is_refused_before_any_request(server):
    with pytest.raises(ConnectionError, match="refused this client's token"):
        BridgeClient(_port(server), bytes(32))
    assert server.connections == {}


RAN: list = []


def _record(*args):
    RAN.append(args)


def test_a_raw_reapy_request_is_never_executed(server):
    """What reapy's own client (or an attacker) sends first: a request naming
    a function. The bridge expects a handshake reply of fixed size, so it
    hangs up without decoding it."""
    with socket.create_connection(("127.0.0.1", _port(server))) as raw:
        raw.settimeout(2)
        raw.recv(8 + reaper_bridge.NONCE_BYTES)
        request = json.dumps({"function": {"__callable__": True, "module_name": __name__,
                                           "name": "_record"},
                              "input": {"args": ["pwned"], "kwargs": {}}}).encode()
        raw.sendall(len(request).to_bytes(8, "little") + request)
        try:
            assert raw.recv(8) == b""  # closed, no reply
        except ConnectionResetError:
            pass  # closed with the request unread
    assert server.connections == {} and RAN == []


def test_a_silent_client_is_dropped_after_the_handshake_timeout(server):
    with socket.create_connection(("127.0.0.1", _port(server))) as raw:
        raw.settimeout(reaper_bridge.HANDSHAKE_SECONDS * 4)
        raw.recv(8 + reaper_bridge.NONCE_BYTES)
        assert raw.recv(8) == b""
    # The bridge still serves a real client afterwards.
    assert BridgeClient(_port(server), TOKEN).request(operator.neg, {"args": (1,), "kwargs": {}}) == -1


def test_the_client_rejects_a_server_without_the_token():
    """An impostor on the port learns nothing usable and gets no request."""
    with _pumped(bytes(32)) as impostor, pytest.raises(ConnectionError):
        BridgeClient(_port(impostor), TOKEN)


def test_the_token_never_crosses_the_socket():
    a, b = socket.socketpair()
    b.sendall(reaper_bridge.NONCE_BYTES.to_bytes(8, "little") + b"n" * reaper_bridge.NONCE_BYTES)
    # The client half of the handshake: its reply is a nonce and a proof.
    server_nonce = reaper_bridge._recv(a, reaper_bridge.NONCE_BYTES, time.monotonic() + 5)
    client_nonce = os.urandom(reaper_bridge.NONCE_BYTES)
    reaper_bridge._send(a, client_nonce + reaper_bridge._proof(TOKEN, b"client",
                                                               server_nonce + client_nonce))
    a.close()
    sent = b""
    while chunk := b.recv(4096):
        sent += chunk
    b.close()
    assert len(sent) == 8 + reaper_bridge.NONCE_BYTES + 32
    assert TOKEN not in sent and TOKEN.hex().encode() not in sent


def test_write_config_is_private_and_keeps_the_token(tmp_path):
    path = tmp_path / "dir" / "bridge.json"
    first = reaper_bridge.write_config(path, sys_path=["/a"])
    second = reaper_bridge.write_config(path, sys_path=["/b"])
    assert second == {"port": reaper_bridge.PORT, "token": first["token"], "sys_path": ["/b"]}
    assert len(bytes.fromhex(first["token"])) == 32
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
