"""reaper-mcp-server --setup-reaper, on a REAPER resource folder in tmp_path
that reapy's configure_reaper (or enable_dist_api) has already set up."""

import json
import re

import pytest

from reaper_mcp import __main__, reaper_bridge, setup_reaper

REAPY_ACTION = "SCR 4 0 RSabc \"Custom: activate_reapy_server.py\" /env/reapy/reascripts/activate_reapy_server.py\n"
OTHER_ACTION = "SCR 4 0 RSdef \"Custom: mine.py\" /home/me/mine.py\n"


@pytest.fixture
def resources(tmp_path, monkeypatch):
    path = tmp_path / "REAPER"
    (path / "Scripts").mkdir(parents=True)
    (path / "reaper.ini").write_text(
        "[reaper]\ncsurf_cnt=2\n"
        "csurf_0=OSC \"phone\" 3 8000\n"
        "csurf_1=HTTP 0 2307 '' 'index.html' 0 ''\n"
        "[audio]\nkeep=me\n"
    )
    (path / "reaper-kb.ini").write_text(REAPY_ACTION + OTHER_ACTION)
    (path / "Scripts" / "__startup.lua").write_text("reaper.ShowConsoleMsg('mine')")
    monkeypatch.setattr(setup_reaper, "python_library", lambda: tmp_path / "lib" / "libpython3.so")
    return path


def _ini(path) -> str:
    return (path / "reaper.ini").read_text()


def test_setup_removes_reapys_distant_api_and_starts_the_bridge(resources, tmp_path):
    config = tmp_path / "home" / "bridge.json"
    done = setup_reaper.setup(resources, config_path=config)
    # reapy's password-less web interface is gone; the user's other surface stays.
    assert _ini(resources) == (
        "[reaper]\ncsurf_cnt=1\ncsurf_0=OSC \"phone\" 3 8000\nreascript=1\n"
        f"pythonlibpath64={tmp_path / 'lib'}\npythonlibdll64=libpython3.so\n"
        "[audio]\nkeep=me\n"
    )
    assert (resources / "reaper.ini.bak").is_file()
    # reapy's server action is gone; the user's own action stays; the bridge is added.
    kb = (resources / "reaper-kb.ini").read_text()
    assert "activate_reapy_server" not in kb and OTHER_ACTION in kb
    [bridge] = [line for line in kb.splitlines() if line.endswith(reaper_bridge.__file__)]
    code = bridge.split(" ")[3]
    startup = (resources / "Scripts" / "__startup.lua").read_text()
    assert startup.startswith("reaper.ShowConsoleMsg('mine')\n")
    assert f'reaper.Main_OnCommand(reaper.NamedCommandLookup("_{code}"), 0)' in startup
    settings = json.loads(config.read_text())
    assert settings["port"] == reaper_bridge.PORT and len(settings["token"]) == 64
    assert any(line.startswith("removed reapy's web interface") for line in done)


def test_setup_is_safe_to_run_again(resources, tmp_path):
    config = tmp_path / "bridge.json"
    setup_reaper.setup(resources, config_path=config)
    token = json.loads(config.read_text())["token"]
    done = setup_reaper.setup(resources, config_path=config)
    startup = (resources / "Scripts" / "__startup.lua").read_text()
    assert len(re.findall("NamedCommandLookup", startup)) == 1
    kb = (resources / "reaper-kb.ini").read_text()
    assert kb.count(reaper_bridge.__file__) == 1
    assert json.loads(config.read_text())["token"] == token
    assert not any("removed" in line for line in done)


def test_setup_refuses_a_folder_that_is_not_reapers(tmp_path):
    with pytest.raises(FileNotFoundError, match="no reaper.ini"):
        setup_reaper.setup(tmp_path, config_path=tmp_path / "bridge.json")


def test_cli_setup_reaper(resources, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(reaper_bridge, "CONFIG", tmp_path / "bridge.json")
    monkeypatch.setattr(setup_reaper.setup, "__kwdefaults__",
                        {"config_path": tmp_path / "bridge.json"})
    monkeypatch.setattr("sys.argv", ["reaper-mcp-server", "--setup-reaper",
                                     "--resource-path", str(resources)])
    with pytest.raises(SystemExit) as exited:
        __main__.main()
    assert exited.value.code == 0
    assert "Done. Start REAPER" in capsys.readouterr().out


def test_cli_setup_reaper_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["reaper-mcp-server", "--setup-reaper",
                                     "--resource-path", str(tmp_path)])
    with pytest.raises(SystemExit) as exited:
        __main__.main()
    assert exited.value.code == 1
    assert "setup failed:" in capsys.readouterr().err
