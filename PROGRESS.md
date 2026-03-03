# Progress Log

---

### 2026-03-02 — Phase 11 Complete: Autonomous Lifecycle

**What was built (all in one session):**
- `/verify` skill: project-type-aware testing with behavior anchors, machine-parseable footer
- 3-tier issue handling: Tier 1 (decisions.md), Tier 2 (skipped.md), Tier 3 (blockers.md) in loop-runner.sh
- loop-runner.sh bug fixes: goal-file race removed, STARTED_COMMIT for accurate diffs, zero-commit detection
- `/orchestrate` Feature: tag for one-feature focus filtering
- `/start` skill + `start.sh`: full autonomous lifecycle (plan → filter → loop → verify → sync → repeat)
- Drift prevention: FROZEN convention + BRAINSTORM proposal rule in both loop-runner.sh and start.sh
- Safety layer: cost guard ($5 default), wall-clock limit, TTY detection, --resume crash recovery

**Key design decisions:**
- start.sh is pure shell (zero LLM context) — each worker is an independent Claude session
- Convergence detected by fresh /orchestrate output, not worker-modified files
- Feature focus: one feature at a time, skipped.md injected to prevent task re-generation
- `claude -p --output-format json` confirmed: `total_cost_usd` + per-model breakdown available

**Cost logging (added post-phase):**
- Supervisor: `--output-format json` + python3 JSON parsing for both result text and `total_cost_usd`
- Workers: marker-file discovery (`find logs/claude-tasks -newer $marker`) to locate stream-json logs from run-tasks-parallel.sh, parse `total_cost_usd` per worker
- Per-iteration log line: `ITER=N COST=$X CUMULATIVE=$Y SUPERVISOR=$S WORKERS=$W DURATION=Nmin ELAPSED=Nmin TASKS=N`
- start.sh `_accumulate_cost()` reads CUMULATIVE value from last log line
- Final summary: total cost + elapsed time + iteration count printed at script end

**Lessons (cost logging):**
- Worker log files are owned by run-tasks-parallel.sh (`logs/claude-tasks/${TIMESTAMP}-task-${idx}.log`), not by loop-runner.sh — discovery via marker file (`find -newer`) is the cleanest cross-script approach
- `--output-format json` wraps the result in `{"result":"...","total_cost_usd":N}` — need python3 JSON parsing to extract text (can't use raw output as task list anymore)
- `--output-format stream-json` (used by workers) embeds `"total_cost_usd"` in the last result event — grep for the last occurrence

**Remaining (deferred):**
- Worker rebalancing across sessions (Phase 12 backlog)
- End-to-end test of full start.sh cycle on a real project

---
### 2026-03-02 — Phase 11 S1: Verification + Template

**Phase 10 verification (code-level trace, no GUI):**
- Priority ranker: full chain wired (`_rank_tasks` → 5min timer → haiku → DB → claim ordering)
- Cross-project overview: `GET /api/sessions/overview` complete with cost_rate
- Model routing + global max_workers: both enforced at multiple points
- Gap: worker rebalancing (inter-session redistribution) not implemented — deferred, not needed for Phase 11

**Cost tracking investigation:**
- `claude -p --output-format json` outputs `total_cost_usd` + per-model `costUSD` breakdown — fully parseable with `jq`
- Bug 4 is NOT a blocker — cost tracking in loop-runner.sh and session-report is feasible

**CLAUDE.md template (11.4):**
- Added `## Project Type` + `## Features (Behavior Anchors)` to template and dogfooded on this project
- 6 anchors: install.sh, slt, /commit, /loop, committer, loop-runner.sh

---
### 2026-03-01 — Loop: docs-review-goal

**Iterations:** 3
**Goal file:** /home/alexshen/projects/claude-code-kit/.claude/docs-review-goal.md
**Commits since start:**
```
62fefd1 Merge branch 'batch/task-2-20260301-225754'
ef96f0c docs: trim PROGRESS.md — remove changelog bloat, keep lessons
f72c1fc docs: fix stale overnight-mode references and Phase 10 status in TODO
d50da15 docs: review pass — clear brainstorm, fix phase ordering, update skills list, fix file map
```

---

### 2026-03-01 — Loop: docs-review-goal

Docs accuracy sweep: cleared BRAINSTORM.md, fixed Phase 8/9 ordering in TODO.md, updated session-report filename format, updated VISION.md skills list, updated CLAUDE.md file map.

---

### 2026-03-01 — Loop: loop-fix-debt3

**Lessons:**
- `import_from_proposed` should call `self.add()` not raw INSERT — gets `source_ref` and `is_critical_path` for free; only need post-call `update()` for `depends_on`
- `add()` doesn't support `depends_on`/`timeout`/`retries` params; these need separate `update()` call if non-default values are needed
- Always add `--dangerously-skip-permissions` to any headless `claude -p` subprocess; without it, Claude prompts interactively and times out silently

---

### 2026-02-28 — Loop: loop-fix-debt

**Lesson:** Autonomous loops introduce silent wiring bugs — new DB columns added but not plumbed through `add()`, new modules created but never called. Post-loop tech debt review (`/review`) is now standard practice. The 10-round gap check caught 8 remaining items the loop missed.

---

### 2026-02-27 — Gap Analysis vs Top Players → Phase 7 & 8 Roadmap

**Key insight — The real bottlenecks:**
1. **Task granularity**: Horizontal tasks at file-level (1 commit/file) outperform feature-level tasks. Fix: task type classification + auto-decomposition for horizontal tasks — not blindly splitting all tasks.
2. **No task factory**: 100% of tasks manually written. Should auto-generate from TODO comments, CI failures, coverage gaps, outdated deps.
3. **No worker auto-scaling**: Queue depth should drive automatic scaling.
4. **Per-file commit discipline**: Worker prompt must explicitly require "commit after each file immediately."

**Math:** Target 1000 commits/day = 62/hour. Phase 7 path: 10 workers × 6 commits/task × 1 task/hour = 960/day.

**Watch for in Phase 7:**
- Horizontal auto-decomposition needs shared context between sibling micro-tasks (all stem from same parent task)
- Worker auto-scaling needs cooldown to prevent spawn storms on brief queue bursts
- Task Factory dedup is critical — scanners will re-run and must not create duplicate tasks

---

### 2026-02-26 — GitHub Community Infrastructure + Docs Audit

Added GitHub templates (issue, PR, CI), CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md. Fixed docs/README accuracy: count mismatches, missing hooks in tables, broken `uninstall.sh`, documented-but-missing `post-tool-use-lint.sh`.

**Lessons:**
- `uninstall.sh` never kept in sync with new additions — worth checking after every feature addition
- Documented-but-not-implemented features accumulate silently; a periodic cross-ref audit catches them
- Community Health 100% requires 8 artifacts: Description + README + CoC + Contributing + License + Security + Issue templates + PR template

---

### 2026-02-25 — Pre-Code Reflection (learning from mistakes)

Added Pre-Code Reflection section to CLAUDE.md: 5 failure-pattern checks (settings/wiring, edge cases, async, security, deploy gap) derived from cross-project audit.

**Lessons:**
- `install.sh` is idempotent and won't overwrite existing `rules.md` or update existing `CLAUDE.md` — existing users need manual steps to pick up template changes
- Seed rules should be universal (cross-platform compat, async subprocess cleanup), not project-specific

---

### 2026-02-24 — Phase 6: Observability & Resilience

Added: session state persistence (recover orphaned tasks on restart), stuck worker detection with one-shot retry guard, token/cost tracking via log parsing, task analytics endpoint, cost budget limit, completion webhooks.

**Lessons:**
- Code review after implementation caught 4 real bugs including an infinite loop — do it every time
- fail-open pattern is essential for all notification/webhook code
- Budget check placement matters: in `status_loop` for auto-start, NOT in `run_task` for manual runs
- Stuck-retry guard: `[STUCK-RETRY]` prefixed tasks must NOT be re-queued on second stuck — prevents infinite loops

---

### 2026-02-24 — Phase 5: Context Intelligence

Added: semantic code TLDR (AST-based for Python, regex for JS/TS), dual-condition exit gate (count convergence OR semantic hash match for oscillation detection), intervention recording (failure pattern → correction → outcome).

**Lessons:**
- AST `tree.body` iteration is cleaner than `ast.walk()` for top-level items — avoids needing parent tracking to distinguish nested vs top-level functions
- Inline migration pattern (wrapping old ints as dicts) works for backward-compatible JSON column format changes
- All three features follow fail-open — errors never block task execution, only add optional intelligence

---

### 2026-02-24 — Phase 4: Agent Teams, Critical Path, Cross-worker Messaging

**Lessons:**
- Critical path model boost logic already existed but data path was broken — `is_critical_path` never persisted in DB. Fix was purely plumbing (DB column + API passthrough), not new logic.
- Generic task update endpoint should filter by `_ALLOWED_TASK_COLS` allowlist — reusable and safe for all future task fields
- Message injection into `Worker.start()` requires passing `task_queue` — keep as optional param to avoid breaking existing callers

---

### 2026-02-24 — Phase 4: GitHub Issues Sync

Key design: event-driven push + manual pull (no polling timer). Conflict policy: pending tasks → GitHub edit wins; running/done → local wins. All `gh` commands guarded by setting — zero behavioral change when disabled.

**Lessons:**
- `gh issue create --label "a,b"` passes comma-separated labels as a single argument — works correctly
- Issue body HTML comments are invisible in GitHub rendered markdown — perfect for metadata
- Fire-and-forget `asyncio.ensure_future` for issue creation keeps the task creation path fast — failures log but don't block

---

### 2026-02-24 — Phase 4: File Ownership Enforcement

**Lessons:**
- Ownership enforcement follows the flag-bridge pattern: set flag in Worker method (no queue access), pick up in `poll_all()` (has queue access)
- `fnmatch` handles simple globs but `dir/**` needs special prefix-check logic — `fnmatch("src/db/schema.py", "src/db/**")` doesn't match in Python's fnmatch
- Lines stay in task description so workers still see OWN_FILES/FORBIDDEN_FILES as guidance — parsing is additive, not destructive

---

### 2026-02-24 — Phase 4: Swarm Mode

Key design: SwarmManager wraps WorkerPool — existing Worker class unchanged, smarter scheduling on top. SQLite CAS (`UPDATE WHERE status='pending'` + `rowcount > 0`) handles single-process concurrency without Python locks.

**Lessons:**
- Swarm (pull-based: workers finish → manager claims next) and iteration loop (push-based: supervisor decides) are fundamentally different dispatch models — mutual exclusion in v1 is correct; combining them requires a complex priority system
- SQLite CAS is sufficient for single-process concurrency; multi-process would need `BEGIN EXCLUSIVE` or a lock file

---

### 2026-02-24 — Phase 3: Handoff detection, Orchestrate --plan, Artifact marking

**Lessons:**
- `claude -p` is non-interactive: no stdin for mid-flight messages. True context injection requires PTY-based workers (Phase 4+ architectural change)
- Handoff detection must happen BEFORE `_cleanup_worktree()` — the handoff file lives in the worktree and gets destroyed on cleanup
- Artifact marking via prompt instruction (not code enforcement) is correct — workers may complete partial work

---

### 2026-02-24 — Phase 3: Oracle, AGENTS.md, Loop --stop

**Lessons:**
- Oracle requeue: do in `poll_all` (has `task_queue` access), not in `verify_and_commit` (Worker method, no queue access) — flag-bridge pattern
- AGENTS.md search order: `.claude/AGENTS.md` first (generated by orchestrator), then project root `AGENTS.md` (manually maintained)
- Loop stop via sentinel file is simpler than PID-based kill — works cross-session without tracking process IDs

---

### 2026-02-24 — Security hardening: 5 rounds

Across multiple rounds: subprocess timeout kill+drain, SQL injection via `_ALLOWED_TASK_COLS`, model alias normalization, worker dedup guard, XSS via `data-*` attributes, settings key allowlist.

**Consolidated lessons:**
- `asyncio.wait_for` cancels the coroutine but NOT the underlying subprocess — always `proc.kill()` + `await proc.communicate()` in TimeoutError handler. Audit ALL `asyncio.wait_for(proc.communicate(), ...)` sites — including utility functions like `verify_and_commit`.
- `data-*` attributes + `this.dataset.*` are the correct pattern for onclick handlers with user-controlled strings — `esc()` is HTML-safe but not JS-string-safe
- Settings endpoints accepting arbitrary dicts must validate against `_SETTINGS_DEFAULTS` keys — `dict.update(body)` is never safe
- Short model aliases must be normalized before allowlist checks — fallback to default model is silent
- `t.get("depends_on")` is falsy for `[]` — use explicit `is not None` or drop the guard
- `auto_start` toggle was frontend-only; server always auto-started. Settings toggles need enforcement at both layers
- TOCTOU on SQLite schema migration: always do related DDL+DML in one connection
- xterm.js captures input via `<textarea class="xterm-helper-textarea">` — `document.activeElement.tagName` check is insufficient; must check class name too
- Worker dedup guard must check `status in ("running", "starting")` to cover the startup race window

---

### 2026-02-23 — P3: Iteration Loop (Supervisor)

**What worked:**
- `re.search(r'\[.*\]', response, re.DOTALL)` reliably extracts JSON array even when supervisor wraps it in prose
- `---ARTIFACT---` / `---END---` delimiters prevent artifact content from confusing the supervisor prompt
- `delete_loop()` + fresh `upsert_loop()` on start avoids partial field pollution from previous runs

**Watch out for:**
- `upsert_loop()` only updates the fields you pass — callers wanting a full reset must call `delete_loop()` first
- Convergence checks `changes_history[-n:]` — list must have at least N entries before convergence is possible

---

### 2026-02-23 — Dead settings fixes (auto_review, default_model)

**Lessons:**
- Settings in `_SETTINGS_DEFAULTS` without a runtime `GLOBAL_SETTINGS.get()` callsite are invisible bugs — adding a key is not enough; audit every callsite that should use it
- `setTimeout(..., 100)` as "wait for PTY to process" is a smell — the PTY already buffers; the delay just introduces fragility

---

### 2026-02-23 — P2: Multi-Project Dashboard + Settings Panel

**Lessons:**
- The formatter PostToolUse hook runs async and can modify files between Edit tool calls — causes "file modified since read" errors on rapid sequential edits. Use Python bulk transforms to make all changes atomically.
- Always verify FastAPI route order for static vs parameterized routes (`/overview` before `/{session_id}`)
- HTML replace via Python: `print(repr(content[idx-5:idx+100]))` to verify exact bytes before building search string — Unicode box-drawing chars look similar but differ in byte count

---

### 2026-02-23 — P1: SQLite persistence, scheduler, score-based routing

**Lessons:**
- aiosqlite `row_factory = aiosqlite.Row` enables `dict(row)` conversion — cleaner than manual column mapping
- sqlite3 JSON stored as text; parse with `json.loads()` on read, `json.dumps()` on write
- `claude --max-tokens` CLI flag doesn't exist; only `--max-budget-usd` — verify CLI flags against `claude --help` before using

---

### 2026-02-23 — Bug fix: worker code loss (verify/cleanup race)

Sequential `await verify_and_commit(); await _cleanup_worktree()` completely closes the race — worktree exists for the full duration of verification. `_original_project_dir` must be set in `__init__` before `start()` overwrites `_project_dir`.

---

### 2026-02-23 — Agent autonomy layer: handoff/pickup, guardian hook, committer

**Lessons:**
- PreToolUse guardian must use `jq -r '.tool_name'` on stdin JSON — NOT command args
- `stat -c %Y` works on Linux for file mtime; `date -r` is macOS — guard both for portability
- `committer.sh` must clear the staging area first (`git restore --staged :/`) before staging specified files — otherwise previously-staged files from other agents leak in
- Agent Ground Rules in global CLAUDE.md are the key forcing function — without them, agents fall back to old habits even if the tools exist

---

### 2026-02-23 — P3: Dependency graph + worker resource limits

**Lessons:**
- `depends_on` migration is seamless: existing tasks without the field get `.get("depends_on", [])` defaulting to `[]`
- `PATCH /api/tasks/{task_id}` must appear BEFORE `POST /api/tasks/import-proposed` in FastAPI route registration to avoid routing conflicts

---

### 2026-02-20 — Stop hook, auto-pull, sync skill

**Lessons:**
- Stop hook returning `ok=false` causes Claude to attempt auto-fix; without a "give up" instruction it loops forever on failures like missing CLI tools or interactive prompts
- CLI flag convention: destructive actions opt-in (`--force`); common desired actions default with opt-out (`--no-commit`)
- `git pull --ff-only` is the right default — fast-forward only, fails safely if branch has diverged

---

### 2026-02-20 — /commit skill, skill ecosystem analysis

**Lessons:**
- Decoupling `/sync` (docs) from `/commit` (code) clarifies responsibility — `/sync` is purely a documentation tool
- Skills ecosystem gaps identified: no `/commit` (now fixed), no PR workflow — these are the next tier

---

### 2026-02-20 — Stop hook JSON validation fix

**Lessons:**
- `type: "prompt"` hooks must output *only* JSON — leading the prompt with an explicit output-format constraint reliably suppresses prose
- 15s timeout is too tight for Stop hook reviewing long conversations; 30s is safer

---

### 2026-02-24 — Loop mode first run + plan_build

**Lessons:**
- Workers in loop mode write changes to the worktree branch — NOT auto-committed back to main unless `verify_and_commit()` succeeds
- If loop coroutine is interrupted (server restart), must Cancel + restart — `changes_history=[]` stays empty and status stays `running`
- Workers tend to describe changes rather than implement them; fix is better prompting (AGENTS.md, CLAUDE.md prepend)

---

### 2026-02-24 — /loop CLI skill

**Lessons:**
- CLI loop vs web UI loop: CLI safer for self-modification (script external to codebase); web UI better for parallel workers + real-time monitoring
- The skill's context enrichment step is where it adds value over raw bash — the skill session has full codebase context that background `claude -p` calls lack
- `unset CLAUDECODE` allows nested claude calls from within a Claude Code session
