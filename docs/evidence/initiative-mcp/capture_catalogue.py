"""Capture Initiative's route-backed MCP tool catalogue.

Run this file from the ``backend`` directory of the pinned Initiative source
checkout documented in README.md. Importing the app constructs its routes but
does not start its lifespan, connect to PostgreSQL, or make network requests.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.main import app
from app.mcp_server import build_mcp_server


async def catalogue() -> str:
    """Return a stable MCP-style tools/list payload."""
    tools = await build_mcp_server(app).list_tools()
    payload = {
        "tools": [
            tool.to_mcp_tool().model_dump(
                by_alias=True, exclude_none=True, mode="json"
            )
            for tool in tools
        ]
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def main() -> None:
    """Capture the catalogue to a named file, or print it when omitted."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = asyncio.run(catalogue())
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
