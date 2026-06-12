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

## Compact mode (default)

By default the server runs in **compact mode** (`CLADE_MCP_COMPACT=1`): instead
of enumerating ~95 per-skill tool definitions into the client's context (the
same system-prompt overflow that hit Claude Code via the repo-root `.mcp.json`
incident), it exposes a search-then-load surface:

| Tool | Purpose |
|------|---------|
| `clade_list_skills` | Full catalog: name, description, argument hints |
| `clade_search_skills` | Keyword search over name + description |
| `clade_run_skill` | Execute a skill by name with an optional args string |

(The three code-search tools `clade_search_class` / `clade_search_method` /
`clade_search_code` are available in both modes.)

To restore one-tool-per-skill enumeration, set the env var in your client's
MCP config:

```json
{
  "mcpServers": {
    "clade": {
      "command": "/home/alexshen/projects/clade/orchestrator/.venv/bin/python",
      "args": ["/home/alexshen/projects/clade/orchestrator/mcp_server.py"],
      "env": { "CLADE_MCP_COMPACT": "0" }
    }
  }
}
```

Per-skill tool names (`clade_commit`, …) keep working in compact mode, so
clients with cached tool lists don't break.

## Restore project-root auto-spawn (not recommended)

```bash
git mv mcp/clade.mcp.json .mcp.json
```

Expect the "skill descriptions dropped" warning to return.
