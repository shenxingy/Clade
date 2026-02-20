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
DEFAULT_TIMEOUT=600     # 10 minutes per task
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

# ─── Format detection ───────────────────────────────────────────────

is_new_format() {
  grep -q '^===TASK===$' "$TASK_FILE"
}

# ─── New format helpers (===TASK=== delimited) ──────────────────────

count_tasks_new() {
  grep -c '^===TASK===$' "$TASK_FILE"
}

# Get a metadata field for Nth task (1-indexed). Usage: get_task_field N "model" "default"
get_task_field() {
  local n="$1"
  local field="$2"
  local default="${3:-}"
  local result
  result=$(awk -v n="$n" -v field="$field" '
    /^===TASK===$/ { count++ }
    count == n && $0 ~ "^"field":" {
      gsub("^"field":[[:space:]]*", ""); print; found=1; exit
    }
    count == n && /^---$/ { if (!found) exit }
    END { if (!found) print "" }
  ' "$TASK_FILE")
  if [[ -z "$result" ]]; then
    echo "$default"
  else
    echo "$result"
  fi
}

get_task_model() {
  get_task_field "$1" "model" "sonnet"
}

get_task_timeout() {
  get_task_field "$1" "timeout" "$DEFAULT_TIMEOUT"
}

get_task_retries() {
  get_task_field "$1" "retries" "$DEFAULT_RETRIES"
}

# Get prompt body for Nth task (1-indexed)
get_task_prompt() {
  local n="$1"
  awk -v n="$n" '
    /^===TASK===$/ { count++; in_meta=1; in_body=0; next }
    count == n && in_meta && /^---$/ { in_meta=0; in_body=1; next }
    count == n && in_body && /^===TASK===$/ { exit }
    count == n && in_body { print }
    count > n { exit }
  ' "$TASK_FILE" | sed -e '1{/^$/d}' -e '${/^$/d}'
}

get_task_name() {
  local n="$1"
  get_task_prompt "$n" | awk 'NF { print; exit }'
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

# Record baseline system state before a task attempt (docker containers, GPU pids)
record_task_start_state() {
  _CONTAINERS_BEFORE=$(docker ps -q 2>/dev/null | sort || true)
  _GPU_PIDS_BEFORE=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | sort || true)
}

# Kill docker containers and GPU processes that appeared during the task (escaped the PGID)
cleanup_escaped_processes() {
  local task_name="$1"
  local cleaned=""

  if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    local containers_now new_containers
    containers_now=$(docker ps -q 2>/dev/null | sort || true)
    new_containers=$(comm -13 <(echo "${_CONTAINERS_BEFORE:-}") <(echo "$containers_now") | tr '\n' ' ')
    if [[ -n "$new_containers" ]]; then
      echo "  🐳 Stopping Docker containers started by task: $new_containers"
      # shellcheck disable=SC2086
      docker stop $new_containers 2>/dev/null || true
      cleaned+="docker:$new_containers "
    fi
  fi

  if command -v nvidia-smi &>/dev/null; then
    local gpu_pids_now new_gpu_pids
    gpu_pids_now=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | sort || true)
    new_gpu_pids=$(comm -13 <(echo "${_GPU_PIDS_BEFORE:-}") <(echo "$gpu_pids_now"))
    if [[ -n "$new_gpu_pids" ]]; then
      echo "  🖥️  Killing GPU processes started by task: $new_gpu_pids"
      echo "$new_gpu_pids" | xargs kill -TERM 2>/dev/null || true
      sleep 5
      echo "$new_gpu_pids" | xargs kill -KILL 2>/dev/null || true
      cleaned+="gpu_pids:$new_gpu_pids "
    fi
  fi

  [[ -n "$cleaned" ]] && echo "  Cleaned up: $cleaned"
}

collect_diagnostics() {
  echo "=== Diagnostics: $(date '+%Y-%m-%d %H:%M:%S') ==="

  if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    echo "--- Running containers ---"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || true
    local unhealthy
    unhealthy=$(docker ps --filter "health=unhealthy" --format "{{.Names}}" 2>/dev/null || true)
    [[ -n "$unhealthy" ]] && echo "⚠️  Unhealthy: $unhealthy"
    for cf in docker-compose.yml docker-compose.yaml compose.yml compose.yaml; do
      [[ -f "$cf" ]] && { docker compose -f "$cf" ps 2>/dev/null || true; break; }
    done
  fi

  if command -v nvidia-smi &>/dev/null; then
    echo "--- GPU processes ---"
    nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory \
      --format=csv,noheader 2>/dev/null || true
  fi

  echo "--- Long-running processes (>30s) ---"
  ps -eo pid,etimes,comm,args --sort=-etimes 2>/dev/null | \
    awk 'NR==1 || ($2>30 && /npm|node|pnpm|bun|expo|metro|cargo|go |python|java|docker|kubectl|helm|deploy|migrate|train|torchrun/)' | \
    head -12 || ps aux 2>/dev/null | head -8

  echo "--- Resources ---"
  df -h . 2>/dev/null | tail -1 || true
  free -h 2>/dev/null | grep Mem || true
}

# Call haiku to analyse why a task timed out; prints a diagnostic box
analyze_timeout() {
  local task_name="$1" timeout_sec="$2" log_file="$3"
  echo ""; echo "🔍 Analyzing timeout — $task_name"

  local diag last_log af
  diag=$(collect_diagnostics 2>/dev/null)
  last_log=$(tail -30 "$log_file" 2>/dev/null || true)
  af=$(mktemp /tmp/claude-analysis-XXXXXX)
  cat > "$af" <<PROMPT
A batch task timed out after ${timeout_sec}s. Diagnose and give specific fix commands.

## Timed-out task
$task_name

## Last 30 lines before timeout
\`\`\`
$last_log
\`\`\`

## System state
\`\`\`
$diag
\`\`\`

Answer concisely (max 12 lines):
1. Root cause of the hang (blocked I/O, deadlock, service down, etc.)
2. Docker/GPU/infra issues? (unhealthy container, stuck deploy, port conflict, prior run still active)
3. Recommendation: RETRY-NOW / RETRY-AFTER-FIX / SKIP
4. If RETRY-AFTER-FIX: give the exact shell commands to fix it
PROMPT

  local analysis=""
  if command -v claude &>/dev/null; then
    analysis=$(timeout 90s claude -p --model haiku --dangerously-skip-permissions < "$af" 2>/dev/null \
      || echo "(analysis unavailable)")
  fi
  rm -f "$af"

  echo ""
  echo "┌─ Timeout Analysis ─────────────────────────────────────────────"
  if [[ -n "$analysis" ]]; then
    while IFS= read -r line; do printf "│ %s\n" "$line"; done <<< "$analysis"
  else
    while IFS= read -r line; do printf "│ %s\n" "$line"; done <<< "$diag"
  fi
  echo "└────────────────────────────────────────────────────────────────"
  echo ""

  { echo ""; echo "=== Timeout Analysis ==="; [[ -n "$analysis" ]] && echo "$analysis"; echo ""; echo "$diag"; } >> "$log_file"
}

# Run a claude task in a new process group session with a watchdog timer.
# Usage: echo "$prompt" | run_claude_task <model> <timeout_sec> <log_file> [workdir]
# Returns: 0=success, 124=timeout, other=claude error
run_claude_task() {
  local model="$1" timeout_sec="$2" log_file="$3" workdir="${4:-$(pwd)}"

  # Write prompt and runner script to temp files (avoids CLAUDE_FLAGS quoting issues)
  local pf runner
  pf=$(mktemp /tmp/claude-task-XXXXXX)
  runner=$(mktemp /tmp/claude-runner-XXXXXX.sh)
  cat > "$pf"   # read prompt from stdin
  printf '#!/usr/bin/env bash\ncd "%s" || exit 1\nexec claude -p --model "%s" %s --verbose\n' \
    "$workdir" "$model" "$CLAUDE_FLAGS" > "$runner"
  chmod +x "$runner"

  # setsid creates a new session; runner PID = new PGID, so kill -PGID kills the whole tree
  touch "$log_file"
  tail -f "$log_file" &
  local tail_pid=$!
  if command -v setsid &>/dev/null; then
    setsid "$runner" < "$pf" >> "$log_file" 2>&1 &
  else
    "$runner" < "$pf" >> "$log_file" 2>&1 &
  fi
  local pgid=$!

  # Watchdog: SIGTERM the process group after timeout, then SIGKILL after 30s grace
  ( sleep "${timeout_sec}"
    if kill -0 "${pgid}" 2>/dev/null; then
      kill -- "-${pgid}" 2>/dev/null || true
      sleep 30
      kill -KILL -- "-${pgid}" 2>/dev/null || true
    fi
  ) &
  local watchdog_pid=$!

  wait "${pgid}"
  local ec=$?
  kill "${watchdog_pid}" 2>/dev/null; kill "${tail_pid}" 2>/dev/null
  wait "${watchdog_pid}" 2>/dev/null; wait "${tail_pid}" 2>/dev/null
  rm -f "${pf}" "${runner}"

  # Normalize SIGTERM(143) / SIGKILL(137) → 124 (same as timeout(1))
  [[ $ec -eq 143 || $ec -eq 137 ]] && ec=124
  return $ec
}

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
      echo ""
      echo "🔄 Retry $attempt/$max_attempts for task $idx..."
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
