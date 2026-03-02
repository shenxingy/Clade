# Claude Code Kit — Project Context

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
config.py          ← leaf: constants, settings, utilities
    ↑
github_sync.py     ← gh CLI wrappers (issues, push, sync)
task_queue.py      ← SQLite-backed task CRUD
    ↑
worker.py          ← WorkerPool, SwarmManager, scoring, oracle
session.py         ← ProjectSession, registry, status_loop
    ↑
server.py          ← FastAPI app, all REST routes, WebSocket
routes/webhooks.py ← GitHub webhook handler (included by server.py)
```

### Key File Map
| File | Purpose |
|------|---------|
| `config.py` | `GLOBAL_SETTINGS`, `_ALLOWED_TASK_COLS`, model aliases, cost utils |
| `task_queue.py` | SQLite CRUD for tasks, loops, messages, interventions |
| `worker.py` | `WorkerPool`, `SwarmManager`, `_score_task`, `_write_pr_review` |
| `session.py` | `ProjectSession`, `SessionRegistry`, `status_loop()` |
| `server.py` | FastAPI app, all REST + WebSocket routes |
| `github_sync.py` | GitHub issue create/update/pull/push via `gh` CLI |
| `web/index.html` | Single-page UI shell (served at `/web/index.html`) |
| `web/app-core.js` | Core state, WebSocket, worker card rendering |
| `web/app-dashboard.js` | Dashboard widgets, session overview |
| `web/app-loop.js` | Loop control, convergence sparklines |
| `web/app-viewers.js` | Log viewer, task detail panels |

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
