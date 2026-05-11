# Clade — Project Context

## Project Type
- Type: cli + skill-system
- Frontend: N/A (orchestrator has vanilla JS UI but not the primary interface)
- Backend: FastAPI (orchestrator/, port 8000) — optional, CLI layer works standalone
- Test command: cd orchestrator && .venv/bin/python -m pytest tests/ -v
- Verify command: cd orchestrator && python -m py_compile server.py session.py session_tree.py task_queue.py worker.py swarm.py worker_tldr.py worker_review.py worker_utils.py worker_hydrate.py condensers.py config.py github_sync.py ideas.py process_manager.py event_stream.py tracing.py reactions.py routes/tasks.py routes/workers.py routes/webhooks.py routes/ideas.py routes/process.py

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

# Syntax check (all Python modules)
cd orchestrator && python -m py_compile server.py session.py session_tree.py task_queue.py worker.py swarm.py worker_tldr.py worker_review.py worker_utils.py worker_hydrate.py condensers.py config.py github_sync.py ideas.py process_manager.py event_stream.py tracing.py reactions.py usage_tracker.py routes/tasks.py routes/workers.py routes/webhooks.py routes/ideas.py routes/process.py routes/usage.py

# Multi-machine usage tracking — see orchestrator/usage_tracker.py
#   Hub:  start orchestrator normally, optionally set usage_ingest_token in ~/.claude/orchestrator-settings.json
#   Node (no orchestrator): python3 configs/scripts/usage-agent.py --hub http://hub:8000 [--token X] [--once]
#   Dashboard: http://hub:8000/web/usage.html
# Per-machine ccusage data is stored in ~/.claude/orchestrator/usage.db.

# MCP Server — exposes skills as MCP tools for EXTERNAL AI coding tools (Cursor, Cline, etc.)
# Inside Claude Code, skills are already native (/blog-write, /commit) — no MCP needed.
# Config lives at mcp/clade.mcp.json (NOT .mcp.json at repo root — that auto-spawned in CC and
# duplicated every skill, overflowing the system prompt). External clients should point at
# orchestrator/mcp_server.py directly. See mcp/README.md.
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
ideas.py             ← leaf: IdeasManager, async idea CRUD (no project imports)
process_manager.py   ← leaf: ProcessPool, start.sh lifecycle (no project imports)
worker_tldr.py       ← leaf: TLDR generation + scoring (no project imports)
worker_review.py     ← leaf: oracle + PR review (no project imports)
    ↑
github_sync.py       ← gh CLI wrappers (issues, push, sync)
task_queue.py        ← SQLite-backed task CRUD
    ↑
worker.py            ← WorkerPool, SwarmManager
session.py           ← ProjectSession, registry, status_loop
    ↑
server.py            ← FastAPI app, remaining routes, router mounts
mcp_server.py        ← MCP server exposing skills as MCP tools (stdio transport)
routes/tasks.py      ← Task CRUD + bulk-action routes
routes/workers.py    ← Worker control + inspection routes
routes/webhooks.py   ← GitHub webhook handler
routes/ideas.py      ← Ideas API routes (CRUD, evaluate, execute, promote)
routes/process.py    ← Process manager API routes
```

```
config.py            ← leaf: constants, settings, utilities
ideas.py             ← leaf: IdeasManager, async idea CRUD (no project imports)
process_manager.py   ← leaf: ProcessPool, start.sh lifecycle (no project imports)
worker_tldr.py       ← leaf: TLDR generation + scoring (no project imports)
worker_review.py     ← leaf: oracle + PR review (no project imports)
    ↑
github_sync.py       ← gh CLI wrappers (issues, push, sync)
task_queue.py        ← SQLite-backed task CRUD
    ↑
worker.py            ← WorkerPool, SwarmManager
session.py           ← ProjectSession, registry, status_loop
    ↑
server.py            ← FastAPI app, remaining routes, router mounts
routes/tasks.py      ← Task CRUD + bulk-action routes
routes/workers.py    ← Worker control + inspection routes
routes/webhooks.py   ← GitHub webhook handler
routes/ideas.py      ← Ideas API routes (CRUD, evaluate, execute, promote)
routes/process.py    ← Process manager API routes
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

## CI (GitHub Actions)

Before committing, ensure CI will pass by running locally:
```bash
# 1. Python syntax check (all modules)
cd orchestrator && python -m py_compile server.py session.py session_tree.py task_queue.py worker.py swarm.py worker_tldr.py worker_review.py worker_utils.py worker_hydrate.py condensers.py config.py github_sync.py ideas.py process_manager.py event_stream.py tracing.py reactions.py routes/tasks.py routes/workers.py routes/webhooks.py routes/ideas.py routes/process.py

# 2. Tests
cd orchestrator && .venv/bin/python -m pytest tests/ -v

# 3. Shell syntax check
bash -n configs/hooks/*.sh configs/scripts/*.sh install.sh
```

CI runs 3 jobs on push/PR to main: `syntax-check`, `pytest`, `shell-tests`.

## Code Rules

- Keep all files < 1500 lines (Read tool default = 2000 lines)
- No circular imports — module deps must form a strict DAG
- Settings → `config.py:_SETTINGS_DEFAULTS` only
- DB migrations → try/except ALTER TABLE in `_ensure_db()`
- Never return `error.message` in 500 responses

## Auto-Promoted Rules
<!-- Promoted from .claude/corrections/rules.md via /audit. Each rule lists its original recording date. -->

- **Explain mechanisms when summarizing** `[auto-promoted 2026-04-15 from 2026-03-30 summary-vs-explanation]`: When wrapping up a completed task, explain where the feature lives, how it's triggered, and what it produces — not just bullet-point outcomes. The user needs the "how" to trust and actually use the feature.

- **Processing external research into Clade** `[auto-promoted 2026-04-15 from 2026-03-31 research cluster × 5]`: When evaluating research on other tools/patterns (landscape docs, competitor analysis), don't mark anything `needs_work` without first: (1) verifying Clade's existing approach is demonstrably *deficient*, not just *different*; (2) comparing actual capabilities, not names (Ralph ≈ /loop — same supervisor-loop pattern, not a gap); (3) confirming the pattern applies to Clade's single-tool scope (Universal Hook Injection targets multi-tool orchestration — N/A here); (4) checking mechanism equivalence before claiming parity (`session-context.sh` ≠ Pi's `before_agent_start` hook — one is a shell script, the other fires between user message and agent `prompt()`). Once a gap IS confirmed, immediately modify code and verify — "plan changes" means "modify code, then verify", not "write TODO".

- **SVG → PNG export** `[auto-promoted 2026-04-15 from 2026-04-01 svg-rendering]`: Use `rsvg-convert`, not ImageMagick — ImageMagick mangles gradients, filters, and low-opacity elements. Also: strip unused `<defs>`, use Linux-available fonts (Helvetica/Arial, not `-apple-system`), and keep opacity ≥ 0.15 for visibility.

- **Domain-specific diagram conventions** `[auto-promoted 2026-04-15 from 2026-04-01 svg-diagram-accuracy]`: Before drawing a domain-specific diagram (cladogram, flowchart, architecture), research the type's established visual conventions. A cladogram uses right-angle bifurcating branches (horizontal + vertical lines), NOT radial/diagonal lines from a center point. Match the established visual language of the diagram type.
- [2026-04-11] config-tracking (deploy-gap): When adding a new ~/.claude/ config file, immediately check if configs/ tracks it and install.sh deploys it — not end with "want me to add it?". Should have run `diff ~/.claude/CLAUDE.md configs/CLAUDE.md` before asking. [auto-promoted 2026-05-11]
- [2026-04-12] github-discussions-api (deploy-gap): Check if a repo has bot-enforced template requirements before using GraphQL API to create discussions — not try API first and let it fail. Should have read the repo's CONTRIBUTING or checked for discussion templates before calling createDiscussion mutation. [auto-promoted 2026-05-11]
- [2026-04-12] prompt-hook-verbosity (settings-disconnect): Always add statusMessage to type:prompt hooks — without it Claude Code displays the full prompt text in the UI, blocking content. Should have noticed the missing statusMessage when writing the hook. [auto-promoted 2026-05-11]
- [2026-04-15] stop-hook-scope (edge-case): Stop-hook cleanliness checks must be session-scoped (baseline at SessionStart, diff at Stop), not repo-global — parallel CC sessions on the same repo cause deadlock when one session's dirt blocks another session's stop. Always pair a blocking Stop hook with an `stop_hook_active`+attempt-counter circuit breaker to escape LLM loops. [auto-promoted 2026-05-11]
- [2026-04-19] stop-hook-ack-loop (async-race): When a Stop hook blocks awaiting user input and the user hasn't replied yet, STOP GENERATING after ONE acknowledgment — every subsequent "等待授权"/"waiting" reply counts as a new turn, re-fires the Stop hook, and creates a response→hook→response cycle that burns tokens until ctrl-C. Circuit-breaker in the hook is defense #1 (see 2026-04-15), my own silence is defense #2 — if the same hook reason fires twice in a row with no user message in between, the next message MUST be the last until the user speaks. [auto-promoted 2026-05-11]
- [2026-04-20] upstream-design (edge-case): When designing an "absorb from external" system, scope the input space BEFORE the mechanics — (a) one upstream owner often ships many repos/clusters, so enumerate the full set, not just the one you first noticed; (b) the trust/review model (blind-sync vs curate-first) is the architectural spine, not a detail. Ask the user "what's your trust level per upstream?" before proposing file-diff logic. Should have fetched AgriciDaniel's profile on first mention of claude-seo instead of treating it as one isolated repo. [auto-promoted 2026-05-11]
- [2026-04-26] decision-paralysis (settings-disconnect): When you've already enumerated A/B options + recommended one + the action is reversible (commits via `committer`, doc writes, file edits) — execute the recommendation instead of asking. The pattern "我推荐 A. ... 你说 A 还是 B？" is a round-trip the user almost always answers with "A". Especially commits: project rule is "commit small and often" + `committer` is git-reversible — just commit. Should have noticed the existing autonomy rule ("Bug fix without permission") generalizes to "Recommendation without permission" for any reversible action. [auto-promoted 2026-05-11]
