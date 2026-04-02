# clade-mcp

MCP server that exposes **29 AI coding skills** as callable tools — autonomous commits, goal-driven loops, code reviews, incident response, security audits, and more.

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
      "command": "clade-mcp"
    }
  }
}
```

### Install manually

```bash
pip install clade-mcp
clade-mcp  # starts the MCP server (stdio transport)
```

## Prerequisites

- **Python 3.10+**
- **Claude Code CLI** installed and in PATH ([install guide](https://docs.anthropic.com/en/docs/claude-code))
  - Skills execute via `claude -p`, so the CLI must be available

## Available Skills (29)

| Skill | Description |
|-------|-------------|
| **commit** | Analyze changes, split into logical commits by module, push |
| **loop** | Goal-driven autonomous improvement loop (Blueprint architecture) |
| **review** | Coverage-driven review — test all VERIFY.md checkpoints |
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
| **next** | Multi-angle "what's next?" priority session |
| **orchestrate** | Decompose goals into tasks for worker execution |
| **frontend-design** | Create production-grade frontend interfaces |
| **audit** | Audit correction rules for promotion/cleanup |
| **merge-pr** | Squash-merge PR and clean up branch |
| **worktree** | Create git worktrees for parallel sessions |
| **pipeline** | Check health of background pipelines |
| **provider** | Switch LLM provider |
| **slt** | Toggle statusline display mode |
| **model-research** | Research latest Claude models |
| **minimax-usage** | Check API usage quota |

## How It Works

1. On startup, the server loads all bundled skill definitions
2. Each skill is registered as an MCP tool with auto-generated JSON Schema
3. When a tool is called, the skill prompt is executed via `claude -p` in your project directory
4. Results are returned through the MCP protocol

Skills from `~/.claude/skills/` (installed via Clade's `install.sh`) are also loaded and merged.

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
