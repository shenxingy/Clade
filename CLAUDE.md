# Clade — Project Context

## Project Type
- Type: cli + skill-system
- Frontend: Vite + React + TypeScript UI under orchestrator/web/src/ (served from web/dist; not the primary interface)
- Backend: FastAPI (orchestrator/, port 8000) — optional, CLI layer works standalone
- Test command: cd orchestrator && .venv/bin/python -m pytest tests/ -v
- Verify command: cd orchestrator && find . \( -name .venv -o -name node_modules -o -name __pycache__ \) -prune -o -name "*.py" -print | xargs -n1 python -m py_compile

## Features (Behavior Anchors)
- install.sh: running `./install.sh` copies skills/hooks/scripts/agents to ~/.claude/ without errors
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
# Install CLI layer (skills, hooks, scripts, agents)
./install.sh

# slt — statusline-toggle (quota pace indicator). See /slt skill.

# Start orchestrator (from project root or orchestrator dir)
cd orchestrator && uvicorn server:app --reload

# Run tests
cd orchestrator && .venv/bin/python -m pytest tests/ -v

# Syntax check (all Python modules — same find-based sweep CI runs)
cd orchestrator && find . \( -name .venv -o -name node_modules -o -name __pycache__ \) -prune -o -name "*.py" -print | xargs -n1 python -m py_compile

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
- `hooks/` — pre/post hooks for Claude Code events (wired via `settings-hooks.json`)
- `scripts/` — shell utilities (e.g., `committer.sh`)
- `agents/` — subagent definitions for the Agent tool

### Orchestrator Layer (`orchestrator/`)
Key modules (import DAG — leaf → root):

```
# Leaves (no project imports)
config.py            ← constants, settings, utilities
ideas.py             ← IdeasManager, async idea CRUD
process_manager.py   ← ProcessPool, start.sh lifecycle
worker_tldr.py       ← TLDR generation, localization, fault location, scoring
worker_review.py     ← oracle + PR review
worker_utils.py      ← output helpers, lint reflection, LoopDetectionService, worker-state helpers
worker_hydrate.py    ← _pre_hydrate (GitHub issue/PR pre-hydration)
condensers.py        ← Condenser ABC + implementations
event_stream.py      ← crash-safe JSONL event logging
tracing.py           ← TracingService, task spans
reactions.py         ← ReactionExecutor
error_classifier.py  ← error classify/summarize + retry decisions
session_tree.py      ← SessionTree
usage_tracker.py     ← multi-machine ccusage ingestion (used by routes/usage.py)
compression_feedback.py ← compression UX feedback (consumed by /handoff skill)
    ↑
# Mid-tier
github_sync.py       ← gh CLI wrappers (issues, push, sync)
task_queue.py        ← SQLite-backed task CRUD
swarm.py             ← SwarmManager (extracted from worker.py)
worker_taskfile.py   ← build_task_file: task file construction + context injection
    ↑
worker.py            ← Worker, WorkerPool — core execution engine
session.py           ← ProjectSession, registry, status_loop (lazy-imports task_factory/)
    ↑
# Roots
server.py            ← FastAPI app, remaining routes, mounts all routes/* routers
mcp_server.py        ← standalone MCP entrypoint exposing skills (stdio transport)
routes/tasks.py      ← Task CRUD + bulk-action routes
routes/workers.py    ← Worker control + inspection routes
routes/webhooks.py   ← GitHub webhook handler
routes/ideas.py      ← Ideas API routes (CRUD, evaluate, execute, promote)
routes/process.py    ← Process manager API routes
routes/usage.py      ← Usage dashboard API routes
```

### Key File Map
| File | Purpose |
|------|---------|
| `config.py` | `GLOBAL_SETTINGS`, `_ALLOWED_TASK_COLS`, model aliases, cost utils |
| `task_queue.py` | SQLite CRUD for tasks, loops, messages, interventions |
| `worker.py` | `Worker`, `WorkerPool` — core execution engine |
| `swarm.py` | `SwarmManager` (extracted from worker.py; re-exported there) |
| `worker_taskfile.py` | `build_task_file` — task file construction + context injection |
| `worker_tldr.py` | `_generate_code_tldr`, `_score_task` — TLDR + scoring (leaf) |
| `worker_review.py` | `_write_pr_review`, `_oracle_review`, `_write_progress_entry` (leaf) |
| `worker_utils.py` | Output helpers, lint reflection, `LoopDetectionService`, worker-state helpers (leaf) |
| `session.py` | `ProjectSession`, `SessionRegistry`, `status_loop()` |
| `server.py` | FastAPI app, session/loop/swarm/usage/settings routes, WebSocket |
| `github_sync.py` | GitHub issue create/update/pull/push via `gh` CLI |
| `ideas.py` | `IdeasManager` — async idea CRUD, AI evaluation, promotion |
| `process_manager.py` | `ProcessPool`, `StartProcess` — start.sh lifecycle control |
| `usage_tracker.py` | Multi-machine ccusage ingestion (`~/.claude/orchestrator/usage.db`) |
| `routes/tasks.py` | Task CRUD + bulk-action routes (13 handlers) |
| `routes/workers.py` | Worker control + inspection routes (9 handlers) |
| `routes/ideas.py` | Ideas API routes (CRUD, evaluate, execute, promote) |
| `routes/usage.py` | Usage dashboard API routes |
| `web/src/` | Vite + React + TypeScript UI source (App.tsx, components/, stores/, hooks/, lib/) |
| `web/index.html` | Vite shell (`<div id="root">` + main.tsx); server serves `web/dist` build when present |
| `web/usage.html` | Standalone usage dashboard (served at `/web/usage.html`) |

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
# 1. Python syntax check (all modules — same find-based sweep CI runs)
cd orchestrator && find . \( -name .venv -o -name node_modules -o -name __pycache__ \) -prune -o -name "*.py" -print | xargs -n1 python -m py_compile

# 2. Tests
cd orchestrator && .venv/bin/python -m pytest tests/ -v

# 3. Shell syntax check
bash -n configs/hooks/*.sh configs/scripts/*.sh install.sh

# 4. mcp-package derived-copy drift gate — mcp-package/skills/ is generated
#    from configs/skills/ via the mcp-package/skills.list manifest. After
#    editing any skill shipped in the package, regenerate and commit:
configs/scripts/regen-mcp-package.sh
```

CI runs 4 jobs on push/PR to main: `syntax-check` (includes the mcp-package
skills drift gate), `pytest`, `shell-tests`, `install-test`. A fifth key-gated
job (`real-api-loop`) runs only on workflow_dispatch/weekly schedule: one live
claude CLI loop scenario (~$0.05) via `bash tests/test-loop.sh --real` —
without claude CLI + credentials it prints SKIP and exits 0.

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
- [2026-04-12] prompt-hook-verbosity (settings-disconnect): Always add statusMessage to type:prompt hooks — without it Claude Code displays the full prompt text in the UI, blocking content. Should have noticed the missing statusMessage when writing the hook. [auto-promoted 2026-05-11]
- [2026-04-15] stop-hook-scope (edge-case): Stop-hook cleanliness checks must be session-scoped (baseline at SessionStart, diff at Stop), not repo-global — parallel CC sessions on the same repo cause deadlock when one session's dirt blocks another session's stop. Always pair a blocking Stop hook with an `stop_hook_active`+attempt-counter circuit breaker to escape LLM loops. [auto-promoted 2026-05-11]
- [2026-04-19] stop-hook-ack-loop (async-race): When a Stop hook blocks awaiting user input and the user hasn't replied yet, STOP GENERATING after ONE acknowledgment — every subsequent "等待授权"/"waiting" reply counts as a new turn, re-fires the Stop hook, and creates a response→hook→response cycle that burns tokens until ctrl-C. Circuit-breaker in the hook is defense #1 (see 2026-04-15), my own silence is defense #2 — if the same hook reason fires twice in a row with no user message in between, the next message MUST be the last until the user speaks. [auto-promoted 2026-05-11]
- [2026-04-20] upstream-design (edge-case): When designing an "absorb from external" system, scope the input space BEFORE the mechanics — (a) one upstream owner often ships many repos/clusters, so enumerate the full set, not just the one you first noticed; (b) the trust/review model (blind-sync vs curate-first) is the architectural spine, not a detail. Ask the user "what's your trust level per upstream?" before proposing file-diff logic. Should have fetched AgriciDaniel's profile on first mention of claude-seo instead of treating it as one isolated repo. [auto-promoted 2026-05-11]
- [2026-05-06] design-scope (edge-case): When designing a learning/automation/observability feature, default to ~/.claude/ universal scope unless the value is genuinely repo-local — not bake it into the project you happen to be sitting in. Cross-project applicability is the input dimension I keep missing: dotfiles deploy is global, memory-sync is global, hooks are global, so "learn from commits" should be too. Should have asked "does this live in ~/.claude/ or in <project>/?" before drafting architecture. [auto-promoted 2026-05-25]
- [2026-05-06] topic-pivot (edge-case): When the user's next message is in a domain with zero overlap with current conversation (e.g. commit-archeology → trial pricing strategy in a project with no pricing), ONE-line confirm scope before investing in investigation — wrong-session / mis-pasted prompts are a real failure mode. The 5-second "wait, is this for this repo?" check saves a 10-minute scan of a project that doesn't have the topic at all. [auto-promoted 2026-05-25]
- [2026-05-07] reduction-recommendation (deploy-gap): Before recommending "remove/disable X" to fix bloat, verify (a) X is actually running, (b) what value X provides beyond the immediate context, (c) whether the bloat is from X itself or from X-being-loaded-in-the-wrong-place. Recommended killing the clade MCP server to fix "95 skill descriptions dropped" without checking it was actively running, what external tools depend on it, or that the real issue was Claude-Code-as-MCP-client double-loading skills. Should have run `ps aux | grep mcp` and read the .mcp.json before proposing the cut. [auto-promoted 2026-05-25]
