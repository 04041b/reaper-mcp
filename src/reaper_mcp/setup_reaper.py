"""reaper-mcp-server --setup-reaper: configure REAPER to start the bridge.

Run with REAPER closed: REAPER rewrites reaper.ini when it quits. It

1. enables Python for ReaScript, with this interpreter's library (as reapy's
   configure_reaper does);
2. removes what reapy's distant API set up: the password-less web interface
   on port 2307, and the action that starts reapy's network-wide server;
3. registers reaper_bridge.py as an action, and runs it from
   Scripts/__startup.lua each time REAPER starts;
4. writes the bridge's port and token to ~/.reaper-mcp/bridge.json.

It is safe to run again, for instance after recreating the environment.
"""

import os
import re
import shutil
import sys
from pathlib import Path

from reaper_mcp import reaper_bridge

REAPY_WEB_INTERFACE_PORT = 2307
REAPY_SERVER_SCRIPT = "activate_reapy_server.py"
STARTUP_BEGIN = "-- reaper-mcp bridge: begin (written by reaper-mcp-server --setup-reaper)"
STARTUP_END = "-- reaper-mcp bridge: end"


def default_resource_paths() -> list[Path]:
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Application Support" / "REAPER"]
    if sys.platform == "win32":
        return [Path(os.path.expandvars(r"$APPDATA\REAPER"))]
    return [Path.home() / ".config" / "REAPER"]


def find_resource_path() -> Path:
    for path in default_resource_paths():
        if (path / "reaper.ini").is_file():
            return path
    raise FileNotFoundError(
        "REAPER's resource folder was not found; pass it with --resource-path "
        "(REAPER shows it under Options > Show REAPER resource path)"
    )


def setup(resource_path: Path, *, config_path: Path = reaper_bridge.CONFIG) -> list[str]:
    """Configure REAPER in resource_path; returns what was done, one line each."""
    import reapy
    from reapy.config.config import add_reascript

    ini = resource_path / "reaper.ini"
    if not ini.is_file():
        raise FileNotFoundError(f"{resource_path} has no reaper.ini; is it REAPER's resource folder?")
    done = []
    lines = ini.read_text(encoding="utf-8").splitlines()
    lines = _enable_python(lines)
    done.append("enabled Python for ReaScript")
    lines, removed = _remove_web_interface(lines, REAPY_WEB_INTERFACE_PORT)
    if removed:
        done.append(f"removed reapy's web interface on port {REAPY_WEB_INTERFACE_PORT}")
    shutil.copyfile(ini, ini.with_name("reaper.ini.bak"))
    ini.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if _remove_reapy_server_action(resource_path / "reaper-kb.ini"):
        done.append("removed reapy's server action")
    action = add_reascript(str(resource_path), reaper_bridge.__file__).strip('"')
    _write_startup(resource_path / "Scripts" / "__startup.lua", action)
    done.append(f"REAPER will start the bridge ({reaper_bridge.__file__}) from Scripts/__startup.lua")
    reapy_dir = str(Path(reapy.__file__).resolve().parent.parent)
    reaper_bridge.write_config(config_path, sys_path=[reapy_dir])
    done.append(f"wrote the bridge's port and token to {config_path}")
    return done


def python_library() -> Path:
    from reapy.config.shared_library import get_python_shared_library

    return Path(get_python_shared_library())


def _enable_python(lines: list[str]) -> list[str]:
    """What reapy's enable_python sets, edited in place: reapy's own ini
    writer fails on Python 3.13 (configparser's UNNAMED_SECTION)."""
    library = python_library()
    lines = _set(lines, "reascript", "1")
    lines = _set(lines, "pythonlibpath64", str(library.parent))
    return _set(lines, "pythonlibdll64", library.name)


def _section(lines: list[str]) -> tuple[int, int]:
    """The [reaper] section's first and past-the-end line indices."""
    start = next((i for i, line in enumerate(lines) if line.strip().lower() == "[reaper]"), None)
    if start is None:
        raise ValueError("reaper.ini has no [reaper] section")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    return start + 1, end


def _set(lines: list[str], key: str, value: str) -> list[str]:
    start, end = _section(lines)
    for i in range(start, end):
        name, sep, _ = lines[i].partition("=")
        if sep and name.strip().lower() == key.lower():
            return [*lines[:i], f"{key}={value}", *lines[i + 1:]]
    return [*lines[:end], f"{key}={value}", *lines[end:]]


def _remove_web_interface(lines: list[str], port: int) -> tuple[list[str], bool]:
    """Remove the HTTP control surface on port (reapy's: "HTTP 0 2307 ..."),
    renumbering the surfaces after it, in place, as REAPER numbers them."""
    start, end = _section(lines)
    slots = sorted((int(m[1]), i) for i in range(start, end)
                   if (m := re.match(r"csurf_(\d+)=", lines[i].strip(), re.I)))
    surfaces = [lines[i].partition("=")[2] for _, i in slots]
    kept = [s for s in surfaces if not _is_web_interface(s, port)]
    if len(kept) == len(surfaces):
        return lines, False
    lines = list(lines)
    for j, (_, i) in enumerate(slots[:len(kept)]):
        lines[i] = f"csurf_{j}={kept[j]}"
    dropped = {i for _, i in slots[len(kept):]}
    lines = [line for i, line in enumerate(lines) if i not in dropped]
    return _set(lines, "csurf_cnt", str(len(kept))), True


def _is_web_interface(surface: str, port: int) -> bool:
    fields = surface.split()
    return len(fields) > 2 and fields[0] == "HTTP" and fields[2] == str(port)


def _remove_reapy_server_action(kb_ini: Path) -> bool:
    if not kb_ini.is_file():
        return False
    lines = kb_ini.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [line for line in lines
            if not (line.startswith("SCR ") and line.rstrip().endswith(REAPY_SERVER_SCRIPT))]
    if len(kept) == len(lines):
        return False
    kb_ini.write_text("".join(kept), encoding="utf-8")
    return True


def _write_startup(startup: Path, action: str) -> None:
    """Add, or replace, this server's block in __startup.lua, keeping the rest."""
    block = (f"{STARTUP_BEGIN}\n"
             f'reaper.Main_OnCommand(reaper.NamedCommandLookup("{action}"), 0)\n'
             f"{STARTUP_END}\n")
    text = startup.read_text(encoding="utf-8") if startup.is_file() else ""
    pattern = re.compile(re.escape(STARTUP_BEGIN) + r".*?" + re.escape(STARTUP_END) + r"\n?", re.S)
    if pattern.search(text):
        text = pattern.sub(lambda _: block, text)
    else:
        text += ("" if not text or text.endswith("\n") else "\n") + block
    startup.parent.mkdir(parents=True, exist_ok=True)
    startup.write_text(text, encoding="utf-8")
