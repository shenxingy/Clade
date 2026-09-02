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

**A provider-neutral delivery control plane for coding agents.**

Clade turns agent work into reviewable delivery: resolved execution identity,
immutable evidence, calibrated verification, correction learning, and truthful
Git history. It ships native Claude Code and Codex surfaces plus an MCP bridge
for other clients.

Use the full **Claude Code framework**, the native **Codex plugin**, or the
provider-neutral **MCP bridge**. The optional **Orchestrator** adds a
provider/model registry, evidence and eval control plane, verifier-aware
routing, delivery state, and multi-project fleet truth.

> If this saves you time, a star helps others find it. Something broken? [Open an issue](https://github.com/shenxingy/clade/issues/new/choose).

> **Blog post:** [Building Clade](https://alexshen.dev/en/blog/clade) — motivation, design decisions, and lessons learned.

## Table of Contents

1. [Install](#install)
2. [MCP Server](#mcp-server--use-skills-in-any-ai-editor)
3. [The Trust Loop](#the-trust-loop)
4. [What It Does](#what-it-does)
5. [Self-Learning Mechanisms](#self-learning-mechanisms)
6. [Skills](#skills-137)
7. [Supported Languages](#supported-languages)
8. [Documentation](#documentation)
9. [Dotfile Sync](#dotfile-sync)
10. [Architecture](#architecture)
11. [OpenClaw Integration](#openclaw-integration)
12. [Contributing](#contributing)
13. [License](#license)

## Install

### Claude Code — Full Framework

```bash
git clone https://github.com/shenxingy/clade.git
cd clade && ./install.sh
```

Installs skills, hooks, agents, scripts, and safety guardian. Start a new Claude Code session to activate.

> **Requires:** `jq`. **Platform:** Linux, macOS, and Windows via Git Bash (native CMD/PowerShell without bash is out of scope).

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

## The Trust Loop

Clade keeps six concerns separate so a green-looking run cannot silently change
runtime, account, history, or evidence semantics:

| Layer | Contract |
|---|---|
| Execution identity | Agent runtime, native connection, inference provider, wire protocol, and opaque model are resolved independently |
| Evidence | Every attempt can carry append-only task, timing, Git SHA, test, oracle, cost, artifact, and delivery evidence with digest-linked revisions |
| Verifier calibration | Cheap→strong routing is default-off and requires deterministic verifier evidence; observational reports never mutate policy |
| Correction learning | Explicit corrections pair rejected work with human context and create reviewable eval candidates; no automatic ground-truth path |
| Delivery | Exact reviewed SHA, live PR topology, CI, and repository policy determine merge semantics; squash is never the universal default |
| Fleet truth | Provider catalogs, task state, usage, evidence health, and delivery status remain provenance- and freshness-aware across projects |

Evidence and oracle approval are gates and audit material, not authorization to
publish or merge. Repository policy and explicit authority still control
external side effects.

## What It Does

| When | What fires | Effect |
|------|-----------|--------|
| Session opens in a git repo | `session-context.sh` | Loads git context, handoff state, correction rules, model guidance |
| Session opens in a git repo | `commit-archeology.sh` | Mines `git log` for recurring fix patterns (wiring/deploy/compat gaps, Claude-overridden) — injects top 4 |
| Claude runs a bash command | `pre-tool-guardian.sh` | **Blocks** dangerous ops: migrations, `rm -rf`, force push, `DROP TABLE` |
| Claude edits code | `post-edit-check.sh` | Async type-check (tsc, pyright, cargo check, go vet, etc.) |
| You correct Claude | `correction-detector.sh` | Logs correction, prompts Claude to save a reusable rule |
| Claude marks task done | `verify-task-completed.sh` | Adaptive quality gate: compile + lint, build + test in strict mode |

See [How It Works](docs/how-it-works.md) for the hook reference. 31 hooks ship; the guide documents the ones you are likely to tune — `ls configs/hooks/` is the complete list.

## Self-Learning Mechanisms

Three mechanisms keep Clade aligned with reality:

- **Commit Lessons** *(reactive)* — `commit-archeology.sh` mines `git log` for recurring fix patterns (wiring-gap, deploy-gap, compat-gap, **claude-overridden**) and injects the top 4 at every session start.
- **Doc Align** *(preventive)* — `doc-align.py` declares shared facts in `docs/facts.json` (auto-derived from filesystem); checks/auto-fixes drift across every `*.md`. A PostToolUse hook flags drift the moment you edit a doc, so stale counts never reach commit.
- **Correction Pairing** *(human-grounded)* — explicit corrections pair rejected
  work with the replacement context. Orchestrator corrections enter quarantine
  as eval candidates; only explicit human review can promote corpus truth.

Commit Lessons and Doc Align run locally in the full Claude distribution and
silently no-op in repos that have not opted in. Correction evidence never
turns an inferred revert or async signal into an automatic rule.

See [Self-Learning Mechanisms](docs/learning-mechanisms.md) for full details, detectors, schemas, and tunable env vars.

## Skills (137)

### Core Workflow

| Skill | What it does |
|-------|-------------|
| `/commit` | Create repository-adaptive checkpoint commits; publish when authorized |
| `/sync` | Check off completed TODOs, append session summary to PROGRESS.md |
| `/review` | Walks every VERIFY.md checkpoint, fixing failures in-session until all pass |

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
| `/merge-pr N` | Merge an exact reviewed PR with topology- and history-aware semantics, then clean up |
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

### Content families

**Blog & Content** (30) · **SEO** (25) · **Paid Ads** (23) · **Email** (6) —
per-skill tables live in [When to Use What](docs/when-to-use-what.md), which
also carries the per-skill usage guidance for the core workflow commands above.

## Supported Languages

Detected per project, with hooks and agents adapting to what they find:
TypeScript/JavaScript, Python, Rust, Go, Swift, Kotlin/Java, LaTeX. The
per-language checker and test-runner table lives in
[How It Works](docs/how-it-works.md). A check whose tool is not installed skips
silently rather than failing the run.

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
| [When to Use What](docs/when-to-use-what.md) | Which skill to reach for, per situation — core workflow commands in depth, content families by table |
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

**Orchestrator** (`orchestrator/`): Optional evidence, evaluation, delivery, and
fleet control plane. It resolves native runtime connections without copying
credentials, watches workers, calibrates verifier-aware routing, records
immutable attempt evidence, and exposes exact delivery state. Native CLI/plugin
surfaces work independently.

**Web UI** (`orchestrator/web/`): Read-only observation window. Task queue, worker status, cost dashboard, settings. No production logic — all executes via CLI.

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
