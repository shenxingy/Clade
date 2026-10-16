#!/usr/bin/env python3
"""Credential pipe for MCP clients only. Never invoke with model-visible stdout."""
import json
import os
import sys

from web_search import RetrievalError, read_key


def main():
    expected = "https://agent.tinyfish.ai/mcp"
    if sys.stdout.isatty() or os.environ.get("CLAUDE_CODE_MCP_SERVER_URL", expected) != expected:
        return 2
    try:
        headers = {"Authorization": "Bearer " + read_key()}
    except (RetrievalError, OSError, ValueError):
        print("TinyFish credential unavailable", file=sys.stderr)
        return 2
    print(json.dumps(headers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
