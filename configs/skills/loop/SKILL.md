---
name: loop
description: Goal-driven autonomous improvement loop — supervisor plans tasks each iteration, workers execute in parallel via batch-tasks, repeats until goal is achieved
argument-hint: 'GOAL_FILE [--model haiku|sonnet|opus] [--worker-model MODEL] [--max-iter N] [--max-workers N] [--dry-run] [--status] [--stop] [--resume]'
user_invocable: true
---

# Loop Skill

Runs an autonomous improvement loop driven by a **goal file** (ideal end state description).

## Architecture

```
You write: goal.md  (what the system should do — NOT a task list)
                ↓
Iteration N:
  Supervisor reads goal + git history → plans 1–4 tasks
  Workers execute ALL tasks IN PARALLEL (batch-tasks style)
  Supervisor re-reads goal + new commits → evaluates progress → re-plans
                ↓
Repeat until STATUS: CONVERGED or max iterations
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
/loop goal.md                          # Start loop (sonnet, max 10 iter, 4 parallel workers)
/loop goal.md --model haiku            # Cheaper/faster supervisor+workers
/loop goal.md --max-iter 3             # Short run to test
/loop goal.md --max-workers 2          # Limit parallel workers
/loop --status                         # Check current loop progress
/loop --stop                           # Stop loop after current iteration
/loop --dry-run goal.md                # Preview without running
/loop --resume goal.md                 # Resume interrupted loop
```
