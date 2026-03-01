**English** | [中文](README.zh-CN.md)

[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/shenxingy/claude-code-kit/blob/main/CONTRIBUTING.md) [![good first issue](https://img.shields.io/github/issues/shenxingy/claude-code-kit/good%20first%20issue)](https://github.com/shenxingy/claude-code-kit/labels/good%20first%20issue)

# Claude Code Kit

**Turn Claude Code from a chat assistant into an autonomous coding system.**

One install script. Ten hooks, five agents, fifteen skills, a safety guardian, and a correction learning loop — all working together so Claude codes better, catches its own mistakes, and can run unattended overnight while you sleep.

> If this saves you time, a star helps others find it — and if something breaks, [open an issue](https://github.com/shenxingy/claude-code-kit/issues/new/choose).

## Table of Contents

1. [Install](#install-30-seconds)
2. [Supported Languages](#supported-languages--frameworks)
3. [What Happens After Install](#what-happens-after-install)
4. [Available Commands](#available-commands)
5. [When to Use What](#when-to-use-what)
6. [Documentation](#documentation)
7. [Repo Structure](#repo-structure)
8. [Uninstall](#uninstall)
9. [Contributing](#contributing)
10. [Known Limitations](#known-limitations)
11. [License](#license)

## Install (30 seconds)

```bash
git clone https://github.com/shenxingy/claude-code-kit.git
cd claude-code-kit
./install.sh
```

Start a new Claude Code session to activate everything.

> **Requirements:** `jq` (for settings merge). Everything else is optional.

## Supported Languages & Frameworks

Auto-detection — hooks and agents adapt to your project type:

| Language | Edit check | Task gate | Type checker | Test runner |
|----------|-----------|-----------|-------------|-------------|
| **TypeScript / JavaScript** | `tsc` (monorepo-aware) | type-check + build | tsc | jest / vitest / npm test |
| **Python** | pyright / mypy | ruff + pyright/mypy | pyright / mypy | pytest |
| **Rust** | `cargo check` | cargo check + test | cargo check | cargo test |
| **Go** | `go vet` | go build + vet + test | go vet | go test |
| **Swift / iOS** | `swift build` | swift build / xcodebuild | swift build | swift test / xcodebuild test |
| **Kotlin / Android / Java** | `gradlew compile` | gradle compile + test | gradle compile | gradle test |
| **LaTeX** | `chktex` | chktex (warnings) | chktex | — |

All checks are **opt-in by detection** — if the tool isn't installed or the project marker isn't present, the hook silently skips.

## What Happens After Install

| When | What fires | What it does |
|------|-----------|-------------|
| You open Claude Code in a git repo | `session-context.sh` | Loads git context, recent handoff, correction rules, and model guidance into context |
| Claude tries to run a Bash command | `pre-tool-guardian.sh` | **Blocks** database migrations (they timeout), catastrophic rm -rf, force push to main, SQL DROP |
| Claude edits a code file | `post-edit-check.sh` | Runs language-appropriate checks **async** (tsc, pyright, cargo check, go vet, swift build, gradle, chktex) |
| You correct Claude ("wrong, use X") | `correction-detector.sh` | Logs the correction, prompts Claude to save a reusable rule |
| Claude marks a task as done | `verify-task-completed.sh` | Adaptive quality gate: checks compilation/lint, adds build+test in strict mode |
| Claude needs permission / goes idle | `notify-telegram.sh` | Sends Telegram alert so you don't have to watch the terminal |
| Every prompt you send | `prompt-tracker.sh` | Tracks prompt fingerprints to surface repeated patterns |
| Session ends | Stop hook (in settings.json) | Verifies all tasks were completed before exit |

## Available Commands

| Command | What it does |
|---------|-------------|
| `/handoff` | Save session state to `.claude/handoff-*.md` — enables overnight runs and context relay between agents |
| `/pickup` | Load latest handoff and immediately resume work — zero-friction session restart |
| `/batch-tasks` | Parse TODO.md, auto-plan each task, execute via `claude -p` (serial or parallel) |
| `/batch-tasks step2 step4` | Plan + run specific TODO steps |
| `/batch-tasks --parallel` | Run tasks concurrently via git worktrees |
| `/sync` | Update TODO.md (check off done items) + append session summary to PROGRESS.md |
| `/commit` | Split uncommitted changes into logical commits by module, commit + push by default |
| `/commit --no-push` | Same, but skip push |
| `/commit --dry-run` | Show the split plan only, don't commit |
| `/review` | Comprehensive tech debt review — auto-writes Critical/Warning findings to TODO.md |
| `/loop GOAL_FILE` | Goal-driven autonomous improvement loop — supervisor plans tasks each iteration, workers execute in parallel |
| `/loop --status` | Show current loop state (iteration, convergence, worker results) |
| `/loop --stop` | Stop a running loop |
| `/audit` | Audit `corrections/rules.md` — find rules to promote to CLAUDE.md, remove redundant or contradictory entries |
| `/model-research` | Search web for latest Claude model data, show what changed |
| `/model-research --apply` | Same + update model guide, session context, and batch-tasks configs |
| `/orchestrate` | Switch to orchestrator mode — ask clarifying questions, decompose goal into tasks, write `proposed-tasks.md` (used by the Web UI) |
| `/worktree` | Create and manage git worktrees for parallel Claude Code sessions |
| `/research` | Deep research on a topic — web search, synthesize, save findings to `docs/research/` |
| `/map` | Generate a codebase map — file ownership, module graph, entry points — useful for onboarding new agents |
| `/incident` | Incident response mode — diagnose a production issue, write a postmortem, add follow-up tasks to TODO |
| `/review-pr` | AI reviews a PR diff and posts a structured review comment |
| `/merge-pr` | Squash-merge a PR and clean up the branch |

## When to Use What

**Direct prompts** — for most day-to-day work:
- Bug fixes, small features, refactoring, codebase questions
- Claude auto-detects complexity and enters plan mode when needed
- Tip: be specific. "Add retry with exponential backoff to the API client" > "improve the API client"

**`/batch-tasks`** — when you have a structured TODO list:
- Multi-step implementations broken into discrete tasks
- Use `--parallel` when tasks don't share files
- Well-defined TODO.md entries get high scout scores; vague tasks may be skipped

**`/review`** — before releases or when onboarding to a codebase:
- Finds dead code, type issues, security risks, stale docs
- Critical and Warning findings are automatically written to the `## Tech Debt` section of TODO.md
- Run periodically — tech debt sneaks in fast

**`/handoff`** — when context is getting full (~80%) or before stopping:
- Saves everything about the current session state to `.claude/handoff-{timestamp}.md`
- Includes: what was done, what's pending, git state, exact next steps, gotchas
- Enables the next session (or a fresh overnight agent) to resume without human re-briefing

**`/pickup`** — at the start of a new session:
- Reads the latest handoff file and presents a concise briefing
- Verifies git state matches the handoff
- Immediately starts executing the first Next Step from the handoff — no waiting

**`/sync`** — at the end of every coding session:
- Checks off completed TODO items and captures lessons in PROGRESS.md
- Run `/commit` after to commit everything (docs + code) split by module
- This builds institutional memory — skip it and you'll repeat past mistakes

**`/commit`** — when you're ready to commit:
- Analyzes all uncommitted changes and splits them into logical commits by module
- Pushes by default; use `--no-push` to skip, `--dry-run` to preview the plan

## Documentation

| Guide | Contents |
|-------|----------|
| [Maximize Throughput](docs/throughput.md) | Skip permission prompts, batch task input, parallel worktrees, task queue patterns, terminal + voice setup |
| [Orchestrator Web UI](docs/orchestrator.md) | Chat-to-plan workflow, worker dashboard, settings reference, broadcast, iteration loop |
| [Overnight Autonomous Operation](docs/autonomous-operation.md) | Task queue pattern, parallel sessions, context relay, safety guarantees |
| [How It Works](docs/how-it-works.md) | Hooks, agents, skills internals, correction learning loop, status line, model selection |
| [Configuration & Customization](docs/configuration.md) | Required/optional settings, tuning thresholds, adding hooks/agents/skills |
| [Hooks Research](docs/research/hooks.md) | Hook system deep dive |
| [Model Selection Guide](docs/research/models.md) | Cost-performance analysis and selection rules |
| [Power Users Research](docs/research/power-users.md) | Patterns from top users |

## Repo Structure

```
claude-code-kit/
├── install.sh                         # One-command deployment
├── uninstall.sh                       # Clean removal
├── orchestrator/                      # Web UI for parallel agent orchestration
│   ├── start.sh                       # Launch script (installs deps, opens browser)
│   ├── server.py                      # FastAPI server (PTY orchestrator + worker pool)
│   ├── requirements.txt               # Python deps (fastapi, uvicorn, ptyprocess, watchfiles)
│   └── web/index.html                 # Single-file vanilla JS UI (chat + dashboard)
├── configs/
│   ├── settings-hooks.json            # Hook definitions (merged into settings.json)
│   ├── hooks/
│   │   ├── session-context.sh         # SessionStart: load git context + handoff + corrections
│   │   ├── pre-tool-guardian.sh       # PreToolUse: block migrations/rm-rf/force-push/DROP
│   │   ├── post-edit-check.sh         # PostToolUse: async type-check after edits
│   │   ├── notify-telegram.sh         # Notification: Telegram alerts
│   │   ├── prompt-tracker.sh          # UserPromptSubmit: track prompt fingerprints
│   │   ├── verify-task-completed.sh   # TaskCompleted: adaptive quality gate
│   │   └── correction-detector.sh     # UserPromptSubmit: learn from corrections
│   ├── agents/
│   │   ├── code-reviewer.md           # Sonnet code reviewer with memory
│   │   ├── test-runner.md             # Haiku test runner
│   │   ├── type-checker.md            # Haiku type checker
│   │   └── verify-app.md              # Sonnet app verification
│   ├── skills/
│   │   ├── handoff/                   # /handoff skill — end-of-session context dump
│   │   ├── pickup/                    # /pickup skill — start-of-session context load
│   │   ├── batch-tasks/               # /batch-tasks skill
│   │   ├── sync/                      # /sync skill
│   │   ├── commit/                    # /commit skill
│   │   ├── loop/                      # /loop skill — goal-driven autonomous improvement loop
│   │   ├── audit/                     # /audit skill — corrections/rules.md cleanup
│   │   ├── orchestrate/               # /orchestrate skill — AI orchestrator persona for Web UI
│   │   ├── model-research/            # /model-research skill
│   │   ├── worktree/                  # /worktree skill — git worktree management
│   │   ├── research/                  # /research skill — deep research + docs synthesis
│   │   ├── map/                       # /map skill — codebase ownership/module graph
│   │   ├── incident/                  # /incident skill — incident response + postmortem
│   │   ├── review-pr/                 # /review-pr skill — AI PR review
│   │   └── merge-pr/                  # /merge-pr skill — squash-merge + branch cleanup
│   ├── scripts/
│   │   ├── committer.sh               # Safe commit for parallel agents (no git add .)
│   │   ├── run-tasks.sh               # Serial task runner
│   │   └── run-tasks-parallel.sh      # Parallel runner (git worktrees)
│   └── commands/
│       └── review.md                  # /review tech debt command
├── templates/
│   ├── settings.json                  # settings.json template (no secrets)
│   ├── CLAUDE.md                      # Agent Ground Rules template (auto-deployed to ~/.claude/)
│   ├── README.md                      # Starter README template for new projects
│   └── corrections/
│       ├── rules.md                   # Initial correction rules
│       └── stats.json                 # Initial domain error rates
└── docs/
    ├── throughput.md                  # Maximize throughput guide
    ├── orchestrator.md                # Orchestrator Web UI guide
    ├── autonomous-operation.md        # Overnight autonomous operation guide
    ├── how-it-works.md                # How hooks, agents, skills work
    ├── configuration.md               # Configuration & customization guide
    └── research/
        ├── hooks.md                   # Hook system deep dive
        ├── subagents.md               # Custom agent patterns
        ├── batch-tasks.md             # Batch execution research
        ├── models.md                          # Model comparison & selection guide
        ├── power-users.md                     # Patterns from top Claude Code users
        ├── openclaw-dev-velocity-analysis.md  # steipete velocity analysis
        └── solo-dev-velocity-playbook.md      # Actionable solo dev playbook
```

## Uninstall

```bash
./uninstall.sh
```

Removes all deployed hooks, agents, skills, scripts, and commands. Preserves:
- `~/.claude/corrections/` (your learned rules and history)
- `~/.claude/settings.json` (env vars and permissions — only hooks are removed)
- Skills not managed by this repo

## Contributing

Contributions are welcome — code, docs, issue triage, and bug reports all count. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions, commit format, and architecture overview.

### Known Limitations

These are real rough edges — good candidates for contributions:

1. **Loop skill on non-code tasks** (research/docs) fails silently — workers produce no diff, no commit, loop reports failure with no useful error
2. **GUI loop controls are rough** — use CLI `/loop` for production runs; the web UI loop is better for experimentation
3. **Workers in worktrees inherit parent environment** — project-specific env vars (DB URLs, API keys) leak into worker shells; sanitize your env before overnight runs
4. **Context budget tracking is per-session** — multi-day overnight runs may exhaust context without a restart; use `/handoff` + `/pickup` for long tasks

## License

[MIT](LICENSE)
