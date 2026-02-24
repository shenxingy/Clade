# TODO — Claude Code Kit

**Two pillars: CLI (configs/) is the foundation, GUI (orchestrator/) extends it.**

---

## Phase 3 — Autonomous Robustness (CURRENT)

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
- [ ] Agent Teams — expose `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
- [ ] Cross-worker messaging — mailbox pattern
- [ ] Task hot-path / critical path indicator + model tier boost for critical-path tasks

---

## Phase 5 — Context Intelligence

- [ ] Semantic code TLDR — AST function signatures + call graph at ~1,200 tokens vs raw 23K
- [ ] Intervention recording — replay successful /message corrections on similar failures
- [ ] Dual-condition exit gate — semantic convergence + change count (not just counting)

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
