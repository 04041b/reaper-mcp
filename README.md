# REAPER MCP Server

A Model Context Protocol (MCP) server that enables AI agents to control REAPER DAW — 61 tools covering project management, tracks, track templates, MIDI, FX, mixing, mastering, rendering, and audio analysis.

## Requirements

- [REAPER](https://www.reaper.fm/) 7 or later, installed and running
- Python 3.10+
- REAPER set up with `reaper-mcp-server --setup-reaper` (see [Setup](#setting-up-reaper))

## Installation

```bash
pip install reaper-mcp-server
```

Or install from source:

```bash
git clone https://github.com/bonfire-systems/reaper-mcp.git
cd reaper-mcp
pip install -e .
```

## Setting Up REAPER

The server drives REAPER through [python-reapy](https://github.com/RomeoDespres/reapy)'s
object model, over a small bridge that runs inside REAPER. The bridge listens on
`127.0.0.1` only and serves only clients that prove a per-user token kept in
`~/.reaper-mcp/bridge.json`.

1. Close REAPER (it rewrites `reaper.ini` when it quits)
2. Run, from the environment the server is installed in:
   ```bash
   reaper-mcp-server --setup-reaper
   ```
   For a portable REAPER install, add `--resource-path <folder>`, the folder REAPER
   shows under Options > Show REAPER resource path.
3. Start REAPER. The bridge starts with it, from `Scripts/__startup.lua`.

Run it again if you recreate the environment: REAPER runs the bridge from there.

> **Do not use reapy's own distant API** (`reapy.config.enable_dist_api()` or
> `reapy.configure_reaper()`), which earlier versions of this README asked for. It
> listens on every network interface (port 2306) without authentication and runs
> any function a request names, and adds a web interface on port 2307 with no
> password: anyone who can reach your machine can run code as you. `--setup-reaper`
> removes both if they are set up.

## Usage

### With Claude Desktop

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "reaper": {
      "command": "reaper-mcp-server",
      "args": []
    }
  }
}
```

### With Claude Code

```bash
claude mcp add reaper -- reaper-mcp-server
```

### Standalone

```bash
reaper-mcp-server          # start the server
reaper-mcp-server --debug  # with debug logging
```

## Tools (60)

### Project Management
`create_project` `load_project` `save_project` `get_project_info` `set_tempo` `set_time_signature` `set_cursor_position` `play_project` `stop_transport`

### Tracks
`create_track` `delete_track` `rename_track` `list_tracks` `get_track_info` `set_track_color` `create_bus` `create_send` `remove_send` `list_sends`

### Track Templates
`list_track_templates` `insert_track_template`

Inserts saved `.RTrackTemplate` files from REAPER's TrackTemplates folder (subfolders included) with their exact FX state, routing, folder structure and items, optionally at a given track position.

### MIDI
`create_midi_item` `add_midi_note` `create_chord_progression` `create_drum_pattern`

### FX & Instruments
`add_fx` `remove_fx` `bypass_fx` `list_track_fx` `get_fx_parameters` `set_fx_parameter` `load_fx_preset` `add_master_fx` `list_master_fx` `set_master_fx_parameter`

### Audio
`import_audio_file` `edit_audio_item` `start_recording` `adjust_pitch` `adjust_playback_rate`

### Mixing
`set_track_volume` `set_track_pan` `set_track_mute` `set_track_solo` `set_send_volume` `set_master_volume` `add_volume_automation` `add_pan_automation`

### Rendering
`render_project` `render_stems` `render_time_selection` `render_regions`

### Mastering
`apply_mastering_chain` `apply_limiter` `normalize_project`

### Analysis
`analyze_loudness` `analyze_dynamics` `analyze_frequency_spectrum` `analyze_stereo_field` `analyze_transients` `detect_clipping`

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: one concern per pull request,
tested against a real REAPER (say which version), and an issue first for new
tools.

## License

MIT
