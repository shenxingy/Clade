# Migrating from Hermes Agent

[← Back to README](../README.md)

This page is for users who have been running [Hermes Agent](https://github.com/NousResearch/hermes-agent) and want to add Clade to their setup, or vice versa.

## TL;DR

**Clade and Hermes are not replacements for each other.** They live at different layers:

| | Hermes Agent | Clade |
|---|---|---|
| Layer | Standalone agent runtime (its own loop, tools, gateway) | Augmentation layer for Claude Code CLI |
| Replaces | Claude Code, OpenClaw, Cursor, Codex CLI | nothing — sits beside Claude Code |
| Provider | Multi (Anthropic, OpenRouter, NIM, Kimi, …) | Claude only (uses your Claude Code subscription) |
| Parallel work | Built-in subagents via RPC | Orchestrator: WorkerPool + git worktrees + GitHub-issue task queue |
| Messaging | Telegram / Discord / Slack / WhatsApp / Signal / Email gateway | None — runs in your terminal |
| Cron | Built-in scheduler with messaging delivery | `/loop`, `/schedule` skills + orchestrator process pool |
| Skills | `agentskills.io` standard, autonomous skill creation | `configs/skills/` installed to `~/.claude/skills/` |

If you were using Hermes for *coding work*, you can keep using Hermes — but the **Claude Code TUI is generally a better coding hot-loop** because the tool schemas were designed by Anthropic and Claude is trained on them. Drop into Hermes for: messaging-platform access, multi-provider failover, long-running cloud-resident agents.

## How they can coexist

Many users run both:

- **Claude Code (with Clade installed)** for interactive coding sessions and project automation (`./orchestrator/start.sh`).
- **Hermes** as a "remote agent" that lives on a VPS / Modal / Daytona instance, reachable from your phone via Telegram.

Both can share the same Claude OAuth credentials (Hermes's `model.provider: anthropic` configuration uses `~/.claude.json` for auth — see [agent-config-kit's hermes.patch.yaml](https://github.com/NousResearch/hermes-agent) for the canonical config).

## Skills portability

Hermes ships skills using the [`agentskills.io`](https://agentskills.io) open-standard frontmatter (`name`, `description`, `version`, `metadata`). Clade skills add `when_to_use`, `argument-hint`, and `user_invocable` fields on top. The two formats are not lossy in either direction — you can:

1. **Hermes → Clade**: copy a `SKILL.md`, add `when_to_use` and `user_invocable` fields if you want it as a slash command.
2. **Clade → Hermes**: copy a skill directory, ensure the frontmatter has `version` and a `metadata` block, drop into `~/.hermes/skills/`.

Hermes provides a migration helper (`hermes claw migrate` for OpenClaw) — a similar Clade-to-Hermes import isn't built yet; doing it manually is a few minutes of `cp + frontmatter touch-up`.

## Memory portability

Clade stores memories in `~/.claude/projects/<project-hash>/memory/` as plain Markdown with YAML frontmatter (typed: `user`, `feedback`, `project`, `reference`).

Hermes uses pluggable memory providers (Honcho, mem0, supermemory, byterover, …) backed by a SQLite session DB.

**Currently no automatic bridge.** If you want shared memory:

- The [`agent-config-kit`](https://github.com/agent-config-kit) project provides a `home-agent/` private repo pattern — your `SOUL.md` / `MEMORY.md` / `USER.md` source-of-truth lives in `home-agent/content/`, and adapters symlink the rendered build into either `~/.claude/` or `~/.hermes/`.
- Manual sync: `~/.claude/projects/*/memory/MEMORY.md` is human-readable and can be copy-pasted into Hermes's `~/.hermes/memories/MEMORY.md`.

## What's deliberately not ported from Hermes

These Hermes features won't show up in Clade because they don't fit Clade's scope (Claude Code augmentation, single-runtime):

- **Messaging gateway** (`gateway/`) — needs runtime ownership of the conversation loop; Claude Code owns it instead.
- **Multi-provider adapters** (`agent/{anthropic,bedrock,gemini_*,codex_responses}_adapter.py`) — Clade is Claude-only by design.
- **Pluggable memory provider system** (`plugins/memory/honcho|mem0|supermemory|...`) — Clade's typed memory is a flat-file system; future-proof interface design isn't worth the abstraction cost today.
- **Built-in TUI** (`hermes_cli/`, `tui_gateway/`, `ui-tui/`) — Clade rides Claude Code's TUI.
- **RL trajectory tooling** (`environments/`, `batch_runner.py`, `trajectory_compressor.py`) — Clade isn't a research project.

## Selectively borrowed from Hermes

These are present in Clade today, inspired by Hermes's design:

| Clade | Inspired by Hermes | What it does |
|---|---|---|
| `orchestrator/error_classifier.py` | `agent/error_classifier.py` | Structured taxonomy for Claude subprocess failures (auth / rate_limit / context_overflow / timeout / …) with recovery hints. |
| `orchestrator/compression_feedback.py` | `agent/manual_compression_feedback.py` | User-facing summary for context compression (before/after counts, "denser summaries" caveat). |
| `configs/scripts/redact.py` + `secret-scanner.sh` hook | `agent/redact.py` | Detects common credential patterns in prompts and warns the user. |
| Owner-only `chmod 0600` on `tasks.db` and `orchestrator-settings.json` | Hermes's cron job-file hardening | Limits blast radius of accidentally world-readable settings. |

See `docs/research/` and the project changelog for additions over time.
