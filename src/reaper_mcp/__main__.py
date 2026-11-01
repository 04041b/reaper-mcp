#!/usr/bin/env python3
import argparse
import logging
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="REAPER MCP Server")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--setup-reaper", action="store_true",
        help="Configure REAPER (closed) to start the local bridge this server connects to, "
             "and remove reapy's network-wide distant API, then exit",
    )
    parser.add_argument("--resource-path", type=Path,
                        help="REAPER's resource folder, for --setup-reaper (default: found)")
    args = parser.parse_args()
    if args.setup_reaper:
        sys.exit(_setup_reaper(args.resource_path))

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )

    from reaper_mcp.server import mcp
    mcp.run(transport="stdio")


def _setup_reaper(resource_path: Path | None) -> int:
    from reaper_mcp.setup_reaper import find_resource_path, setup

    try:
        for line in setup(resource_path or find_resource_path()):
            print(line)
    except (OSError, RuntimeError) as e:
        print(f"setup failed: {e}", file=sys.stderr)
        return 1
    print("Done. Start REAPER; the bridge starts with it.")
    return 0


if __name__ == "__main__":
    main()
