**English** | [中文](https://github.com/shenxingy/Clade/blob/main/mcp-package/README.zh-CN.md)

# clade-mcp 0.3.1

Provider-neutral MCP server that exposes **34 AI coding skills** as callable tools — autonomous commits, reviews, incident response, security audits, and more. Skill prompts can run through Claude or Codex.

Part of the [Clade](https://github.com/shenxingy/clade) autonomous coding framework.

## What's New in 0.3.1

- Native Codex execution through `codex exec --json`, selected with
  `CLADE_RUNTIME=codex`
- Conservative `auto` runtime selection: Claude when available, otherwise Codex
- Configurable Codex sandbox with an explicit, opt-in permission bypass
- 34 bundled workflows, up from 29 in 0.1.0
- Runtime name reported by `clade_list_skills` for configuration diagnostics

Upgrade with:

```bash
pip install --upgrade clade-mcp
```

## Quick Start

### Claude runtime

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

### Codex runtime

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

Use either configuration in Claude Desktop, Cursor, Windsurf, or another MCP
client. Do not mount this server inside Codex when the native Clade plugin is
enabled, or inside Claude Code when the full Clade framework is installed; both
already load Clade workflows directly.

### Install manually

```bash
pip install --upgrade clade-mcp
clade-mcp  # starts the MCP server (stdio transport)
```

## Runtime Selection

- **Python 3.10+**
- At least one supported agent CLI installed and authenticated

| Variable | Default | Values and behavior |
|----------|---------|---------------------|
| `CLADE_RUNTIME` | `claude` | `claude` executes with `claude -p`; `codex` uses `codex exec --json`; `auto` prefers Claude when installed, otherwise Codex |
| `CLADE_CODEX_SANDBOX` | `workspace-write` | `read-only`, `workspace-write`, or `danger-full-access` |
| `CLADE_CODEX_BYPASS_PERMISSIONS` | unset | Set to `1` only inside an externally isolated environment |

The permission bypass takes precedence over the sandbox setting and passes
Codex's `--dangerously-bypass-approvals-and-sandbox` flag. It is intentionally
never enabled by default.

## Available Skills (34)

| Skill | Description |
|-------|-------------|
| **commit** | Analyze changes, split into logical commits by module, push |
| **create-pr** | Publish or update one exact-SHA pull request |
| **delivery** | Run the full checkpoint, review, integration, and cleanup workflow |
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

- **138 skills** — coding, research, SEO, content, paid ads, and email workflows
- **32 hooks** — safety guardian, correction learning, type-checking, session context
- **42 shell scripts + 31 Python utilities** — commits, loops, parallel tasks, health scanning
- **37 agents** — code, security, compliance, marketing, research, and verification specialists
- **Native Codex plugin** — 26 core workflows, usage visibility, and lifecycle safety hooks
- **Orchestrator** — FastAPI web UI with task queue, worker pool, GitHub sync

Install the full framework:

```bash
git clone https://github.com/shenxingy/clade.git
cd clade && ./install.sh
```

## License

MIT

See the project [changelog](https://github.com/shenxingy/Clade/blob/main/CHANGELOG.md)
for release and upgrade details.
