[English](how-it-works.md) | [中文](how-it-works.zh-CN.md)

← Back to [README](../README.md)

# How It Works

## Table of Contents

1. [Hooks (automatic behaviors)](#hooks-automatic-behaviors)
2. [Agents (specialized sub-agents)](#agents-specialized-sub-agents)
3. [Skills (slash commands)](#skills-slash-commands)
4. [Correction Learning Loop](#correction-learning-loop)
5. [Status Line](#status-line)
6. [Scripts (task runners)](#scripts-task-runners)
7. [Automatic Model Selection](#automatic-model-selection)

---

## Hooks (automatic behaviors)

| Hook | Trigger | Model cost |
|------|---------|-----------|
| `session-context.sh` | SessionStart | None (shell only) |
| `pre-tool-guardian.sh` | PreToolUse (Bash) | None (shell only) |
| `revert-detector.sh` | PreToolUse (Bash) | None (shell only) |
| `post-edit-check.sh` | PostToolUse (Edit/Write) | None (shell only) |
| `post-tool-use-lint.sh` | PostToolUse (Edit/Write) | None (shell only) |
| `edit-shadow-detector.sh` | PostToolUse (Edit/Write) | None (shell only) |
| `correction-detector.sh` | UserPromptSubmit | None (shell only) |
| `verify-task-completed.sh` | TaskCompleted | None (shell only) |
| `notify-telegram.sh` | Notification | None (shell only) |
| `prompt-tracker.sh` | UserPromptSubmit | None (shell only) |

All hooks are shell scripts — zero API cost, sub-second execution.

**`post-tool-use-lint.sh`** runs your project's `verify_cmd` after every file edit. On failure it writes `.claude/lint-feedback.md` and exits with code 2 — Claude sees the error output and fixes it in the next turn. Configure via `.claude/orchestrator.json`:

```json
{
  "verify_cmd": "python3 -m py_compile src/main.py"
}
```

Common values: `"tsc --noEmit"` (TypeScript), `"python3 -m py_compile <file>"` (Python), `"cargo check"` (Rust), `"go build ./..."` (Go). Leave unset to disable.

## Agents (specialized sub-agents)

| Agent | Model | Use case |
|-------|-------|----------|
| `code-reviewer` | Sonnet | Code review with persistent memory |
| `paper-reviewer` | Sonnet | Academic paper review — structured critique for LaTeX papers before submission |
| `verify-app` | Sonnet | Runtime verification — adapts to project type (web, Rust, Go, Swift, Gradle, LaTeX) |
| `type-checker` | Haiku | Fast type/compilation check — auto-detects language (TS, Python, Rust, Go, Swift, Kotlin, LaTeX) |
| `test-runner` | Haiku | Test execution — auto-detects framework (pytest, jest, cargo test, go test, swift test, gradle, make) |

Claude auto-selects agents. Haiku agents are fast and cheap for mechanical checks; Sonnet agents reason deeper for reviews.

## Skills (slash commands)

**`/handoff`** saves the entire session state to `.claude/handoff-{timestamp}.md`: what was accomplished, git state, blockers, ordered next steps, and gotchas. Run this when context is ~80% full, before stopping work, or before handing off to a parallel agent. The next session auto-loads it via `session-context.sh`.

**`/pickup`** reads the latest handoff, verifies git state, and immediately resumes work from the first pending Next Step. Zero briefing required for the new session or agent.

**`/batch-tasks`** reads TODO.md, researches the codebase, generates detailed plans for each task, scores them on readiness (scout scoring), assigns the optimal model per task (haiku for mechanical, sonnet for standard, opus for complex), then executes via `claude -p`. Supports serial and parallel (git worktree) execution.

**`/sync`** reviews recent git history, checks off completed TODO items, and appends a session summary to PROGRESS.md. Does not commit — run `/commit` after to commit everything.

**`/commit`** analyzes all uncommitted changes, groups files into logical commits by module (schema, API, frontend, config, docs, etc.), generates commit messages, shows the plan for confirmation, then executes and pushes by default. `--no-push` skips push; `--dry-run` shows the plan only.

**`/orchestrate`** now includes:
- **Step 0**: reads `PROGRESS.md` (last 3000 chars) + `.claude/AGENTS.md` before planning — avoids past mistakes and respects existing file ownership
- **Enhanced task template**: every task gets `verify_cmd`, `own_files`, `forbidden_files`, acceptance checklist, Context Management (`/compact` at 75%), and Commit Rules blocks auto-filled
- **Step 3.5**: auto-generates `.claude/AGENTS.md` from task `own_files` after writing `proposed-tasks.md` — workers see who owns what before starting

**`/batch-tasks`** now:
- **Reads AGENTS.md** before planning: injects file ownership into each task description; flags overlapping file claims for review
- **Scout scoring**: tasks scoring 0–49 are skipped (a GitHub Issue is created in their place); tasks scoring 50–79 are flagged with a `# WARNING` comment and run with caution; 80–100 run normally

**`/model-research`** searches the web for latest Claude model announcements, benchmarks, and pricing. Compares against the current guide and shows what changed. With `--apply`, updates `docs/research/models.md`, the session-context model guidance, and batch-tasks model assignment criteria.

**`/worktree`** creates a new git worktree in `.claude/worktrees/` with an isolated branch, switches the session into it. Use when running parallel Claude Code sessions on the same repo.

**`/research`** runs a structured deep-dive on a topic — web search, synthesize findings, save to `docs/research/<topic>.md`. Useful before starting a complex feature.

**`/map`** generates a codebase map: file → branch ownership from `git log`, module dependency graph, and entry points. Output is saved as `.claude/AGENTS.md` for workers to use.

**`/incident`** activates incident response mode: diagnose the issue, propose a root cause, draft a postmortem, and add follow-up tasks to TODO.md.

**`/review-pr`** reads a PR diff and posts a structured review comment with Critical/Warning/Suggestion sections.

**`/merge-pr`** squash-merges a PR and deletes the feature branch.

## Correction Learning Loop

The most distinctive feature. Here's how it works:

```
You correct Claude          correction-detector.sh        Claude saves rule
("don't use relative   ──>  detects correction pattern ──>  to corrections/
  imports")                  via keyword matching             rules.md

Next session starts         session-context.sh            Claude follows
                       ──>  loads rules.md into      ──>  the rule without
                            system context                 being told again
```

Over time, Claude's behavior aligns to your style automatically. The quality gate (`verify-task-completed.sh`) also adapts — domains where Claude makes more errors get stricter checks.

Error rates are tracked per domain in `~/.claude/corrections/stats.json`:
```json
{
  "frontend": 0.35,  // >0.3 = strict mode (adds build + test)
  "backend": 0.05,   // <0.1 = relaxed mode (basic checks only)
  "ml": 0.2,         // ML/AI training code
  "ios": 0,          // Swift / Xcode
  "android": 0,      // Kotlin / Gradle
  "systems": 0,      // Rust / Go
  "academic": 0,     // LaTeX
  "schema": 0.2
}
```

## Status Line

The status line shows `dir  git:(branch)  ● (4d)` — the quota pace indicator on the right.

### Display Modes

Four modes — cycle with `slt`, or set directly:

| Mode | Example | When to use |
|------|---------|-------------|
| `symbol` (default) | `🐥 (4d)` | Glance at emoji + color |
| `percent` | `🐥 +4% (4d)` | Emoji + delta vs 95% target |
| `number` | `+4% (4d)` | Delta only, no emoji |
| `off` | *(nothing)* | Hide completely |

```bash
slt              # cycle: symbol → percent → number → off → symbol
slt percent      # set specific mode
slt symbol
slt off
```

Mode is saved to `~/.claude/.statusline-mode` and persists across sessions.

### Metric: Delta vs 95% Target

The indicator shows `delta = usage% − elapsed% × 0.95`:

- **0%** = exactly on pace for 95% weekly utilization (the "excellent" target)
- **positive** = ahead of target (`+8%` means you've used 8% more than the target pace)
- **negative** = behind target (`−12%` means you're lagging behind)

This is linear: 1pt delta always represents the same amount of token usage, regardless of the day of the week. (Unlike a projected-end% metric, which would count the same tokens as more significant early in the week.)

### Color Gradient

Color is based on projected week-end utilization (a separate calculation used only for coloring). Muted palette — low saturation so the indicator doesn't compete with the prompt:

| Color | Projected utilization | Meaning |
|-------|-----------------------|---------|
| Soft green | > 100% | Overpacing |
| Sage green | ~95% | Excellent — right on target |
| Amber | ~50% | Moderate usage |
| Soft red | ~0% | Very low usage |

### Themes

Switch emoji themes with `slt theme`:

| Theme | Emojis | Stage logic |
|-------|--------|-------------|
| `circles` | ○ ◑ ● ◉ | fill level |
| `bird` | 🥚🐣🐥🦢 | ugly duckling → swan |
| `moon` | 🌑🌙🌛🌝 | new → full moon |
| `weather` | 🌩️🌧️🌤️🌈 | storm → rainbow |
| `mood` | 🫠😐😊🤩 | melting → ecstatic |
| `coffee` | 😴☕💪⚡ | tired → wired |
| `rocket` | 🌍🚀🛸⭐ | earth → star |
| `ocean` | 🫧🐠🐬🐋 | ripple → whale |
| `dragon` | 🥚🦎🐉👑 | egg → dragon king |

Each theme maps to four delta thresholds:

| Stage | Delta | Meaning |
|-------|-------|---------|
| level 0 | < −15% | Far behind target |
| level 1 | −15% to −5% | A bit behind |
| level 2 | −5% to +5% | On track |
| level 3 | > +5% | Ahead of target |

```bash
slt theme           # list all themes (current marked with →)
slt theme rocket    # set theme + show stage breakdown
```

Theme is saved to `~/.claude/.statusline-theme` and persists across sessions.

### Time Remaining Format

| Remaining | Format | Example |
|-----------|--------|---------|
| > 48h | whole days | `6d`, `5d`, `3d` |
| 24h – 48h | one decimal place | `1.5d`, `1.2d` |
| 1h – 24h | hours | `18h`, `9h` |
| < 1h | minutes | `45m`, `12m` |

**How it works:** calls `GET https://api.anthropic.com/api/oauth/usage` (same source as `/usage`) every 5 minutes, reads `seven_day.utilization` and `resets_at`, computes `delta = utilization% − elapsed% × 0.95`. Token is read from `~/.claude/.credentials.json` — no extra setup needed.

## Scripts (task runners)

| Script | What it does |
|--------|-------------|
| `run-tasks.sh` | Serial execution with timeout, retry, and rollback |
| `run-tasks-parallel.sh` | Parallel execution using git worktrees |

Both are called by `/batch-tasks` — you don't need to run them directly.

## Automatic Model Selection

The kit optimizes model usage at every level:

| Level | How it works |
|-------|-------------|
| **Session start** | `session-context.sh` injects model guidance — Claude will suggest switching to Opus for complex refactors |
| **Batch tasks** | Each task is assigned haiku/sonnet/opus based on complexity and cost-performance data |
| **Sub-agents** | Haiku for mechanical checks (type-check, tests), Sonnet for reasoning (review, verification) |
| **Staying current** | Run `/model-research --apply` when new models drop to update all selection logic |

Based on benchmarks: Sonnet 4.6 scores 79.6% on SWE-bench vs Opus 4.6's 80.8% at 60% of the cost. The kit defaults to Sonnet and only escalates to Opus when the task genuinely needs it.
