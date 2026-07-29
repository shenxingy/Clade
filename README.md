**English** | [中文](README.zh-CN.md)

<p align="center">
  <img src="assets/banner.svg" alt="Clade" width="800" />
</p>

<p align="center">
  <a href="https://pypi.org/project/clade-mcp/"><img src="https://img.shields.io/pypi/v/clade-mcp?label=MCP%20Server&color=blue" alt="PyPI" /></a>
  <a href="https://github.com/shenxingy/clade/blob/main/CONTRIBUTING.md"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome" /></a>
  <a href="https://github.com/shenxingy/clade/labels/good%20first%20issue"><img src="https://img.shields.io/github/issues/shenxingy/clade/good%20first%20issue" alt="good first issue" /></a>
</p>

# Clade

**Autonomous coding, evolved.**

132 skills, 30 hooks, 37 agents, a safety guardian, and a correction learning loop — with native distributions for Claude Code and Codex, plus a provider-neutral MCP bridge for other editors.

Three ways to use Clade: the full **Claude CLI framework**, the native **Codex plugin**, or the provider-neutral **MCP bridge**. Add the optional **Orchestrator** for multi-worker observability, quality gates, and task routing.

> If this saves you time, a star helps others find it. Something broken? [Open an issue](https://github.com/shenxingy/clade/issues/new/choose).

> **Blog post:** [Building Clade](https://alexshen.dev/en/blog/clade) — motivation, design decisions, and lessons learned.

## Table of Contents

1. [Install](#install)
2. [MCP Server](#mcp-server--use-skills-in-any-ai-editor)
3. [What It Does](#what-it-does)
4. [Self-Learning Mechanisms](#self-learning-mechanisms)
5. [Skills](#skills-132)
6. [Supported Languages](#supported-languages)
7. [Documentation](#documentation)
8. [Repo Structure](#repo-structure)
9. [Contributing](#contributing)
10. [License](#license)

## Install

### Claude Code — Full Framework

```bash
git clone https://github.com/shenxingy/clade.git
cd clade && ./install.sh
```

Installs skills, hooks, agents, scripts, and safety guardian. Start a new Claude Code session to activate.

> **Requires:** `jq`. **Platform:** Linux and macOS.

### Codex — Native Plugin

```bash
codex plugin marketplace add shenxingy/Clade
codex plugin add clade@clade
```

Start a new Codex thread, then invoke a workflow naturally or explicitly with
the plugin-qualified names `$clade:review`, `$clade:verify`,
`$clade:investigate`, and the other bundled skills. Open `/hooks` once to
review and trust Clade's session-context and command-safety hooks.

Run `$clade:codex-usage setup minimal` for a compact native footer.
`$clade:codex-usage` defaults to the equally compact
`project(branch)-9% (6d)` pace view; icon and detail styles are optional. It
never reads or exposes Codex credentials.

The native plugin runs directly in Codex and does **not** require Claude Code.
It currently ships 25 provider-native core workflows; Claude-specific overnight
orchestration remains in the full framework. See [Native Codex Support](docs/codex.md).

### MCP Server Only

If you want Clade tools in another MCP client:

```bash
pip install --upgrade clade-mcp
```

Version 0.2.0 adds the Codex execution runtime while keeping Claude as the
backwards-compatible default. See [MCP Server](#mcp-server--use-skills-in-any-ai-editor)
below for configuration and the [MCP package guide](mcp-package/README.md) for
all runtime and sandbox options.

## MCP Server — Use Skills in Any AI Editor

The MCP package exposes 34 bundled Clade skills, plus compatible user-installed
skills, as callable tools via the [Model Context Protocol](https://modelcontextprotocol.io).
It can execute them with either Claude or Codex.

**Claude Desktop or another client using Claude as its runtime:**
```json
{
  "mcpServers": {
    "clade": { "command": "uvx", "args": ["clade-mcp"] }
  }
}
```

**Cursor / Windsurf:**
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

`CLADE_RUNTIME` accepts `claude` (the backwards-compatible default), `codex`, or
`auto`. Prefer the native Codex plugin inside Codex itself; adding the MCP server
there would duplicate skills and spawn nested agent sessions. The same applies
inside the full Claude Code framework, where Clade skills are already native.

## What It Does

| When | What fires | Effect |
|------|-----------|--------|
| Session opens in a git repo | `session-context.sh` | Loads git context, handoff state, correction rules, model guidance |
| Session opens in a git repo | `commit-archeology.sh` | Mines `git log` for recurring fix patterns (wiring/deploy/compat gaps, Claude-overridden) — injects top 4 |
| Claude runs a bash command | `pre-tool-guardian.sh` | **Blocks** dangerous ops: migrations, `rm -rf`, force push, `DROP TABLE` |
| Claude edits code | `post-edit-check.sh` | Async type-check (tsc, pyright, cargo check, go vet, etc.) |
| You correct Claude | `correction-detector.sh` | Logs correction, prompts Claude to save a reusable rule |
| Claude marks task done | `verify-task-completed.sh` | Adaptive quality gate: compile + lint, build + test in strict mode |

See [How It Works](docs/how-it-works.md) for the full hook reference (30 hooks).

## Self-Learning Mechanisms

Two mechanisms keep Clade aligned with reality without manual upkeep:

- **Commit Lessons** *(reactive)* — `commit-archeology.sh` mines `git log` for recurring fix patterns (wiring-gap, deploy-gap, compat-gap, **claude-overridden**) and injects the top 4 at every session start.
- **Doc Align** *(preventive)* — `doc-align.py` declares shared facts in `docs/facts.json` (auto-derived from filesystem); checks/auto-fixes drift across every `*.md`. A PostToolUse hook flags drift the moment you edit a doc, so stale counts never reach commit.

Both work on any project Claude Code is run in (universal, in `~/.claude/scripts/`). Both are silent no-ops on repos that haven't opted in.

See [Self-Learning Mechanisms](docs/learning-mechanisms.md) for full details, detectors, schemas, and tunable env vars.

## Skills (132)

### Core Workflow

| Skill | What it does |
|-------|-------------|
| `/commit` | Create repository-adaptive checkpoint commits; publish when authorized |
| `/sync` | Check off completed TODOs, append session summary to PROGRESS.md |
| `/review` | 8-phase coverage review — finds AND fixes issues, loops until clean |
| `/verify` | Verify project behavior anchors (compile, test, lint) |

### Autonomous Operation

| Skill | What it does |
|-------|-------------|
| `/start` | Autonomous session launcher — morning brief, overnight runs, cross-project patrol |
| `/loop GOAL` | Goal-driven improvement loop — supervisor plans, workers execute in parallel |
| `/iloop TASK` | In-session iterative loop — Stop hook re-prompts until done (no background workers) |
| `/batch-tasks` | Execute TODO steps via unattended sessions (serial or parallel) |
| `/orchestrate` | Decompose goals into tasks for worker execution |
| `/handoff` | Save session state for context relay between agents |
| `/pickup` | Resume from previous handoff — zero-friction restart |
| `/worktree` | Create git worktrees for parallel sessions |
| `/poke` | Heartbeat after `esc` — 3-line status, auto-continues if still progressing |
| `/status` | Session dashboard — background agents, loops, worktrees, unpushed commits |
| `/go` | Execute the recommendation from your most recent A/B/C option set |

### Code Quality

| Skill | What it does |
|-------|-------------|
| `/review-pr N` | AI code review on a PR diff — Critical / Warning / Suggestion |
| `/merge-pr N` | Squash-merge PR and clean up branch |
| `/investigate` | Root cause analysis — no fix without confirmed hypothesis |
| `/incident DESC` | Incident response — diagnose, postmortem, follow-up tasks |
| `/cso` | Security audit (OWASP + STRIDE) |
| `/map` | Generate ARCHITECTURE.md with module graph + file ownership |

### Research & Planning

| Skill | What it does |
|-------|-------------|
| `/research TOPIC` | Deep web research, synthesize to docs/research/ |
| `/model-research` | Latest Claude model data + auto-update configs |
| `/next` | "What's next?" — fast 1-shot recommendation (default); `/next deep` for multi-round interview |
| `/brief` | Morning briefing — overnight commits, costs, next steps |
| `/retro` | Engineering retrospective from git history |
| `/frontend-design` | Create production-grade frontend interfaces |

### System

| Skill | What it does |
|-------|-------------|
| `/audit` | Clean up correction rules — promote, deduplicate, remove stale |
| `/document-release` | Post-ship doc sync (README, CHANGELOG, CLAUDE.md) |
| `/pipeline` | Health check for background pipelines |
| `/provider` | Switch LLM provider |
| `slt` | Toggle statusline quota pace indicator |

### Blog & Content (30 skills)

| Skill | What it does |
|-------|-------------|
| `/blog` | Full lifecycle — brief → outline → write → SEO check |
| `/blog-write` | Write SERP-informed articles from scratch |
| `/blog-rewrite` | Optimize existing posts for quality and SEO |
| `/blog-audit` | Full-site health scan (thin content, meta, cannibalization) |
| + 26 more | analyze · audio · brand · brief · calendar · cannibalization · chart · cluster · discourse · factcheck · flow · geo · google · image · locale-audit · localize · multilingual · notebooklm · outline · persona · repurpose · schema · seo-check · strategy · taxonomy · translate |

### SEO (25 skills)

| Skill | What it does |
|-------|-------------|
| `/seo` | Full SEO audit suite |
| `/seo-technical` | Crawlability, indexability, Core Web Vitals |
| `/seo-page` | Deep single-page analysis |
| `/seo-content` | E-E-A-T and content quality scoring |
| + 21 more | audit · backlinks · cluster · competitor-pages · content-brief · dataforseo · drift · ecommerce · flow · geo · google · hreflang · image-gen · images · local · maps · plan · programmatic · schema · sitemap · sxo |

### Paid Ads (23 skills)

| Skill | What it does |
|-------|-------------|
| `/ads` | Multi-platform ads audit suite |
| `/ads-google` | Google Ads — Quality Score, PMax, bidding |
| `/ads-meta` | Meta Ads — Pixel/CAPI, creative fatigue, Advantage+ |
| `/ads-create` | Create new ad campaigns from brief |
| + 19 more | amazon · apple · attribution · audit · budget · competitor · creative · dna · generate · landing · linkedin · math · microsoft · photoshoot · plan · server-side-tracking · test · tiktok · youtube |

### Email (6 skills)

| Skill | What it does |
|-------|-------------|
| `/email-write` | Compose high-converting emails (PAS, AIDA, BAB frameworks) |
| `/email-audit` | Deliverability audit — SPF, DKIM, DMARC, blacklists, health score |
| `/email-sequence` | Design automation sequences (welcome, nurture, re-engagement) |
| + 3 more | check · plan · review |

See [When to Use What](docs/when-to-use-what.md) for detailed usage guidance.

## Supported Languages

Auto-detected — hooks and agents adapt to your project:

| Language | Edit check | Type checker | Test runner |
|----------|-----------|-------------|-------------|
| TypeScript / JavaScript | tsc (monorepo-aware) | tsc | jest / vitest |
| Python | pyright / mypy | pyright / mypy | pytest |
| Rust | cargo check | cargo check | cargo test |
| Go | go vet | go vet | go test |
| Swift / iOS | swift build | swift build | swift test |
| Kotlin / Android / Java | gradlew | gradlew | gradle test |
| LaTeX | chktex | chktex | — |

All checks are opt-in by detection — if the tool isn't installed, the hook silently skips.

## Documentation

| Guide | Contents |
|-------|----------|
| [Native Codex Support](docs/codex.md) | Plugin installation, native skills/hooks, MCP runtime selection, compatibility boundaries |
| [MCP Package](mcp-package/README.md) | clade-mcp 0.2.0 installation, runtime selection, sandbox and skill catalog |
| [0.2.0 Release Notes](docs/releases/v0.2.0.md) | Native Codex support, MCP changes, upgrade steps, and validation results |
| [Changelog](CHANGELOG.md) | Release history and upgrade notes |
| [Maximize Throughput](docs/throughput.md) | Skip permissions, batch tasks, parallel worktrees, terminal + voice |
| [Orchestrator Web UI](docs/orchestrator.md) | Chat-to-plan, worker dashboard, settings, iteration loop |
| [Overnight Operation](docs/autonomous-operation.md) | Task queue, parallel sessions, context relay, safety |
| [How It Works](docs/how-it-works.md) | Hooks, agents, skills internals, correction learning, model selection |
| [Configuration](docs/configuration.md) | Settings, thresholds, adding custom hooks/agents/skills |
| [When to Use What](docs/when-to-use-what.md) | Detailed usage guidance for every skill |
| [Who to Learn From](docs/who-to-learn-from.md) | Vetted watch-list of the agentic-coding frontier — people, repos, bot behavior, reviewed quarterly |

## Dotfile Sync

Keep `~/.claude/` in sync across machines — memory, corrections, skills, hooks, and scripts.

```bash
~/.claude/scripts/sync-setup.sh            # auto-detect NFS or GitHub
~/.claude/scripts/sync-setup.sh --github   # explicit GitHub backend
```

Fully automatic once configured. See [Configuration](docs/configuration.md) for details.

## Architecture

**Claude CLI layer** (`configs/` → installed to `~/.claude/`): Full skill, hook, script, and agent framework.

**Codex plugin** (`plugins/clade/`): Generated provider-native core skills plus Codex lifecycle hooks. Distributed through `.agents/plugins/marketplace.json`.

**Orchestrator** (`orchestrator/`): Observability + gates + execution adapter. Watches parallel workers, enforces quality gates, routes tasks, provides web UI for multi-project oversight. Optional — CLI works independently.

**Web UI** (`orchestrator/web/`): Read-only observation window. Task queue, worker status, cost dashboard, settings. No production logic — all executes via CLI.

```
clade/
├── install.sh               # One-command deployment
├── configs/                 # ← THE PRODUCT CENTER
│   ├── skills/              # 132 skill definitions
│   ├── hooks/               # 30 event hooks
│   ├── agents/              # 37 agent definitions
│   └── scripts/             # 35 shell + 13 Python utilities
├── plugins/clade/           # Native Codex plugin (25 generated core skills + hooks)
├── .agents/plugins/         # Codex marketplace manifest
├── orchestrator/            # ← THE EXECUTION ADAPTER
│   ├── server.py            # FastAPI app, routes, WebSocket
│   ├── worker.py            # WorkerPool, SwarmManager, task dispatch
│   ├── task_queue.py        # SQLite task queue + CRUD
│   ├── evidence_bundle.py   # Immutable lifecycle evidence + digest chains
│   └── web/                 # ← THE OBSERVATION WINDOW
│       └── src/             # React + Vite UI (served from dist/)
├── docs/                    # Guides and research
├── adapters/openclaw/       # OpenClaw integration (mobile monitoring)
└── templates/               # Settings, CLAUDE.md templates
```

## OpenClaw Integration

Monitor and control overnight loops from your phone via [OpenClaw](https://openclaw.ai).

| Skill | Trigger | Effect |
|-------|---------|--------|
| clade-status | "how's the loop going" | Iteration progress, cost, commits |
| clade-control | "start a loop to fix tests" | Start/stop autonomous loops |
| clade-report | "what did it do overnight" | Session report, cost breakdown |

See [`adapters/openclaw/README.md`](adapters/openclaw/README.md) for setup.

## Contributing

Contributions welcome — code, docs, issue triage, bug reports. See [CONTRIBUTING.md](CONTRIBUTING.md).

### Known Limitations

1. **Loop on non-code tasks** (research/docs) fails silently — workers produce no diff, loop reports failure
2. **Workers inherit parent env** — project-specific env vars leak into worker shells; sanitize before overnight runs
3. **Context budget is per-session** — multi-day runs may exhaust context; use `/handoff` + `/pickup`

## License

[MIT](LICENSE)
