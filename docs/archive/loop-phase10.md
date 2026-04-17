# Goal: Phase 10 — Portfolio Mode
<!-- STATUS: DEFERRED 2026-04-12 — portfolioPanel UI + cross-project cost API not yet implemented; defer until orchestrator has ≥2 active projects in regular use -->

## Context

Phases 1–9 done. Phase 10 turns the orchestrator from a single-project tool into a
**portfolio manager**: oversees N projects simultaneously, auto-ranks work, routes workers
intelligently, and generates morning briefings + next-goal suggestions.

Read PROGRESS.md first — past lesson: "silent wiring bugs happen when DB columns are added
but not plumbed through add()". Trace every new feature end-to-end (schema → logic → UI/CLI).

## Feature 1 — Cross-Project Session Overview (GUI + API)

### 1a. Enhance `GET /api/sessions/overview` (`orchestrator/server.py`)

Add to each session entry in the response:
- `total_cost: float` — sum of `estimated_cost` across all tasks
- `cost_rate_per_hour: float | None` — total_cost / elapsed_hours since first task started_at
  (None if no tasks have started). `elapsed_hours = (now - min(started_at)) / 3600`

### 1b. Portfolio panel in UI (`orchestrator/web/app.js`)

Add a collapsible `<div id="portfolioPanel">` widget near the top of the Execute panel.
It appears only when `registry.all()` has ≥ 2 sessions. Shows a table:

```
Session    Pending  Running  Done  Failed  Cost      Rate/hr   ETA
proj-a     5        2        8     1       $0.23     $0.04     12min
proj-b     0        0        3     0       $0.11     —         done
```

Poll `GET /api/sessions/overview` every 5s when visible.
Add a toggle button "📊 Portfolio" in the header (only visible when ≥ 2 sessions exist).

## Feature 2 — Task Priority Ranker

### 2a. `_rank_tasks()` function in `orchestrator/worker.py`

```python
async def _rank_tasks(task_queue: TaskQueue, claude_dir: Path) -> None:
    """Score all unranked pending tasks by impact/urgency using haiku.
    Updates priority_score (0.0–1.0) in DB. 1.0 = highest priority."""
```

- Fetch all tasks with `status == "pending"` and `priority_score == 0.0`
- If 0 such tasks, return immediately
- Build prompt: list of up to 20 tasks (id + first 120 chars of description)
- Call haiku: `'claude -p "..." --model claude-haiku-4-5-20251001 --dangerously-skip-permissions'`
- Parse JSON response: `[{"id": "...", "score": 0.0–1.0}, ...]`
- For each: `await task_queue.update(task_id, priority_score=score)`
- Timeout: 60s. Fail-open (catch all exceptions).

### 2b. Wire into `status_loop()` (`orchestrator/session.py`)

Add to `ProjectSession.__init__`:
```python
self._priority_rank_last: float = 0.0
```

In `status_loop()`, after `poll_all()`:
```python
# Priority ranking: re-rank unranked pending tasks every 5 minutes
if (GLOBAL_SETTINGS.get("auto_start", True)
        and time.time() - session._priority_rank_last > 300):
    _unranked = [t for t in _auto_tasks
                 if t["status"] == "pending" and not (t.get("priority_score") or 0)]
    if _unranked:
        session._priority_rank_last = time.time()
        asyncio.create_task(
            _rank_tasks(session.task_queue, session.claude_dir)
        )
```

Import `_rank_tasks` in `session.py` from `worker`.

### 2c. Sort by priority in `task_queue.py`

Change `list()` ORDER BY:
```sql
ORDER BY priority_score DESC, created_at ASC
```

Change `claim_next_pending()` ORDER BY:
```sql
ORDER BY priority_score DESC, created_at ASC
```

Also in `import_from_proposed()` inline SELECT (line ~534):
```sql
ORDER BY priority_score DESC, created_at ASC
```

## Feature 3 — Worker Pool Router (Cross-Session Global Cap)

### Fix `status_loop()` auto-start loop (`orchestrator/session.py`)

Current: per-session `max_workers` check. This means with 3 sessions × max_workers=3, up to 9
workers can run simultaneously, ignoring the global cap.

**Fix**: Before the per-session auto-start loop, compute global running count:

```python
# Worker pool router: enforce max_workers as a global ceiling across all sessions
_global_max = GLOBAL_SETTINGS.get("max_workers", 0)
if _global_max > 0:
    _global_running = sum(
        sum(1 for w in s.worker_pool.all() if w.status == "running")
        for s in registry.all()
    )
    if _global_running >= _global_max:
        # Global cap hit — skip auto-start for all sessions this tick
        # (still do poll, notifications, etc.)
        _newly_ready = []  # prevent spawning
```

Place this block right before the `if _newly_ready and GLOBAL_SETTINGS.get("auto_start", True):`
check (after _newly_ready is computed). When global cap is hit, set `_newly_ready = []` to
prevent spawning without breaking the rest of the loop.

Also fix auto-scaling the same way: check `_global_running < _global_max` instead of
`_running_now < _max_w` when `_global_max > 0`.

## Feature 4 — Morning Briefing Skill (`/brief`)

### 4a. `configs/skills/brief/SKILL.md`

```markdown
# Brief Skill

Generates a morning briefing: what ran overnight, what it cost, what to do next.

## When to use

Run at the start of a session to catch up on overnight/unattended work.

## Usage

/brief                   # Full briefing for current project
/brief --all             # Briefing across all registered sessions (if orchestrator running)
```

### 4b. `configs/skills/brief/prompt.md`

The skill prompt should instruct Claude to:

1. Run `git log --since="18 hours ago" --oneline` to get recent commits
2. Run `git log --since="18 hours ago" --format="%s" | wc -l` to count commits
3. Check if orchestrator is running: `curl -s http://localhost:4000/api/sessions/overview 2>/dev/null`
   - If running: extract pending/done/failed/cost from overview
   - If not running: skip API data
4. Read last 2000 chars of PROGRESS.md if it exists
5. Read TODO.md to find the next open `- [ ]` items

Output a concise markdown briefing with sections:
- **Overnight Activity** (commits count, most recent 5 commits)
- **Queue Status** (pending/running/done/failed, total cost if available)
- **Recent Lessons** (from PROGRESS.md, last entry only)
- **Suggested Next Actions** (top 3 open TODO items + one improvement suggestion)

Keep the briefing under 40 lines. Be specific and actionable.

## Feature 5 — Goal Suggestion Engine

### 5a. `_suggest_next_goals()` async function in `orchestrator/session.py`

```python
async def _suggest_next_goals(session: ProjectSession) -> None:
    """After loop converges: use haiku to suggest 3 next goals. Writes to .claude/suggested-goals.md."""
```

Logic:
1. Read last 2000 chars of `session.project_dir / "PROGRESS.md"` (if exists)
2. Read last 1000 chars of `session.project_dir / "VISION.md"` (if exists)
3. Read last 500 chars of `session.project_dir / "TODO.md"` (if exists, get open `- [ ]` items)
4. Build haiku prompt asking for 3 concrete next loop goals in this format:
   ```
   1. [Goal title]: [2-sentence description of what to build/fix and why]
   2. ...
   3. ...
   ```
5. Call haiku (60s timeout), write response to `session.claude_dir / "suggested-goals.md"`
6. Broadcast to WebSocket subscribers:
   ```json
   {"type": "suggested_goals", "session_id": "...", "content": "..."}
   ```
7. Fail-open (wrap entire function in try/except)

### 5b. Hook into convergence in `_run_supervisor()` and `_run_plan_build()` (`session.py`)

In `_run_supervisor()`, after `await self.task_queue.upsert_loop(status="converged")`:
```python
asyncio.create_task(_suggest_next_goals(self))
```

In `_run_plan_build()`, same: after the final `upsert_loop(status="converged")` calls.

### 5c. UI: show suggested goals after loop converges (`orchestrator/web/app.js`)

In the WebSocket message handler, handle `type === "suggested_goals"`:
```javascript
case "suggested_goals":
    showSuggestedGoals(msg.content);
    break;
```

Add `showSuggestedGoals(content)`:
- Creates/updates a `<div id="suggestedGoals">` below the loop control panel
- Shows the content in a styled pre/code block with a "✨ Suggested Next Goals" header
- Has a dismiss button (×) and a "Copy" button
- Persists in sessionStorage so it survives page refresh (keyed by session_id)

## Files to Modify

| File | What changes |
|------|-------------|
| `orchestrator/server.py` | Enhance `sessions_overview()` with `total_cost` + `cost_rate_per_hour` |
| `orchestrator/worker.py` | Add `_rank_tasks()` function |
| `orchestrator/session.py` | Wire `_rank_tasks` + goal suggestion + global worker cap fix; add `_priority_rank_last` to `__init__` |
| `orchestrator/task_queue.py` | Change 3× ORDER BY to `priority_score DESC, created_at ASC` |
| `orchestrator/web/app.js` | Portfolio panel + suggested goals widget |
| `configs/skills/brief/SKILL.md` | New skill |
| `configs/skills/brief/prompt.md` | New skill prompt |
| `TODO.md` | Check off Phase 10 items, update VISION.md milestone |
| `VISION.md` | Mark Phase 10 as ✓ DONE |

## Success Criteria

```bash
# 1. API: overview has cost fields
curl -s http://localhost:4000/api/sessions/overview | python3 -m json.tool | grep -E "total_cost|cost_rate"

# 2. Priority ranker exists in worker.py
grep "_rank_tasks" /home/alexshen/projects/claude-code-kit/orchestrator/worker.py

# 3. _rank_tasks wired in session.py
grep "_rank_tasks\|_priority_rank_last" /home/alexshen/projects/claude-code-kit/orchestrator/session.py

# 4. TaskQueue ORDER BY updated
grep "priority_score DESC" /home/alexshen/projects/claude-code-kit/orchestrator/task_queue.py | wc -l  # should be >= 3

# 5. Global worker cap in status_loop
grep "_global_running\|_global_max" /home/alexshen/projects/claude-code-kit/orchestrator/session.py

# 6. Goal suggestion engine wired
grep "_suggest_next_goals" /home/alexshen/projects/claude-code-kit/orchestrator/session.py | wc -l  # >= 3

# 7. Brief skill exists
test -f /home/alexshen/projects/claude-code-kit/configs/skills/brief/prompt.md && echo "OK"
test -f /home/alexshen/projects/claude-code-kit/configs/skills/brief/SKILL.md && echo "OK"

# 8. All tests pass
cd /home/alexshen/projects/claude-code-kit/orchestrator && .venv/bin/python -m pytest tests/ -v

# 9. Syntax check
cd /home/alexshen/projects/claude-code-kit/orchestrator && .venv/bin/python -m py_compile server.py session.py worker.py task_queue.py

# 10. No circular imports
cd /home/alexshen/projects/claude-code-kit/orchestrator && .venv/bin/python -c "import server; print('OK')"
```
