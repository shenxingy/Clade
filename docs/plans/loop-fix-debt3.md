# Goal: Fix /review Round 3 Tech Debt (2026-03-01)

## Context

A `/review` pass on 2026-03-01 surfaced 9 items now in TODO.md Tech Debt. This loop fixes all 9.
All items are in `orchestrator/`. Previous loop lessons: read PROGRESS.md before starting.

## Requirements

### R1 — Remove phantom columns from `_ALLOWED_TASK_COLS` (🔴)
`config.py:_ALLOWED_TASK_COLS` contains `"mode"` and `"result"` but neither column exists in the
`tasks` table (`task_queue.py`). Calling `task_queue.update(task_id, mode="x")` causes a runtime
`OperationalError`. Remove both from the set.

### R2 — Fix `str(e)` leak in `merge_all_done` (🔴)
`server.py:796`: `results.append({"worker_id": w.id, "error": str(e)})` returns raw Python
exception strings. Replace `str(e)` with the static string `"PR merge failed"`.

### R3 — Extract JS from `web/index.html` into `web/app.js` (🟡)
`web/index.html` is 2945 lines, violating the 1500-line project limit. The CSS is already
extracted to `web/styles.css`. Extract the inline `<script>...</script>` block (approx 1800 lines)
to `web/app.js`. Update `index.html` to load it with `<script src="/web/app.js"></script>`.
`web/app.js` will be served by the existing static mount at `/web`.
Target: `index.html` < 1200 lines, `app.js` < 1900 lines.

### R4 — Add `--dangerously-skip-permissions` to `_decompose_horizontal` (🟡)
`session.py:668`: `asyncio.create_subprocess_exec("claude", "--model", "claude-haiku-4-5-20251001", "-p", ...)`
is missing `"--dangerously-skip-permissions"`. In headless automated context, claude will prompt
for permission interactively and time out after 30s. Add the flag to the exec args list.

### R5 — Declare autoscale/factory timer attrs in `ProjectSession.__init__` (🟡)
`session.py`: Four attributes are set dynamically in `status_loop()` via `getattr(session, '_last_autoscale', 0)`:
- `_last_autoscale: float`
- `_ci_watcher_last: float`
- `_coverage_scan_last: float`
- `_dep_update_last: float`
Declare all four in `ProjectSession.__init__` (around line 107-129) with value `0.0`.
After declaring, the `getattr(..., 0)` fallbacks in `status_loop` can stay (they still work).

### R6 — Refactor `import_from_proposed` to call `add()` (🟡)
`task_queue.py:import_from_proposed()` has its own raw INSERT that bypasses `add()`, missing
`source_ref` and `is_critical_path`. Refactor the per-task write to call `await self.add(...)`
instead of the raw INSERT. Pass through `task_type`, `own_files`, `forbidden_files` params.
Note: `add()` also triggers `_score_task` via `asyncio.create_task` — this is acceptable.

### R7 — Add CORS middleware (🟡)
`server.py`: Add `CORSMiddleware` to the FastAPI app so mobile/remote access via Caddy HTTPS works.
Add after the app is created:
```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### R8 — Fix `schedule` endpoint error message (🔵)
`server.py:464`: Error message says "use ISO 8601 (e.g. 2026-03-01T09:00:00)" but the parser
only accepts `HH:MM`. Fix to: `"Invalid time format. Use HH:MM (24h), e.g. 09:00"`.

### R9 — Update TODO.md to check off completed items
After all fixes are committed, check off the 9 new Tech Debt items in TODO.md.

## Files to Modify

| File | What changes |
|------|-------------|
| `orchestrator/config.py` | Remove `"mode"` and `"result"` from `_ALLOWED_TASK_COLS` |
| `orchestrator/server.py` | Fix `str(e)`, add CORS, fix schedule error msg |
| `orchestrator/session.py` | Add `--dangerously-skip-permissions` to decompose_horizontal; declare 4 attrs in `__init__` |
| `orchestrator/task_queue.py` | Refactor `import_from_proposed` to call `add()` |
| `orchestrator/web/index.html` | Extract `<script>` block, add `<script src="/web/app.js">` |
| `orchestrator/web/app.js` | New file: extracted JS |
| `TODO.md` | Check off 9 items |

## Success Criteria

```bash
cd /home/alexshen/projects/claude-code-kit/orchestrator

# 1. No phantom columns
python3 -c "from config import _ALLOWED_TASK_COLS; assert 'mode' not in _ALLOWED_TASK_COLS; assert 'result' not in _ALLOWED_TASK_COLS; print('OK')"

# 2. No str(e) in server.py merge_all_done
grep -n 'str(e)' server.py && echo "FAIL: str(e) found" || echo "OK"

# 3. index.html under limit
wc -l web/index.html  # should be < 1200
test -f web/app.js && echo "app.js exists" || echo "FAIL"

# 4. decompose_horizontal has the flag
grep "dangerously-skip-permissions" session.py | grep "decompose\|claude.*haiku" && echo "OK" || grep -n "decompose_horizontal" -A 15 session.py | grep "dangerously"

# 5. Attrs in __init__
grep "_last_autoscale\|_ci_watcher_last\|_coverage_scan_last\|_dep_update_last" session.py | grep "self\." | head -4

# 6. import_from_proposed uses add()
grep "await self.add" task_queue.py | grep -i "import\|proposed" || grep -A 30 "def import_from_proposed" task_queue.py | grep "await self.add"

# 7. CORS middleware present
grep "CORSMiddleware" server.py && echo "OK"

# 8. Schedule error msg fixed
grep "HH:MM" server.py && echo "OK"

# 9. All tests still pass
.venv/bin/python -m pytest tests/ -v

# 10. Syntax check
.venv/bin/python -m py_compile server.py session.py task_queue.py config.py
```
