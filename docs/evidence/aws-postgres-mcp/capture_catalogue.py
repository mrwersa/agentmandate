"""Capture the published AWS Labs PostgreSQL MCP tool catalogue.

Run this file with the isolated dependency version documented in README.md.
Importing the server registers its FastMCP tools but does not connect to AWS or
PostgreSQL; ``list_tools`` returns the same tool definitions served over MCP.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from awslabs.postgres_mcp_server.server import mcp


async def catalogue() -> str:
    """Return a stable MCP-style tools/list payload."""
    tools = await mcp.list_tools()
    payload = {
        "tools": [
            tool.model_dump(by_alias=True, exclude_none=True, mode="json")
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
