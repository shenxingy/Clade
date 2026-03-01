# Phase 10: Portfolio Mode — Loop Goal

## Goal
Implement Phase 10 Portfolio Mode across 5 features:
1. Cross-project session overview API + UI tab
2. Task priority ranker (AI-scored via haiku)
3. Global worker pool router (cross-session max_workers cap)
4. Goal suggestion engine (post-convergence trigger)
5. `/brief` morning briefing skill

## Feature 1: Cross-project session overview

### API
Add to `orchestrator/server.py`:
```python
@app.get("/api/portfolio/overview")
async def portfolio_overview():
    sessions = registry.all()
    result = []
    for s in sessions:
        tasks = await s.task_queue.list()
        pending = sum(1 for t in tasks if t["status"] == "pending")
        running = sum(1 for t in tasks if t["status"] == "running")
        done = sum(1 for t in tasks if t["status"] == "done")
        failed = sum(1 for t in tasks if t["status"] == "failed")
        total_cost = sum(t.get("estimated_cost") or 0 for t in tasks)
        result.append({
            "session_id": s.session_id,
            "project_name": Path(s.project_dir).name,
            "status": "active" if running > 0 else "idle",
            "pending": pending, "running": running,
            "done": done, "failed": failed,
            "total_cost": round(total_cost, 4),
            "active_workers": len(s.worker_pool._workers) if hasattr(s, "worker_pool") else 0,
        })
    return result
```

Need to check: `registry.all()` method on `SessionRegistry` — verify it exists in session.py.

### UI
In `orchestrator/web/index.html`:
- Add "Portfolio" tab in nav bar (alongside existing tabs)
- Table: session name | pending | running | done | cost | status
- Click row → call existing session-switch logic (POST /api/sessions/switch or set active session)
- Fetch on tab open: `GET /api/portfolio/overview`

## Feature 2: Task priority ranker

### DB migration (task_queue.py `_ensure_db`)
```python
try:
    await db.execute("ALTER TABLE tasks ADD COLUMN priority_score REAL DEFAULT 0.0")
except Exception:
    pass
```

### config.py
Add `"priority_score"` to `_ALLOWED_TASK_COLS`.

### task_queue.py `list()`
Change `ORDER BY created_at` to `ORDER BY priority_score DESC, created_at ASC`.

### New endpoint (server.py)
```python
@app.post("/api/sessions/{session_id}/rank-tasks")
async def rank_tasks(session_id: str):
    session = _resolve_session(session_id)
    tasks = [t for t in await session.task_queue.list() if t["status"] == "pending"]
    if not tasks:
        return {"ranked": 0}
    desc_list = "\n".join(f'{t["id"]}: {t["description"][:120]}' for t in tasks)
    prompt = f'Score each task 0-100 by impact+urgency. Output only JSON array: [{{"id":"...","score":N}}]\n\nTasks:\n{desc_list}'
    proc = await asyncio.create_subprocess_exec(
        "claude", "--model", "claude-haiku-4-5-20251001", "-p", prompt,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    scores = json.loads(stdout.decode())
    for item in scores:
        await session.task_queue.update(item["id"], priority_score=float(item["score"]))
    return {"ranked": len(scores)}
```

### UI
"Rank" button in task queue header → POST to rank-tasks endpoint → reload queue.

## Feature 3: Global worker pool router

### config.py `_SETTINGS_DEFAULTS`
```python
"global_max_workers": 0,  # 0 = disabled, use per-session max_workers
```

### session.py `status_loop()` (before auto-start block)
```python
global_max = GLOBAL_SETTINGS.get("global_max_workers", 0)
if global_max > 0:
    total_running = sum(
        len(s.worker_pool._workers) for s in registry.all()
        if hasattr(s, "worker_pool")
    )
    if total_running >= global_max:
        continue  # skip this session's auto-start
```

### UI
In settings panel: "Global Max Workers" number input (0 = per-session limits apply).

## Feature 4: Goal suggestion engine

### session.py
Add `_completed_since_last_suggestion` counter (int, default 0) to `ProjectSession.__init__`.

When a task transitions to "done" in status_loop, increment the counter.

When `pending_count == 0 and running_count == 0 and session._completed_since_last_suggestion > 0`:
- Call `_suggest_goals(session)` as asyncio.ensure_future
- Reset `session._completed_since_last_suggestion = 0`

```python
async def _suggest_goals(session):
    progress_path = Path(session.project_dir) / "PROGRESS.md"
    vision_path = Path(session.project_dir) / "VISION.md"
    context = ""
    if progress_path.exists():
        lines = progress_path.read_text().splitlines()
        context += "PROGRESS (last 40 lines):\n" + "\n".join(lines[-40:]) + "\n\n"
    if vision_path.exists():
        lines = vision_path.read_text().splitlines()
        context += "VISION (first 60 lines):\n" + "\n".join(lines[:60]) + "\n\n"
    prompt = f"{context}Based on the above, suggest 3 specific, actionable next goals for this project. Be concrete."
    proc = await asyncio.create_subprocess_exec(
        "claude", "--model", "claude-haiku-4-5-20251001", "-p", prompt,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        out_path = Path(session.project_dir) / ".claude" / "suggested-goals.md"
        out_path.parent.mkdir(exist_ok=True)
        out_path.write_text(f"# Suggested Goals\n\n{stdout.decode()}")
        await session.broadcast({"type": "goals_suggested", "path": str(out_path)})
    except Exception as e:
        logger.warning("Goal suggestion failed: %s", e)
```

### UI
WebSocket handler for `goals_suggested` message → show toast notification "💡 Goals suggested — check .claude/suggested-goals.md".

## Feature 5: `/brief` morning briefing skill

### File: `configs/skills/brief/prompt.md`

```markdown
# Morning Brief Skill

Generate a morning briefing for all active Claude Code projects.

Steps:
1. List sessions from orchestrator: GET http://localhost:8000/api/portfolio/overview (if running)
   OR scan ~/.claude/projects/ for project directories
2. For each project directory found:
   - Run: git -C {project_dir} log --oneline --since="24 hours ago"
   - Read last 20 lines of PROGRESS.md if it exists
   - Read .claude/suggested-goals.md if it exists
   - Count done/failed tasks from the portfolio overview data
3. Generate a markdown morning brief:

# Morning Brief — {date}

## {project_name}
- 📝 Commits (N): <list of commits>
- ✅ Tasks done: N | ❌ Failed: N | 💰 Cost: $X
- 📚 Latest lesson: <last meaningful line from PROGRESS.md>
- 💡 Suggested next: <content from suggested-goals.md if exists>

---

Output the brief to stdout and also save to ~/.claude/morning-brief-{date}.md
```

## Verification Checklist

After implementation:
- [ ] `python -m py_compile server.py session.py task_queue.py config.py` — no errors
- [ ] `python -m pytest tests/ -v` — all 14 tests still pass
- [ ] `curl http://localhost:8000/api/portfolio/overview` — returns JSON array
- [ ] UI: Portfolio tab visible in nav
- [ ] UI: Rank button in queue header works
- [ ] UI: Toast appears when goals_suggested WebSocket event received
- [ ] `/brief` skill generates a formatted brief

## Key Files to Modify

- `orchestrator/server.py` — portfolio overview + rank-tasks endpoints
- `orchestrator/session.py` — global worker router + goal suggestion trigger + _suggest_goals()
- `orchestrator/config.py` — global_max_workers setting + priority_score in _ALLOWED_TASK_COLS
- `orchestrator/task_queue.py` — priority_score column + ORDER BY change
- `orchestrator/web/index.html` — Portfolio tab + Rank button + goals toast

## Key Files to Create

- `configs/skills/brief/prompt.md` — morning brief skill
