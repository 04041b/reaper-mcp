"""reaper_mcp.reaper without REAPER: the null-pointer test, and connecting
once with an error that says how to set REAPER up."""

import pytest
import reapy

from reaper_mcp import reaper


@pytest.mark.parametrize(("pointer", "null"), [
    ("(TrackEnvelope*)0x0000000000000000", True),
    ("(ReaProject*)0x0000000000000000", True),
    ("", True),
    ("(TrackEnvelope*)0x00000001580089F0", False),
    ("(MediaTrack*)0x0000000000000010", False),
])
def test_is_null(pointer, null):
    assert reaper.is_null(pointer) is null


@pytest.fixture
def disconnected(monkeypatch):
    monkeypatch.setattr(reaper, "_connected", False)


def test_connects_once(monkeypatch, disconnected):
    calls = []
    monkeypatch.setattr(reaper, "_connect", lambda: calls.append("connect"))
    monkeypatch.setattr(reapy, "Project", lambda: "project")
    assert reaper.get_project() == "project"
    assert reaper.get_project() == "project"
    assert calls == ["connect"]


def test_unreachable_reaper_explains_how_to_set_it_up(monkeypatch, disconnected):
    def refuse():
        raise ConnectionRefusedError("[Errno 61] Connection refused")

    monkeypatch.setattr(reaper, "_connect", refuse)
    with pytest.raises(RuntimeError) as raised:
        reaper.ensure_connected()
    message = str(raised.value)
    assert message.startswith("Cannot connect to REAPER: [Errno 61] Connection refused.")
    assert "reaper-mcp-server --setup-reaper" in message
    assert "enable_dist_api" not in message
    assert isinstance(raised.value.__cause__, ConnectionRefusedError)
    assert reaper._connected is False


def test_connect_without_setup_names_the_missing_config(monkeypatch, disconnected, tmp_path):
    missing = tmp_path / "bridge.json"
    monkeypatch.setattr(reaper.reaper_bridge, "CONFIG", missing)
    monkeypatch.setattr(reaper.reaper_bridge, "load_config", lambda: (_ for _ in ()).throw(
        FileNotFoundError(missing)))
    with pytest.raises(RuntimeError, match=f"{missing} does not exist"):
        reaper.ensure_connected()


def test_connect_goes_through_the_bridge_only(monkeypatch, disconnected):
    clients, selected = [], []
    monkeypatch.setattr(reaper.reaper_bridge, "load_config",
                        lambda: {"port": 4321, "token": "ab" * 32})
    monkeypatch.setattr(reaper.reaper_bridge, "BridgeClient",
                        lambda port, token: clients.append((port, token)) or "client")
    monkeypatch.setattr(reapy, "connect", lambda host: selected.append(
        (host, reaper._machines.CLIENTS[host])))
    monkeypatch.setitem(reaper._machines.CLIENTS, "localhost", None)
    reaper.ensure_connected()
    assert clients == [(4321, bytes.fromhex("ab" * 32))]
    assert selected == [("localhost", "client")]
