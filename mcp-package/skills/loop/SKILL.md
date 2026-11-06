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
  reconcile_goal   — coordinator marks exact task-bound goal items
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
  repository). An in-repo DIR, a scenario symlinked into the repository, an
  empty DIR and an empty `--holdout` value are refused before anything runs.
- Each top-level executable file in DIR is a scenario. It runs after the verify
  node with cwd = the checkout root and stdin closed; exit 0 = satisfied.
  Non-executable files are notes and do not run.
- A failing scenario keeps the iteration out of goal reconciliation and keeps
  the run from converging, even when the checklist is ticked.
- Scenario names, paths and contents never enter a prompt: the supervisor sees
  only "F of T held-out scenarios failed". Names and output go to the
  human-facing `logs/loop/loop.log` and `logs/loop/iter-N-holdout.log`.
- A red holdout under a green `verify_cmd` logs `HOLDOUT FAILED — visible
  verify_cmd passed`. A scenario edited mid-run logs `HOLDOUT CHANGED`, and a
  `verify_cmd` that changes after pre-flight (including one deleted) is warned
  about once per change.

Honest scope: the workers run as your user, so they can still read or write
DIR by its absolute path. This makes the scenarios harder to rewrite, not
impossible to rewrite. Never write the holdout path or a scenario into the goal
file or a `--context` file: both are pasted into the supervisor prompt.

Resume is explicit and fail-closed: the checkpoint must match the current
checkout, goal path, branch, and HEAD. A normal launch starts fresh and never
silently consumes an older checkpoint.

Workers never mutate the shared goal file. The supervisor binds each task to
exact goal line/text evidence, and the coordinator marks those items only
after the worker, syntax, test, and final verification gates all pass. Commit
progress counts commits created directly by workers as well as the final sweep.
If the supervisor runtime is unavailable, Loop preserves its raw response,
reports `supervisor_failed`, and leaves the checkpoint resumable instead of
misclassifying repeated provider failures as empty plans or max-iteration work;
terminal execution failures also propagate a non-zero process exit.

## After convergence

Run `/review` to verify all behavior anchors still pass after autonomous changes.
