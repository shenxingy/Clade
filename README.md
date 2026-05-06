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

103 skills, 24 hooks, 34 agents, a safety guardian, and a correction learning loop — all working together so Claude codes better, catches its own mistakes, and can run unattended overnight while you sleep.

> If this saves you time, a star helps others find it. Something broken? [Open an issue](https://github.com/shenxingy/clade/issues/new/choose).

> **Blog post:** [Building Clade](https://alexshen.dev/en/blog/clade) — motivation, design decisions, and lessons learned.

## Table of Contents

1. [Install](#install)
2. [MCP Server](#mcp-server--use-skills-in-any-ai-editor)
3. [What It Does](#what-it-does)
4. [Commit Lessons](#commit-lessons--learn-from-your-git-history)
5. [Skills](#skills-103)
5. [Hooks](#hooks-14)
6. [Supported Languages](#supported-languages)
7. [Documentation](#documentation)
8. [Repo Structure](#repo-structure)
9. [Contributing](#contributing)
10. [License](#license)

## Install

### Full Framework (recommended)

```bash
git clone https://github.com/shenxingy/clade.git
cd clade && ./install.sh
```

Installs skills, hooks, agents, scripts, and safety guardian. Start a new Claude Code session to activate.

> **Requires:** `jq`. **Platform:** Linux and macOS.

### MCP Server Only

If you just want the skills in Cursor, Windsurf, Claude Desktop, or any MCP client:

```bash
pip install clade-mcp
```

See [MCP Server](#mcp-server--use-skills-in-any-ai-editor) below for configuration.

## MCP Server — Use Skills in Any AI Editor

The MCP server exposes all 103 Clade skills as callable tools via the [Model Context Protocol](https://modelcontextprotocol.io). Works with any MCP-compatible client.

**Claude Desktop / Claude Code:**
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
    "clade": { "command": "clade-mcp" }
  }
}
```

> **Prerequisite:** [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) must be installed — skills execute via `claude -p`.

## What It Does

| When | What fires | Effect |
|------|-----------|--------|
| Session opens in a git repo | `session-context.sh` | Loads git context, handoff state, correction rules, model guidance |
| Session opens in a git repo | `commit-archeology.sh` | Mines `git log` for recurring fix patterns (wiring/deploy/compat gaps, Claude-overridden) — injects top 4 |
| Claude runs a bash command | `pre-tool-guardian.sh` | **Blocks** dangerous ops: migrations, `rm -rf`, force push, `DROP TABLE` |
| Claude edits code | `post-edit-check.sh` | Async type-check (tsc, pyright, cargo check, go vet, etc.) |
| You correct Claude | `correction-detector.sh` | Logs correction, prompts Claude to save a reusable rule |
| Claude marks task done | `verify-task-completed.sh` | Adaptive quality gate: compile + lint, build + test in strict mode |

See [How It Works](docs/how-it-works.md) for the full hook reference (24 hooks).

## Commit Lessons — learn from your git history

Every project's `git log` is a record of mistakes you (or Claude) already made. Clade mines it.

At every session start, `commit-archeology.sh` scans the last 60 days of commits for **recurring** patterns and injects the top 4 as context:

```
## 🧠 Commit Lessons (this repo, last 60d)
- 5× wiring-gap (last ef6ef76 on 2026-04-11) → fix: ... wire sessionId to all API calls
- 8× compat-gap (last 9d8afb1 on 2026-03-30) → fix(commit): cross-platform CI guidance
- 3× deploy-gap (last 1f32dd8 on 2026-04-27) → fix(install): deploy orchestrator-settings.example.json
- 12× claude-overridden (last 700b952) → 12 Claude commits whose files later got a non-Claude fix
```

**Detectors (all run locally, never upload):**
- `wiring-gap` — fix commits with "wire / hook up / not registered / not called"
- `deploy-gap` — fix commits referencing install.sh or "missing from"
- `compat-gap` — fix commits about macOS / bash / cross-platform fallbacks
- `disambiguate` — naming collisions / built-in conflicts
- `claude-overridden` — Claude-authored commits whose files later got a human-only fix (uses `Co-Authored-By: Claude` trailer)
- `mass-fix-day-*` — any single day with ≥10 fix commits (noisy initial pass signal)

**Works in any Claude Code frontend** (TUI, desktop, IDE) — the hook is in `~/.claude/settings.json`, fires regardless of UI. Web (claude.ai/code) is the only exception (it can't read your local git).

**Tunable via env vars:** `COMMIT_ARCH_WINDOW=60` (days), `COMMIT_ARCH_TOP_N=4` (lines injected), `COMMIT_ARCH_MIN=3` (min occurrences), `COMMIT_ARCH_CACHE_HOURS=24` (rescan throttle).

To verify on any project: `cd <repo> && bash ~/.claude/scripts/commit-archeology.sh --inject --force`.

If nothing prints: repo has <5 commits in window, or no pattern hit ≥3 occurrences. Both are fine — silent no-op is the design.

## Doc Align — keep counts and facts in sync across all docs

Every project has shared facts that drift: skill counts in README, version numbers in landing pages, trial periods in marketing copy. Manual sync is a losing game — `git log` already shows multiple "update README counts" commits in this repo alone.

`docs/facts.json` is the **single source of truth**. `doc-align.py` checks every `*.md` against it.

```json
{
  "facts": [
    {
      "name": "skills",
      "value": 103,
      "derive": {"type": "count_glob", "pattern": "configs/skills/*/"},
      "patterns": ["^## Skills\\s*\\((\\d+)\\)", "^(\\d+) skills,"]
    }
  ]
}
```

**Modes:**
- `doc-align.py check` — report drift, exit non-zero if any
- `doc-align.py apply` — auto-rewrite drifting values in-place
- `doc-align.py refresh` — re-derive auto-derivable facts (counts from filesystem)
- `doc-align.py sync` — refresh + apply (one-shot)

**`derive` types (V1):** `count_glob` (count files/dirs matching glob). More to come (`http_get_json`, `count_lines`, etc.) when needed. No shell-injection surface — safe primitives only.

**Auto-runs on every install.** `install.sh` calls `refresh` so `facts.json` always reflects the filesystem (skill/hook/agent/script counts). `apply` is opt-in (you decide when to rewrite docs).

**Universal:** lives in `~/.claude/scripts/doc-align.py` after install — works on any project that has a `docs/facts.json`. Repos without one are silent no-ops.

## Skills (103)

### Core Workflow

| Skill | What it does |
|-------|-------------|
| `/commit` | Split changes into logical commits by module, push by default |
| `/sync` | Check off completed TODOs, append session summary to PROGRESS.md |
| `/review` | 8-phase coverage review — finds AND fixes issues, loops until clean |
| `/verify` | Verify project behavior anchors (compile, test, lint) |

### Autonomous Operation

| Skill | What it does |
|-------|-------------|
| `/start` | Autonomous session launcher — morning brief, overnight runs, cross-project patrol |
| `/loop GOAL` | Goal-driven improvement loop — supervisor plans, workers execute in parallel |
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

### Blog & Content (22 skills)

| Skill | What it does |
|-------|-------------|
| `/blog` | Full lifecycle — brief → outline → write → SEO check |
| `/blog-write` | Write SERP-informed articles from scratch |
| `/blog-rewrite` | Optimize existing posts for quality and SEO |
| `/blog-audit` | Full-site health scan (thin content, meta, cannibalization) |
| + 18 more | analyze · audio · brief · calendar · chart · factcheck · geo · google · image · notebooklm · outline · persona · repurpose · schema · seo-check · strategy · taxonomy · cannibalization |

### SEO (19 skills)

| Skill | What it does |
|-------|-------------|
| `/seo` | Full SEO audit suite |
| `/seo-technical` | Crawlability, indexability, Core Web Vitals |
| `/seo-page` | Deep single-page analysis |
| `/seo-content` | E-E-A-T and content quality scoring |
| + 15 more | audit · backlinks · competitor-pages · dataforseo · geo · google · hreflang · image-gen · images · local · maps · plan · programmatic · schema · sitemap |

### Paid Ads (18 skills)

| Skill | What it does |
|-------|-------------|
| `/ads` | Multi-platform ads audit suite |
| `/ads-google` | Google Ads — Quality Score, PMax, bidding |
| `/ads-meta` | Meta Ads — Pixel/CAPI, creative fatigue, Advantage+ |
| `/ads-create` | Create new ad campaigns from brief |
| + 14 more | apple · audit · budget · competitor · creative · dna · generate · landing · linkedin · microsoft · photoshoot · plan · tiktok · youtube |

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
| [Maximize Throughput](docs/throughput.md) | Skip permissions, batch tasks, parallel worktrees, terminal + voice |
| [Orchestrator Web UI](docs/orchestrator.md) | Chat-to-plan, worker dashboard, settings, iteration loop |
| [Overnight Operation](docs/autonomous-operation.md) | Task queue, parallel sessions, context relay, safety |
| [How It Works](docs/how-it-works.md) | Hooks, agents, skills internals, correction learning, model selection |
| [Configuration](docs/configuration.md) | Settings, thresholds, adding custom hooks/agents/skills |
| [When to Use What](docs/when-to-use-what.md) | Detailed usage guidance for every skill |

## Dotfile Sync

Keep `~/.claude/` in sync across machines — memory, corrections, skills, hooks, and scripts.

```bash
~/.claude/scripts/sync-setup.sh            # auto-detect NFS or GitHub
~/.claude/scripts/sync-setup.sh --github   # explicit GitHub backend
```

Fully automatic once configured. See [Configuration](docs/configuration.md) for details.

## Repo Structure

```
clade/
├── install.sh               # One-command deployment
├── uninstall.sh             # Clean removal
├── mcp-package/             # PyPI package (clade-mcp)
├── orchestrator/            # FastAPI web UI + worker pool + task queue
│   ├── server.py            # App, routes, WebSocket
│   ├── worker.py            # WorkerPool, SwarmManager
│   ├── task_queue.py        # SQLite-backed task CRUD
│   ├── mcp_server.py        # MCP server (local dev version)
│   └── web/                 # Single-page dashboard
├── configs/
│   ├── skills/              # 93 skill definitions (SKILL.md + prompt.md)
│   ├── hooks/               # 21 event hooks + lib/
│   ├── agents/              # 35 agent definitions
│   └── scripts/             # 27 shell + Python utilities
├── adapters/openclaw/       # OpenClaw integration (mobile monitoring)
├── templates/               # Settings, CLAUDE.md, corrections templates
└── docs/                    # Guides and research
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
