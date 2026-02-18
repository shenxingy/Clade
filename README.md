**English** | [中文](README.zh-CN.md)

# Claude Code Kit

**Turn Claude Code from a chat assistant into an autonomous coding system.**

One install script. Five hooks, four agents, two skills, and a correction learning loop — all working together so Claude codes better, catches its own mistakes, and remembers your preferences across sessions.

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
| You open Claude Code in a git repo | `session-context.sh` | Loads git context, correction rules, and model selection guidance into context |
| Claude edits a code file | `post-edit-check.sh` | Runs language-appropriate checks **async** (tsc, pyright, cargo check, go vet, swift build, gradle, chktex) |
| You correct Claude ("wrong, use X") | `correction-detector.sh` | Logs the correction, prompts Claude to save a reusable rule |
| Claude marks a task as done | `verify-task-completed.sh` | Adaptive quality gate: checks compilation/lint, adds build+test in strict mode |
| Claude needs permission / goes idle | `notify-telegram.sh` | Sends Telegram alert so you don't have to watch the terminal |
| Session ends | Stop hook (in settings.json) | Verifies all tasks were completed before exit |

## Available Commands

| Command | What it does |
|---------|-------------|
| `/batch-tasks` | Parse TODO.md, auto-plan each task, execute via `claude -p` (serial or parallel) |
| `/batch-tasks step2 step4` | Plan + run specific TODO steps |
| `/batch-tasks --parallel` | Run tasks concurrently via git worktrees |
| `/sync` | Update TODO.md (check off done items) + append session summary to PROGRESS.md |
| `/sync --commit` | Same + commit the doc changes |
| `/review` | Comprehensive tech debt review of the current project |

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
- Run periodically — tech debt sneaks in fast

**`/sync`** — at the end of every coding session:
- Checks off completed TODO items and captures lessons in PROGRESS.md
- `--commit` bundles doc updates into a git commit
- This builds institutional memory — skip it and you'll repeat past mistakes

## How It Works

### Hooks (automatic behaviors)

| Hook | Trigger | Model cost |
|------|---------|-----------|
| `session-context.sh` | SessionStart | None (shell only) |
| `post-edit-check.sh` | PostToolUse (Edit/Write) | None (shell only) |
| `correction-detector.sh` | UserPromptSubmit | None (shell only) |
| `verify-task-completed.sh` | TaskCompleted | None (shell only) |
| `notify-telegram.sh` | Notification | None (shell only) |

All hooks are shell scripts — zero API cost, sub-second execution.

### Agents (specialized sub-agents)

| Agent | Model | Use case |
|-------|-------|----------|
| `code-reviewer` | Sonnet | Code review with persistent memory |
| `verify-app` | Sonnet | Runtime verification — adapts to project type (web, Rust, Go, Swift, Gradle, LaTeX) |
| `type-checker` | Haiku | Fast type/compilation check — auto-detects language (TS, Python, Rust, Go, Swift, Kotlin, LaTeX) |
| `test-runner` | Haiku | Test execution — auto-detects framework (pytest, jest, cargo test, go test, swift test, gradle, make) |

Claude auto-selects agents. Haiku agents are fast and cheap for mechanical checks; Sonnet agents reason deeper for reviews.

### Skills (slash commands)

**`/batch-tasks`** reads TODO.md, researches the codebase, generates detailed plans for each task, scores them on readiness (scout scoring), assigns the optimal model per task (haiku for mechanical, sonnet for standard, opus for complex), then executes via `claude -p`. Supports serial and parallel (git worktree) execution.

**`/sync`** reviews recent git history, checks off completed TODO items, appends a session summary to PROGRESS.md, and optionally commits.

### Correction Learning Loop

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

### Scripts (task runners)

| Script | What it does |
|--------|-------------|
| `run-tasks.sh` | Serial execution with timeout, retry, and rollback |
| `run-tasks-parallel.sh` | Parallel execution using git worktrees |

Both are called by `/batch-tasks` — you don't need to run them directly.

### Automatic Model Selection

The kit optimizes model usage at every level:

| Level | How it works |
|-------|-------------|
| **Session start** | `session-context.sh` injects model guidance — Claude will suggest switching to Opus for complex refactors |
| **Batch tasks** | Each task is assigned haiku/sonnet/opus based on complexity and cost-performance data |
| **Sub-agents** | Haiku for mechanical checks (type-check, tests), Sonnet for reasoning (review, verification) |

Based on benchmarks: Sonnet 4.6 scores 79.6% on SWE-bench vs Opus 4.6's 80.8% at 60% of the cost. The kit defaults to Sonnet and only escalates to Opus when the task genuinely needs it.

## Configuration

### Required

Nothing. Everything works out of the box with sensible defaults.

### Optional

Set these in `~/.claude/settings.json` under `"env"`:

| Variable | Purpose |
|----------|---------|
| `TG_BOT_TOKEN` | Telegram bot token for notifications |
| `TG_CHAT_ID` | Telegram chat ID for notifications |

### Tuning

| File | What to tune |
|------|-------------|
| `~/.claude/corrections/rules.md` | Add/edit correction rules directly |
| `~/.claude/corrections/stats.json` | Adjust error rates per domain (0-1) to control quality gate strictness |

## Customization

### Add a correction rule manually

Edit `~/.claude/corrections/rules.md`:
```
- [2026-02-17] imports: Use @/ path aliases instead of relative paths
- [2026-02-17] naming: Use camelCase for TypeScript variables, not snake_case
```

### Adjust quality gate thresholds

Edit `~/.claude/corrections/stats.json`:
```json
{
  "frontend": 0.4,
  "backend": 0.05,
  "ml": 0.2,
  "ios": 0,
  "android": 0,
  "systems": 0,
  "academic": 0,
  "schema": 0.2
}
```

`> 0.3` triggers strict mode (adds build + test checks). `< 0.1` triggers relaxed mode (basic checks only). Domains: `frontend`, `backend`, `ml`, `ios`, `android`, `systems` (Rust/Go), `academic` (LaTeX), `schema`.

### Add a new hook

1. Create `configs/hooks/your-hook.sh`
2. Add the hook definition to `configs/settings-hooks.json`
3. Run `./install.sh`

### Add a new agent

1. Create `configs/agents/your-agent.md` with frontmatter (name, description, tools, model)
2. Run `./install.sh`

### Add a new skill

1. Create `configs/skills/your-skill/SKILL.md` (frontmatter + description)
2. Create `configs/skills/your-skill/prompt.md` (full skill prompt)
3. Run `./install.sh`

## Repo Structure

```
claude-code-kit/
├── install.sh                         # One-command deployment
├── uninstall.sh                       # Clean removal
├── configs/
│   ├── settings-hooks.json            # Hook definitions (merged into settings.json)
│   ├── hooks/
│   │   ├── session-context.sh         # SessionStart: load git context + corrections
│   │   ├── post-edit-check.sh         # PostToolUse: async type-check after edits
│   │   ├── notify-telegram.sh         # Notification: Telegram alerts
│   │   ├── verify-task-completed.sh   # TaskCompleted: adaptive quality gate
│   │   └── correction-detector.sh     # UserPromptSubmit: learn from corrections
│   ├── agents/
│   │   ├── code-reviewer.md           # Sonnet code reviewer with memory
│   │   ├── test-runner.md             # Haiku test runner
│   │   ├── type-checker.md            # Haiku type checker
│   │   └── verify-app.md              # Sonnet app verification
│   ├── skills/
│   │   ├── batch-tasks/               # /batch-tasks skill
│   │   │   ├── SKILL.md
│   │   │   └── prompt.md
│   │   └── sync/                      # /sync skill
│   │       ├── SKILL.md
│   │       └── prompt.md
│   ├── scripts/
│   │   ├── run-tasks.sh               # Serial task runner
│   │   └── run-tasks-parallel.sh      # Parallel runner (git worktrees)
│   └── commands/
│       └── review.md                  # /review tech debt command
├── templates/
│   ├── settings.json                  # settings.json template (no secrets)
│   └── corrections/
│       ├── rules.md                   # Initial correction rules
│       └── stats.json                 # Initial domain error rates
└── docs/
    └── research/
        ├── hooks.md                   # Hook system deep dive
        ├── subagents.md               # Custom agent patterns
        ├── batch-tasks.md             # Batch execution research
        ├── models.md                  # Model comparison & selection guide
        └── power-users.md             # Patterns from top Claude Code users
```

## Uninstall

```bash
./uninstall.sh
```

Removes all deployed hooks, agents, skills, scripts, and commands. Preserves:
- `~/.claude/corrections/` (your learned rules and history)
- `~/.claude/settings.json` (env vars and permissions — only hooks are removed)
- Skills not managed by this repo

## Learn More

- [Hooks Research](docs/research/hooks.md) — Hook system deep dive
- [Subagents Research](docs/research/subagents.md) — Custom agent patterns
- [Batch Tasks Research](docs/research/batch-tasks.md) — Batch execution improvements
- [Model Selection Guide](docs/research/models.md) — Cost-performance analysis and selection rules
- [Power Users Research](docs/research/power-users.md) — Patterns from top users

## License

[MIT](LICENSE)
