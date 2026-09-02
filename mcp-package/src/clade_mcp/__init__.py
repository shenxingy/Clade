"""Provider-neutral Clade MCP server."""

from __future__ import annotations

import asyncio

from .server import run_server

__version__ = "0.3.1"


def main() -> None:
    """Entry point for `clade-mcp` CLI command."""
    asyncio.run(run_server())
