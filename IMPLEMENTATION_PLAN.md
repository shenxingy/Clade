# Implementation Plan: Phase 7 + Phase 8

## Context

- **Current state**: Phase 1–6 complete. Server: FastAPI + SQLite (aiosqlite). Frontend: vanilla JS SPA (web/index.html + styles.css). CLI: bash scripts in configs/. Hook system in configs/hooks/. Task parsing: `import_from_proposed()` in task_queue.py parses ===TASK=== blocks.
- **Target state**: Phase 7 (task velocity engine) + Phase 8 (closed-loop work generation) fully implemented.

---

## Architecture Decisions

1. **task_type field** → parsed in `import_from_proposed()` alongside OWN_FILES/FORBIDDEN_FILES. Values: `HORIZONTAL` / `VERTICAL` / `AUTO`. Stored as TEXT in tasks table. Also add `source_ref TEXT` (factory dedup key) and `parent_task_id TEXT` (horizontal subtask linkage) in the same migration.

2. **auto_scale / min_workers / max_workers / webhook_secret** → added to `_SETTINGS_DEFAULTS` in config.py (same task as DB migration). No new API endpoints needed — existing `GET/POST /api/settings` auto-exposes them via GLOBAL_SETTINGS passthrough.

3. **Auto-scaling logic** → in `status_loop()` in session.py. Uses `_last_scale_time` local var for 30s cooldown. Spawns one worker at a time when `pending > running * 2 AND running < max_workers`.

4. **MCP auto-load** → WorkerPool.start_worker() in worker.py checks `project_dir / ".claude" / "mcp.json"` → appends `--mcp-config <path>` to the claude subprocess args.

5. **Frontend** → All index.html + styles.css changes batched into one task (T5) to avoid conflicts. Badge uses `task_type` field from `/api/sessions/{id}/tasks` response.

6. **Horizontal auto-decomp** → blocking haiku call in session.py. Before `worker_pool.start_worker()`, if `task.task_type == 'HORIZONTAL'`, call `await _decompose_horizontal(task, session)`. Haiku lists files → create N subtasks → set original to `grouped`. Each subtask has `parent_task_id`. Depends on T3 merge (needs task_type in DB).

7. **Task factories (GUI)** → pure API endpoints: `POST /api/factory/ci`, `/api/factory/coverage`, `/api/factory/deps`. Each factory module in `orchestrator/task_factory/`. Registered in server.py (Wave 2). source_ref dedup prevents duplicate tasks.

8. **GitHub webhook** → new FastAPI router in `orchestrator/routes/webhooks.py`. HMAC-SHA256 verification via `webhook_secret` setting. Two triggers: Issue labeled `claude-do-it`, or comment `/claude <instruction>` on Issue/PR.

---

## Risks & Mitigations

- **session.py touched by 3 features (7.3a import, 7.3c status_loop, 7.3b start_worker)** → split across Wave 1 (T3 touches task_queue.py only, not session.py; T4 touches session.py for status_loop) and Wave 2 (T7 touches session.py for start_worker). T3 and T4 own different files — no conflict.
- **Haiku LLM call blocks start_worker()** → add 30s timeout; if haiku call fails or times out, fall back to starting the HORIZONTAL task as-is (non-blocking fallback).
- **server.py touched by multiple features** → only Wave 2 T8 touches server.py (factory + webhook registration). Wave 1 doesn't touch server.py at all.
- **web/index.html touched by multiple features** → batched into T5. Includes task_type badge + auto-scale settings + preset cards all in one worker.

---

## Execution Order

### Wave 1 — All 6 tasks run in parallel

| Task | What | Files Owned |
|------|------|-------------|
| **T1** | 7.1 Hook Layer + CLAUDE.md per-file rule | configs/hooks/post-edit-check.sh, configs/hooks/verify-task-completed.sh, configs/templates/CLAUDE.md, ~/.claude/CLAUDE.md |
| **T2** | 7.2 CLI velocity (loop HORIZONTAL + scan-todos + tmux-dispatch) | configs/scripts/loop-runner.sh, configs/templates/loop-goal.md, configs/scripts/scan-todos.sh, configs/scripts/tmux-dispatch.sh |
| **T3** | 7.3a task_type DB foundation (★ MUST MERGE before Wave 2 T7) | orchestrator/task_queue.py, orchestrator/config.py |
| **T4** | 7.3c auto-scaling + 8.3 MCP worker load | orchestrator/session.py, orchestrator/worker.py |
| **T5** | 7.3 + 8.3 GUI frontend (badges + settings UI + preset cards) | orchestrator/web/index.html, orchestrator/web/styles.css |
| **T6** | 8.1 CLI scripts + 8.3 CLI templates | configs/scripts/scan-ci-failures.sh, configs/scripts/scan-coverage.sh, configs/scripts/scan-deps.sh, configs/templates/task-*.md |

### Wave 2 — After Wave 1 merges (T7 specifically needs T3)

| Task | What | Files Owned |
|------|------|-------------|
| **T7** | 7.3b Horizontal auto-decomp (haiku LLM subtask generator) | orchestrator/session.py, orchestrator/worker.py |
| **T8** | 8.1 GUI factory modules + 8.2 webhook + docs/mcp-setup.md + server.py registration | orchestrator/task_factory/*.py, orchestrator/routes/webhooks.py, orchestrator/server.py, docs/mcp-setup.md |

---

## File Interaction Graph

```
config.py (leaf: no internal imports)
    ← task_queue.py (imports config constants + GLOBAL_SETTINGS)
    ← session.py (imports GLOBAL_SETTINGS, _fire_notification, etc.)
    ← worker.py (imports GLOBAL_SETTINGS)
    ← server.py (imports all of the above)

task_queue.py ← session.py (TaskQueue used by ProjectSession)
worker.py ← session.py (WorkerPool, SwarmManager, _generate_code_tldr)
session.py ← server.py (status_loop, ProjectSession, Sessions)

web/index.html (standalone; reads REST API — no import coupling)
configs/* (standalone bash scripts; no Python coupling)
```

---

## Verification Steps

After Wave 1:
- [ ] `committer` commit lands on main with task_type column migration
- [ ] Existing tasks DB still loads (migration is ALTER TABLE, fail-open)
- [ ] TYPE: HORIZONTAL in proposed-tasks.md → task.task_type = 'HORIZONTAL' in DB
- [ ] auto_scale toggle in settings panel saves/loads correctly
- [ ] H/V/A badge appears on worker cards in UI
- [ ] Preset card click pre-fills task form
- [ ] `scan-todos.sh --help` runs without error
- [ ] `tmux-dispatch.sh --help` runs without error
- [ ] post-edit-check.sh emits systemMessage when ≥ 2 files uncommitted
- [ ] loop-runner.sh with MODE: HORIZONTAL uses 20-task cap

After Wave 2:
- [ ] HORIZONTAL task spawns N subtasks with parent_task_id set
- [ ] POST /api/factory/ci returns tasks list
- [ ] POST /api/webhooks/github with valid signature creates task
- [ ] POST /api/webhooks/github with invalid signature returns 401
- [ ] docs/mcp-setup.md exists and is readable
- [ ] .claude/mcp.json in project dir → claude subprocess gets --mcp-config flag

---

## Task files

- Wave 1: `.claude/proposed-tasks.md` (ready to run now)
- Wave 2: `.claude/proposed-tasks-wave2.md` (run after Wave 1 merges + T3 confirmed in DB)
