# Claude Code Kit — Project Context

## Project Type
- Type: cli + skill-system
- Frontend: N/A (orchestrator has vanilla JS UI but not the primary interface)
- Backend: FastAPI (orchestrator/, port 8000) — optional, CLI layer works standalone
- Test command: cd orchestrator && .venv/bin/python -m pytest tests/ -v
- Verify command: cd orchestrator && python -m py_compile server.py session.py task_queue.py worker.py worker_tldr.py worker_review.py routes/tasks.py routes/workers.py

## Features (Behavior Anchors)
- install.sh: running `./install.sh` copies skills/hooks/scripts/keybindings to ~/.claude/ without errors
- slt: running `slt` cycles the statusline mode (symbol → percent → number → off)
- /commit: analyzes uncommitted changes, splits into logical commits by module, pushes by default
- /loop: given a goal file, runs supervisor+worker iterations until converged or max-iter
- committer: `committer "type: msg" file1 file2` stages only named files and commits
- loop-runner.sh: runs background loop — supervisor plans tasks, workers execute in parallel via worktrees

## What This Project Is

A two-layer automation toolkit on top of Claude Code CLI:

- **CLI layer** (`configs/`) — skills, hooks, scripts installed via `./install.sh`
- **Orchestrator layer** (`orchestrator/`) — FastAPI web server with worker pool, task queue, GitHub sync, iteration loops

## Key Commands

```bash
# Install CLI layer (skills, hooks, keybindings)
./install.sh

# slt — statusline-toggle (quota pace indicator). See /slt skill.

# Start orchestrator (from project root or orchestrator dir)
cd orchestrator && uvicorn server:app --reload

# Run tests
cd orchestrator && .venv/bin/python -m pytest tests/ -v

# Syntax check
cd orchestrator && python -m py_compile server.py session.py task_queue.py worker.py
```

## Architecture — Two Layers

### CLI Layer (`configs/`)
- `skills/` — skill prompts invoked via `/skill-name` in Claude Code
- `hooks/` — pre/post hooks for Claude Code events
- `scripts/` — shell utilities (e.g., `committer.sh`)
- `keybindings.json` — Claude Code keyboard shortcuts

### Orchestrator Layer (`orchestrator/`)
Key modules (import DAG — leaf → root):

```
config.py            ← leaf: constants, settings, utilities
    ↑
github_sync.py       ← gh CLI wrappers (issues, push, sync)
task_queue.py        ← SQLite-backed task CRUD
worker_tldr.py       ← TLDR generation + scoring (leaf, no project imports)
worker_review.py     ← oracle + PR review (leaf, no project imports)
    ↑
worker.py            ← WorkerPool, SwarmManager
session.py           ← ProjectSession, registry, status_loop
    ↑
server.py            ← FastAPI app, remaining routes, router mounts
routes/tasks.py      ← Task CRUD + bulk-action routes
routes/workers.py    ← Worker control + inspection routes
routes/webhooks.py   ← GitHub webhook handler
```

### Key File Map
| File | Purpose |
|------|---------|
| `config.py` | `GLOBAL_SETTINGS`, `_ALLOWED_TASK_COLS`, model aliases, cost utils |
| `task_queue.py` | SQLite CRUD for tasks, loops, messages, interventions |
| `worker.py` | `WorkerPool`, `SwarmManager`, core execution engine |
| `worker_tldr.py` | `_generate_code_tldr`, `_score_task` — TLDR + scoring (leaf) |
| `worker_review.py` | `_write_pr_review`, `_oracle_review`, `_write_progress_entry` (leaf) |
| `session.py` | `ProjectSession`, `SessionRegistry`, `status_loop()` |
| `server.py` | FastAPI app, session/loop/swarm/usage/settings routes, WebSocket |
| `github_sync.py` | GitHub issue create/update/pull/push via `gh` CLI |
| `ideas.py` | `IdeasManager` — async idea CRUD, AI evaluation, promotion |
| `process_manager.py` | `ProcessPool`, `StartProcess` — start.sh lifecycle control |
| `routes/tasks.py` | Task CRUD + bulk-action routes (13 handlers) |
| `routes/workers.py` | Worker control + inspection routes (9 handlers) |
| `routes/ideas.py` | Ideas API routes (CRUD, evaluate, execute, promote) |
| `web/index.html` | Single-page UI shell (served at `/web/index.html`) |
| `web/app-core.js` | Core state, WebSocket, session tabs, settings |
| `web/app-dashboard.js` | Tasks, workers, process cards, queue management |
| `web/app-viewers.js` | Log viewer, usage bar, history, GitHub sync, portfolio |
| `web/app-ideas.js` | Ideas inbox UI, evaluation cards, execute/promote actions |

## Settings

Global settings stored at `~/.claude/orchestrator-settings.json`. Defaults defined in `config.py:_SETTINGS_DEFAULTS`. To add a new setting: add to `_SETTINGS_DEFAULTS`, NOT task_queue.py.

## DB Migrations

Add try/except `ALTER TABLE` blocks in `task_queue.py:TaskQueue._ensure_db()`. New columns added to `_ALLOWED_TASK_COLS` in `config.py`.

## Commits

```bash
# Always use committer script — NEVER git add .
committer "type: message" file1 file2 file3
```

Conventional commit types: `feat` / `fix` / `refactor` / `test` / `chore` / `docs` / `perf`

## Code Rules

- Keep all files < 1500 lines (Read tool default = 2000 lines)
- No circular imports — module deps must form a strict DAG
- Settings → `config.py:_SETTINGS_DEFAULTS` only
- DB migrations → try/except ALTER TABLE in `_ensure_db()`
- Never return `error.message` in 500 responses
