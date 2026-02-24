# Progress Log

---

### 2026-02-24 — Phase 4: GitHub Issues Sync

**What was done:**
- `server.py`: Added `gh_issue_number INTEGER` column to `tasks` table (schema + ALTER migration)
- `server.py`: `_format_issue_body()` / `_parse_issue_body()` — HTML comment metadata block (`<!-- orchestrator-meta ... -->`) keeps task_id, model, own_files, depends_on invisible on GitHub while description is freely editable
- `server.py`: `_gh_create_issue()` — creates GitHub Issue via `gh issue create`, parses issue number from URL, stores in DB. Fire-and-forget from POST /api/tasks and import-proposed
- `server.py`: `_gh_update_issue_status()` — updates labels (pending/running/done/failed) and closes issues on completion. Called from `poll_all()` when task reaches done/failed
- `server.py`: `_gh_pull_issues()` — fetches orchestrator-labeled issues, creates local tasks for new open issues, updates pending task descriptions from GitHub edits, deletes local pending tasks when issue closed on GitHub
- `server.py`: `_gh_push_all()` — pushes all local tasks to GitHub (create missing, update status on existing)
- `server.py`: REST endpoints `POST /api/issues/sync-pull` and `POST /api/issues/sync-push` with sync-disabled guard
- `server.py`: Settings `github_issues_sync` (bool, default off) + `github_issues_label` (str, default "orchestrator")
- `server.py`: `poll_all()` signature updated to accept `project_dir` for issue status sync on task completion
- `index.html`: Settings panel — checkbox for sync toggle + text input for label
- `index.html`: Sync button in queue header (hidden when sync disabled) — calls pull then push, shows toast
- `index.html`: Purple `#N` badge on tasks with linked GitHub issues

**Key design decisions:**
- Event-driven push + manual pull (no polling timer) — simple, no background load
- Conflict policy: pending tasks → phone edit wins; running/done → local wins
- Labels: `orchestrator` namespace + status labels for filtering
- All `gh` commands guarded by `github_issues_sync` setting — zero behavioral change when disabled (default)

**Lessons:**
- `gh issue create --label "a,b"` passes comma-separated labels as a single argument — works correctly
- Issue body HTML comments are invisible in GitHub's rendered markdown — perfect for metadata
- Fire-and-forget `asyncio.ensure_future` for issue creation keeps the task creation path fast — failures are logged but don't block the user

---

### 2026-02-24 — Phase 4: File Ownership Enforcement

**What was done:**
- `server.py`: Added `own_files`/`forbidden_files` TEXT columns to `tasks` table (schema + ALTER migration)
- `server.py`: `import_from_proposed()` now parses `OWN_FILES:` and `FORBIDDEN_FILES:` lines from task description body → stored as JSON arrays in DB
- `server.py`: `_row_to_dict()` deserializes both fields (same pattern as `depends_on`)
- `server.py`: `TaskQueue.add()` accepts `own_files`/`forbidden_files` params — used by requeue to preserve rules
- `server.py`: `Worker` class gains `own_files`, `forbidden_files`, `_ownership_violation`, `_ownership_violation_reason` fields; plumbed from task dict in `start_worker()`
- `server.py`: `_check_file_ownership(changed_files)` helper — checks forbidden glob matches and own-files allowlist; supports `dir/**` prefix patterns + `fnmatch` globs
- `server.py`: `verify_and_commit()` calls ownership check before haiku verify; on violation: `git checkout . && git clean -fd` to discard, returns False
- `server.py`: `poll_all()` detects `_ownership_violation` flag → requeues task with violation reason, preserves ownership rules, marks original as failed

**Lessons:**
- Ownership enforcement follows the same flag-bridge pattern as oracle requeue: set flag in Worker method (no queue access), pick up in `poll_all()` (has queue access)
- `fnmatch` handles simple globs well but `dir/**` needs special prefix-check logic — `fnmatch("src/db/schema.py", "src/db/**")` doesn't match in Python's fnmatch
- Lines are left in the description body so workers still see OWN_FILES/FORBIDDEN_FILES as guidance text — parsing is additive, not destructive

---

### 2026-02-24 — Phase 4: Swarm Mode (N-slot self-claiming workers)

**What was done:**
- `server.py`: `TaskQueue.claim_next_pending(done_ids)` — atomic CAS via `UPDATE ... WHERE status='pending'` with `rowcount > 0` check; SQLite serialized writes guarantee exclusivity without Python locks
- `server.py`: `SwarmManager` class — state machine (`idle → active → draining → done/stopped`); `_refill_loop()` runs every 0.5s, counts running workers, cleans finished, claims tasks via CAS, fills open slots; detects completion (`all_complete` or `blocked`)
- `server.py`: `ProjectSession._swarm` field + cleanup in `SessionRegistry.remove()` (force_stop on session teardown)
- `server.py`: `status_loop` guard — skips `auto_start` when swarm is active for that session; `poll_all()` still runs (timeouts, completions, oracle/handoff requeue)
- `server.py`: `swarm_state` added to WebSocket broadcast alongside `loop_state`
- `server.py`: 4 REST endpoints — `/swarm/start`, `/swarm/stop` (graceful/force), `/swarm/resize`, `GET /swarm`; registered before `/{session_id}` catch-all route
- `server.py`: Mutual exclusion — swarm rejects start if loop running; loop rejects start if swarm active
- `index.html`: Swarm control bar (execute mode) — slots input, start/stop/force-stop/resize buttons, status badge, progress line (`3/5 slots · 7 done · 2m 15s`), completion toast
- `index.html`: `updateSwarmUI()` called from `updateDashboard()`; swarm bar visibility toggled in `setMode()`

**Key design decisions:**
- SwarmManager wraps WorkerPool — existing Worker class (one-shot `claude -p`) unchanged; smarter scheduling on top
- `claim_next_pending` uses two connections: read candidates first, then atomic CAS update — avoids long-held locks
- Refill loop at 0.5s (2x faster than status_loop's 1s) for responsive slot filling
- Completion detection: `all_complete` (no pending tasks), `blocked` (pending but all deps unmet, nothing running), `drained` (manual stop), `force_stopped` (immediate kill)
- Global `max_workers` is respected as a ceiling — `to_fill = min(target_slots - running, global_available)`

**Lessons:**
- Swarm and iteration loop are fundamentally different dispatch models: swarm is pull-based (workers finish → manager claims next), loop is push-based (supervisor decides what to do each iteration). Mutual exclusion in v1 is the right call — combining them would require a complex priority system.
- SQLite CAS (`UPDATE WHERE status='pending'` + `rowcount > 0`) is sufficient for single-process concurrency — no need for a distributed lock. If we ever go multi-process, we'd need `BEGIN EXCLUSIVE` or a separate lock file.

---

### 2026-02-24 — Phase 3 complete: all 7 items done

**What was done (batch 2 — remaining 4 items):**
- `server.py`: `context_warning` bool in `to_dict()` — broadcasts via WebSocket for UI badge. Workers use `claude -p` (non-interactive) so stdin injection isn't possible without switching to PTY-based workers.
- `server.py`: `_on_worker_done()` — checks for `.claude/handoff-{task_id}.md` after verify+commit; reads content, sets `_handoff_requeue` flag; `poll_all` picks it up and creates continuation task with handoff context + `/pickup` instruction
- `orchestrate/prompt.md` + `SKILL.md`: Two-phase mode (`--plan`) — Phase 1 writes `IMPLEMENTATION_PLAN.md` (architecture, risks, execution order, file graph); Phase 2 decomposes plan into `proposed-tasks.md` with `OWN_FILES`/`FORBIDDEN_FILES` per task
- `loop-runner.sh`: Artifact marking — supervisor prompt now instructs workers to mark `- [ ]` → `- [x]` in goal file; all 3 worker footer templates include the reminder

**Lessons:**
- `claude -p` is non-interactive: reads task from argument, executes, exits. No stdin for mid-flight messages. True context injection requires switching workers to interactive `claude` sessions (PTY-based), which is a Phase 4+ architectural change.
- Handoff detection must happen BEFORE `_cleanup_worktree()` — the handoff file lives in the worktree directory and gets destroyed on cleanup
- Artifact marking via prompt instruction (not code enforcement) is the right approach — workers may complete partial work and shouldn't be forced to mark items done

---

### 2026-02-24 — Phase 3 quick wins: AGENTS.md prepend, oracle requeue, loop --stop

**What was done:**
- `server.py` `Worker.start()`: AGENTS.md auto-prepend alongside CLAUDE.md — checks `.claude/AGENTS.md` then `project_dir/AGENTS.md`, prepends as "File Ownership" block
- `server.py` `verify_and_commit()`: oracle rejection now flags `_oracle_requeue=True` with reason
- `server.py` `poll_all()`: picks up `_oracle_requeue` flag → re-queues task with rejection reason as retry context
- `loop-runner.sh`: SIGTERM/SIGINT trap for graceful shutdown (saves state + progress before exit)
- `loop-runner.sh`: STOP sentinel check at top of main loop — `/loop --stop` writes `STOP=true` to state file, loop exits after current iteration
- `/loop` skill: added `--stop` action (SKILL.md, prompt.md)

**Lessons:**
- Oracle requeue is best done in `poll_all` (has `task_queue` access) not in `verify_and_commit` (Worker method, no queue access) — use a flag bridge pattern
- AGENTS.md search order: `.claude/AGENTS.md` first (generated by orchestrator endpoint), then project root `AGENTS.md` (manually maintained)
- Loop stop via sentinel file is simpler than PID-based kill — works cross-session without tracking process IDs

---

### 2026-02-24 — Security & correctness round 5: 7 backend + 6 frontend fixes

**What was done:**
- `server.py`: `push_proc` and `merge_proc` kill+drain on TimeoutError — completes the subprocess timeout audit
- `server.py`: `_ALLOWED_LOOP_COLS` allowlist for `upsert_loop` UPDATE (parallel to `_ALLOWED_TASK_COLS`)
- `server.py`: `SessionRegistry.remove()` now stops all running/starting/paused workers with `ensure_future(w.stop())`
- `server.py`: `import_from_proposed` normalizes model alias via `_MODEL_ALIASES`; `retry_failed` does too
- `server.py`: `wt_proc` (first worktree attempt) now has explicit TimeoutError → kill+drain handler
- `server.py`: `verify_and_commit` git diff/ls-files initial calls now have TimeoutError → kill+drain → return False
- `index.html`: `renderQueue` onclick wraps `task.id` with `esc()`
- `index.html`: `blockedBy.join(', ')` in title attribute now wrapped with `esc()`
- `index.html`: `#loopK`/`#loopN` now have `oninput="this._userEdited=true"`; `loadSettings` corrected from `_userSet` → `_userEdited`; `updateLoopUI` resets flag on idle/converged/cancelled
- `index.html`: `setMode('execute')` hides `proposedOverlay`
- `index.html`: `switchTab()` clears `_logRefreshInterval` to prevent cross-session log polling
- `index.html`: `decodeHtml()` helper added; `openWorkerLog`/`openWorkerChat` use it to prevent double-encoding

**Lessons:**
- Subprocess timeout audit must include ALL `asyncio.wait_for(proc.communicate())` calls, including git push, gh pr merge, git diff, git ls-files — not just the "main" subprocess. A structured audit pattern: grep for `wait_for.*communicate` and verify each site has kill+drain in TimeoutError handler.
- `session.remove()` must be treated as a full resource teardown — workers, tasks, loop coroutine, watch task, and WebSocket subscribers all need explicit cleanup.
- `loadSettings` guard flag naming must exactly match the flag set by the input handler — `_userSet` vs `_userEdited` discrepancy silently disables the guard.

---

### 2026-02-24 — Security & correctness round 4: 6 backend + 5 frontend fixes

**What was done:**
- `server.py`: `verify_and_commit` TimeoutError now kills subprocess (was the only remaining unpatched timeout path)
- `server.py`: `post_settings` key allowlist — only `_SETTINGS_DEFAULTS` keys accepted; arbitrary injection blocked
- `server.py`: `create_task`/`create_session`/`switch_project` — `body["key"]` → `.get()` + `HTTPException(400)`; `{"error":...}` 200 responses → `HTTPException(400)`
- `server.py`: `_run_supervisor` supervisor subprocess now kill+drain on TimeoutError
- `server.py`: `upsert_loop` INSERT now includes `mode` column — plan_build mode no longer silently reverts to 'review' on first start
- `server.py`: `wt_proc2` in `Worker.start()` now kill+drain on TimeoutError
- `index.html`: `runAllTasks()` / `retryAllFailed()` — button disabled during fetch (double-submit prevention)
- `index.html`: `broadcastAll()` — button disabled during fetch; `broadcastBtn` id added to HTML
- `index.html`: keyboard shortcut listener now skips when xterm `.xterm-helper-textarea` has focus
- `index.html`: `updateLoopUI()` syncs loopArtifact/contextDir/K/N from live loop_state on page reload; `_userEdited` flag prevents overwriting manual edits
- `index.html`: `renderHistory` t.status now wrapped in `esc()` for CSS class + inner text

**Lessons:**
- When applying a "kill subprocess on TimeoutError" fix, audit EVERY `asyncio.wait_for(proc.communicate(), ...)` call in the file — it's easy to fix the obvious ones and miss one in a utility function like `verify_and_commit`.
- Settings endpoints that accept arbitrary dicts must validate against a known-good key set before merging into global state — `dict.update(body)` is never safe.
- xterm.js captures keyboard input via a hidden `<textarea class="xterm-helper-textarea">` — checking `document.activeElement.tagName` for INPUT/TEXTAREA is insufficient because xterm also uses a textarea but it's the `document.activeElement`.

---

### 2026-02-24 — Security & correctness round 3: 8 backend + 5 frontend fixes

**What was done:**
- `server.py`: `_MODEL_ALIASES` dict — short aliases ("haiku"/"sonnet"/"opus") now map to full model IDs; auto_model_routing was previously a complete no-op
- `server.py`: `asyncio.wait_for` TimeoutError now kills the subprocess before draining — prevents zombie accumulation in `_score_task`, `_oracle_review`, `_write_progress_entry`, `_write_pr_review`
- `server.py`: `status_loop` `_newly_ready` filter — removed `and t.get("depends_on")` so no-dep tasks auto-start too; wrapped with `GLOBAL_SETTINGS.get("auto_start", True)` so toggle is respected server-side
- `server.py`: `start_loop` endpoint now reads `mode` from request body and passes to `upsert_loop`
- `server.py`: `OrchestratorSession.stop()` now cancels `_read_task` alongside PTY termination
- `server.py`: `status_loop` exception logged via `logger.exception()` instead of silently swallowed
- `server.py`: `_upsert_lock` on `TaskQueue` prevents TOCTOU race in `upsert_loop`
- `server.py`: `_write_progress_entry` file I/O moved to `asyncio.to_thread`
- `index.html`: `loopStartBtn` id added — double-submit prevention in `startLoop()` now actually works
- `index.html`: `confirmProposed()` wrapped in try/catch with toast on failure
- `index.html`: `addTask()` wrapped in try/catch; textarea value preserved on error
- `index.html`: `connectStatus()` onerror schedules reconnect (for browsers where onclose doesn't fire)
- `index.html`: `renderOverview()` inner `sessions` var renamed to `overviewData` (was shadowing outer module var)

**Lessons:**
- Short model aliases in settings/routing must be normalized before the allowlist check — easy to miss because fallback to default model is silent and the feature "works" just with the wrong model.
- `asyncio.wait_for` cancels the coroutine but NOT the underlying subprocess — always `proc.kill()` + `await proc.communicate()` in the TimeoutError handler.
- `t.get("depends_on")` is falsy for `[]` — conditions like `and t.get(field)` silently exclude items with empty lists. Use explicit `is not None` or just drop the guard.
- `auto_start` toggle was frontend-only; the server always auto-started via `status_loop`. Settings toggles need to be enforced at both layers.

---

### 2026-02-23 — Security hardening round 2: 8 more backend + 4 frontend fixes

**What was done:**
- `server.py`: `shlex.quote(str(task_file))` in `Worker.start()` — path with spaces no longer breaks shell cmd
- `server.py`: `_ALLOWED_TASK_COLS` allowlist in `TaskQueue.update()` — blocks SQL injection via rogue column names
- `server.py`: Worker dedup guard now checks `status in ("running", "starting")` — prevents double-spawn during startup race
- `server.py`: `shlex.quote(branch)` in `merge_all_done` — fixes gh pr create injection via branch name
- `server.py`: `asyncio.Lock` wraps `_ensure_db` — prevents concurrent double-initialization
- `server.py`: `asyncio.to_thread(target.read_text)` in `_watch_session_proposed_tasks` — unblocks event loop on large files
- `server.py`: `asyncio.to_thread(scan_projects, ...)` in GET /api/projects — directory scan no longer blocks event loop
- `server.py`: Empty supervisor response guard in `_run_supervisor` — 3 consecutive empty responses → cancel loop, prevents infinite spin
- `index.html`: Worker Chat/Log buttons use `data-wid`/`data-name` + `this.dataset.*` — eliminates backslash-injection risk in onclick
- `index.html`: Worker Pause/Resume/Chat/Log buttons have deterministic `id="btn-*-{wid}"` — focus restoration now actually works
- `index.html`: `startLoop()` POSTs `max_iterations` + `supervisor_model` from settings panel
- `index.html`: `confirmProposed()` passes `_lastProposedContent` in POST body — no longer depends on stale disk file

**Lessons:**
- `asyncio.Lock` must wrap the entire `_ensure_db` including the `if _initialized: return` check — setting the flag before the first await is insufficient because coroutines can interleave between the check and the flag set.
- `data-*` attributes + `this.dataset.*` are the correct pattern for all onclick handlers that involve user-controlled strings — `esc()` is HTML-safe but not JS-string-safe.
- Always quote branch names in shell commands — branch names containing `/`, `-`, or `.` are fine but names containing spaces or special chars (e.g., from automated tooling) silently break the command.

---

### 2026-02-23 — Security hardening: 8 backend + 5 frontend fixes

**What was done:**
- `server.py`: ALTER TABLE TOCTOU — moved migration into same aiosqlite connection as CREATE TABLE
- `server.py`: `shlex.quote()` on all user-controlled paths in `_score_task()` and `verify_and_commit()`
- `server.py`: Wrong model alias "haiku" → "claude-haiku-4-5-20251001" in `verify_and_commit()`
- `server.py`: Blocking `open()` fd leak fixed with `try/finally` in `Worker.start()`
- `server.py`: Worker dedup guard — same task_id cannot spawn two concurrent workers
- `server.py`: Blocking `_save_settings()` moved to `asyncio.to_thread()` in POST /settings endpoint
- `server.py`: `_loop_task` now cancelled (alongside `_watch_task`) in `SessionRegistry.remove()`
- `server.py`: `_run_supervisor()` respects `max_workers` limit before spawning FIXABLE/DATA_CHECK workers
- `index.html`: Token bar denominator corrected `/ 2000` → `/ 200000 * 100` (was always 100%)
- `index.html`: `sessionId` (undefined var) fallback removed in `broadcastAll()` and `generateAgentsMd()`
- `index.html`: XSS in `loadProjects()` onclick replaced with `data-*` attribute + `addEventListener`
- `index.html`: Focus preservation before/after `renderWorkers()` innerHTML replacement
- `index.html`: Start Loop button disabled during fetch (double-submit prevention)

**Lessons:**
- Token bar at constant 100% is a silent bug — no error, just misleading UI. Always check the denominator against the actual context window size.
- `sessionId` as a bare variable inside an async function looks like it could reference an outer scope — always use explicit globals (`activeSessionId`) to avoid the silent undefined fallback.
- `esc()` escapes HTML entities but doesn't prevent JS injection in onclick attributes if the attacker controls quotes. DOM manipulation is always safer than innerHTML+onclick templates.
- TOCTOU on SQLite schema migration: using two sequential `async with aiosqlite.connect()` blocks means the second block may not see the first's commit. Always do related DDL+DML in one connection.

---

### 2026-02-23 — P3/P4/CC-CLI: Oracle, Broadcast, Model Routing, Context Budget, AGENTS.md, Hooks

**What was done (5-task parallel batch):**
- `server.py`: `_oracle_review()` — haiku diff review after auto_commit; gates auto_push; oracle result in to_dict()
- `server.py`: `_estimate_tokens()` — worker method; estimates from description + log size; poll_all writes context-warning-{id}.md at >160K
- `server.py`: `start_worker()` — score-based model routing (haiku ≥80 / sonnet 50-79 / sonnet+clarify <50) when `auto_model_routing` is ON; sets `worker.model_score`
- `server.py`: `broadcast_to_workers()` endpoint — stops workers, injects message into task description, restarts
- `server.py`: `get_agents_md()` endpoint — git log-based file→branch ownership map, returns AGENTS.md block
- `server.py`: `ALTER TABLE iteration_loops ADD COLUMN mode` (idempotent); `_run_supervisor()` reads mode at top of each iteration (stub for plan_build)
- `index.html`: broadcast bar (hidden by default, shown in execute mode); oracle badge + model/score in worker card; token bar (3px strip under commit hash)
- `index.html`: loopMode selector (review/plan_build) in loop control bar
- `index.html`: File Ownership section + Quality Gates section in settings panel; broadcastAll() + generateAgentsMd() JS functions
- `orchestrate/prompt.md`: Step 0 (read PROGRESS.md + AGENTS.md before planning); enhanced task template (verify_cmd, own_files, forbidden_files, acceptance, Context Management, Commit Rules); Step 3.5 (auto-generate AGENTS.md from own_files)
- `batch-tasks/prompt.md`: AGENTS.md check in planning phase (step 3); scout_threshold config from orchestrator.json; low-score-tasks.md for below-threshold items
- `~/.claude/hooks/post-tool-use-lint.sh`: runs verify_cmd after Write/Edit; writes lint-feedback.md; exits 2 on failure to surface back to Claude
- `~/.claude/hooks/post-commit-verify.sh`: runs verify_cmd after commit (only when CLAUDE_POST_COMMIT_VERIFY=1); reverts HEAD on failure; writes to blockers.md
- `~/.claude/settings.json`: registered post-tool-use-lint.sh as second PostToolUse hook (alongside post-edit-check.sh)

**What worked:**
- Parallel batch (`/batch-tasks --parallel all todos`) ran tasks 1 (server.py) and 2 (index.html) simultaneously — wall time ~8 min instead of 15+ sequential
- Tasks 3/4/5 (prompt + hooks) ran serially after task 2 — they edit `~/.claude/` files outside the git repo, so no merge needed
- All 5 task logs confirmed success; py_compile passes on server.py; JSON validation passes on settings.json
- Agents editing absolute paths (main repo) instead of worktree paths is acceptable when tasks don't create commits — the batch runner merges worktree commits, but these tasks just edited files directly

**Watch out for:**
- Broadcast endpoint currently stops running workers and restarts them — this loses in-progress Claude context for those workers; use sparingly or only for new context (not corrections mid-task)
- Oracle review (`_oracle_review`) runs haiku with the diff; haiku may approve code it doesn't fully understand — it's a syntactic sanity check, not a semantic review
- `context-warning-{id}.md` is written but NOT auto-injected into the worker process (no stdin/PTY mechanism yet) — the file exists for manual inspection; the auto-inject bullet remains open
- PLANNING/BUILDING loop phase is stub only — `_run_supervisor()` reads `mode` but doesn't implement the two-phase logic yet
- Oracle rejection currently blocks push but doesn't re-queue the task — fourth oracle bullet remains open

---

### 2026-02-23 — Bug fix: worker code loss (verify/cleanup race condition)

**What was done:**
- `server.py`: Fixed race condition where `verify_and_commit()` ran concurrently with `_cleanup_worktree()`, causing the worktree to be deleted before git diff/commit could run
- `server.py`: Added `_original_project_dir` to Worker to survive worktree path reassignment
- `server.py`: Added `_on_worker_done()` coroutine — runs verify first, then cleanup, sequentially
- `server.py`: `poll()` now schedules `_on_worker_done()` (not `_cleanup_worktree()` directly)
- `server.py`: Removed duplicate `verify_and_commit()` trigger from `poll_all()` (now handled inside `_on_worker_done()`)
- `server.py`: `_cleanup_worktree()` restores `_project_dir = _original_project_dir` so later git cmds still have a valid cwd
- `server.py`: `stop()` now delegates to `_cleanup_worktree()` (DRY, uses same `_original_project_dir` cwd)

**What worked:**
- The sequential `await verify_and_commit(); await _cleanup_worktree()` pattern completely closes the race — worktree exists for the full duration of verification

**Watch out for:**
- Workers can still exit with rc=0 and produce no commits (claude says "Done" without using committer). The verify step handles this: if no changed files found → returns False; the task stays "done" but without auto_committed=True, so no push/PR happens. This is acceptable — the bigger bug (code silently lost) is now fixed.
- `_original_project_dir` must be set in `__init__` before `start()` can overwrite `_project_dir`

---

### 2026-02-23 — P3: Iteration Loop (Ralph-style Supervisor)

**What was done:**
- `server.py`: Added `iteration_loops` DB table (artifact_path, status, iteration, changes_history, deferred_items, convergence params)
- `server.py`: `TaskQueue.get_loop()`, `upsert_loop()`, `delete_loop()` — pattern mirrors `get_schedule`/`save_schedule`
- `server.py`: `ProjectSession._run_supervisor()` coroutine — reads artifact, calls supervisor model with JSON-only prompt wrapped in `---ARTIFACT---` delimiters, parses findings, spawns FIXABLE/DATA_CHECK workers, accumulates DEFERRED items, waits for workers, checks convergence
- `server.py`: 5 loop endpoints (`/loop/start`, `/loop`, `/loop/pause`, `/loop/resume`, `DELETE /loop`) all registered before `/{session_id}` routes
- `server.py`: `status_loop()` now includes `loop_state` in every WebSocket broadcast
- `server.py`: 4 new `_SETTINGS_DEFAULTS` keys: `loop_supervisor_model`, `loop_convergence_k/n`, `loop_max_iterations`
- `index.html`: Loop control bar (execute-mode only) with artifact input, K/N inputs, Start/Pause/Resume/Cancel buttons, sparkline canvas, convergence label
- `index.html`: Deferred items accordion below loop bar; auto-expands on convergence
- `index.html`: `updateLoopUI()` function wired into `updateDashboard()` via `data.loop_state`
- `index.html`: `drawSparkline()` renders mini bar chart of changes_history on `<canvas>`
- `index.html`: 4 new settings panel rows + `loadSettings()`/`saveSettings()` wired

**What worked:**
- `re.search(r'\[.*\]', response, re.DOTALL)` reliably extracts JSON array even when supervisor wraps it in prose
- Using `---ARTIFACT---` / `---END---` delimiters prevents the artifact content from confusing the supervisor prompt
- `delete_loop()` + fresh `upsert_loop()` on start avoids partial field pollution from previous runs
- Loop coroutine is stored as `session._loop_task` — cancellable via `task.cancel()` for pause/stop

**Watch out for:**
- `upsert_loop()` only updates the fields you pass (partial update) — callers that want a full reset must call `delete_loop()` first (as `start_loop` endpoint does)
- Convergence checks `changes_history[-n:]` — the list must have at least N entries before convergence is possible; initial iterations with few spawned tasks won't trigger it prematurely
- Loop badge CSS classes (`idle`, `running`, `paused`, `converged`, `cancelled`) must be defined — they're now added alongside existing `badge.*` definitions

---

### 2026-02-23 — fix: dead settings and UI bugs (auto_review, default_model, orchestrate, toast)

**What was done:**
- `server.py`: `auto_review` — implemented `_write_pr_review()` coroutine; fires after PR creation if setting is ON
  - Gets PR diff via `gh pr diff`, calls haiku for 3-5 bullet review, posts via `gh pr comment`
  - Fire-and-forget (`asyncio.ensure_future`), never blocks the merge pipeline
- `server.py`: `default_model` — 3 callers now respect `GLOBAL_SETTINGS.get("default_model")`:
  - `create_task` endpoint, `import_from_proposed()` parser default, `retry_failed` endpoint
  - Pattern: `body.get("model") or GLOBAL_SETTINGS.get("default_model", "sonnet")`
- `index.html`: Orchestrate button — removed unreliable 100ms `setTimeout`; both sends now go synchronously (PTY buffers and sequences them correctly)
- `index.html`: run-complete toast — replaced global `window._runCompleteToasted` boolean with per-session Map; toast now fires per-project with project name in message

**What worked:**
- `or` pattern (`body.get("model") or GLOBAL_SETTINGS.get(...)`) correctly handles both `None` and empty string from callers
- Fire-and-forget pattern (`asyncio.ensure_future`) keeps merge endpoint fast even with haiku review latency
- PTY buffer sequencing: removing the setTimeout doesn't cause race conditions since the PTY serializes stdin reads naturally

**Lessons:**
- Settings that exist in `_SETTINGS_DEFAULTS` but have no runtime `GLOBAL_SETTINGS.get()` call are invisible bugs — adding a setting key is not enough; must audit every callsite that should use it
- `setTimeout(..., 100)` as a "wait for PTY to process" is a smell — the PTY already buffers; the delay just introduces fragility

---

### 2026-02-23 — P2: Multi-Project Dashboard + Settings Panel

**What was done:**
- `server.py`: Expanded `_SETTINGS_DEFAULTS` with 5 new keys: `auto_start`, `auto_push`, `auto_merge`, `auto_review`, `default_model`
  - `_load_settings()` now merges over defaults — backward compatible (existing files just have `max_workers`)
- `server.py`: `auto_push` gate in `verify_and_commit()` — push block skipped when `auto_push=False`
- `server.py`: `auto_merge` gate in `merge_all_done()` — squash merge skipped when `auto_merge=False`
- `server.py`: `GET /api/sessions/overview` endpoint — aggregates pending/running/done/failed per session, computes ETA
  - **Route ordering**: registered BEFORE `/{session_id}` to avoid FastAPI routing conflict
- `server.py`: `POST /api/sessions/start-all-queued` — starts pending tasks across ALL sessions at once
  - Respects `max_workers` per session, skips tasks with unmet deps
- `index.html`: Multi-project overview section (execute mode, hidden when only 1 session)
  - Progress bar fill, running/done/failed counts, ETA label
  - Click a row to `switchTab()` to that session
- `index.html`: `▶▶ Start All Queued` button — calls `/api/sessions/start-all-queued`
- `index.html`: Settings panel expanded from 1 field to 6
  - Checkboxes for auto_start, auto_push, auto_merge, auto_review; model dropdown; max_workers number input
  - `loadSettings()` populates all 6 fields + syncs `autoStartToggle` in chat header
  - `saveSettings()` sends all 6 keys (debounced 400ms)
- `index.html`: `setMode('execute')` starts `_overviewInterval` (8s poll); `setMode('plan')` clears it
- `index.html`: `switchTab()` now calls `renderOverview()` to update active row highlight
- `index.html`: Footer success rate span — `renderHistory()` also updates `#footerSuccessRate`

**What worked:**
- Python script bulk edits (vs Edit tool) essential when formatter hook races with sequential edits
- `_SETTINGS_DEFAULTS` dict + `defaults.update(loaded)` pattern is clean and backward-compatible
- Route ordering is easily verified with `grep -n "app.get.*sessions\|app.post.*sessions"` after insertion

**Lessons:**
- The formatter PostToolUse hook (`post-edit-check.sh`) runs asynchronously and can modify files between Edit tool calls — causes "file modified since read" errors on rapid sequential edits. Use Python bulk transforms to make all changes atomically.
- Always verify FastAPI route order for static vs parameterized routes (`/overview` before `/{session_id}`)
- HTML replace via Python: always `print(repr(content[idx-5:idx+100]))` to verify exact bytes before building search string — Unicode box-drawing chars look similar but differ in byte count

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

### 2026-02-24 — Loop mode first run + plan_build implementation

**What was done:**
- Ran loop-1 using `LOOP_ARTIFACT.md` as the artifact with 6 workers for 6 open tasks
- One worker (plan_build task) produced 169-line implementation of `_run_plan_build()` — committed
- Other 5 workers completed without commits (tasks may have been description-only or worker didn't use committer)
- Fixed `_run_supervisor()` to dispatch to `_run_plan_build()` when `mode == "plan_build"`

**plan_build implementation details:**
- PLAN phase: reads artifact + codebase file listing → calls `claude -p` → writes `IMPLEMENTATION_PLAN.md`
- BUILD phase: finds first `- [ ] item` → spawns one worker → polls until done → marks `[x]` → loops
- DB schema: added `plan_phase TEXT DEFAULT 'plan'` column with ALTER TABLE migration guard
- All subprocess calls wrapped with `asyncio.wait_for()` timeouts (30s/300s/10s)

**What worked:**
- Workers operating in worktrees can still modify the main `server.py` (worktree isolation is per-branch, not per-file)
- Loop supervisor correctly spawns 6 workers from a 6-task artifact without deadlocking

**Lessons:**
- Workers in loop mode write changes to the worktree branch — changes are NOT auto-committed back to main unless `verify_and_commit()` succeeds
- If loop coroutine is interrupted (server restart), `changes_history=[]` stays empty and loop status stays `running` — must Cancel + restart the loop
- Workers tend to describe changes in output rather than actually implement them; the fix is better prompting in `start_worker()` (AGENTS.md, CLAUDE.md prepend)
- The `_run_plan_build()` BUILD phase tight-loop (poll every 3s) is correct — no asyncio.sleep(0) needed since we're waiting for external process

### 2026-02-24 — /loop CLI skill

**What was done:**
- Implemented `~/.claude/scripts/loop-runner.sh` — autonomous supervisor+worker loop in pure bash
- Implemented `~/.claude/skills/loop/` (SKILL.md + prompt.md) — `/loop` skill with context enrichment
- Loop runner: supervisor (`claude -p`) reads artifact → outputs next task or `STATUS: CONVERGED` → worker via `run-tasks.sh`
- Skill: generates `loop-context.md` from codebase exploration (key optimization — saves tokens on every supervisor call)
- Supports: `--status`, `--dry-run`, `--resume`, `--model`, `--worker-model`, `--max-iter`

**Key design decisions:**
- Supervisor uses `claude -p` (non-interactive, cheap); workers use full `claude --dangerously-skip-permissions` via run-tasks.sh
- State file is plain KEY=VALUE (no JSON dependencies); progress file format matches run-tasks.sh
- `unset CLAUDECODE` allows nested claude calls from within Claude Code session
- Context file (loop-context.md) is generated once per launch by the skill, then reused each iteration

**Lessons:**
- CLI loop vs web UI loop: CLI loop is safer for self-modification (script is external to codebase); web UI is better for parallel workers + real-time monitoring
- The skill's context enrichment step is where it adds value over raw bash — the skill session has full codebase context that the background `claude -p` calls lack
