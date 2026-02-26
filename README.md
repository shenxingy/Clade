**English** | [中文](README.zh-CN.md)

[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/shenxingy/claude-code-kit/blob/main/CONTRIBUTING.md) [![good first issue](https://img.shields.io/github/issues/shenxingy/claude-code-kit/good%20first%20issue)](https://github.com/shenxingy/claude-code-kit/labels/good%20first%20issue)

# Claude Code Kit

**Turn Claude Code from a chat assistant into an autonomous coding system.**

One install script. Nine hooks, five agents, nine skills, a safety guardian, and a correction learning loop — all working together so Claude codes better, catches its own mistakes, and can run unattended overnight while you sleep.

> If this saves you time, a star helps others find it — and if something breaks, [open an issue](https://github.com/shenxingy/claude-code-kit/issues/new/choose).

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

## Maximize Throughput

The bottleneck for Claude Code is not code generation — it's **how fast you input tasks**. These setups eliminate the friction.

### 1. Skip permission prompts

```bash
# Add to ~/.zshrc or ~/.bashrc
alias cc='claude --dangerously-skip-permissions'
```

With this alias, Claude runs fully autonomously — no approval dialogs, no interruptions. Use `cc` instead of `claude`. Always commit before starting a session (git is your rollback).

### 2. Batch your task input (the core habit)

Write all tasks upfront, then launch agents simultaneously:

```bash
mkdir -p .claude/tasks

# Good task file: specific files, patterns to follow, edge cases to handle
cat > .claude/tasks/task-001.md << 'EOF'
Add rate limiting to all /api/auth/* routes.
Use the existing rateLimiter in lib/middleware.ts.
Set 10 req/min for POST /auth/login, 60/min for GET endpoints.
Return 429 with {"error": "rate_limit_exceeded", "retry_after": N} on breach.
EOF

cat > .claude/tasks/task-002.md << 'EOF'
Write E2E tests for the checkout flow in tests/e2e/checkout.spec.ts.
Follow the pattern in tests/e2e/cart.spec.ts.
Cover: add to cart, apply coupon, checkout success, payment failure (card_declined).
EOF

# Launch agents — one per terminal, fully autonomous
cc -p "$(cat .claude/tasks/task-001.md)"   # Terminal 1 (non-interactive)
cc -p "$(cat .claude/tasks/task-002.md)"   # Terminal 2 (non-interactive)

# Or run interactively if you want to watch/guide:
cc   # Terminal 3 → paste task content
```

> **What makes a good task file:** Name the exact files to edit/create. Reference existing patterns to follow (`"follow the pattern in X"`). Specify edge cases and error formats. Vague tasks ("improve the auth flow") get vague results.

Your thinking decouples from execution — design all tasks in one burst, let agents execute while you do other things.

### 3. Run parallel agents with worktrees

Use `/worktree` to create isolated git worktrees so multiple agents work the same repo without conflicts:

```
/worktree create feat/auth-rework    # Terminal 1
/worktree create feat/rate-limiting  # Terminal 2
```

Each agent works in its own directory. `committer` prevents staging conflicts. Merge when done.

### 4. Task queue — sequential tasks, one shot

Claude processes messages in order — send all tasks at once and go do something else:

```
1. Fix the null pointer in UserService.getUserById()
2. Add input validation to all POST endpoints
3. Update the API docs in README.md
```

No waiting required. You're free from the moment you send.

### 5. Orchestrator Web UI — chat to plan, watch workers execute

The fastest way to go from idea to parallel execution. One chat session with an AI orchestrator decomposes your goal into tasks; a dashboard shows N workers executing them simultaneously.

```bash
./orchestrator/start.sh
# → Opens http://localhost:8765 in your browser
```

**Workflow:**

```
1. Chat: "Build a SaaS with auth, billing, analytics"
   → Orchestrator asks 2-3 clarifying questions (stack, constraints, existing code)
   → You answer (type or use OS voice input)

2. Orchestrator proposes task breakdown
   → Writes .claude/proposed-tasks.md
   → UI shows confirmation overlay: "4 tasks ready. Start all?"

3. Click "Start All Workers"
   → Workers launch in parallel: claude -p "$(cat task.md)" --dangerously-skip-permissions
   → Dashboard updates every 1s: status, last commit, elapsed time

4. Monitor:
   Worker 1 │ running  │ feat: add NextAuth config    │ 2m34s │ [Pause] [Chat]
   Worker 2 │ running  │ feat: create Stripe webhook  │ 1m12s │ [Pause] [Chat]
   Worker 3 │ blocked  │ needs Stripe API key         │ 0m45s │        [Chat]

5. Worker 3 blocked → click [Chat] → type "Use sk_test_xxx"
   → Worker stops, message injected as context, worker restarts

6. All done: progress bar 100%, review with: git log --oneline
```

**Layout:**

```
┌─────────────────────────────────┬──────────────────────────────┐
│  Orchestrator Chat (PTY)        │  Task Queue                  │
│                                 │  ├ pending: Implement auth   │
│  > Build a SaaS with auth...    │  ├ pending: Add Stripe       │
│  < What tech stack?             │  └ [Run] [Delete] [+ Add]    │
│  > Next.js, Prisma, Stripe      ├──────────────────────────────┤
│  < Writing 4 tasks...           │  Workers                     │
│                                 │  ┌──────────────────────────┐│
│  ┌─ 4 tasks ready ──────────┐   │  │ running │ feat: auth...  ││
│  │ Start All Workers? [Yes] │   │  │ 2m34s   │ [Pause][Chat]  ││
│  └──────────────────────────┘   │  └──────────────────────────┘│
│  [Type message... ]   [Send]    │  ████░░░░░ 35%  ETA ~8 min   │
└─────────────────────────────────┴──────────────────────────────┘
```

**No build step.** Single HTML file + FastAPI backend. Requires Python 3.9+.

#### GUI Settings Reference

Open the **⚙ Settings** panel (top-right of the Web UI) to configure:

| Setting | Default | Effect |
|---------|---------|--------|
| Auto-start workers | ON | Workers launch immediately when `proposed-tasks.md` is written |
| Auto-push | ON | Push to feature branch after each commit |
| Auto-merge | ON | Squash-merge `orchestrator/task-*` PRs automatically |
| Auto-review | ON | Post AI code review comment on each PR |
| **Oracle validation** | OFF | Haiku independently reviews each diff before push — catches "completed but wrong" silently; rejects bad pushes |
| **Auto model routing** | OFF | Picks model by scout score: score ≥80 → haiku, 50-79 → sonnet, <50 → sonnet + ask-first warning |
| **Context budget warnings** | ON | Token bar on every worker card (green → amber at 120K → red at 160K); writes `.claude/context-warning-{id}.md` with `/compact` instructions |
| **AGENTS.md → Generate** | — | Builds file→branch ownership map from `git log`; copy output to `.claude/AGENTS.md` to prevent cross-worker collisions |

#### Broadcast to All Workers

When all running workers need the same correction mid-run, use the **→ All Workers** bar visible at the top of the workers section in Execute mode:

```
Example: "The DB schema changed — column is now user_id not userId"
→ All running workers stop, receive the message as prepended context, and restart
```

Useful when you realize a global constraint changed and every worker needs to know.

#### Iteration Loop (Autonomous Refinement)

Closes the review → fix → verify feedback loop for any iterative artifact (papers, code audits, content QA).

```
1. Execute mode → Loop section
2. Enter: artifact path = paper.tex  (or server.py, README.md, etc.)
           codebase dir = ./src       (optional, for DATA_CHECK workers)
           K = 2, N = 3               (converge when ≤2 changes for 3 consecutive iters)

3. ▶ Start Loop — the supervisor:
     FIXABLE   → spawns a worker to fix it automatically
     DATA_CHECK → spawns a read-only worker to verify a claim against your codebase
     DEFERRED  → adds to the accordion below (requires human review — never auto-fixed)
     CONVERGED → loop ends, toast fires

4. After all workers finish → count changes → check convergence → repeat
5. Converged? Review deferred items in the accordion.
```

The loop runs fully unattended. Set `max_iterations` in Settings as a safety cap.

---

## Overnight Autonomous Operation

The kit is designed to run unattended — you sleep, agents work.

### Pattern: Task Queue → Sleep → Review

```bash
# 1. Write task files for what you want done
cat > tasks.txt << 'EOF'
===TASK===
model: sonnet
timeout: 600
retries: 2
---
Implement the user settings page at app/settings/page.tsx.
Follow the pattern in app/profile/page.tsx. Use the existing
useUser hook and the settingsSchema from lib/schema.ts.
===TASK===
model: sonnet
timeout: 600
retries: 2
---
Add rate limiting middleware to all /api/auth/* routes.
Use the existing rateLimiter in lib/middleware.ts. Set 10 req/min.
EOF

# 2. Queue and run
claude  # open session
/batch-tasks --run tasks.txt  # starts in background, you can close the terminal

# 3. You get Telegram notifications when blocked or done
# 4. Next morning: /pickup to see what was done, review commits
```

### Pattern: Parallel Sessions (3-4x throughput)

```bash
# Terminal 1 — feature A
git worktree add ../proj-feat-a -b feat/settings-page
cd ../proj-feat-a && claude
# → assign task A, /handoff when done

# Terminal 2 — feature B (independent)
git worktree add ../proj-feat-b -b feat/rate-limiting
cd ../proj-feat-b && claude
# → assign task B, /handoff when done

# Review both in main branch, merge PRs
```

### Pattern: Context Relay (long tasks across sessions)

```bash
# Session 1 (context getting full at ~80%)
/handoff  # saves state to .claude/handoff-2026-02-23-14-30.md
# close session

# Session 2 (fresh context)
/pickup   # reads handoff, immediately resumes next step
```

The `pre-tool-guardian.sh` hook protects unattended runs: database migrations, catastrophic `rm -rf`, force pushes to main, and SQL DROP statements are automatically blocked and redirected to manual execution — so agents can't irreversibly destroy state while you sleep.

---

## How It Works

### Hooks (automatic behaviors)

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

All hooks are shell scripts — zero API cost, sub-second execution.

**`post-tool-use-lint.sh`** runs your project's `verify_cmd` after every file edit. On failure it writes `.claude/lint-feedback.md` and exits with code 2 — Claude sees the error output and fixes it in the next turn. Configure via `.claude/orchestrator.json`:

```json
{
  "verify_cmd": "python3 -m py_compile src/main.py"
}
```

Common values: `"tsc --noEmit"` (TypeScript), `"python3 -m py_compile <file>"` (Python), `"cargo check"` (Rust), `"go build ./..."` (Go). Leave unset to disable.

### Agents (specialized sub-agents)

| Agent | Model | Use case |
|-------|-------|----------|
| `code-reviewer` | Sonnet | Code review with persistent memory |
| `paper-reviewer` | Sonnet | Academic paper review — structured critique for LaTeX papers before submission |
| `verify-app` | Sonnet | Runtime verification — adapts to project type (web, Rust, Go, Swift, Gradle, LaTeX) |
| `type-checker` | Haiku | Fast type/compilation check — auto-detects language (TS, Python, Rust, Go, Swift, Kotlin, LaTeX) |
| `test-runner` | Haiku | Test execution — auto-detects framework (pytest, jest, cargo test, go test, swift test, gradle, make) |

Claude auto-selects agents. Haiku agents are fast and cheap for mechanical checks; Sonnet agents reason deeper for reviews.

### Skills (slash commands)

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
| **Staying current** | Run `/model-research --apply` when new models drop to update all selection logic |

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
│   │   └── model-research/            # /model-research skill
│   ├── scripts/
│   │   ├── committer.sh               # Safe commit for parallel agents (no git add .)
│   │   ├── run-tasks.sh               # Serial task runner
│   │   └── run-tasks-parallel.sh      # Parallel runner (git worktrees)
│   └── commands/
│       └── review.md                  # /review tech debt command
├── templates/
│   ├── settings.json                  # settings.json template (no secrets)
│   ├── CLAUDE.md                      # Agent Ground Rules template (auto-deployed to ~/.claude/)
│   └── corrections/
│       ├── rules.md                   # Initial correction rules
│       └── stats.json                 # Initial domain error rates
└── docs/
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

## Learn More

- [Hooks Research](docs/research/hooks.md) — Hook system deep dive
- [Subagents Research](docs/research/subagents.md) — Custom agent patterns
- [Batch Tasks Research](docs/research/batch-tasks.md) — Batch execution improvements
- [Model Selection Guide](docs/research/models.md) — Cost-performance analysis and selection rules
- [Power Users Research](docs/research/power-users.md) — Patterns from top users

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
