# Clade MCP Server

Exposes Clade skills as MCP tools for **external** AI coding tools (Cursor, Cline, Continue, etc.).

## Why this directory?

`.mcp.json` at the repo root caused Claude Code itself to auto-spawn the MCP server in every session — duplicating every skill (e.g. `/blog-write` and `mcp__clade__clade_blog-write`) and overflowing the system prompt (95 skill descriptions dropped).

Moving the config to `mcp/clade.mcp.json` means Claude Code no longer auto-loads it, while external MCP clients can still point at this file or directly at `orchestrator/mcp_server.py`.

## Use from Claude Code (this repo)

You don't need MCP — skills are already native (`/blog-write`, `/commit`, etc.).

## Use from another MCP client

Point your client's MCP config at `mcp_server.py`:

```json
{
  "mcpServers": {
    "clade": {
      "command": "/home/alexshen/projects/clade/orchestrator/.venv/bin/python",
      "args": ["/home/alexshen/projects/clade/orchestrator/mcp_server.py"]
    }
  }
}
```

Or copy `clade.mcp.json` into the client's expected location.

## Restore project-root auto-spawn (not recommended)

```bash
git mv mcp/clade.mcp.json .mcp.json
```

Expect the "skill descriptions dropped" warning to return.
