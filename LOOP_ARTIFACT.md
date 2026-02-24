# Claude Code Kit — Loop Work Queue

## Project Layout
- Backend: `orchestrator/server.py` (FastAPI + asyncio)
- Frontend: `orchestrator/web/index.html` (single-file vanilla JS + xterm.js)
- Skills: `~/.claude/skills/` (markdown prompt files)
- Commit convention: `committer "fix/feat/chore: message" file1 file2`
- Verify: `cd orchestrator && python -m py_compile server.py`

## Open Tasks

### P3 — Oracle rejection auto-requeue
When `auto_oracle=True` and the oracle rejects a diff, the commit is undone (already done)
but the task is NOT re-queued with the rejection reason as context.
Fix: after `git reset HEAD~1`, call `task_queue.add(original_desc + rejection_reason)` and start a worker.
Files: `orchestrator/server.py` — `verify_and_commit()` method, around the oracle rejection block.

### ~~P3 — plan_build two-phase loop~~ DONE
~~`_run_supervisor()` reads `mode` from loop_state but falls through to review logic regardless.~~
~~Implement plan_build mode: PLAN phase + BUILD phase.~~
Implemented by loop-1 worker: `_run_plan_build()` added, `_run_supervisor()` dispatches on `mode == "plan_build"`.

### P4 — Context budget auto-inject
`context-warning-{id}.md` is already written at 80% context but never sent to the worker.
Fix: in `poll_all`, if the file exists, inject its content into the worker via the PTY stdin.
Files: `orchestrator/server.py` — `poll_all()` method.

### P4 — AGENTS.md auto-prepend to workers
`GET /api/sessions/{id}/agents-md` generates the file ownership map but it is never
automatically prepended to worker task descriptions.
Fix: in `start_worker()`, if `.claude/AGENTS.md` exists in the project dir, prepend its content
alongside the existing CLAUDE.md injection.
Files: `orchestrator/server.py` — `WorkerPool.start_worker()`.

### P4 — Task hot-path / critical path indicator
After the DAG is drawn, compute the longest dependency chain (critical path).
Critical-path tasks get a ⚡ badge in the queue list.
If `auto_model_routing` is ON, critical-path tasks get +1 model tier.
Files: `orchestrator/web/index.html` — `renderDag()` and `renderQueue()`.

### P4 — Worker handoff auto-trigger
If a worker writes `.claude/handoff-{task_id}.md`, the server should detect it and
automatically create a continuation task with `/pickup` + original task description.
Fix: in `poll()` or `_on_worker_done()`, check for handoff file; if exists, re-queue.
Files: `orchestrator/server.py` — `Worker.poll()` or `_on_worker_done()`.

## Completion Criteria
Each task above should be:
1. Implemented in the correct file
2. python -m py_compile passing for server.py changes
3. Committed with `committer "feat/fix: ..." file`
4. The task entry above marked as DONE by removing or striking through

## Already Done (do not re-implement)
- Worktree isolation, subprocess timeouts, WebSocket snapshot iteration, HTTP 404s, wss:// support,
  JSON.parse guards, log interval fix, Ctrl+Shift+X shortcut, overview CSS styles, pr_url XSS guard,
  formatElapsed hours, settingAutoStart two-way sync, oracle commit undo.
