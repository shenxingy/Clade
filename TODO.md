# TODO — Claude Code Orchestrator Redesign

**North star:** Plan once, run overnight, wake up to hundreds of commits.
**UX principle:** Every action must be completable in the minimum possible clicks.
If two steps can become one button or one setting, they must.

---

## P0 — Plan/Execute UI Split (highest immediate value)

The current UI forces constant context switching between planning and monitoring.
Split into two modes; the brain stays in one mode at a time.

- [ ] **Plan mode layout**: Terminal takes 70% width; right sidebar shows live Task Backlog
  - Task Backlog syncs automatically from `proposed-tasks.md` (already wired via WebSocket)
  - Tasks are editable inline (click to edit description, drag to reorder, × to delete)
  - No separate "Import Proposed" button needed — file changes auto-populate the sidebar
- [ ] **"⚡ Orchestrate" one-click button** in Plan mode header
  - Sends `/orchestrate\r` to the active PTY — replaces manual typing
  - Optionally: input field next to it so user types goal → click → sends `{goal}\r/orchestrate\r`
- [ ] **"Auto-start" toggle** (default: ON)
  - When ON: proposed-tasks are auto-imported + all workers auto-started the moment `proposed-tasks.md` is written
  - No overlay, no extra click — set it once and walk away
  - When OFF: overlay appears for manual review (current behavior)
- [ ] **Execute mode layout**: Full-width worker dashboard, no terminal unless you need to intervene
  - Top bar: per-project progress bars (all projects at once)
  - Worker rows: task name | status badge | elapsed | commit hash | pushed? | [Log] [Retry]
  - Terminal hidden by default; [Intervene] button opens a slide-in terminal panel for that session
- [ ] **Mode toggle** in header: `[📋 Plan]  [▶ Execute]` — one click to switch

---

## P0 — Git Worktree Isolation (code safety, required before overnight runs)

Without this, parallel workers on the same repo will corrupt each other's changes.

- [ ] **Worker spawns in its own git worktree**
  - On worker start: `git worktree add .claude/worktrees/worker-{id} -b orchestrator/task-{id}`
  - Worker's `cwd` is the worktree path, not the main repo
  - On worker done/failed: worktree is cleaned up (`git worktree remove --force`)
- [ ] **Auto-push to feature branch after each commit** (setting, default: ON)
  - After `verify_and_commit()` succeeds: immediately `git push origin orchestrator/task-{id}`
  - "Committed" status in UI shows: `✓ committed · ✓ pushed` or `✓ committed · ⏳ pushing`
  - Code is safe on remote the moment it's done — no batch push needed
- [ ] **"Merge All Done" → AI PR Pipeline** in Execute mode
  - For each `done + auto_pushed` worker: `gh pr create --head {branch} --base main --fill`
  - Worker card shows PR URL after creation
  - **Auto-merge logic**: if branch matches `orchestrator/task-*` (spawned by us) → squash merge automatically after PR created; no human review needed — "ship it, fix bugs later"
  - External PRs (branches not matching `orchestrator/task-*`) → manual review required

---

## P0 — AI PR Skills (the OpenClaw pipeline)

Three slash skills that make the PR lifecycle AI-native — parallel to OpenClaw's `/review-pr → /prepare-pr → /merge-pr`.

- [ ] **`/review-pr`** — AI reads PR diff, writes structured review as PR body comment
  - Triggered automatically after PR creation if `auto-review` setting is ON
  - Output: summary of changes, risks, suggestions — posted to PR via `gh pr comment`
- [ ] **`/merge-pr`** — squash merge + branch cleanup
  - For `orchestrator/task-*` branches: triggered automatically after PR creation
  - For external PRs: triggered manually by user
  - After merge: `git branch -d {branch}` + `git worktree remove`
- [ ] **Worker self-verification** before marking done
  - After `verify_and_commit()`, run project-defined check command (e.g. `npm run build`, `pytest`, `tsc --noEmit`)
  - Pass → status = done; Fail → status = failed, check output appended to failure_context
  - Check command configured per-project in `.claude/orchestrator.json` → `"verify_cmd": "npm run build"`

---

## P1 — Retry with Lessons Learned

Current blind retry wastes worker time repeating the same mistake.

- [ ] **Capture failure context** when worker exits with non-zero code
  - Extract last 50 lines of worker log as `error_summary`
  - Store in task record: `failed_reason`
- [ ] **Inject failure context into retry task**
  - Retry task description = original description + `\n\n---\nPrevious attempt failed:\n{error_summary}\nDo NOT repeat the same approach.`
  - Max retries configurable per task (default: 2)
- [ ] **"Retry All Failed" button** in Execute mode
  - One click to requeue all failed tasks with their error context injected
  - No need to manually inspect each failure and re-create tasks

---

## P1 — SQLite Persistence

JSON files lose history on server restart and can't be queried across projects.

- [ ] **Migrate from JSON to SQLite** (`aiosqlite`)
  - Tables: `projects`, `tasks`, `workers`, `commits`
  - `tasks` retains history (done/failed tasks not deleted, just marked)
  - `commits` tracks: hash, branch, committed_at, pushed_at, merged_at
- [ ] **Task history view** in Execute mode
  - Expandable "Done" section showing all completed tasks with outcomes
  - Success rate per project (done / total attempted)
- [ ] **Cross-session persistence**: task queue survives server restart

---

## P1 — Project Context Injection

Workers currently run "blind" without knowing the project's tech stack or constraints.

- [ ] **Auto-inject CLAUDE.md into task description**
  - When a task is created for a project, prepend the project's `.claude/CLAUDE.md` content
  - Worker knows the stack, conventions, and what NOT to do before it starts
- [ ] **Task dependency support** (`depends_on: [task_id]`)
  - Scheduler holds dependent tasks in "waiting" state until dependencies are done
  - In Plan mode: drag a task onto another to set dependency (visual arrow)
  - Prevents "write frontend calls" starting before "write API" is done

---

## P2 — Global Multi-Project Dashboard

One screen to rule all overnight runs across all projects.

- [ ] **Multi-project overview** at top of Execute mode
  - Each project: name | progress bar | running/done/failed counts | ETA
  - Click to drill into that project's workers
- [ ] **Global "Start All Queued"** button
  - Starts all pending tasks across all open project sessions at once
- [ ] **Success rate metrics**
  - Per project: % tasks done successfully, avg time per task
  - Displayed in Execute mode footer

---

## P2 — Settings Panel (set once, run forever)

One-time configuration so every session runs the same way without manual setup.

- [ ] **Auto-start workers** when proposed tasks arrive (ON/OFF)
- [ ] **Auto-push** to feature branch after commit (ON/OFF)
- [ ] **Auto-merge** for `orchestrator/task-*` branches (ON/OFF, default ON)
- [ ] **Auto-review** run `/review-pr` after PR creation (ON/OFF, default ON)
- [ ] **Default model** per task priority (opus/sonnet/haiku)
- [ ] **Max parallel workers** per project
- [ ] **Settings persist** in localStorage (or SQLite)

---

## P3 — Advanced Scheduling

- [ ] **Scheduled runs**: "Start at 11pm" — queue tasks, workers auto-start at scheduled time
- [ ] **Dependency graph view**: visual DAG of task dependencies in Plan mode
- [ ] **Worker resource limits**: max N workers across all projects (prevents API rate limiting)

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
