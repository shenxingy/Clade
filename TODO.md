# TODO — Claude Code Kit

**Two pillars: CLI (configs/) is the foundation, GUI (orchestrator/) extends it.**

---

## Phase 3 — Autonomous Robustness

### Server-side (orchestrator/server.py)

- [x] **Oracle rejection → auto-requeue** — after oracle rejects + `git reset HEAD~1`, call `task_queue.add(original_desc + rejection_reason)` and start a new worker
  - Location: `verify_and_commit()` oracle rejection block
- [x] **Context budget auto-inject** — `context_warning` bool in worker to_dict() for UI badge; workers use `claude -p` (non-interactive) so stdin injection not possible without architecture change
  - File-based warning still written; `context_warning` field broadcast via WebSocket
- [x] **AGENTS.md auto-prepend** — in `start_worker()`, if `.claude/AGENTS.md` exists in project dir, prepend alongside CLAUDE.md injection
  - Endpoint already generates it (`GET /agents-md`); missing: auto-inject on worker spawn
- [x] **Worker handoff auto-trigger** — in `_on_worker_done()`, check for `.claude/handoff-{task_id}.md`; if exists, create continuation task with `/pickup` + original description

### CLI-side (configs/skills/, configs/scripts/)

- [x] **Two-phase orchestrate** (`/orchestrate --plan`) — Phase 1: codebase analysis → `IMPLEMENTATION_PLAN.md`, Phase 2: plan → `proposed-tasks.md` with `OWN_FILES`/`FORBIDDEN_FILES`
- [x] **Loop artifact marking** — instruct workers to mark `- [ ]` → `- [x]` in goal file on completion (enforce via supervisor prompt)
- [x] **Loop `--stop`** — write STOP sentinel to state file; loop-runner checks before each iteration
- [x] **Loop signal handling** — trap SIGTERM/SIGINT in loop-runner.sh for graceful shutdown

---

## Phase 4 — Swarm Intelligence

- [x] Swarm mode — N workers self-claim from shared queue (no central allocator)
- [x] File ownership enforcement — OWN_FILES/FORBIDDEN_FILES parsed from proposed-tasks.md, stored in DB, enforced in verify_and_commit, violation → requeue
- [x] GitHub Issues sync — Issues as persistent task database (survives machine restarts, editable from phone)
- [x] Agent Teams — expose `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
- [x] Cross-worker messaging — mailbox pattern
- [x] Task hot-path / critical path indicator + model tier boost for critical-path tasks

---

## Phase 5 — Context Intelligence

- [x] Semantic code TLDR — AST function signatures + JS/TS regex extraction at ~750 tokens vs raw 5K+ file paths
- [x] Intervention recording — replay successful /message corrections on similar failures
- [x] Dual-condition exit gate — semantic diff hash + change count (not just counting)

---

## Phase 6 — Observability & Resilience (CURRENT)

- [ ] **Task analytics** — success/failure rate, avg duration per model, distribution chart; new dashboard widget
  - Data source: `tasks` table (status, elapsed_s, model, started_at)
  - Endpoint: `GET /api/sessions/{session_id}/analytics`
  - UI: collapsible stats card in execute panel (pie chart + summary numbers)
- [ ] **Token/cost tracking** — parse `claude -p` stdout for token usage lines, store in tasks table
  - New columns: `input_tokens`, `output_tokens`, `estimated_cost`
  - Parse in `Worker.poll()` or `_on_worker_done()` from log file
  - UI: cost column in task list, session total in header
- [ ] **Cost budget limit** — max spend per session; auto-pause workers when budget exceeded
  - New setting: `cost_budget` (default: 0 = unlimited)
  - Check in `poll_all()` before starting new workers
  - UI: budget input in settings panel, warning toast when approaching limit
- [ ] **Stuck worker detection** — log file mtime unchanged for N minutes → kill + requeue
  - Check in `poll_all()`: compare `log_path.stat().st_mtime` against threshold
  - New setting: `stuck_timeout_minutes` (default: 15)
  - Requeue with `[STUCK-RETRY]` prefix for context
- [ ] **Session state persistence** — survive server restart
  - On startup: scan for orphaned worktree dirs, match to tasks in DB still marked `running`
  - Mark orphaned tasks as `interrupted`, allow one-click retry
  - Persist worker→task mapping in DB (not just in-memory WorkerPool)
- [ ] **Completion notifications** — webhook when batch/loop finishes
  - New setting: `notification_webhook` (URL)
  - Fire on: all tasks done, loop converged, error count > threshold
  - Payload: session_id, summary stats, failed task list

---

## Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| DB | SQLite (aiosqlite) | Lightweight, no server, queryable history |
| Parallelism | Git worktrees | True isolation, no file conflicts |
| Push | Commit + push immediately | Code never lost, remote is backup |
| Merge | Auto-merge orchestrator branches; manual for external | Our tasks → ship fast; external → gate |
| Retry | With error context injected | Workers learn from failures |
| Oracle | Off by default | Opt-in quality gate, doesn't break existing flow |
| Model routing | Off by default | User may want explicit control |
| CLI loop | Pure bash (loop-runner.sh) | No Python dependency, safe for self-modification |
