---
name: Anthropic — Effective Harnesses for Long-Running Agents (Tier-1)
date: 2026-06-18
status: integrated
review_date: 2026-06-18
reconciled: 2026-06-18
summary: >
  Anthropic's two engineering posts on long-running agent harnesses (Nov 2025 +
  Mar 2026). Core thesis: the win is a smarter *environment around the model*,
  not a smarter model. Patterns — initializer/coding split, feature-list.json +
  claude-progress.txt + git as cross-session memory, a session-start HEALTH CHECK,
  single-feature-per-session, JSON-over-Markdown for tamper-resistance, and a
  GAN-style generator/evaluator separation with hard-threshold grading criteria.
  Clade already implements the supervisor/worker split, persistent cross-session
  state (event_stream + PROGRESS.md + git-log hydration), the independent-judge
  oracle with per-criterion verdicts, a pre-push functional test gate, browser
  verification, and convergence with k-of-n / max-iter / consecutive-no-commit
  stops. ONE genuine deficit: no *iteration-start broken-state health check* —
  Clade reads prior state but never re-runs the app/tests before planning new work.
sources:
  - https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
  - https://www.anthropic.com/engineering/harness-design-long-running-apps
  - https://www.anthropic.com/research/building-effective-agents
integrated_items:
  - "Supervisor/worker (planner/generator) split — configs/scripts/loop-runner.sh:8 ([LLM] supervisor plans tasks OR CONVERGED) + node_run_workers; orchestrator parallel workers via worktrees (worker.py WorkerPool)"
  - "Cross-session memory artifacts (Anthropic: claude-progress.txt + git + feature-list) — Clade: event_stream.py:202 (replay_from_path, crash-safe JSONL) + PROGRESS.md (worker_review.py:87 _write_progress_entry) + git-log hydration (loop-runner.sh:279 'git log --oneline -20' → .claude/loop-context.md)"
  - "Session bootstrap reads prior state before working (Anthropic: read git log + progress at session start) — loop-runner.sh:270 node_hydrate_context injects git log + diff stat + branch + status into supervisor context every iteration; worker.py:441 reads git log -1"
  - "Generator/evaluator separation against self-eval bias (Anthropic GAN loop) — worker_review.py:191/237 independent reviewer + quality-reviewer prompts run as a PURE JUDGE on a separate model (HAIKU_MODEL, worker_review.py:69/400) with no repo access (worker_review.py:292 'NO repository or filesystem access')"
  - "Hard-threshold grading with per-criterion verdicts + specific feedback (Anthropic: any failed criterion = rejection, specific code-location feedback) — worker_review.py:229/344 'give a verdict for EACH' acceptance criterion → satisfied/violated + evidence file:line; per-finding fix→requeue (worker_review.py:254)"
  - "Sprint-contract / acceptance-criteria handoff (Anthropic Pattern 4) — worker_taskfile.py:365 injects task schema (acceptance criteria + contracts) into the task file; oracle grades against them (worker_review.py:330 _build_oracle_task_block)"
  - "Functional verification gate before commit (Anthropic: test before marking complete) — worker.py:818 _run_project_tests pre-push; failure undoes commit + skips push (worker.py:838); test_cmd from .claude/orchestrator.json (worker_utils.py:399)"
  - "Browser/visual end-to-end verification (Anthropic: Playwright/Puppeteer, 'test as a human would') — worker_taskfile.py:56 'you MUST see it in a real browser before claiming done' via mcp__playwright__* (setup-browser-verify.sh); console-error check worker_taskfile.py:64"
  - "Context compaction augmented by structured artifacts (Anthropic: compaction alone insufficient) — condensers.py Condenser ABC + event_stream replay + PROGRESS.md; matches Anthropic's 'compaction + artifacts' stance"
  - "Stopping conditions / anti-premature-completion (Anthropic: feature-list prevents false 'done') — loop-runner.sh:1010 _check_convergence: supervisor returns CONVERGED, max_iter (config.py:92 loop_max_iterations=20), 3× consecutive-no-commits (loop-runner.sh:78) + 3× consecutive-failures (loop-runner.sh:79); k-of-n convergence (config.py:90-91)"
  - "Broken-state recovery on restart (Anthropic: detect broken state, fix before new work) — config.py:352 _recover_orphaned_tasks relabels interrupted tasks on session start (server.py:55); per-worker --continue resume with full-restart fallback (worker.py:1025)"
  - "Token-budget / context-anxiety guard (Anthropic: 'context anxiety' premature wrap) — worker_token_budget kill + token-budget cap; reflection retry capped 3× (auto_classify_retry_max, worker_utils.py:859)"
  - "Iteration-start health check — DONE (commit 32556fd): loop-runner.sh `node_health_check` runs verify_cmd at iteration start (fresh on iter 1, reuses prior result after), writes `.claude/health-warning.md` which `node_hydrate_context` folds into the supervisor context so a broken baseline is repaired before new work"
needs_work_items: []
reference_items:
  - "Initializer agent (one-time env setup: write init.sh + seed feature-list.json + initial commit) — N/A by scope: Anthropic builds greenfield apps from a 1-4 sentence prompt; Clade operates on EXISTING <500-file repos with a human-authored goal file + CLAUDE.md + start.sh already present. The 'set up the environment from scratch' step has no input in Clade's problem space. The durable half (machine-readable task inventory) is covered by the goal file + task_queue."
  - "feature-list.json with mandatory `passes` field + 'unacceptable to remove tests' prompt language — different-not-deficient: Clade's equivalent is the SQLite task_queue (per-task status) + VERIFY.md anchor checkpoints (review skill, convergence when all ✅/⚠) + acceptance-criteria schema. Clade's anti-tamper guard is structural (DB rows the worker cannot edit; oracle is a pure judge with no FS access, worker_review.py:292) rather than a prompt admonition over a JSON file — a stronger guarantee, not a weaker one."
  - "Single-feature-per-session constraint — different-not-deficient: Clade decomposes per ITERATION into ≤max_workers parallel tasks (loop-runner.sh:400 'plan at most $MAX_WORKERS tasks'), each worker in an isolated worktree on one task. Parallel-bounded decomposition is a deliberate, equivalent throughput choice for the multi-worker orchestrator, not a missing constraint."
  - "Three-agent (planner/generator/evaluator) decomposition — different-not-deficient: Clade is supervisor(planner) + worker(generator) + oracle(evaluator), the same three roles. The oracle is invoked as a gate inside the worker pipeline (worker.py:909 _run_oracle_gate) rather than as a peer agent negotiating sprint contracts, but the generator≠judge separation — the load-bearing insight — is present (separate model, no FS access)."
  - "Iterative evaluator-tuning loop (review logs, tighten prompts/few-shots until judgment aligns) — N/A as a runtime feature: this is a HUMAN dev-time calibration practice, not a harness component. Clade's oracle prompts have been hand-tuned across live-eval runs (worker_review.py:264 '4000 (was 400 — criteria never reached the oracle)', :270 fail-open audit) — the same practice, applied; nothing to ship."
  - "Context-reset + handoff vs continuous-session+compaction A/B (Opus 4.5 vs 4.6) — reference: Anthropic's own finding is that newer models make the reset/handoff scaffold largely unnecessary. Clade's /handoff + event-replay covers the reset path; condensers cover compaction. The A/B is a model-capability observation, not an action item."
  - "Strategic-pivot option (generator may abandon current aesthetic direction) — N/A by scope: design-space local-maxima escape is specific to subjective frontend-design generation; Clade's reflection retry already allows approach-change via --continue with episodic failure memory (worker_utils.py:812 _maybe_enqueue_classify_retry)."
---

[English] | [Back to README](../../README.md)

# Anthropic — Effective Harnesses for Long-Running Agents (Tier-1)

## Overview

Two Anthropic engineering posts (Nov 2025 + Mar 2026) on getting Claude to make
consistent progress across **many context windows** on multi-hour autonomous
coding tasks. Headline finding: the lever was **not a smarter model but a smarter
environment around the model** — a *harness*. The framing analogy: engineers
working in shifts, each arriving with **no memory of the previous shift**. Two
failure modes drive the design:

- **Over-ambitious one-shotting** — the agent tries to build the whole app, runs
  out of context mid-implementation, and leaves features half-finished and
  undocumented.
- **Premature completion** — a later session sees progress, declares the job
  done, and stops despite incomplete features.

The posts are directly on-target for Clade (an autonomous Claude-Code
supervisor→worker loop). The verdict below is **reference**: nearly every pattern
is already integrated, with **one genuine deficit**.

## What It Recommends — Key Harness Patterns

### Post 1 (Nov 2025) — Initializer + Coding agent

1. **Initializer agent (run once)** — writes `init.sh` (boots the dev server),
   seeds a `feature_list.json` (every feature, `"passes": false`), makes the
   initial commit, and writes `claude-progress.txt`.
2. **Coding agent (every later session)** — reads progress + git log to get up to
   speed, **runs init.sh and smoke-tests basic functionality first**, picks **one**
   feature, implements it, verifies end-to-end, flips `passes` to true, commits,
   updates the progress file.
3. **Session health check** — "start the dev server, run a basic end-to-end test
   *before* new feature work; if broken, fix it first." Called out as the cure for
   the "leaves bugs / broken state" failure mode.
4. **JSON over Markdown** for the feature list — "the model is less likely to
   inappropriately change or overwrite JSON files." Coding agents may edit **only**
   the `passes` field; "unacceptable to remove or edit tests."
5. **Browser automation for verification** (Puppeteer MCP) — "test as a human user
   would," screenshot to confirm. "Dramatically improved performance."
6. **Compaction is necessary but not sufficient** — structured artifacts (progress
   file, feature list, git) are required alongside SDK context compaction.

### Post 2 (Mar 2026) — Three-agent GAN-style harness

7. **Planner / Generator / Evaluator** split. Planner expands a 1-4 sentence
   prompt into an ambitious spec; generator builds; evaluator tests the **running**
   app via Playwright and grades against hard thresholds.
8. **GAN-style generator≠evaluator separation** — the central insight: "agents
   confidently praise their own work … separating the agent doing the work from the
   agent judging it proves to be a strong lever." Evaluator gets few-shot calibrated
   grading criteria; **any failed criterion = rejection** + specific feedback (code
   location, function name, expected vs actual).
9. **Sprint contracts** — generator + evaluator agree what "done" means before
   coding.
10. **Periodic harness-simplification review** — when a new model ships, A/B-remove
    scaffolding that's no longer load-bearing (Opus 4.6 made context-resets mostly
    unnecessary).

## Per-Pattern Clade Comparison (file:line evidence)

| Anthropic pattern | Clade status | Evidence |
|---|---|---|
| Planner / generator / evaluator split | **Integrated** | supervisor `loop-runner.sh:8`; workers `node_run_workers`; oracle `worker.py:909` |
| Cross-session memory (progress + git + list) | **Integrated** | `event_stream.py:202` replay; `worker_review.py:87` PROGRESS.md; `loop-runner.sh:279` git-log hydrate |
| Session bootstrap reads prior state | **Integrated** | `loop-runner.sh:270` node_hydrate_context → supervisor context |
| Generator≠evaluator (self-eval bias) | **Integrated** | `worker_review.py:191/237` pure judge, separate model `:69`, no FS `:292` |
| Hard-threshold per-criterion grading + specific feedback | **Integrated** | `worker_review.py:344` verdict-for-EACH + evidence file:line; per-finding requeue `:254` |
| Sprint contract / acceptance criteria | **Integrated** | `worker_taskfile.py:365` injects acceptance criteria + contracts |
| Functional test gate before commit | **Integrated** | `worker.py:818` pre-push `_run_project_tests`; undo on fail `:838` |
| Browser end-to-end verification | **Integrated** | `worker_taskfile.py:56` Playwright "see it in a real browser" |
| Compaction + structured artifacts | **Integrated** | `condensers.py` + `event_stream` + PROGRESS.md |
| Stopping / anti-premature-completion | **Integrated** | `loop-runner.sh:1010` CONVERGED + max_iter + 3× no-commit + k-of-n |
| Broken-state recovery on restart | **Integrated** | `config.py:352` _recover_orphaned_tasks; `worker.py:1025` --continue/restart |
| JSON-over-Markdown tamper guard | **Reference** (stronger equiv) | SQLite task_queue + oracle no-FS `:292` — DB rows worker can't edit |
| Single-feature-per-session | **Reference** (diff) | `loop-runner.sh:400` ≤max_workers parallel tasks, 1 task/worktree |
| Initializer agent (greenfield env setup) | **Reference** (N/A scope) | Clade runs on existing repos; start.sh + goal file pre-exist |
| **Iteration-start health check** | **NEEDS WORK** | `loop-runner.sh:247/270` pre_flight + hydrate are READ-ONLY; no app/test run before planning |

## The One Genuine Gap — Iteration-Start Health Check

Anthropic's strongest error-recovery lever: **at the start of each session, run
the app and smoke-test it; if the prior session left it broken, fix that first,
because proceeding with new features "would likely make the problem worse."**

Clade has every *read* of prior state (git-log hydration, PROGRESS.md, orphaned-task
recovery) but **no active broken-state probe at the loop level before the supervisor
plans the next iteration.** The functional test gate (`worker.py:818
_run_project_tests`) is **per-worker, pre-push** — it only catches breakage from
*that worker's own diff*. A broken state introduced by a prior merged iteration, an
out-of-band edit, or a flaky environment is invisible until (and unless) a later
worker happens to trip over it. `node_pre_flight` (loop-runner.sh:247) and
`node_hydrate_context` (loop-runner.sh:270) read git log / status / blocker-file —
they never execute `test_cmd`.

**Fix (small, reversible):** add a `[DET] node_health_check` between
`node_hydrate_context` and `node_supervisor`. Run the project `test_cmd` (already
read at `worker_utils.py:399`) once per iteration; on failure, prepend the
supervisor context with a "REPAIR FIRST: the build is currently broken — <output>"
banner so the iteration's first planned task is repair, not new features. This is
precisely the row in Anthropic's failure-mode table that Clade does not yet cover.

## Verdict

**Reference**, with **1 needs-work item**. Clade's harness is a near-complete
superset of Anthropic's recommendations: the supervisor/worker/oracle split, the
generator≠judge self-eval-bias mitigation (with the *stronger* guarantee of a
no-filesystem pure judge on a separate model), persistent event-sourced
cross-session state, hard-threshold per-criterion grading with file:line feedback,
a pre-push functional gate, browser verification, and multi-signal convergence
stops are all present and cited above. The initializer agent and JSON-feature-list
are out of scope or covered by stronger structural equivalents. The single real
deficit is the **iteration-start broken-state health check**, which maps to a
concrete, small, reversible loop-runner node.
