# TODO — Claude Code Orchestrator Redesign

**North star:** Plan once, run overnight, wake up to hundreds of commits.
**UX principle:** Every action must be completable in the minimum possible clicks.
If two steps can become one button or one setting, they must.

---

## P0 — Plan/Execute UI Split (highest immediate value)

The current UI forces constant context switching between planning and monitoring.
Split into two modes; the brain stays in one mode at a time.

- [x] **Plan mode layout**: Terminal takes 70% width; right sidebar shows live Task Backlog
  - Task Backlog syncs automatically from `proposed-tasks.md` (already wired via WebSocket)
  - Tasks are editable inline (click to edit description, drag to reorder, × to delete)
  - No separate "Import Proposed" button needed — file changes auto-populate the sidebar
- [x] **"⚡ Orchestrate" one-click button** in Plan mode header
  - Sends `/orchestrate\r` to the active PTY — replaces manual typing
  - Optionally: input field next to it so user types goal → click → sends `{goal}\r/orchestrate\r`
- [x] **"Auto-start" toggle** (default: ON)
  - When ON: proposed-tasks are auto-imported + all workers auto-started the moment `proposed-tasks.md` is written
  - No overlay, no extra click — set it once and walk away
  - When OFF: overlay appears for manual review (current behavior)
- [x] **Execute mode layout**: Full-width worker dashboard, no terminal unless you need to intervene
  - Top bar: per-project progress bars (all projects at once)
  - Worker rows: task name | status badge | elapsed | commit hash | pushed? | [Log] [Retry]
  - Terminal hidden by default; [Intervene] button opens a slide-in terminal panel for that session
- [x] **Mode toggle** in header: `[📋 Plan]  [▶ Execute]` — one click to switch

---

## P0 — Git Worktree Isolation (code safety, required before overnight runs)

Without this, parallel workers on the same repo will corrupt each other's changes.

- [x] **Worker spawns in its own git worktree**
  - On worker start: `git worktree add .claude/worktrees/worker-{id} -b orchestrator/task-{id}`
  - Worker's `cwd` is the worktree path, not the main repo
  - On worker done/failed: worktree is cleaned up (`git worktree remove --force`)
- [x] **Auto-push to feature branch after each commit** (setting, default: ON)
  - After `verify_and_commit()` succeeds: immediately `git push origin orchestrator/task-{id}`
  - "Committed" status in UI shows: `✓ committed · ✓ pushed` or `✓ committed · ⏳ pushing`
  - Code is safe on remote the moment it's done — no batch push needed
- [x] **"Merge All Done" → AI PR Pipeline** in Execute mode
  - For each `done + auto_pushed` worker: `gh pr create --head {branch} --base main --fill`
  - Worker card shows PR URL after creation
  - **Auto-merge logic**: if branch matches `orchestrator/task-*` (spawned by us) → squash merge automatically after PR created; no human review needed — "ship it, fix bugs later"
  - External PRs (branches not matching `orchestrator/task-*`) → manual review required

---

## P0 — AI PR Skills (the OpenClaw pipeline)

Three slash skills that make the PR lifecycle AI-native — parallel to OpenClaw's `/review-pr → /prepare-pr → /merge-pr`.

- [x] **`/review-pr`** — AI reads PR diff, writes structured review as PR body comment
  - Triggered automatically after PR creation if `auto-review` setting is ON
  - Output: summary of changes, risks, suggestions — posted to PR via `gh pr comment`
- [x] **`/merge-pr`** — squash merge + branch cleanup
  - For `orchestrator/task-*` branches: triggered automatically after PR creation
  - For external PRs: triggered manually by user
  - After merge: `git branch -d {branch}` + `git worktree remove`
- [x] **Worker self-verification** before marking done
  - After `verify_and_commit()`, run project-defined check command (e.g. `npm run build`, `pytest`, `tsc --noEmit`)
  - Pass → status = done; Fail → status = failed, check output appended to failure_context
  - Check command configured per-project in `.claude/orchestrator.json` → `"verify_cmd": "npm run build"`

---

## P1 — Retry with Lessons Learned

Current blind retry wastes worker time repeating the same mistake.

- [x] **Capture failure context** when worker exits with non-zero code
  - Extract last 50 lines of worker log as `error_summary`
  - Store in task record: `failed_reason`
- [x] **Inject failure context into retry task**
  - Retry task description = original description + `\n\n---\nPrevious attempt failed:\n{error_summary}\nDo NOT repeat the same approach.`
  - Max retries configurable per task (default: 2)
- [x] **"Retry All Failed" button** in Execute mode
  - One click to requeue all failed tasks with their error context injected
  - No need to manually inspect each failure and re-create tasks

---

## P1 — SQLite Persistence

JSON files lose history on server restart and can't be queried across projects.

- [x] **Migrate from JSON to SQLite** (`aiosqlite`)
  - Tables: `tasks` (history-preserving — done/failed tasks kept, just marked)
  - Auto-migrates from `task-queue.json` on first startup
- [x] **Task history view** in Execute mode
  - Expandable "History" section showing done/failed tasks
  - Success rate per project (done / total attempted) shown in header
- [x] **Cross-session persistence**: task queue survives server restart

---

## P1 — Project Context Injection

Workers currently run "blind" without knowing the project's tech stack or constraints.

- [x] **Auto-inject CLAUDE.md into task description**
  - When a task is created for a project, prepend the project's `.claude/CLAUDE.md` content
  - Worker knows the stack, conventions, and what NOT to do before it starts
- [x] **Task dependency support** (`depends_on: [task_id]`)
  - Scheduler holds dependent tasks in "waiting" state until dependencies are done
  - DAG view in Plan mode — click node, Ctrl+click to add dependency edge
  - Prevents "write frontend calls" starting before "write API" is done

---

## P2 — Global Multi-Project Dashboard

One screen to rule all overnight runs across all projects.

- [x] **Multi-project overview** at top of Execute mode
  - Each project: name | progress bar | running/done/failed counts | ETA
  - Click to drill into that project's workers
- [x] **Global "Start All Queued"** button
  - Starts all pending tasks across all open project sessions at once
- [x] **Success rate metrics**
  - Per project: % tasks done successfully, avg time per task
  - Displayed in Execute mode footer

---

## P2 — Settings Panel (set once, run forever)

One-time configuration so every session runs the same way without manual setup.

- [x] **Auto-start workers** when proposed tasks arrive (ON/OFF)
- [x] **Auto-push** to feature branch after commit (ON/OFF)
- [x] **Auto-merge** for `orchestrator/task-*` branches (ON/OFF, default ON)
- [x] **Auto-review** run `/review-pr` after PR creation (ON/OFF, default ON)
- [x] **Default model** per task priority (opus/sonnet/haiku)
- [x] **Max parallel workers** per project
- [x] **Settings persist** in `~/.claude/orchestrator-settings.json` (server-side)

---

## P1 — Scheduled Overnight Runs

North star is "run overnight, wake up to commits" — this is P1, not a nice-to-have.

- [x] **"Start at HH:MM" scheduler** in Execute mode header
  - User sets time → server queues start; workers auto-launch at scheduled time
  - UI shows countdown: "Starting in 4h 23m" with cancel button
- [x] **Auto-stop when queue empty**: server stays up but workers idle; no runaway costs
- [x] **Persist schedule across server restart** (SQLite — currently in-memory only)

---

## P1 — Task Quality Feedback Loop

Poor task descriptions = high failure rate. Close the loop so each batch makes the next one better.

- [x] **Post-merge summary injection**: after `/merge-pr`, extract worker log summary + PR diff → append to project `PROGRESS.md` as a lesson entry
  - Format: `### [date] Task: {task title}\n- What worked: ...\n- Watch out for: ...`
- [x] **PROGRESS.md fed into Orchestrate**: when `⚡ Orchestrate` is triggered, prepend recent PROGRESS.md entries to the orchestrator prompt
  - Fetches `/api/sessions/{id}/progress-md` (last 3000 chars) and prepends to terminal input
- [x] **Scout readiness scoring**: score each proposed task 0-100 before starting
  - Background `_score_task()` coroutine uses claude-haiku after import
  - Score < 50 → red badge on task card; ≥ 80 → green; shown on every queue item

---

## P0 — Granular Commit Injection

OpenClaw's velocity comes from agents committing every sub-step, not just at task end.

- [x] **Inject commit discipline into every worker task description**
  - Append to every task before sending to worker:
    ```
    ## Commit Rules
    Commit after each logical unit of work — don't accumulate.
    Each commit must be self-contained and buildable.
    Use: committer "type: message" file1 file2
    ```
  - This goes into the CLAUDE.md prepend block, not the task body — applies universally

---

## P3 — Advanced Scheduling

- [x] **Dependency graph view**: visual DAG of task dependencies in Plan mode
- [x] **Worker resource limits**: max N workers across all projects (prevents API rate limiting)

---

## P3 — Iteration Loop (Ralph-style Supervisor)

Closes the review→fix→verify feedback loop. Runs autonomously until convergence.

- [x] **DB: `iteration_loops` table** in `TaskQueue._ensure_db()`
  - Fields: artifact_path, context_dir, status, iteration, changes_history, deferred_items, convergence_k/n, max_iterations, supervisor_model
  - Methods: `get_loop()`, `upsert_loop()`, `delete_loop()`
- [x] **`_run_supervisor()` coroutine** on ProjectSession
  - Reads artifact, calls supervisor model, parses JSON findings array
  - FIXABLE → TaskQueue.add() + start worker; DATA_CHECK → codebase worker; DEFERRED → append to DB; CONVERGED → signal done
  - Waits for spawned workers, counts changes, appends to changes_history
- [x] **Convergence detector** inside `_run_supervisor()`
  - After each iteration: check if last N entries in changes_history all ≤ K
  - On convergence: set status=converged, broadcast WebSocket, fire toast
- [x] **Loop endpoints** (registered BEFORE `/{session_id}` routes)
  - `POST /api/sessions/{id}/loop/start` — launch supervisor coroutine
  - `GET /api/sessions/{id}/loop` — return loop state
  - `POST /api/sessions/{id}/loop/pause` — cancel coroutine, status=paused
  - `POST /api/sessions/{id}/loop/resume` — re-launch coroutine
  - `DELETE /api/sessions/{id}/loop` — cancel + reset
- [x] **WebSocket broadcast**: include `loop_state` in every status tick
- [x] **Loop settings**: add `loop_supervisor_model`, `loop_convergence_k/n`, `loop_max_iterations` to `_SETTINGS_DEFAULTS`
- [x] **Loop control bar** in Execute mode HTML
  - Artifact path + context dir inputs, K/N inputs, Start/Pause/Resume/Cancel buttons
  - Show in execute mode, hidden in plan mode
- [x] **Convergence sparkline** (canvas mini bar chart of changes_history)
  - "N/M iter within threshold" text below bar
- [x] **Deferred items accordion** below loop bar
  - Renders deferred_items from DB; count badge in summary
- [x] **Loop settings panel rows** (4 new settings-row entries)
- [x] **Convergence toast** + auto-expand deferred items when loop ends

---

## P3 — Phase 2: Feedback Loop Upgrades
*Derived from OpenClaw / Ralph research. Each item is independently shippable.*

### Oracle Validation (second-model review before merge)
After `verify_and_commit()` passes but before auto-push, send diff + task description to a fresh model instance with no prior context. Independent validation catches "completed but wrong" silently.
- [x] `_oracle_review(task_description, diff_text)` async function → calls haiku, returns APPROVED/REJECTED + reason
- [x] Gate `auto_push` on oracle approval (new setting `auto_oracle`, default OFF to avoid breaking existing flow)
- [x] Worker card shows oracle result badge (✓ oracle / ✗ oracle rejected)
- [ ] Oracle rejection → task re-queued with rejection reason as context (same as retry-with-failure-context)

### Broadcast to All Workers
- [x] `POST /api/sessions/{id}/workers/broadcast` endpoint
  - Appends message to each running worker's task description; pokes each worker process (SIGCONT if paused, or writes to stdin via proc)
  - Returns list of worker IDs that received the message
- [x] "Broadcast" button in Execute mode workers header
  - Small input + "→ All" button, visible when ≥1 worker is running
  - On click: POST broadcast, show toast "Broadcast sent to N workers"

### Model Tier Auto-Routing
- [x] When `auto_start` launches a worker, pick model by scout score:
  - score ≥ 80 → haiku (clear task, cheap)
  - score 50-79 → sonnet (default)
  - score < 50 → escalate to sonnet + prepend "This task needs clarification — ask before coding"
  - score = null (not yet scored) → wait for score OR fallback to default_model after 15s
- [x] New setting `auto_model_routing` (default OFF)
- [x] Worker card shows model used + score that determined it

### PLANNING/BUILDING Loop Phase Distinction
Upgrade the existing iteration loop to match the proven ralph-loop pattern.
- [x] Loop config: add `mode` field — `"review"` (current default) | `"plan_build"`
- [x] In `plan_build` mode, `_run_supervisor()` runs two sub-phases:
  - **PLAN phase**: supervisor reads artifact + codebase context → writes `IMPLEMENTATION_PLAN.md` to artifact dir → no workers spawned yet
  - **BUILD phase**: supervisor reads plan → picks top unfinished item → spawns one FIXABLE worker → marks item done → repeats until "STATUS: COMPLETE"
- [x] UI: loop config shows mode selector when starting a loop

---

## P4 — Phase 3: Context Engineering
*Reduces worker failure rate; each item is a standalone improvement.*

### Context Budget Indicator
- [x] Estimate token usage per worker: `len(task_description) / 4 + log_file_size / 4` (rough heuristic)
- [x] Worker card shows mini token bar: gray → yellow at 60%, red at 80%
- [ ] At 80%, inject "CONTEXT: You are approaching your context limit. Use /compact to preserve critical state before continuing." into worker via broadcast-style message
- [x] New setting `context_budget_warning` (default ON)

### AGENTS.md Auto-Generation
- [x] `GET /api/sessions/{id}/agents-md` endpoint — runs `git log` on changed files, builds file→branch-owner map, formats as AGENTS.md block
- [x] New "Generate AGENTS.md" button in settings panel
- [ ] Output is prepended to every worker's task description (alongside existing CLAUDE.md injection)
- [ ] Format: "## File Ownership\n- /src/api/ → task-{id}\n- Do NOT edit files owned by other workers"

### Task Hot-Path Indicator
- [ ] After DAG is drawn, compute critical path (longest chain by task count)
- [ ] Critical-path tasks get a ⚡ badge in the queue list
- [ ] `auto_model_routing` gives critical-path tasks +1 model tier (haiku→sonnet, sonnet→opus)
- [ ] Critical path shown highlighted in DAG view (thicker edges)

---

## P4 — Phase 4: Swarm Intelligence
*Bigger architectural changes; implement after Phase 3 is stable.*

### Self-Organizing Swarm Mode
- [ ] New "Swarm" mode: N workers all start with the same "claim and execute" prompt
  - Worker loop: `TaskList()` → filter unclaimed → `TaskUpdate(owner=worker_id)` → execute → `TaskUpdate(status=completed)` → repeat
  - Workers never wait for assignment; they self-schedule
- [ ] `POST /api/sessions/{id}/swarm/start?n=5` — spawns N swarm workers
- [ ] UI: "🐝 Swarm (N)" button in Execute mode, input for N
- [ ] Swarm workers shown with a different icon in worker list

### GitHub Issues Sync
- [ ] `GET /api/sessions/{id}/issues/sync` — fetches open Issues from GitHub, creates tasks for each (deduplicated by issue URL in task description)
- [ ] Worker completing a task with `fixes #N` in commit → closes the issue automatically
- [ ] `POST /api/sessions/{id}/issues/push` — pushes all pending tasks as GitHub Issues
- [ ] UI: "⬆ Sync Issues" button in queue section header

---

## CC/CLI Side — Worker Prompt & Tooling Upgrades
*These improvements live in `~/.claude/skills/` and `~/.claude/scripts/` — the Claude Code layer, not the GUI.*

### Structured Task Description Format
*Current `orchestrate/prompt.md` has `===TASK===` blocks but is missing key fields workers need for safe parallel execution.*

- [x] **Add mandatory fields to `===TASK===` block template** in `orchestrate/prompt.md`:
  - `VERIFY_CMD:` — command to run after implementation (e.g. `npm run build`, `pytest tests/`, `tsc --noEmit`)
  - `OWN_FILES:` — glob patterns this worker owns and may edit (e.g. `src/api/auth/**`)
  - `FORBIDDEN_FILES:` — explicit "do NOT touch" list (populated from other tasks' `OWN_FILES`)
  - Workers must refuse to edit files in `FORBIDDEN_FILES` and write to `.claude/blockers.md` if they must
- [x] **Acceptance criteria field** — structured checklist appended to every task so worker self-checks before committing
  ```
  ACCEPTANCE:
  - [ ] All existing tests still pass
  - [ ] VERIFY_CMD exits 0
  - [ ] No files outside OWN_FILES were modified
  ```

### AGENTS.md File Ownership
*Prevents cross-worker file collisions in parallel runs without needing the GUI to generate AGENTS.md.*

- [x] **`/orchestrate` skill generates AGENTS.md stub** when writing `proposed-tasks.md`
  - Format: `## File Ownership\n### worker task-{id}\n- owns: src/api/auth/**\n- hands-off: src/frontend/**`
  - Written to `.claude/AGENTS.md` in the project root (workers read this automatically via CLAUDE.md include)
- [x] **AGENTS.md injected into every worker task description** alongside CLAUDE.md content
  - `/orchestrate` prepends `## Parallel Worker Boundaries\n{AGENTS.md content}` to every task before writing to proposed-tasks.md
  - Worker sees exactly who owns what before starting

### Worker `/compact` Discipline
*Workers currently run until context overflow with no self-awareness — they silently degrade.*

- [x] **Add `/compact` instruction block to every task description** (appended by orchestrate skill):
  ```
  ## Context Management
  When your context window reaches ~75% full:
  1. Run /compact — preserve: current task state, files modified so far, next steps
  2. Continue from compacted context
  Do NOT wait until overflow — compact early and often between logical sub-steps.
  ```
- [ ] **Worker handoff auto-trigger** (for tasks that span multiple context windows):
  - Add to task description: `If you cannot complete this task in one context window, write a handoff to .claude/handoff-{task_id}.md and stop. A new worker will /pickup and continue.`
  - `/orchestrate` skill detects `.claude/handoff-*.md` files at startup and auto-creates continuation tasks

### PostToolUse Lint/Type-Check Hook
*Workers write bad code, commit it, push it. A hook running after every file write catches errors before they accumulate.*

- [x] **`~/.claude/hooks/post-tool-use-lint.sh`** — runs project lint after every `Write`/`Edit` tool call
  - Reads `VERIFY_CMD` from `.claude/orchestrator.json` (same field as server-side verify_cmd)
  - If exit code non-zero: write error to `.claude/lint-feedback.md`; worker reads it next turn and fixes
  - Hook registered in `~/.claude/settings.json` under `hooks.PostToolUse`
- [x] **`~/.claude/hooks/post-commit-verify.sh`** — runs full verify_cmd after every commit
  - On failure: `git revert HEAD --no-edit` + write to `.claude/blockers.md`
  - Prevents bad commits from accumulating in the worktree

### `/orchestrate` Skill PLANNING Phase Upgrade
*Currently orchestrate jumps straight to task decomposition. A planning loop first produces better tasks.*

- [ ] **Two-phase orchestrate**: add `--plan` flag to trigger planning phase before task decomposition
  - Phase 1 (PLAN): read codebase context + PROGRESS.md → write `IMPLEMENTATION_PLAN.md` with architecture decisions, risks, and ordered steps
  - Phase 2 (DECOMPOSE): read `IMPLEMENTATION_PLAN.md` → decompose into `proposed-tasks.md` tasks with `OWN_FILES`/`FORBIDDEN_FILES` filled from plan
  - This is the `/orchestrate` analog of the GUI's PLANNING/BUILDING loop phase distinction
- [x] **PROGRESS.md prepend in orchestrate prompt** (already in GUI's ⚡ Orchestrate button — match it in the skill)
  - Skill reads last 3000 chars of `PROGRESS.md` and prepends to planning context: `## Past Lessons\n{progress}`
  - Workers learn from previous batch failures before the next batch starts

### Scout Scoring in CLI Batch Tasks
*`batch-tasks` skill already has scout scoring — expose it in the orchestrate→batch pipeline.*

- [x] **`/batch-tasks` auto-reads AGENTS.md** when executing tasks from `proposed-tasks.md`
  - Injects file ownership into each task description before spawning worker
  - Conflicts (two tasks claiming same file) → warning toast + manual resolution prompt
- [x] **Scout score threshold configurable** via `.claude/orchestrator.json` → `"scout_threshold": 50`
  - Tasks below threshold written to `.claude/low-score-tasks.md` instead of executed
  - User reviews and either rewrites or promotes manually

---

## Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| DB | SQLite (aiosqlite) | Lightweight, no server, queryable history |
| Parallelism | Git worktrees | True isolation, no file conflicts |
| Push strategy | Commit + push immediately to feature branch | Code never lost, remote is backup |
| Merge strategy | Auto-merge `orchestrator/task-*` branches; manual for external PRs | Our own tasks → ship fast, fix bugs later; external → gate |
| Retry | With error context injected | Workers learn from failures |
| Plan→Execute flow | Auto-start toggle (default ON) | Zero-click overnight mode |
| Oracle gate | Off by default | Don't break existing flow; opt-in quality gate |
| Model routing | Off by default | User may want explicit model control |
| Swarm | Phase 4 | Requires stable task-claiming primitive first |
