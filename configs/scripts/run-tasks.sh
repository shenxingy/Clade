#!/usr/bin/env bash
# run-tasks.sh v2 — Feed tasks to Claude Code with timeout, retry, rollback, and failure reporting
#
# Usage:
#   bash scripts/run-tasks.sh tasks.txt              # Run all tasks (auto-cleans on success)
#   bash scripts/run-tasks.sh tasks.txt --dry-run     # Preview without executing
#   bash scripts/run-tasks.sh tasks.txt --safe        # Run WITHOUT --dangerously-skip-permissions
#   bash scripts/run-tasks.sh tasks.txt --keep-logs   # Keep logs and task file even on success
#
# Features:
#   - Per-task timeout (default 10 min, configurable via timeout: metadata)
#   - Retry on failure (default 2 retries, configurable via retries: metadata)
#   - Git checkpoint/rollback on failure (restores clean state before retry)
#   - Failure reporting: PROGRESS.md + GitHub Issue for persistent failures
#   - Writes a progress file so other sessions can monitor status
#   - Re-reads task file each iteration — new tasks appended during execution are picked up
#   - Per-task model assignment (haiku/sonnet/opus) via new format
#
# Task file format:
#   ===TASK===
#   model: haiku
#   timeout: 300
#   retries: 3
#   ---
#   Remove the non-functional audience checkboxes...

set -uo pipefail
# NOTE: -e intentionally omitted — we handle errors explicitly in the main loop

TASK_FILE="${1:?Usage: run-tasks.sh <task-file> [--dry-run|--safe|--keep-logs]}"
MODE="${2:-}"
LOG_DIR="logs/claude-tasks"
KEEP_LOGS=false
if [[ "$MODE" == "--keep-logs" ]]; then
  KEEP_LOGS=true
  MODE=""
fi
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
PROGRESS_FILE="$LOG_DIR/${TIMESTAMP}-progress"

# Defaults
DEFAULT_TIMEOUT=1800    # 30 minutes per task
DEFAULT_RETRIES=2       # Retry failed tasks up to 2 times

# Default: skip permissions for unattended execution
CLAUDE_FLAGS="--dangerously-skip-permissions"
if [[ "$MODE" == "--safe" ]]; then
  CLAUDE_FLAGS=""
fi

if [[ ! -f "$TASK_FILE" ]]; then
  echo "Error: Task file '$TASK_FILE' not found"
  exit 1
fi

# Allow launching claude -p from within a Claude Code session
unset CLAUDECODE 2>/dev/null || true

mkdir -p "$LOG_DIR"

# ─── Shared library ─────────────────────────────────────────────────
# Parsing, timeout diagnostics and the worker runner are shared with
# run-tasks-parallel.sh. Sourced AFTER the globals above because it reads
# TASK_FILE, CLAUDE_FLAGS and DEFAULT_RETRIES. Fail hard rather than fall
# through: these run unattended under loop-runner.sh, and a silently missing
# library reproduces exactly the silent-success class run_claude_task's
# setsid comment calls CRITICAL.
_SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$_SELF_DIR/run_tasks_common.sh" ]]; then
  echo "Error: run_tasks_common.sh not found beside $0" >&2
  exit 1
fi
# shellcheck source=run_tasks_common.sh
. "$_SELF_DIR/run_tasks_common.sh"

# ─── New format helpers (===TASK=== delimited) ──────────────────────
# is_new_format, get_task_field, get_task_model, get_task_retries,
# get_task_prompt_new and get_task_name come from run_tasks_common.sh.

count_tasks_new() {
  # Count only tasks with non-empty body (skip trailing ===TASK=== with no content)
  awk '
    /^===TASK===$/ { if (has_body) valid++; has_body=0; in_meta=1; next }
    in_meta && /^---$/ { in_meta=0; next }
    !in_meta && NF { has_body=1 }
    END { if (has_body) valid++; print valid+0 }
  ' "$TASK_FILE"
}

# Serial mode's per-task timeout is the flat $DEFAULT_TIMEOUT. Deliberately
# NOT shared: run-tasks-parallel.sh's get_task_timeout uses model-aware
# defaults (haiku=900 / opus=3600 / else=1800). Unifying the two is a timeout
# decision with a real consequence, not part of a de-duplication move.
get_task_timeout() {
  get_task_field "$1" "timeout" "$DEFAULT_TIMEOUT"
}

# New-format prompt body. get_task_name (run_tasks_common.sh) resolves this
# name in the caller at call time, so serial mode keeps its own format
# dispatch — the legacy path lives in get_prompt/get_name below.
get_task_prompt() {
  get_task_prompt_new "$1"
}

# ─── Legacy format helpers (one task per line) ──────────────────────

read_tasks_legacy() {
  local tasks=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    tasks+=("$line")
  done < "$TASK_FILE"
  printf '%s\n' "${tasks[@]}"
}

# ─── Unified interface ──────────────────────────────────────────────

get_total() {
  if is_new_format; then
    count_tasks_new
  else
    read_tasks_legacy | wc -l
  fi
}

get_prompt() {
  local n="$1"
  if is_new_format; then
    get_task_prompt "$n"
  else
    read_tasks_legacy | sed -n "${n}p"
  fi
}

get_name() {
  local n="$1"
  if is_new_format; then
    get_task_name "$n"
  else
    read_tasks_legacy | sed -n "${n}p"
  fi
}

get_model() {
  local n="$1"
  if is_new_format; then
    get_task_model "$n"
  else
    echo "sonnet"
  fi
}

get_timeout() {
  local n="$1"
  if is_new_format; then
    get_task_timeout "$n"
  else
    echo "$DEFAULT_TIMEOUT"
  fi
}

get_retries() {
  local n="$1"
  if is_new_format; then
    get_task_retries "$n"
  else
    echo "$DEFAULT_RETRIES"
  fi
}

# ─── Progress tracking ──────────────────────────────────────────────

processed=0
success=0
failed=0
skipped=0
declare -a FAILED_TASKS=()
declare -a FAILED_ERRORS=()

write_progress() {
  local status="$1"
  local current_task="${2:-}"
  local current_model="${3:-}"
  local current_attempt="${4:-}"
  local max_attempts="${5:-}"
  local total
  total=$(get_total)
  cat > "$PROGRESS_FILE" <<EOF
TIMESTAMP=$TIMESTAMP
CURRENT=$processed
TOTAL=$total
SUCCESS=$success
FAILED=$failed
SKIPPED=$skipped
STATUS=$status
CURRENT_TASK=$current_task
CURRENT_MODEL=$current_model
CURRENT_ATTEMPT=$current_attempt
MAX_ATTEMPTS=$max_attempts
TASK_FILE=$TASK_FILE
LOG_DIR=$LOG_DIR
EOF
}

write_progress "starting"
echo "Progress file: $PROGRESS_FILE"

# ─── Git checkpoint helpers ──────────────────────────────────────────

has_git() {
  git rev-parse --is-inside-work-tree &>/dev/null
}

# Take a snapshot of working tree state before a task
checkpoint_before_task() {
  if ! has_git; then return 0; fi
  # Stage everything and record the tree state
  git add -A 2>/dev/null || true
  CHECKPOINT_SHA=$(git stash create 2>/dev/null || echo "")
  if [[ -z "$CHECKPOINT_SHA" ]]; then
    # No changes to stash — record HEAD
    CHECKPOINT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
  fi
}

# Rollback working tree to the checkpoint state
rollback_to_checkpoint() {
  if ! has_git; then return 0; fi
  echo "🔄 Rolling back to pre-task state..."
  git checkout . 2>/dev/null || true
  git clean -fd 2>/dev/null || true
}

# ─── Failure reporting ───────────────────────────────────────────────

append_to_progress_md() {
  local progress_file="PROGRESS.md"
  if [[ ! -f "$progress_file" ]]; then return 0; fi

  local date_str
  date_str=$(date +%Y-%m-%d)

  {
    echo ""
    echo "### Batch Task Failures ($date_str)"
    echo ""
    for i in "${!FAILED_TASKS[@]}"; do
      echo "- **${FAILED_TASKS[$i]}**: ${FAILED_ERRORS[$i]}"
    done
    echo "- _Lesson_: Review logs in \`$LOG_DIR/\` for details. Consider adding more specific plans for these tasks."
    echo ""
  } >> "$progress_file"

  echo "📝 Failures appended to PROGRESS.md"
}

create_github_issue() {
  # Only create issue if gh is available and we're in a git repo with a remote
  if ! command -v gh &>/dev/null; then return 0; fi
  if ! has_git; then return 0; fi
  if ! git remote get-url origin &>/dev/null; then return 0; fi

  local date_str
  date_str=$(date +"%Y-%m-%d %H:%M")
  local total
  total=$(get_total)

  local body="## Batch Task Failures — $date_str"$'\n\n'
  body+="**Source**: \`$TASK_FILE\`"$'\n'
  body+="**Results**: $success/$total succeeded, $failed failed"$'\n\n'
  body+="### Failed Tasks"$'\n\n'

  for i in "${!FAILED_TASKS[@]}"; do
    body+="#### $(( i + 1 )). ${FAILED_TASKS[$i]}"$'\n'
    body+="- **Error**: ${FAILED_ERRORS[$i]}"$'\n'
    body+="- **Log**: \`$LOG_DIR/${TIMESTAMP}-task-*.log\`"$'\n\n'
  done

  body+="### Successful Tasks"$'\n\n'
  body+="$success tasks completed successfully."$'\n\n'
  body+="_Generated automatically by \`run-tasks.sh\`_"

  echo "📋 Creating GitHub Issue for failures..."
  gh issue create \
    --title "Batch task failures: $date_str ($failed/$total failed)" \
    --body "$body" \
    --label "batch-failure" 2>/dev/null || \
  gh issue create \
    --title "Batch task failures: $date_str ($failed/$total failed)" \
    --body "$body" 2>/dev/null || \
  echo "⚠️  Could not create GitHub Issue (label may not exist or gh not authenticated)"
}

# ─── Timeout + cleanup helpers ───────────────────────────────────────
# record_task_start_state, cleanup_escaped_processes, collect_diagnostics,
# analyze_timeout and run_claude_task live in run_tasks_common.sh, sourced
# above — they were byte-identical copies of run-tasks-parallel.sh's.

# ─── Main loop ──────────────────────────────────────────────────────

while true; do
  # Re-read total each iteration to pick up dynamically added tasks
  total=$(get_total)

  # All done?
  if [[ $processed -ge $total ]]; then
    break
  fi

  idx=$((processed + 1))
  processed=$idx

  task_name=$(get_name "$idx")
  task_prompt=$(get_prompt "$idx")
  model=$(get_model "$idx")
  task_timeout=$(get_timeout "$idx")
  max_retries=$(get_retries "$idx")
  max_attempts=$((max_retries + 1))

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "[$idx/$total] [$model] $task_name"
  echo "Timeout: ${task_timeout}s | Max attempts: $max_attempts"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  if [[ "$MODE" == "--dry-run" ]]; then
    echo "[DRY RUN] Would execute: claude -p --model $model (timeout: ${task_timeout}s, retries: $max_retries)"
    write_progress "dry-run" "$task_name" "$model"
    continue
  fi

  task_succeeded=false
  last_error=""

  for attempt in $(seq 1 "$max_attempts"); do
    log_file="$LOG_DIR/${TIMESTAMP}-task-${idx}-attempt-${attempt}.log"

    if [[ $attempt -gt 1 ]]; then
      # Exponential backoff on timeout (like TCP congestion control)
      task_timeout=$(( task_timeout * 3 / 2 ))
      echo ""
      echo "🔄 Retry $attempt/$max_attempts for task $idx (timeout: ${task_timeout}s)..."
      sleep 3  # Brief cooldown between retries
    fi

    write_progress "running" "$task_name" "$model" "$attempt" "$max_attempts"

    # Checkpoint + baseline state before task
    checkpoint_before_task
    record_task_start_state

    # Run Claude Code with process-group isolation and watchdog
    exit_code=0
    echo "$task_prompt" | run_claude_task "$model" "$task_timeout" "$log_file" || exit_code=$?

    if [[ $exit_code -eq 0 ]]; then
      task_succeeded=true
      echo "✓ Task $idx completed [$model] (attempt $attempt)"
      break
    elif [[ $exit_code -eq 124 ]]; then
      last_error="Timed out after ${task_timeout}s"
      echo "⏰ Task $idx timed out after ${task_timeout}s (attempt $attempt/$max_attempts)"
      cleanup_escaped_processes "$task_name"
      analyze_timeout "$task_name" "$task_timeout" "$log_file"
    else
      last_error="Exit code $exit_code"
      # Capture last few lines of log for error context
      if [[ -f "$log_file" ]]; then
        tail_output=$(tail -5 "$log_file" 2>/dev/null | tr '\n' ' ' | cut -c1-200)
        if [[ -n "$tail_output" ]]; then
          last_error="Exit code $exit_code — $tail_output"
        fi
      fi
      echo "✗ Task $idx failed with exit code $exit_code (attempt $attempt/$max_attempts)"
    fi

    # Rollback on failure (only if there are more attempts or we need clean state)
    rollback_to_checkpoint
  done

  if $task_succeeded; then
    success=$((success + 1))
  else
    failed=$((failed + 1))
    FAILED_TASKS+=("$task_name")
    FAILED_ERRORS+=("$last_error (after $max_attempts attempts)")
    echo ""
    echo "❌ Task $idx permanently failed after $max_attempts attempts"
    echo "   Continuing to next task..."
  fi

  echo ""
done

write_progress "done"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Done. Total: $processed | Success: $success | Failed: $failed"
echo "Logs: $LOG_DIR/"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ─── Failure reporting ──────────────────────────────────────────────

if [[ $failed -gt 0 ]]; then
  echo ""
  echo "⚠️  $failed task(s) failed permanently:"
  for i in "${!FAILED_TASKS[@]}"; do
    echo "   $(( i + 1 )). ${FAILED_TASKS[$i]}"
    echo "      ${FAILED_ERRORS[$i]}"
  done
  echo ""

  # Append failures to PROGRESS.md
  append_to_progress_md

  # Create GitHub Issue
  create_github_issue
fi

# Auto-cleanup on full success
if [[ "$failed" -eq 0 && "$KEEP_LOGS" == false && "$MODE" != "--dry-run" && "$processed" -gt 0 ]]; then
  echo ""
  echo "All tasks succeeded — cleaning up intermediate files..."
  rm -f "$TASK_FILE"
  rm -rf "$LOG_DIR"
  rmdir logs 2>/dev/null || true
  echo "Removed: $TASK_FILE, $LOG_DIR/"
fi

[[ "$failed" -eq 0 ]]
