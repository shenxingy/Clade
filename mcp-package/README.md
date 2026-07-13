# clade-mcp

Provider-neutral MCP server that exposes **32 AI coding skills** as callable tools — autonomous commits, reviews, incident response, security audits, and more. Skill prompts can run through Claude or Codex.

Part of the [Clade](https://github.com/shenxingy/clade) autonomous coding framework.

## Quick Start

### With Claude Desktop / Claude Code

Add to your MCP configuration:

```json
{
  "mcpServers": {
    "clade": {
      "command": "uvx",
      "args": ["clade-mcp"]
    }
  }
}
```

### With Cursor / Windsurf / other MCP clients

```json
{
  "mcpServers": {
    "clade": {
      "command": "clade-mcp",
      "env": { "CLADE_RUNTIME": "codex" }
    }
  }
}
```

### Install manually

```bash
pip install clade-mcp
clade-mcp  # starts the MCP server (stdio transport)
```

## Runtime Selection

- **Python 3.10+**
- One supported agent CLI installed and authenticated:
  - `CLADE_RUNTIME=claude` — backwards-compatible default; executes with `claude -p`
  - `CLADE_RUNTIME=codex` — executes with `codex exec --json`
  - `CLADE_RUNTIME=auto` — prefers Claude when installed, otherwise Codex

Codex execution defaults to the `workspace-write` sandbox. Operators can set
`CLADE_CODEX_SANDBOX=read-only|workspace-write|danger-full-access`. The stronger
`CLADE_CODEX_BYPASS_PERMISSIONS=1` escape hatch is intentionally opt-in.

## Available Skills (32)

| Skill | Description |
|-------|-------------|
| **commit** | Analyze changes, split into logical commits by module, push |
| **loop** | Clade goal-driven Blueprint loop (NOT the CC built-in interval poller) |
| **review** | Coverage-driven VERIFY.md review (NOT a PR review — use review-pr) |
| **review-pr** | AI-powered PR code review with structured feedback |
| **investigate** | Root cause analysis — no fix without confirmed hypothesis |
| **incident** | Incident response — diagnose, postmortem, follow-up tasks |
| **cso** | Security audit (OWASP + STRIDE) |
| **map** | Generate ARCHITECTURE.md with Mermaid diagrams |
| **research** | Deep research on a topic with web search |
| **batch-tasks** | Execute TODO steps via unattended sessions |
| **handoff** | Save session state for context relay between agents |
| **pickup** | Resume from a previous handoff |
| **start** | Autonomous session launcher |
| **verify** | Verify project behavior anchors (compile, test, lint) |
| **sync** | End-of-session doc sync (TODO.md, PROGRESS.md) |
| **document-release** | Post-ship documentation sync |
| **brief** | Morning briefing — overnight activity, costs, next steps |
| **retro** | Engineering retrospective from git history |
| **next** | "What's next?" — fast 1-shot recommendation by default; `/next deep` for multi-round interview |
| **orchestrate** | Decompose goals into tasks for worker execution |
| **frontend-design** | Create production-grade frontend interfaces |
| **audit** | Audit correction rules meta-file (NOT a domain audit — use seo-audit/blog-audit/ads-audit) |
| **merge-pr** | Squash-merge PR and clean up branch |
| **worktree** | Create git worktrees for parallel sessions |
| **pipeline** | Check health of background pipelines |
| **provider** | Switch LLM provider |
| **slt** | Toggle statusline display mode |
| **model-research** | Research latest Claude models |
| **minimax-usage** | Check API usage quota |
| **poke** | Heartbeat after esc — 3-line status, continue if progressing |
| **status** | Session dashboard — background agents, loops, worktrees, unpushed commits |
| **go** | Execute the recommendation from your most recent A/B/C option set |

## How It Works

1. On startup, the server loads all bundled skill definitions
2. Each skill is registered as an MCP tool with auto-generated JSON Schema
3. When a tool is called, the skill prompt is executed by the selected runtime in your project directory
4. Results are returned through the MCP protocol

Skills from `~/.claude/skills/` (installed by the legacy full framework) are also loaded and merged. Native Codex users should prefer the Clade plugin rather than mounting this MCP server inside Codex.

## Full Clade Framework

This MCP server is one part of Clade. The full framework includes:

- **22 hooks** — safety guardian, correction learning, type-checking, session context
- **30 scripts** — committer, loop-runner, parallel task execution, health scanning
- **5 agents** — code-reviewer, test-runner, type-checker, paper-reviewer, verify-app
- **Orchestrator** — FastAPI web UI with task queue, worker pool, GitHub sync

Install the full framework:

```bash
git clone https://github.com/shenxingy/clade.git
cd clade && ./install.sh
```

## License

MIT
