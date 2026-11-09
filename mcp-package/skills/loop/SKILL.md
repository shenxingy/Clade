---
name: loop
description: Clade goal-driven autonomous improvement loop (Blueprint architecture — deterministic pre/post phases + LLM supervisor/worker nodes, converges on goal met or max-iter). NOT the Claude Code built-in /loop (interval polling like `/loop 5m /foo`) — route those to the built-in.
when_to_use: "run loop with goal file, autonomous supervisor+worker loop, keep fixing until tests pass in background workers, iterate until converged, goal.md, Blueprint loop, 自动循环, run until converged — NOT for TODO.md tasks (/batch-tasks), task decomposition (/orchestrate), in-session iteration (/iloop), or interval polling (CC built-in /loop)"
argument-hint: 'GOAL_FILE [--model haiku|sonnet|opus] [--worker-model MODEL] [--max-iter N] [--max-workers N] [--supervisor-timeout N] [--holdout DIR] [--dry-run] [--status] [--stop] [--resume]'
user_invocable: true
---

# Loop Skill

Runs an autonomous improvement loop driven by a **goal file** (ideal end state description).

## Architecture

```
You write: goal.md  (what the system should do — NOT a task list)
                ↓
PRE (deterministic):
  pre_flight       — goal exists, no blockers
  hydrate_context  — git log + status
  parse_todo       — extract unchecked items from goal file
                ↓
LLM CORE:
  Supervisor       — plans 1–4 tasks (output: JSON task array)
  Workers          — execute ALL tasks IN PARALLEL
                ↓
POST (deterministic + conditional LLM):
  syntax_check     — validate all changed files
  fix_syntax       — [LLM] one attempt to fix failures
  test_sample      — run verify_cmd from CLAUDE.md
  mid-iter fix     — [LLM] if test fails → fix → re-test (Stripe pattern)
  verify           — require an explicit final-state pass
  holdout          — run --holdout scenarios kept outside the repository
  reconcile_goal   — coordinator marks exact task-bound goal items whose task changed the tree
  commit_changes   — sweep leftovers and count every iteration commit
                ↓
Deterministic convergence check:
  - remaining unchecked items = 0 → CONVERGED (and every --holdout scenario passes)
  - max iterations hit        → exit
  - stuck (N× no-commits)    → exit
                ↓
Repeat until CONVERGED or max iterations
```

## What you write (goal.md)

```markdown
# Goal: Improve orchestrator loop mode

## Requirements
- Oracle rejection re-queues task with rejection reason as context
- Worker context budget warning auto-injected at 80%
- Workers get AGENTS.md prepended automatically

## Success criteria
- python -m py_compile server.py passes
- Existing features unaffected
```

The **supervisor** does the task breakdown — not you.

## Usage

```
/loop goal.md                                # Start loop (sonnet, max 10 iter, 4 parallel workers)
/loop goal.md --model haiku                  # Cheaper/faster supervisor+workers
/loop goal.md --max-iter 3                  # Short run to test
/loop goal.md --max-workers 2                # Limit parallel workers
/loop goal.md --max-consecutive-failures 5  # Stop after 5 consecutive worker failures (default: 3)
/loop --status                               # Check current loop progress
/loop --stop                                 # Stop loop after current iteration
/loop --dry-run goal.md                      # Preview without running (goal may precede or follow flags)
/loop goal.md --supervisor-timeout 600      # Bigger planning budget (default 300s)
/loop --resume goal.md                       # Resume an exact matching interrupted loop
/loop goal.md --holdout ~/holdout/myproj     # Acceptance scenarios the workers' commits cannot reach
```

## Holdout scenarios (`--holdout DIR`)

Every gate above lives in the tree the workers commit into: `verify_cmd` is
re-read from the repository's CLAUDE.md each iteration, and the whole goal file
is pasted into the supervisor prompt. StrongDM's software-factory write-up names
the risk: "A test, stored in the codebase, can be lazily rewritten to match the
code." `--holdout DIR` adds a gate kept outside it:

- DIR must resolve outside the repository (`cd DIR && pwd -P` against
  `git rev-parse --show-toplevel`, and outside every other worktree of the same
  repository). An in-repo DIR, a scenario symlinked into the repository or
  into another worktree of it, an empty DIR and an empty `--holdout` value are
  refused before anything runs.
- Each top-level executable file in DIR is a scenario. It runs after the verify
  node with cwd = the checkout root and stdin closed; exit 0 = satisfied. A
  scenario still running after 120 s is cut off and fails
  (`CLADE_LOOP_HOLDOUT_TIMEOUT=N` changes the bound): the loop's own watchdog
  (python3, so no `timeout`/`gtimeout` is needed, stock macOS included) sends
  SIGTERM to its whole process group, then SIGKILL 5 s later. Other files —
  fixtures, expected outputs, helpers, notes — do not run.
- A scenario must not write into the checkout. Whatever the scenarios create,
  change or delete there (tracked or untracked, ignored files aside) is put
  back after they run, so the iteration's commit cannot carry it. The git
  index is put back byte for byte, so skip-worktree (sparse checkout) and
  intent-to-add entries survive. The loop's own `.claude/`, log directory and
  state file are left alone.
- A failing scenario keeps the iteration out of goal reconciliation and keeps
  the run from converging, even when the checklist is ticked. So does a set
  that can no longer run (deleted, or no longer executable).
- Scenario names, paths, contents and output never enter a prompt or any file
  inside the checkout: the supervisor sees only "F of T held-out scenarios
  failed", and `logs/loop/loop.log` and `last-progress` get counts (a failing
  scenario is "scenario 2 of 3"). Names, exit codes, output and what was put
  back go to `~/.claude/loop-holdout/<checkout>-<hash>/iter-N-holdout.log`,
  outside the repository; the terminal is told the path at start and after
  each check. `CLADE_LOOP_HOLDOUT_LOG_DIR` moves it, and is refused inside the
  checkout, another worktree of it, or DIR.
- A red holdout under a green `verify_cmd` logs `HOLDOUT FAILED — visible
  verify_cmd passed`. Any file under DIR added, removed, edited or chmod'ed
  mid-run — a fixture or an expected output as much as a scenario, at any
  depth — logs `HOLDOUT CHANGED`; that iteration's pass does not count until
  the set passes again unchanged, and the end-of-run report and `--status`
  say "scenario set CHANGED mid-run at iteration N". A `verify_cmd` that
  changes after pre-flight (including one deleted) is warned about once per
  change.

Honest scope: the workers run as your user, so they can still read or write
DIR, and the holdout log, by absolute path. This makes the scenarios harder to
rewrite, not impossible to rewrite. Never write the holdout path or a scenario
into the goal file or a `--context` file: both are pasted into the supervisor
prompt. The runner warns, and does not refuse, when either names DIR as given,
its physical path or its `~/` form; a scenario name is not searched for, since
a short one would match prose.

Resume is explicit and fail-closed: the checkpoint must match the current
checkout, goal path, branch, HEAD and `--holdout` directory. Resume with the
same `--holdout DIR` the interrupted run had; a resume without it, or with
another one, is refused rather than run with the held-out gate off. A normal
launch starts fresh and never silently consumes an older checkpoint.

Workers never mutate the shared goal file. The supervisor binds each task to
exact goal line/text evidence, and the coordinator marks those items only
after the worker, syntax, test, and final verification gates all pass, and only
for tasks whose worker actually changed the tree. Both worker runners record a
per-task outcome (`changed` / `unchanged` / `failed`); a worker that exits 0
having changed nothing (the Tier-2 "skip, log, continue" path) leaves its item
unchecked and the coordinator logs it as withheld. Commit
progress counts commits created directly by workers as well as the final sweep.
If the supervisor runtime is unavailable, Loop preserves its raw response,
reports `supervisor_failed`, and leaves the checkpoint resumable instead of
misclassifying repeated provider failures as empty plans or max-iteration work;
terminal execution failures also propagate a non-zero process exit.

## After convergence

Run `/review` to verify all behavior anchors still pass after autonomous changes.
