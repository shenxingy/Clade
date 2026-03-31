# Batch Tasks Improvement Research

---
name: batch-tasks.md
date: 2026-02-19
status: integrated
review_date: 2026-03-31
summary:
  - "Timeout, retry, rollback, failure reporting + AI diagnostics for batch tasks"
integrated_items:
  - "timeout/retry/rollback — run-tasks.sh 有完整实现，ff53250+14fb860"
  - "Failure reporting (PROGRESS.md + GitHub Issue) — run-tasks.sh 有完整实现，ff53250"
  - "Per-task metadata (model/timeout/retries) — run-tasks.sh + batch-tasks skill 有完整实现，b461716+64ddac9"
  - "Stall detection + heartbeat — run-tasks.sh 有实现，01c1918"
  - "Docker/GPU cleanup — run-tasks.sh 有实现，ff53250"
  - "setsid --wait zombie prevention — run-tasks.sh 有实现，7c98375"
  - "Timeout analysis with AI diagnostics — run-tasks.sh 有 analyze_timeout 函数"
  - "Scout scoring — batch-tasks skill 有完整实现，64ddac9"
needs_work_items: []
reference_items:
  - "Alternative: git worktrees per task — research 认为是 overkill，Clade 判断一致（正确）"
  - "Alternative: Docker per task — research 认为是 overkill，Clade 判断一致（正确）"
  - "Alternative approaches (git worktrees per task, Docker per task) — not implemented, verdict was 'overkill for most tasks'"
---

## Current Architecture

```
/batch-tasks skill (prompt.md)
  → Parses TODO.md
  → Plans each task with file paths, line numbers
  → Assigns model (haiku/sonnet/opus)
  → Writes tasks.txt
  → Calls scripts/run-tasks.sh
    → For each task:
      → echo "$prompt" | claude -p --model $model --dangerously-skip-permissions
      → Logs to logs/claude-tasks/
      → Updates progress file
```

## Current Problems

### 1. No timeout → tasks can hang forever
`claude -p` has no built-in timeout. If it enters a loop or waits for something, it blocks the entire batch indefinitely.

### 2. `set -euo pipefail` → one failure kills everything
One task failing kills the entire batch. The remaining tasks never run, even if they're independent.

### 3. No rollback → half-finished code
When a task fails mid-execution, the codebase is left in a partially modified state. The next task may fail because of the broken state from the previous one.

### 4. No retry → transient failures are permanent
Network issues, rate limits, or context window overflows could cause a task to fail. A simple retry would fix many of these.

### 5. No failure reporting → failures get lost
Failures are only in log files. No PROGRESS.md update, no GitHub issue, no notification.

## Proposed Solution

### Enhanced run-tasks.sh

```bash
#!/usr/bin/env bash
# run-tasks.sh v2 — with timeout, retry, rollback, and failure reporting

set -uo pipefail  # Remove -e: handle errors explicitly

DEFAULT_TIMEOUT=600      # 10 minutes per task
DEFAULT_RETRIES=2        # Retry failed tasks up to 2 times
FAILED_TASKS=()          # Track failures for reporting

# ... (existing setup code) ...

run_single_task() {
  local idx="$1"
  local task_prompt="$2"
  local model="$3"
  local task_timeout="${4:-$DEFAULT_TIMEOUT}"
  local max_retries="${5:-$DEFAULT_RETRIES}"
  local task_name="$6"
  local attempt=0

  while [ $attempt -le $max_retries ]; do
    attempt=$((attempt + 1))

    # Checkpoint: save current state
    git add -A 2>/dev/null
    git stash push -m "batch-checkpoint-task-${idx}-attempt-${attempt}" 2>/dev/null
    git stash pop 2>/dev/null  # Restore but keep the stash entry

    # Run with timeout
    if timeout "${task_timeout}s" bash -c \
      'echo "$1" | claude -p --model "$2" $3 --verbose' \
      -- "$task_prompt" "$model" "$CLAUDE_FLAGS" \
      2>&1 | tee "${log_file}-attempt-${attempt}"; then
      # Success
      return 0
    else
      exit_code=$?
      if [ $exit_code -eq 124 ]; then
        echo "⏰ Task $idx timed out after ${task_timeout}s (attempt $attempt/$((max_retries+1)))"
      else
        echo "✗ Task $idx failed with exit code $exit_code (attempt $attempt/$((max_retries+1)))"
      fi

      # Rollback: restore to checkpoint
      git checkout . 2>/dev/null
      git clean -fd 2>/dev/null

      if [ $attempt -le $max_retries ]; then
        echo "🔄 Retrying task $idx..."
        sleep 5  # Brief cooldown
      fi
    fi
  done

  # All retries exhausted
  return 1
}
```

### New task metadata fields

```
===TASK===
model: sonnet
timeout: 900
retries: 3
---
```

Parser additions in `get_task_timeout()` and `get_task_retries()` follow the same awk pattern as `get_task_model()`.

### Failure reporting

After batch completion, if there are failures:

1. **PROGRESS.md** — append failure summary:
```markdown
### Batch Task Failures (2026-02-17)
- Task 3 "Add loading skeleton" failed after 3 attempts: type-check error in LoadingSkeleton.tsx
- Lesson: Need to check component imports before generating new components
```

2. **GitHub Issue** — create with `gh issue create`:
```bash
if [ ${#FAILED_TASKS[@]} -gt 0 ]; then
  BODY=$(generate_failure_report)
  gh issue create \
    --title "Batch task failures: $(date +%Y-%m-%d)" \
    --body "$BODY" \
    --label "batch-failure,automated"
fi
```

### Progress file enhancements

```
TIMESTAMP=20260217-153000
CURRENT=3
TOTAL=5
SUCCESS=2
FAILED=1
RETRYING=0
STATUS=running
CURRENT_TASK=Add estimate field inline edit
CURRENT_MODEL=sonnet
CURRENT_ATTEMPT=1
MAX_ATTEMPTS=3
TASK_FILE=tasks.txt
LOG_DIR=logs/claude-tasks
TIMEOUT=600
```

## Alternative Approaches Considered

### 1. Use Agent Teams instead of serial claude -p
- **Pro**: True parallelism, shared context, message passing
- **Con**: More complex setup, harder to debug, new feature (less stable)
- **Verdict**: Keep serial for now, explore agent teams as Phase 5

### 2. Use git worktrees per task
- **Pro**: Complete isolation, no rollback needed
- **Con**: Each worktree needs `pnpm install`, much slower
- **Verdict**: Overkill for most tasks; use rollback approach instead

### 3. Docker containers per task
- **Pro**: Perfect isolation
- **Con**: Extreme overhead, complex setup
- **Verdict**: Not worth it

## Implementation Checklist

- [ ] Remove `set -e` from main loop
- [ ] Add `timeout` command wrapper for `claude -p`
- [ ] Add git checkpoint/rollback logic
- [ ] Add retry loop with configurable attempts
- [ ] Add `timeout:` and `retries:` metadata parsing
- [ ] Add failure collection array
- [ ] Add PROGRESS.md failure reporting
- [ ] Add GitHub Issue creation for failures
- [ ] Update progress file with attempt/retry info
- [ ] Update batch-tasks prompt.md to generate new metadata fields
- [ ] Test with intentionally failing tasks
