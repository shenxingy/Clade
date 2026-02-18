---
name: batch-tasks
description: Execute TODO.md steps via unattended Claude Code sessions
argument-hint: '[step2 step4 ...] | "task1" "task2" ... | --run [file] | --dry-run [file] | --parallel [file]'
---

# Batch Tasks Skill

Read steps from TODO.md, auto-plan implementation details, and run them sequentially (or in parallel) via `claude -p`. Each task runs in a fresh Claude Code session with pre-generated plans.

## Key features

- **TODO.md integration** — Reads project TODO.md, parses steps and unchecked items. Default: first uncompleted step. Specify steps: `/batch-tasks step2 step4`.
- **Auto-planning** — Before writing tasks, the skill researches relevant files in the current session (which has codebase context) and generates detailed implementation plans with file paths, line numbers, and patterns to follow. This dramatically reduces token waste from redundant exploration in `claude -p` sessions.
- **Scout scoring** — Each task is scored (0-100) before execution. Tasks scoring <50 are skipped and a GitHub Issue is created instead. Tasks 50-79 are flagged as risky.
- **Per-task model assignment** — Each task is automatically assigned `haiku` (simple deletions, <20 lines), `sonnet` (standard features, 2-4 files), or `opus` (architectural, 5+ files) based on complexity.
- **Per-task timeout & retries** — Each task has a configurable timeout (default 10 min) and retry count (default 2). Timed-out or failed tasks are rolled back via git and retried automatically.
- **Failure resilience** — Failed tasks don't kill the batch. After all retries are exhausted, failures are logged to PROGRESS.md and a GitHub Issue is created automatically.
- **Parallel execution** — `--parallel` flag runs independent tasks concurrently using git worktrees, with automatic conflict detection and merge.
- **Background execution** with live progress monitoring

## Usage

### Execute TODO steps (primary usage)
```
/batch-tasks              # First uncompleted step from TODO.md
/batch-tasks step2        # Execute Step 2
/batch-tasks step2 step4  # Execute Steps 2 and 4
```

### Run from quoted task descriptions
```
/batch-tasks "Fix sidebar padding" "Add loading skeleton to /projects"
```

### Run / preview an existing task file
```
/batch-tasks --run                # Serial execution
/batch-tasks --parallel           # Parallel execution (git worktrees)
/batch-tasks --dry-run
```

## How it works

1. **Parse TODO.md** — Finds the target step(s), extracts unchecked `- [ ]` items
2. **Planning phase** — For each item, searches the codebase (Glob/Grep), reads relevant files, and generates a detailed plan with exact file paths, line numbers, and implementation steps
3. **Scout scoring** — Each task is scored on readiness (target files found, patterns clear, no blocking deps). Tasks scoring <50 are skipped.
4. **Model assignment** — Each task gets assigned `haiku`, `sonnet`, or `opus` based on complexity
5. Tasks are written to `tasks.txt` in delimited block format
6. `scripts/run-tasks.sh` (serial) or `scripts/run-tasks-parallel.sh` (parallel) executes tasks
7. Each task runs with a timeout; on failure, working tree is rolled back and the task is retried
8. Logs go to `logs/claude-tasks/` with timestamps (per attempt)
9. After all tasks complete: success/failure summary, failures logged to PROGRESS.md + GitHub Issue
