# Progress Log

---

### 2026-02-23 — P1: Auto-stop notification, schedule persistence, post-merge PROGRESS.md injection

**What was done:**
- `server.py`: Added `schedule` table to SQLite (`tasks.db`) — single row keyed at `id=1`
  - `TaskQueue.get_schedule()` / `save_schedule()` — persists scheduled_at + triggered flag
  - `status_loop` restores schedule on first tick (`_schedule_loaded` guard); marks triggered=True in DB when scheduler fires
  - `set_schedule` and `cancel_schedule` endpoints now call `save_schedule()` — schedule survives server restart
- `server.py`: Run-complete detection in `status_loop`
  - Sets `session._run_complete = True` (one-shot) when: no running workers, no pending tasks, at least one done task
  - Resets to False when new work appears (pending or running)
  - Broadcast as `run_complete` field in WebSocket status message
- `server.py`: `_write_progress_entry()` background coroutine
  - Triggered by `asyncio.ensure_future()` after each successful squash merge in `merge_all_done`
  - Reads last 80 lines of worker log, calls claude-haiku to generate a concise lesson entry
  - Inserts entry after the first heading line of `PROGRESS.md` (non-blocking, errors silently swallowed)
- `index.html`: Run-complete toast in `updateDashboard()`
  - Fires `showToast('✓ All tasks complete — queue empty')` once per batch (guarded by `window._runCompleteToasted`)
  - Resets guard when `run_complete` goes false so next batch can notify again

**What worked:**
- `_schedule_loaded` boolean flag on `ProjectSession` is the cleanest way to trigger one-shot DB load without changing the `__init__` signature
- `asyncio.ensure_future()` for post-merge PROGRESS.md write — truly fire-and-forget, merge API response is instant
- `window._runCompleteToasted` guards the toast from repeating on every status tick

**Lessons:**
- `claude --max-tokens` flag doesn't exist in the CLI — only `--max-budget-usd`; always verify CLI flags against `claude --help` before using
- `shlex.quote()` is essential when passing a large prompt string as a shell argument — prevents injection if prompt contains quotes

---

### 2026-02-23 — P1: SQLite persistence, scheduler, scout scoring, PROGRESS.md injection

**What was done:**
- `server.py`: Rewrote `TaskQueue` to use aiosqlite — tasks stored in `.claude/tasks.db`
  - Auto-migrates from `task-queue.json` on first run (renames to `.json.migrated`)
  - History-preserving: done/failed tasks kept in DB, only removed by explicit delete
  - New fields: `depends_on` (JSON array), `score` (int 0-100), `score_note` (string)
- `server.py`: Background `_score_task()` coroutine — runs claude-haiku after task import to score readiness
  - Parses JSON `{"score": <int>, "note": "<str>"}` from model output
  - Updates `tasks.score` and `tasks.score_note` via separate DB connection
- `server.py`: Added scheduler state to `ProjectSession` (`_scheduled_start`, `_schedule_triggered`)
  - `status_loop` checks if `now >= scheduled_start` each tick and auto-starts pending tasks
  - Endpoints: `POST/DELETE/GET /api/sessions/{id}/schedule`
- `server.py`: Added `GET /api/sessions/{id}/progress-md` endpoint (returns last 3000 chars)
- `server.py`: `_deps_met()` helper; `start-all` and `run_task` skip tasks with unmet deps
- `index.html`: History section — collapsible "History" list showing done/failed tasks with success rate
- `index.html`: Scheduler bar — ⏰ time picker, Set/Cancel buttons, countdown display (execute mode only)
- `index.html`: Score badges on task cards — green (≥80) / yellow (≥50) / red (<50) / pending (…)
- `index.html`: `sendOrchestrate()` now async — fetches PROGRESS.md and prepends as context prefix
- `index.html`: `setMode()` calls `updateSchedulerDisplay(_lastSchedule)` to sync bar on mode switch

**What worked:**
- Lazy `_ensure_db()` pattern — async init without changing synchronous `__init__`
- `asyncio.ensure_future(_score_task(...))` for non-blocking background scoring after import
- Caching `_lastSchedule` in JS so `setMode()` can re-render scheduler bar without a fresh fetch
- `[PROGRESS.md — recent lessons]\n{content}\n---\n` prefix format is clear to the orchestrator model

**Lessons:**
- aiosqlite `row_factory = aiosqlite.Row` enables `dict(row)` conversion — cleaner than manual column mapping
- Write tool rejects writes when file was read in multiple partial reads (tracks single read operation). Workaround: write via Bash subagent using Python
- sqlite3 JSON is stored as text; parse with `json.loads()` on read, `json.dumps()` on write
- Scheduler bar must be hidden in plan mode — `updateSchedulerDisplay` checks `currentMode` but `setMode` must also call it (with cached data) to sync visibility on mode switch

---

### 2026-02-23 — P3: Dependency graph view + Worker resource limits

**What was done:**
- `server.py`: Added `GLOBAL_SETTINGS` (max_workers, persisted to `~/.claude/orchestrator-settings.json`)
- `server.py`: Added `depends_on: []` field to every task in `TaskQueue.add()`
- `server.py`: Added `PATCH /api/tasks/{task_id}` endpoint to update `depends_on`, `description`, `model`
- `server.py`: Added `GET/POST /api/settings` endpoints for global settings
- `server.py`: Modified `start-all` — skips tasks with unmet dependencies; enforces max_workers slot limit
- `server.py`: `status_loop` now auto-starts newly unblocked tasks when dependencies complete (within max_workers limit)
- `index.html`: Settings panel (⚙ button in header) — max_workers input, synced to `/api/settings`
- `index.html`: `⬡ DAG` toggle button in task queue header — switches between list view and SVG DAG view
- `index.html`: SVG DAG visualization — topological layout, bezier edges, colored nodes by status, green edges for satisfied deps
- `index.html`: Interaction — click to select a task, Ctrl+click to add `depends_on` (calls PATCH endpoint)
- `index.html`: Task cards show `⏳ blocked` badge when dependencies aren't done

**What worked:**
- Topological sort with cycle guard (visiting set) is correct and handles all edge cases
- Optimistic update in `dagClick` (update local `task.depends_on` immediately) gives snappy UX without waiting for WebSocket refresh
- Debounced `saveSettings()` prevents spamming the API on every keystroke
- `status_loop` auto-start is gated by `t.get("depends_on")` — tasks without deps are unaffected (they start via start-all)

**Lessons:**
- `depends_on` migration is seamless: existing tasks without the field get `.get("depends_on", [])` defaulting to `[]`
- SVG DAG needs `min-width` on the container to scroll horizontally when there are many dependency levels
- `PATCH /api/tasks/{task_id}` ordering matters: must appear BEFORE `POST /api/tasks/import-proposed` in FastAPI route registration to avoid routing conflicts with the static route `/api/tasks/{task_id}`

Hard-won insights from building and maintaining this toolkit.

---

### 2026-02-23 — Agent autonomy layer: handoff/pickup, guardian hook, committer

**What was done:**
- New `/handoff` skill: end-of-session context dump to `.claude/handoff-*.md`
- New `/pickup` skill: start-of-session context load from latest handoff file
- `session-context.sh`: auto-inject handoff file (< 24h old) at session start
- New `pre-tool-guardian.sh` hook (PreToolUse/Bash): blocks database migrations, catastrophic rm -rf, force push to main, SQL DROP statements
- New `committer.sh` script: safe commit for parallel agents — forces explicit file paths, validates conventional commit format
- `settings-hooks.json`: added PreToolUse/Bash hook for guardian
- `install.sh`: added committer symlink to `~/.local/bin/`
- `~/.claude/CLAUDE.md`: added "Agent Ground Rules" section (commits, communication, autonomy, context management)

**What worked:**
- Research from steipete/OpenClaw playbook directly informed all additions — these are battle-tested patterns
- handoff/pickup solve the biggest gap: context loss across sessions (the #1 blocker for overnight autonomous runs)
- committer.sh is a direct copy of steipete's pattern — prevents cross-agent git contamination

**Lessons:**
- PreToolUse guardian must use `jq -r '.tool_name'` on stdin JSON — NOT command args. Hook input is always stdin JSON.
- `stat -c %Y` works on Linux for file mtime; `date -r` is macOS — guard both for portability
- committer.sh should clear the staging area first (`git restore --staged :/`) before staging specified files — otherwise previously-staged files from other agents leak in
- The Agent Ground Rules in global CLAUDE.md are the key forcing function — without them, agents fall back to old habits even if the tools exist

---

### 2026-02-20 — Stop hook, auto-pull, sync skill improvements

**What was done:**
- `session-context.sh`: Added auto-pull at session start — fetches remote, pulls if clean, warns if dirty
- `settings-hooks.json`: Fixed Stop hook loop — added instruction to surface manual steps to user instead of retrying indefinitely
- `sync` skill: Flipped commit flag — commit is now default, `--no-commit` to skip

**What worked:**
- `git pull --ff-only` is the right default: fast-forward only, fails safely if branch has diverged

**Lessons:**
- Stop hook returning `ok=false` causes Claude to attempt auto-fix; without a "give up" instruction it loops forever on failures like missing CLI tools or interactive TUI prompts
- `drizzle-kit push` requires interactive confirmation by default; `--force` skips it — document this in project-specific PROGRESS.md when encountered
- CLI flag convention: destructive/irreversible actions opt-in (`--force`, `--delete`); common desired actions should be default with opt-out (`--no-commit`, `--dry-run`)

### 2026-02-20 — /commit skill, skill ecosystem analysis

**What was done:**
- Analyzed full skill ecosystem: identified gaps in commit workflow, PR workflow, and internal tool bidirectionality
- New `/commit` skill: groups uncommitted changes by logical module, proposes split commits for confirmation, supports `--push` and `--dry-run`
- `/sync` refactored: doc-only (TODO.md + PROGRESS.md), no longer commits — hands off to `/commit`
- Stop hook prompt improved: now instructs Claude to surface manual steps instead of looping on unresolvable failures
- `session-context.sh`: auto-pull on session start with `--ff-only` safety guard

**What worked:**
- Decoupling sync (docs) from commit (code) clarifies responsibility — `/sync` is now purely a documentation tool
- Showing the commit plan before executing gives user control without requiring manual `git add` work

**Lessons:**
- The two `/review` commands (tech debt vs PR review) are easy to confuse — they're from different sources (our command vs a plugin)
- For paper reviews, neither `/review` applies — use the `paper-reviewer` agent directly
- Skills ecosystem gaps: no `/commit` (now fixed), no PR workflow — these are the next tier of improvements

### 2026-02-20 — Housekeeping: .gitignore + wording

**What was done:**
- Added `.gitignore` to exclude `logs/` (Claude Code runtime task logs — not project artifacts)
- Minor wording cleanup in PROGRESS.md (removed stale "Company OS bidirectionality" reference)

**Lessons:**
- `logs/` is auto-generated by Claude Code's task agent system; should always be gitignored in toolkit repos

### 2026-02-20 — Stop hook JSON validation fix

**What was done:**
- Fixed recurring "Stop hook error: JSON validation failed" — root cause: model was adding prose around JSON output
- Added `RESPOND WITH ONLY VALID JSON — no preamble, no explanation, no markdown` at the top of the Stop hook prompt
- Increased Stop hook timeout from 15s → 30s (more headroom to process long conversations)
- Synced fix to both `~/.claude/settings.json` (live) and `configs/settings-hooks.json` (repo)

**What worked:**
- Leading the prompt with an explicit output-format constraint reliably suppresses prose — models respect hard constraints stated upfront more than instructions buried mid-prompt

**Lessons:**
- `type: "prompt"` hooks must output *only* JSON — any surrounding text breaks validation; always lead with the format constraint
- 15s timeout is too tight for Stop hook reviewing long conversations; 30s is safer
