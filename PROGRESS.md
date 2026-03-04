# Progress Log

---
### 2026-03-04 — Stress test #4: claude-code-kit self-test + post-test fixes

**Config:** $10 budget, 5 max iterations, sonnet supervisor/workers

**Results:** Converged at iteration 3, $1.64 total, 3 minutes. Phase 12.3 (Design System Constraint) fully implemented by workers — 3 parallel tasks in iter 1, 1 fixup in iter 2 (install.sh update that iter 1 missed), CONVERGED in iter 3. install.sh auto-ran after convergence to deploy changes.

**Issues found & fixed:**
1. **`claude -p` hangs with command-line args** — passing large prompts as `claude -p "$(printf '...')"` causes T (stopped) state. Stdin pipe (`printf ... | claude -p`) works reliably. Fixed in `e377334` (pre-test). Root cause: likely shell ARG_MAX or claude CLI stdin detection.
2. **Phantom empty task** — trailing `===TASK===` with no body creates a phantom task that runs with empty prompt. Supervisor in iter 2 output `===TASK===` at EOF; task 2 was empty but "SUCCESS". Fixed: `count_tasks` now uses awk to skip tasks with empty body (both run-tasks.sh + run-tasks-parallel.sh).
3. **`git diff --cached --stat` pager hang** — committer.sh spawns pager in non-interactive context. Fixed: `git --no-pager diff` + `git --no-pager commit`.
4. **design-system.md `#` rendering** — template used `#` for instructional comments, rendered as H1 headings in Markdown. Fixed: converted to prose paragraphs + blockquotes.
5. **frontend-design `[placeholder]` guard missing** — skill prompt didn't handle unfilled `[placeholder]` tokens. Fixed: added explicit skip instruction.

**Worker quality assessment:** All 3 Phase 12.3 workers succeeded, produced correct code. Supervisor correctly identified install.sh gap in iter 2. However, iter 2's install.sh worker (haiku) "succeeded" with 0 commits — the fix was already applied by another path. One phantom empty task (bug #2 above) ran uselessly.

**Lessons:**
- First stress test where the kit tested itself — meta-level validation
- Supervisor quality was excellent: correctly decomposed Phase 12.3 into 3 parallel tasks matching the proposed-tasks.md spec, then caught the install.sh gap
- Post-convergence auto-install (`configs/ changed → running install.sh`) is valuable for self-evolving projects
- Phantom task bug wasted ~$0.13 on an empty sonnet call — task parsing must validate body

---
### 2026-03-04 — Loop: loop-goal

**Iterations:** 3
**Goal file:** .claude/loop-goal.md
**Commits since start:**
```
4fd3e16 Merge branch 'batch/task-3-20260304-124505'
547d1f7 Merge branch 'batch/task-2-20260304-124505'
3959334 feat: Phase 12.3 — design system template + orchestrate injection
0e8fffc feat: Phase 12.3 — frontend-design skill with design system awareness
77c66b1 chore: Phase 12.3 — mark design system tasks complete
e377334 fix: use stdin pipe for claude -p calls — prevents hang on large prompts
```

---

### 2026-03-04 — Stress test #3 bug fixes + Phase 12.2: Autonomous Work Discovery

**Bug fixes (2):**
1. **SIGPIPE trap** — `trap '' PIPE` added after signal handlers in start.sh. Piping through `head -N` no longer kills the script.
2. **Budget enforcement in inner loop** — loop-runner.sh accepts `--budget` flag; start.sh passes remaining budget (`BUDGET - TOTAL_COST`) each iteration; loop breaks when cumulative cost exceeds budget. Prevents 2.5x budget overruns seen in stress test #3.

**Phase 12.2 — Autonomous Work Discovery (4 items):**
1. **Task factories already existed** — scan-ci-failures.sh, scan-coverage.sh, scan-deps.sh were built in Phase 8.1
2. **scan-health.sh** — new code health scanner: TODO/FIXME comments (grouped by file), mypy/tsc type errors, ruff/eslint lint warnings, large files (>1500 lines). Outputs `===TASK===` blocks.
3. **Post-convergence scan** — `_post_convergence_scan()` in start.sh runs all 4 scan scripts after feature convergence; if findings exist, injects them as next iteration tasks instead of declaring "done". Runs once per session (`_POST_CONVERGENCE_DONE` flag) to prevent infinite loops.
4. **UX audit as work source** — already implemented in Phase 12.1 (INTERACTION_RESULT parsing)

**Key design decisions:**
- Post-convergence scan runs once per session — if scan findings aren't fixed in one pass, they're logged but don't block convergence
- Budget is passed as remaining amount, not total — inner loop only sees what it's allowed to spend
- scan-health.sh groups TODOs by file (one task per file) to keep task count manageable
- `${LOOP_BUDGET_ARGS[@]+"${LOOP_BUDGET_ARGS[@]}"}` pattern avoids `set -u` failure on empty arrays

**Files changed:** `start.sh`, `loop-runner.sh`, `scan-health.sh` (new)

---
### 2026-03-03 — Phase 12.1: UI Interaction Testing via Playwright MCP

**What was built:**
- `/verify` skill now has a conditional "UI Interaction" strategy for `web-fullstack` projects
- Uses `@playwright/mcp` (Microsoft's official server) with `--headless` for autonomous use
- Flow: detect frontend port → navigate → snapshot → walk up to 5 pages → click/fill → evaluate
- Findings written to `.claude/playwright-issues.md` with `[BUG]`/`[UX]` tags
- `INTERACTION_RESULT: pass|partial|fail|skipped` added as 4th footer line
- `start.sh` parses INTERACTION_RESULT: `[BUG]` → fix tasks, `[UX]` → BRAINSTORM.md
- `start.sh` passes `--mcp-config .claude/mcp.json` to verify when file exists
- Auth-gated pages handled gracefully (mark unverifiable, not BUG)

**Review findings fixed (6 issues):**
1. `$MCP_FLAG` word splitting → array `MCP_ARGS=()` + `"${MCP_ARGS[@]}"`
2. `fail` with missing `playwright-issues.md` → log + degrade to partial
3. `fail` with 0 `[BUG]` items → log + degrade to partial
4. Stale `playwright-issues.md` across iterations → `rm -f` before each verify
5. Dead `|| ux_items=""` → `|| true`
6. Redundant guard condition simplified + commented

**Files changed:** `mcp.json.example`, `verify/prompt.md`, `start.sh`, `docs/mcp-setup.md`

**Lessons:**
- Unquoted shell variables for optional flags (`$MCP_FLAG`) are fragile — arrays are the correct pattern
- LLM output can drift from spec (fail without writing issues file) — always handle missing/empty gracefully
- Stale files from previous iterations cause false positives — clear transient state before each verify run

---
### 2026-03-03 — Stress Test #3: deepfake-platform (ML monorepo, code health + security)

**Third stress test, different project type. ML monorepo with 5 code health tasks on deepfake-platform (multi-domain detection platform).**

**Config:** `start.sh --goal .claude/stress-test-goal.md --budget 5 --max-iter 3 --confirm`
- 5 goal tasks: import cleanup, type annotations, dead code detection, security audit of V2, test gap analysis
- Branch: `alex/kit-stress-test` (work project, PR-only constraints)
- HORIZONTAL mode, MAX_WORKERS=4

**Result:** Max iterations (5 inner), **$12.79 total**, **32 minutes**, **41 commits** (including merge commits).

| Iteration | Tasks | Duration | Cost | Key Results |
|-----------|-------|----------|------|-------------|
| 1 | 4 (parallel) | 6min | $4.38 | Import cleanup (8 files), type annotations (3 files), security fixes (5 vulns), test coverage (evaluation.py) |
| 2 | 3 (parallel) | 15min | $4.95 | Dead code removal, face_quality_scorer test, more type annotations + merge conflict serial retry |
| 3 | 3 (parallel) | 3min | $1.24 | More import cleanup (flows/), type annotations, security review (score_history_store, threat_prioritizer) |
| 4 | 2 (parallel) | 3min | $0.98 | Import cleanup (agentic/), type annotations (remaining helpers) |
| 5 | 2 (parallel) | 3min | $1.24 | Final security audit (webhook_server, governance) |

**Security findings fixed:**
- Path traversal via `cycle_id` in governance.py
- MLflow filter string injection via `expert_name` in drift_detector.py
- Path traversal + missing env sanitization in sandbox.py
- Error message leakage (str(e)) in webhook_server.py
- SECURITY-REVIEW annotations on clean files

**3-project comparison:**

| Metric | owlcast | ai-ap-manager | deepfake-platform |
|--------|---------|---------------|-------------------|
| Project type | AI video pipeline | FastAPI+Next.js | ML monorepo |
| Duration | 66min | 5min (v2) | 32min |
| Cost | $10.48 | $3.86 (v2) | $12.79 |
| Commits | 21 | 20 (v2) | 41 |
| Tasks | 6 | 5 | 5 (expanded to ~14 by supervisor) |
| $/commit | $0.50 | $0.19 | $0.31 |
| Iterations | 4 | 2 (v2) | 5 |
| Failures | 1 partial | 0 | 0 |

**Bugs found:**
1. **Budget not enforced by inner loop** — start.sh budget check is at the outer loop level; loop-runner.sh has no budget awareness. $5 budget → $12.79 actual spend. Fix needed: pass budget to loop-runner.sh or check between iterations.
2. **Merge conflict handling works** — `.claude/decisions.md` conflicted (two workers wrote to it simultaneously); auto-serial-retry resolved it correctly.
3. **`head -N` kills pipeline** — piping start.sh through `head -80` sends SIGPIPE when head exits, killing the entire pipeline. Never pipe start.sh output through line-limiting commands.

**What worked well:**
- Supervisor task planning was excellent — correctly split 5 high-level goals into granular file-level tasks
- Security audit found 5 real vulnerabilities (not just speculative hardening)
- Haiku workers fast and cheap for import cleanup + type annotations ($0.07-0.38/task)
- 3-tier issue handling: workers logged decisions to `.claude/decisions.md` instead of blocking
- Dead code detection correctly identified and removed unused `image_attributes.py` module

**Lessons:**
- ML monorepos work well with start.sh — the flat import layout and large file count are handled correctly by workers in worktrees
- Budget enforcement gap is a real issue for unattended runs — inner loop can spend 2.5x budget before outer loop checks
- Supervisor gets progressively more targeted — iter 1 covers broad strokes, later iterations fill remaining gaps
- `committer` in worktrees works reliably — 41 commits, 0 staging conflicts between workers

---
### 2026-03-03 — Stale scripts auto-detection

**Problem:** `install.sh` re-run was mandatory after script changes but nothing caught staleness. All 5 bug fixes were "fixed" in git but never deployed in stress test #2.

**Solution:** 3-point detection:
1. `install.sh` writes `~/.claude/.kit-source-dir` (repo path) + `~/.claude/.kit-checksum` (combined sha256 of all `configs/` files)
2. `session-context.sh` (SessionStart hook) compares checksums → warns in context if stale
3. `start.sh` `_check_startup_health()` → TTY: auto-reinstall prompt (15s timeout, default Y); non-TTY: hard abort

**Lessons:**
- `sha256sum` output includes filenames — must use consistent absolute paths between writer and checker (both use `$KIT_DIR/configs`)
- `LC_ALL=C sort` ensures deterministic file ordering across locales
- Three detection points cover all entry paths: interactive session, autonomous run, manual check

---
### 2026-03-03 — Stress Test #2b: ai-ap-manager with fixed scripts (parallel validated)

**Re-run after deploying all bug fixes via `install.sh`. All fixes validated.**

**Config:** `start.sh --goal .claude/stress-test-goal-v2.md --budget 5 --max-iter 3 --confirm`
- 5 goal-level tasks → supervisor decomposed into 20 HORIZONTAL micro-tasks
- HORIZONTAL mode, MAX_WORKERS=4

**Result:** CONVERGED at iteration 2, **$3.86 total**, **5 minutes**, **20 commits** (+ 18 merge commits).

**All fixes validated:**

| Bug Fix | Status | Evidence |
|---------|--------|----------|
| #1 Parallel execution (OWN_FILES) | **PASS** | 20 groups of 1 task each, 4 running simultaneously |
| #2 Model-aware timeout | **PASS** | Supervisor set explicit timeouts per task |
| #3 Disk health check | **PASS** | `⚠ Disk usage at 93% — running low.` printed, continued |
| #5 Cost log at startup | **PASS** | File existed before first iteration completed |
| #7 Watchdog fd leak | **PASS** | Zero orphaned `sleep` processes after completion, start.sh exited immediately |

**v1 vs v2 comparison (same project):**

| Metric | v1 (stale scripts) | v2 (fixed scripts) |
|--------|--------------------|--------------------|
| Parallelism | Serial (1 group) | Parallel (20 groups, 4 workers) |
| Duration | 22min (12 workers + 10 blocked) | 5min |
| Cost | $4.21 | $3.86 |
| start.sh exit | Blocked 10min by orphaned sleeps | Immediate |

**Lessons:**
- HORIZONTAL mode + 20 micro-tasks completes in 5min vs 22min serial — 4.4x speedup with 4 workers
- OWN_FILES-based conflict detection is correct: each file-level task gets its own group
- Watchdog trap fix (`kill $_wd_sleep_pid`) eliminates fd leak completely
- install.sh re-run is the single most important step — source != installed

---
### 2026-03-03 — Stress Test #2: start.sh on ai-ap-manager (fullstack FastAPI+Next.js)

**Second stress test, different project type. 5 code-health tasks on ai-ap-manager (319/320 TODOs complete).**

**Config:** `start.sh --goal .claude/stress-test-goal.md --budget 5 --max-iter 3 --confirm`
- 5 targeted tasks: mypy setup, frontend build/lint, dead code cleanup, security audit, docs review
- HORIZONTAL mode requested for 5 parallel workers

**Result:** CONVERGED at iteration 2, **$4.21 total**, **22 minutes** (12min workers + 10min blocked by bug), **7 commits**.

| Task | Model | Timeout | Cost | Result | Commit |
|------|-------|---------|------|--------|--------|
| 1. Backend mypy setup | sonnet | 1800s | $2.93 | SUCCESS | `6e505b4` |
| 2. Frontend build/lint | haiku | 900s | $0.07 | SUCCESS (no errors found) | (no changes) |
| 3. Dead code cleanup | haiku | 900s | $0.38 | SUCCESS | `01c2d8e` |
| 4. Security audit | haiku | 900s | $0.15 | SUCCESS | `c45cd3b` |
| 5. CLAUDE.md/README review | haiku | 900s | $0.21 | SUCCESS | `8300c59` |
| Supervisor (2 iters) | sonnet | — | $0.47 | — | — |

**Comparison with owlcast baseline:**

| Metric | owlcast | ai-ap-manager |
|--------|---------|---------------|
| Duration | 66min | 22min |
| Cost | $10.48 | $4.21 |
| Tasks | 6 | 5 |
| Commits | 21 | 7 |
| $/task | $1.75 | $0.84 |
| $/commit | $0.50 | $0.60 |
| Iterations to converge | 4 | 2 |
| Failures | 1 partial (mypy timeout) | 0 |

**Critical finding: installed scripts are stale!**
All 5 bug fixes from the pre-run hardening exist in `configs/scripts/` (source) but NOT in `~/.claude/scripts/` (installed). `install.sh` was never re-run after the fixes were committed. Result:

| Bug Fix | Source (configs/) | Installed (~/.claude/) | Impact |
|---------|-------------------|------------------------|--------|
| #1 Parallel (OWN_FILES) | Fixed | OLD (extract_file_refs) | All 5 tasks ran serially |
| #2 Model-aware timeout | Fixed | OLD (flat 1800s) | N/A (supervisor set explicit) |
| #3 Disk health check | Fixed | MISSING | No warning at 93% |
| #4 /orchestrate retry | Fixed | OLD | N/A (--goal mode) |
| #5 Cost log touch | Fixed | MISSING | Cost log created late |

**2 new bugs found:**
1. **Bug #6: 3-Tier boilerplate causes false file conflicts** — the old `extract_file_refs()` regex picks up `decisions.md`, `skipped.md`, `blockers.md` from the 3-Tier boilerplate appended to EVERY task prompt → all tasks grouped serial. The source already has the OWN_FILES fix, but this shows the old code's failure mode.
2. **Bug #7: Orphaned watchdog `sleep` processes hold pipe open** — `run-tasks-parallel.sh` spawns `sleep $TIMEOUT` watchdogs per task that inherit the loop-runner stdout fd. When workers finish early, the `sleep` processes keep the pipe open → `tee` never gets EOF → `start.sh` blocks until all sleeps expire (up to 1800s!). Fix needed: redirect watchdog sleep stdout to /dev/null, or kill watchdog when worker exits.

**Lessons:**
- **install.sh re-run is mandatory after script changes** — source != installed. The 5 bug fixes were "fixed" in git but never deployed. Must add a "stale scripts" check or auto-install on version mismatch.
- Serial execution penalty: 5 tasks took 12min serial vs estimated ~5min parallel (longest task = sonnet mypy at ~5min). 2.4x slower.
- Haiku is highly cost-effective for bounded tasks: $0.07-$0.38 vs sonnet's $2.93
- Frontend build/lint found zero issues — confirms ai-ap-manager's existing code quality
- Auto-merge worked cleanly: 4 worktree branches merged to main without conflicts, including one that touched the same file as another (backend/app/core/deps.py) — git's merge strategy handled it

---
### 2026-03-03 — Fix 5 Stress-Test Bugs (pre-run hardening)

**Fixed all 5 bugs from owlcast stress test in 5 commits:**
1. **Parallel execution** — root cause: `extract_file_refs()` regex matched ALL file-like strings in task prose → false conflicts → everything serial. Fix: only match explicit `OWN_FILES:` declarations + `depends_on:` fields. Default is now parallel.
2. **Model-aware timeout** — flat 1800s was too short for opus, too long for haiku. Now: haiku=900s, sonnet=1800s, opus=3600s.
3. **Disk health check** — `_check_startup_health()` added to start.sh. ≥95% aborts, ≥90% warns with TTY prompt.
4. **/orchestrate retry** — missing `===TASK===` triggers one retry with format enforcement prefix. Checks for explicit `STATUS: CONVERGED`.
5. **Cost log** — `touch` at loop-runner.sh startup + guard in `_accumulate_cost()`.

**Lessons:**
- Regex-based file extraction from prose is fundamentally unreliable — explicit metadata fields (OWN_FILES:) are the only safe approach
- Model-aware defaults are better than one-size-fits-all — the model field already exists in task blocks, use it
- Health checks are cheap insurance — a 5-line `df` check prevents hours of cascading timeout debugging

---
### 2026-03-03 — Stress Test: start.sh on owlcast (real project, 6 tasks)

**First multi-hour stress test on a real codebase (owlcast — AI video pipeline, ~50 Python files).**

**Config:** `start.sh --goal .claude/stress-test-goal.md --budget 3 --hours 1`
- 6 targeted tasks: BGM populate, analytics investigation, mypy fix, CLI review, pipeline review, quality checker review
- Used `--goal` mode because `/orchestrate` returned conversational text on ambiguous TODO items

**Result:** CONVERGED at iteration 4, **$10.48 total**, **66 minutes**, **21 commits**.

| Task | Model | Result | Commits |
|------|-------|--------|---------|
| BGM populate + ffprobe verify | haiku | SUCCESS | `ac34ce2`, `ff9e21c` |
| Analytics platform limitation | haiku | SUCCESS (→ skipped.md) | `b266608` |
| Mypy 47 type errors | sonnet | PARTIAL (109→65 errors, 2x timeout) | `c2c6635` + 10 fix commits |
| CLI entry point wiring | sonnet | SUCCESS | `0a54a33` |
| Pipeline error handling | sonnet | SUCCESS (1x timeout, retry worked) | `0b5ffe1` |
| Quality checker gaps | haiku | SUCCESS | `775a876`, `81bc7e3` |

**Iteration breakdown:**
- Iter 1: Supervisor planned 4 tasks (combined some goals). Workers 1+3 succeeded, Worker 2 timed out 2x (permanently failed), Worker 4 timed out 1x then succeeded on retry.
- Iter 2: Supervisor saw Worker 4 results merged. Iter 1's Worker 4 had completed pipeline+CLI review.
- Iter 3: Supervisor found 8 uncommitted files from mypy partial fix. Planned cleanup task → merge conflict → serial retry → success (6 commits).
- Iter 4: Supervisor checked all 6 goals against commit history → CONVERGED.

**5 bugs found:**
1. **All tasks serial despite MAX_WORKERS=4** — `run-tasks-parallel.sh` puts all tasks in Group 1 (serial). Parallelism not working for targeted mode.
2. **Cost log initially empty** — `.claude/loop-cost.log` stayed empty for first iterations; cost tracking delay.
3. **Default timeout too short** — 600s insufficient for large mypy fix tasks on disk-pressure servers. Mypy task made real progress (109→65 errors) but timed out twice.
4. **Merge conflict on cleanup iteration** — worktree worker committed `.claude/session-progress.md` which conflicted with main. Auto-serial-retry handled it, but adds latency.
5. **/orchestrate conversational fallback** — when TODO items are vague, /orchestrate returns prose instead of ===TASK=== formatted tasks. `--goal` mode is the workaround.

**What worked well:**
- 3-tier issue handling: Worker 3 correctly wrote analytics limitation to skipped.md instead of failing
- Timeout analysis: each timeout produces a structured diagnosis (root cause, infrastructure status, recommendation)
- Session report: clean summary auto-generated with cost, commits, skipped items
- Supervisor convergence: correctly identified all 6 goals as done by checking commit history
- Merge conflict recovery: auto-serial-retry handled it without manual intervention

**Lessons:**
- Targeted mode (`--goal`) is more reliable than `/orchestrate` for well-defined task lists — removes the "conversational response" failure mode
- Haiku workers succeed more reliably than sonnet for bounded tasks (BGM populate, doc writing, quality review) — sonnet is better for large refactors but hits timeouts
- Disk pressure (93% full) is a real timeout contributor — should warn at start if disk > 90%
- Partial progress on timeout is valuable — mypy task reduced errors from 109→65 despite "failing"; next iteration cleaned up the uncommitted work
- Cost: $10.48 for 21 commits across 6 tasks = ~$0.50/commit, $1.75/task

---
### 2026-03-02 — start.sh Comprehensive Hardening (12 issues)

**Fixed 12 issues from full audit:**
1. **Verify-fail retry path**: fix tasks were overwritten by next /orchestrate. Added `VERIFY_FIX_PENDING` flag to skip orchestrate + preserve `VERIFY_RETRIES` count across re-loops.
2. **No timeout on `claude -p`**: orchestrate/verify 300s, sync 120s, morning 300s. Timeout → partial (not crash).
3. **No signal handler**: Added `trap _shutdown SIGTERM SIGINT` — writes session report + fires notification before exit.
4. **Python injection in `_filter_by_feature`**: Replaced shell-interpolated `'$VAR'` with `os.environ['_FILTER_FEATURE']`.
5. **Stale loop-state-start**: `rm -f .claude/loop-state-start` before each loop-runner.sh call.
6. **No lock file**: `flock -n .claude/start.lock` prevents concurrent instances.
7. **Resume doesn't restore settings**: BUDGET/HOURS/MAX_WORKERS/models saved to session-progress.md, restored on `--resume` (CLI flags override).
8. **Verify/sync failures silent**: Detect timeout (exit 124) and empty output explicitly, log warnings.
9. **--max-iter / --max-inner-iter flags**: Both configurable (defaults: 20 outer, 5 inner).
10. **Notification on completion/interrupt**: `_notify()` fires Telegram webhook (if configured) on session end.
11. **--dry-run flag**: (implemented by worker in e2e test)
12. **Verify retry count reset bug**: `VERIFY_RETRIES=0` was inside outer loop — now only resets on fresh orchestrate, not on verify-fix re-loop.

**Lessons:**
- `flock -n FD` + `exec FD>lockfile` is the idiomatic bash lock pattern — lock released on process exit (no cleanup needed)
- Env vars for python inline scripts (`_VAR="$shell_var" python3 -c "os.environ['_VAR']"`) is the safest shell→python data passing
- Verify-fail retry requires both flag (`VERIFY_FIX_PENDING`) AND preserving retry count — two separate state pieces that must travel together through `continue`

---
### 2026-03-02 — End-to-End Test: start.sh on claude-code-kit

**First real test of full start.sh → loop-runner.sh → worker pipeline.**

**Result:** Goal achieved in 2 iterations, $0.78 total cost, 2 minutes.
- Iter 1: supervisor planned 1 haiku task → worker implemented --dry-run → merge conflict → auto-serial-retry → success (1 commit)
- Iter 2: supervisor verified all checklist items done → CONVERGED
- Auto-deploy triggered (configs/ changed)

**4 bugs found and fixed:**
1. `grep -c "pattern" file || echo 0` produces `"0\n0"` (not `"0"`) — grep outputs count "0" before failing, then `|| echo 0` appends another "0". Fixed across loop-runner.sh, start.sh, tmux-dispatch.sh with `var=$(grep -c ...) || var=0` pattern.
2. Loop-runner cost logging unreachable on CONVERGED — `break` exits before cost block. Fixed: log supervisor cost before break.
3. `/orchestrate` returning conversational text ("No goal file found") passes `-s` (non-empty) check. Fixed: also check for `===TASK===` markers.
4. Targeted mode (`--goal`) convergence check counts `===TASK===` markers, but plain goal files don't have them → instant false convergence. Fixed: skip task-count convergence in targeted mode, delegate to loop-runner supervisor.

**Lessons:**
- `grep -c` returns exit code 1 when count=0 (unlike `wc -l` which returns 0 with exit 0). Never use `$(grep -c ... || echo 0)` — use `$(grep -c ...) || var=0` instead.
- Worktree merge conflict → serial fallback works perfectly for single-worker scenarios. The serial worker ran on main directly, which also captured our uncommitted manual fixes.
- Cost tracking works end-to-end: supervisor $0.25 + worker $0.33 per iteration, cumulative total accurate.

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
