# MCP Setup Guide

Model Context Protocol (MCP) servers extend Claude workers with additional capabilities: web search, browser automation, filesystem access, database queries, and more.

The orchestrator automatically detects `.claude/mcp.json` in a project directory and passes it to workers via `--mcp-config`.

---

## Quick Start

1. Copy the example config to your project:
   ```bash
   cp ~/.claude/templates/mcp.json.example /path/to/your/project/.claude/mcp.json
   ```

2. Edit `.claude/mcp.json` — enable the servers you need and fill in API keys.

3. Start the orchestrator and open a session for your project. Workers will automatically pick up the config.

---

## Recommended Servers

### Brave Search — web search for workers

```json
"brave-search": {
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-brave-search"],
  "env": {
    "BRAVE_API_KEY": "your-key-here"
  }
}
```

Get a free API key at [brave.com/search/api](https://brave.com/search/api) (2,000 queries/month free).

**Best for:** research tasks, `/research` skill, fetching current docs.

---

### Filesystem — direct file access outside the project

```json
"filesystem": {
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"]
}
```

Grants workers read/write access to paths outside the git worktree.

**Best for:** tasks that need to read config files, shared data dirs, or cross-project references.

---

### Playwright — browser automation

```json
"playwright": {
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-playwright"]
}
```

Requires: `npm install -g playwright && playwright install chromium`

**Best for:** end-to-end testing tasks, scraping, visual regression checks.

---

### PostgreSQL / SQLite — database access

```json
"postgres": {
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://user:pass@localhost/dbname"]
}
```

**Best for:** data migration tasks, schema analysis, query optimization.

---

## Full Example Config

See `~/.claude/templates/mcp.json.example` for a ready-to-copy config with all servers above.

---

## Per-Project vs Global

- **Per-project** (`.claude/mcp.json`): Orchestrator auto-loads. Best for project-specific tools.
- **Global** (`~/.claude/mcp.json`): Loaded by your Claude Code sessions automatically. Best for universal tools like Brave Search.

Both can be active simultaneously — Claude merges them.

---

## Troubleshooting

**Server not starting:** Check that `npx` can resolve the package. Run `npx @modelcontextprotocol/server-brave-search` manually to test.

**Worker ignoring MCP:** Verify `.claude/mcp.json` exists in the project root (not the orchestrator dir). The orchestrator checks `{project_dir}/.claude/mcp.json`.

**API key not found:** MCP server env vars are separate from the worker's shell env. Set them explicitly in the `"env"` block of the server config.
