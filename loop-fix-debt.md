# Goal: Fix Post-Loop Tech Debt

## Context

The `loop-gui-features` loop successfully implemented 9 GUI features but introduced 4 runtime-breaking bugs
and left doc/wiring gaps. This loop fixes them.

**Key files:**
- `orchestrator/task_queue.py` — `add()` at line 234, `_ensure_db()` migrations at ~line 117
- `orchestrator/session.py` — `status_loop()` at line 711, `_decompose_horizontal()` at line 673
- `orchestrator/routes/webhooks.py` — dedup logic at line 100
- `orchestrator/task_factory/ci_watcher.py` — `httpx` import at line 9
- `orchestrator/requirements.txt` — dependencies
- `TODO.md`, `VISION.md` — doc sync

---

## Requirements

### 1. Fix `TaskQueue.add()` — add new column params

`orchestrator/task_queue.py` line 234: `add()` only accepts `(description, model, own_files, forbidden_files, is_critical_path)`.

Add `task_type: str = "AUTO"`, `source_ref: str | None = None`, `parent_task_id: str | None = None` to the signature.

Include them in the task dict and INSERT statement. The INSERT currently lists 19 columns — add 3 more:
```python
# add to INSERT column list: task_type, source_ref, parent_task_id
# add to VALUES: ?, ?, ?
# add to params tuple: task["task_type"], task["source_ref"], task["parent_task_id"]
```

Read the full `add()` method first (lines 234–280) to get the exact current INSERT statement before editing.

### 2. Fix webhook dedup — wrong status strings

`orchestrator/routes/webhooks.py` line 101:
```python
# WRONG:
t.get("status") not in ("completed", "failed", "cancelled")
# CORRECT:
t.get("status") not in ("done", "failed")
```
Real task statuses: `pending`, `running`, `starting`, `done`, `failed`, `interrupted`, `grouped`. No `"completed"` or `"cancelled"` status exists.

### 3. Fix webhook — persist source_ref in task

`orchestrator/routes/webhooks.py` line 106:
```python
# WRONG (source_ref silently dropped):
task = await task_queue.add(description=description)

# CORRECT (after fixing add() in requirement 1):
task = await task_queue.add(description=description, source_ref=source_ref)
```

### 4. Fix `httpx` missing dependency

`orchestrator/requirements.txt`: add `httpx` as a dependency.
`orchestrator/task_factory/ci_watcher.py`: `httpx` is used for async HTTP calls to GitHub API.

Also check `orchestrator/task_factory/ci_watcher.py` — it uses f-strings with `logging.warning(f"...")` which is inconsistent with the rest of the codebase that uses `logging.warning("...", arg)` style. Fix to `%s` format style for consistency.

### 5. Wire task factories into `status_loop()`

`orchestrator/session.py` `status_loop()`: Add periodic calls to the 3 task factories.

After the existing "Auto-scaling" block (around line 781), add factory polling:
```python
# Task factories: poll every 5 minutes
_now = time.time()
if GLOBAL_SETTINGS.get("github_issues_sync", False):
    if _now - getattr(session, '_ci_watcher_last', 0) > 300:
        session._ci_watcher_last = _now
        try:
            from task_factory.ci_watcher import check_ci_failures
            asyncio.ensure_future(check_ci_failures(session.task_queue, str(session.project_dir)))
        except Exception as e:
            logger.warning("CI watcher error: %s", e)
```

Coverage scan and dep_update: add similar 30-minute polling blocks guarded by new settings.
- `coverage_scan`: `GLOBAL_SETTINGS.get("coverage_scan", False)` every 1800s
- `dep_update`: `GLOBAL_SETTINGS.get("dep_update_scan", False)` every 3600s

Also add `"coverage_scan": False` and `"dep_update_scan": False` to `_SETTINGS_DEFAULTS` in `config.py`.

### 6. Fix `_decompose_horizontal` missing cwd

`orchestrator/session.py` line 678: `create_subprocess_exec("claude", ...)` needs `cwd`:
```python
proc = await asyncio.create_subprocess_exec(
    "claude", "--model", "claude-haiku-4-5-20251001", "-p",
    f"List the source files that need changes ...",
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.DEVNULL,
    cwd=str(session.project_dir),  # ADD THIS
)
```

Also remove the redundant `import asyncio, shlex` on line 675 — both are already imported at module level.

### 7. Sync TODO.md + VISION.md

`TODO.md`: Mark these items `[x]` (they are now implemented):
- Line 104: Task type field
- Line 110: Horizontal auto-decomposition
- Line 116: Worker auto-scaling
- Line 183: GitHub webhook endpoint
- Line 198: GUI preset cards
- Line 203: MCP integration

Also check CI failure watcher GUI, coverage scan GUI, dep update GUI items (~lines 170-178) and mark done.

`VISION.md` milestone table (line 58-60): Update Phase 7 and Phase 8 status:
- Phase 7: `🔄 IN PROGRESS` → `✓ DONE`
- Phase 8: `📋 PLANNED` → `✓ DONE`
- Phase 9: keep `🔄 IN PROGRESS` (still some items remaining)

---

## Acceptance Criteria

- [ ] `cd orchestrator && .venv/bin/python -c "import server; print('OK')"` passes
- [ ] `cd orchestrator && .venv/bin/python -c "from task_factory.ci_watcher import check_ci_failures; print('OK')"` passes (no httpx error)
- [ ] `cd orchestrator && .venv/bin/python -c "from routes.webhooks import router; print('OK')"` passes
- [ ] `TaskQueue.add()` accepts `task_type`, `source_ref`, `parent_task_id` kwargs without TypeError
- [ ] Webhook dedup checks for `"done"` not `"completed"`
- [ ] `source_ref` passed to `task_queue.add()` in webhooks.py
- [ ] `httpx` in `requirements.txt`
- [ ] Task factory calls present in `status_loop()`
- [ ] `_decompose_horizontal` has `cwd=str(session.project_dir)` and no redundant imports
- [ ] Phase 7.3 + Phase 8 TODO items marked `[x]` in TODO.md
- [ ] VISION.md Phase 7 and Phase 8 show `✓ DONE`

---

## Verification

```bash
cd orchestrator && .venv/bin/python -c "import server; from task_factory.ci_watcher import check_ci_failures; from routes.webhooks import router; print('All imports OK')"
```

---

## Implementation Notes

- Read each file fully before editing
- `add()` INSERT statement: read lines 260–280 carefully before modifying — don't miss a column
- DB has already been migrated with the 3 new columns (done by previous loop) — just fix the Python insert
- `_SETTINGS_DEFAULTS` is in `config.py` not `task_queue.py`
- Use `committer "fix: ..." file1 file2` for each logical unit
- After each file edit, commit immediately with committer
