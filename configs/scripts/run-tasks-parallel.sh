#!/usr/bin/env bash
# run-tasks-parallel.sh — Execute tasks in parallel using git worktrees
#
# Usage:
#   bash scripts/run-tasks-parallel.sh tasks.txt              # Run tasks in parallel
#   bash scripts/run-tasks-parallel.sh tasks.txt --dry-run     # Preview grouping and execution plan
#   bash scripts/run-tasks-parallel.sh tasks.txt --safe        # Run WITHOUT --dangerously-skip-permissions
#
# Environment:
#   MAX_WORKERS=3     — Max concurrent tasks (default: 3)
#   WORKTREE_BASE=    — Base dir for worktrees (default: ../.worktrees-<repo>)
#
# Features:
#   - Parallel execution via git worktrees (each task gets its own working copy)
#   - Simple conflict detection: tasks touching the same files run serially
#   - Progress tracking with flock for atomic writes
#   - Auto-merge results back to main branch
#   - Falls back to serial on merge conflicts

set -uo pipefail

TASK_FILE="${1:?Usage: run-tasks-parallel.sh <task-file> [--dry-run|--safe]}"
MODE="${2:-}"
MAX_WORKERS="${MAX_WORKERS:-3}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_DIR="logs/claude-tasks"
PROGRESS_FILE="$LOG_DIR/${TIMESTAMP}-progress"

DEFAULT_TIMEOUT=600
DEFAULT_RETRIES=2

CLAUDE_FLAGS="--dangerously-skip-permissions"
if [[ "$MODE" == "--safe" ]]; then
  CLAUDE_FLAGS=""
fi

if [[ ! -f "$TASK_FILE" ]]; then
  echo "Error: Task file '$TASK_FILE' not found"
  exit 1
fi

if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  echo "Error: Must be in a git repo for parallel execution (needs worktrees)"
  exit 1
fi

# Allow launching claude -p from within a Claude Code session
unset CLAUDECODE 2>/dev/null || true

mkdir -p "$LOG_DIR"

MAIN_BRANCH=$(git rev-parse --abbrev-ref HEAD)
REPO_ROOT=$(git rev-parse --show-toplevel)
REPO_NAME=$(basename "$REPO_ROOT")
WORKTREE_BASE="${WORKTREE_BASE:-$(dirname "$REPO_ROOT")/.worktrees-${REPO_NAME}}"

# ─── Task parsing (reuse format from run-tasks.sh) ──────────────────

is_new_format() {
  grep -q '^===TASK===$' "$TASK_FILE"
}

count_tasks() {
  if is_new_format; then
    grep -c '^===TASK===$' "$TASK_FILE"
  else
    grep -cvE '^[[:space:]]*(#|$)' "$TASK_FILE"
  fi
}

get_task_field() {
  local n="$1" field="$2" default="${3:-}"
  local result
  result=$(awk -v n="$n" -v field="$field" '
    /^===TASK===$/ { count++ }
    count == n && $0 ~ "^"field":" {
      gsub("^"field":[[:space:]]*", ""); print; found=1; exit
    }
    count == n && /^---$/ { if (!found) exit }
    END { if (!found) print "" }
  ' "$TASK_FILE")
  echo "${result:-$default}"
}

get_task_prompt() {
  local n="$1"
  if is_new_format; then
    awk -v n="$n" '
      /^===TASK===$/ { count++; in_meta=1; in_body=0; next }
      count == n && in_meta && /^---$/ { in_meta=0; in_body=1; next }
      count == n && in_body && /^===TASK===$/ { exit }
      count == n && in_body { print }
      count > n { exit }
    ' "$TASK_FILE" | sed -e '1{/^$/d}' -e '${/^$/d}'
  else
    grep -cvE '^[[:space:]]*(#|$)' "$TASK_FILE" | sed -n "${n}p"
  fi
}

get_task_name() {
  local n="$1"
  get_task_prompt "$n" | awk 'NF { print; exit }'
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

# ─── Conflict detection ──────────────────────────────────────────────
# Simple heuristic: extract file paths mentioned in task prompts

extract_file_refs() {
  local prompt="$1"
  # Match common file path patterns
  echo "$prompt" | grep -oP '[a-zA-Z0-9_./-]+\.(ts|tsx|js|jsx|py|ipynb|md|json|yaml|yml|sh|css|scss|rs|go|swift|kt|java|c|cpp|h|hpp|tex|bib|rb|lua|zig|dart)' | sort -u
}

detect_conflicts() {
  local total
  total=$(count_tasks)
  declare -gA TASK_FILES_MAP

  for i in $(seq 1 "$total"); do
    local prompt
    prompt=$(get_task_prompt "$i")
    TASK_FILES_MAP[$i]=$(extract_file_refs "$prompt")
  done

  # Build conflict groups: tasks sharing files go in the same serial group
  declare -ga GROUPS=()
  declare -gA ASSIGNED
  local group_idx=0

  for i in $(seq 1 "$total"); do
    if [[ -n "${ASSIGNED[$i]:-}" ]]; then continue; fi

    local group="$i"
    ASSIGNED[$i]=$group_idx

    for j in $(seq $((i + 1)) "$total"); do
      if [[ -n "${ASSIGNED[$j]:-}" ]]; then continue; fi

      local files_i="${TASK_FILES_MAP[$i]}"
      local files_j="${TASK_FILES_MAP[$j]}"
      local conflict=false

      if [[ -n "$files_i" && -n "$files_j" ]]; then
        while IFS= read -r f; do
          if echo "$files_j" | grep -qF "$f"; then
            conflict=true
            break
          fi
        done <<< "$files_i"
      fi

      if $conflict; then
        group="$group $j"
        ASSIGNED[$j]=$group_idx
      fi
    done

    GROUPS+=("$group")
    group_idx=$((group_idx + 1))
  done
}

# ─── Timeout + cleanup helpers ───────────────────────────────────────

record_task_start_state() {
  _CONTAINERS_BEFORE=$(docker ps -q 2>/dev/null | sort || true)
  _GPU_PIDS_BEFORE=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | sort || true)
}

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

run_claude_task() {
  local model="$1" timeout_sec="$2" log_file="$3" workdir="${4:-$(pwd)}"

  local pf runner
  pf=$(mktemp /tmp/claude-task-XXXXXX)
  runner=$(mktemp /tmp/claude-runner-XXXXXX.sh)
  cat > "$pf"
  printf '#!/usr/bin/env bash\ncd "%s" || exit 1\nexec claude -p --model "%s" %s --verbose\n' \
    "$workdir" "$model" "$CLAUDE_FLAGS" > "$runner"
  chmod +x "$runner"

  touch "$log_file"
  tail -f "$log_file" &
  local tail_pid=$!
  if command -v setsid &>/dev/null; then
    setsid "$runner" < "$pf" >> "$log_file" 2>&1 &
  else
    "$runner" < "$pf" >> "$log_file" 2>&1 &
  fi
  local pgid=$!

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

  [[ $ec -eq 143 || $ec -eq 137 ]] && ec=124
  return $ec
}

# ─── Progress tracking (atomic with flock) ────────────────────────────

update_progress() {
  local status="$1" current="${2:-0}" total="${3:-0}" success="${4:-0}" failed="${5:-0}"
  (
    flock -x 200
    cat > "$PROGRESS_FILE" <<EOF
TIMESTAMP=$TIMESTAMP
CURRENT=$current
TOTAL=$total
SUCCESS=$success
FAILED=$failed
SKIPPED=0
STATUS=$status
MODE=parallel
MAX_WORKERS=$MAX_WORKERS
TASK_FILE=$TASK_FILE
LOG_DIR=$LOG_DIR
EOF
  ) 200>"$PROGRESS_FILE.lock"
}

# ─── Worker: execute one task in a worktree ───────────────────────────

run_task_in_worktree() {
  local task_idx="$1"
  local task_name task_prompt model task_timeout max_retries
  task_name=$(get_task_name "$task_idx")
  task_prompt=$(get_task_prompt "$task_idx")
  model=$(get_task_model "$task_idx")
  task_timeout=$(get_task_timeout "$task_idx")
  max_retries=$(get_task_retries "$task_idx")
  max_attempts=$((max_retries + 1))

  local wt_dir="$WORKTREE_BASE/task-${task_idx}"
  local branch_name="batch/task-${task_idx}-${TIMESTAMP}"
  local log_file="$REPO_ROOT/$LOG_DIR/${TIMESTAMP}-task-${task_idx}.log"

  echo "[$task_idx] Starting: $task_name [$model]"

  # Create worktree
  git branch "$branch_name" "$MAIN_BRANCH" 2>/dev/null
  git worktree add "$wt_dir" "$branch_name" 2>/dev/null
  if [[ $? -ne 0 ]]; then
    echo "[$task_idx] FAILED: Could not create worktree"
    return 1
  fi

  local succeeded=false
  for attempt in $(seq 1 "$max_attempts"); do
    if [[ $attempt -gt 1 ]]; then
      echo "[$task_idx] Retry $attempt/$max_attempts..."
      # Reset worktree on retry
      (cd "$wt_dir" && git checkout . && git clean -fd) 2>/dev/null
    fi

    record_task_start_state

    local exit_code=0
    echo "$task_prompt" | run_claude_task "$model" "$task_timeout" "$log_file" "$wt_dir" || exit_code=$?

    if [[ $exit_code -eq 0 ]]; then
      succeeded=true
      # Commit changes in worktree
      (cd "$wt_dir" && git add -A && git diff --cached --quiet) 2>/dev/null
      if [[ $? -ne 0 ]]; then
        (cd "$wt_dir" && git commit -m "batch: $task_name" --no-verify) 2>/dev/null
      fi
      break
    elif [[ $exit_code -eq 124 ]]; then
      echo "[$task_idx] Timed out (attempt $attempt/$max_attempts)"
      cleanup_escaped_processes "$task_name"
      analyze_timeout "$task_name" "$task_timeout" "$log_file"
    else
      echo "[$task_idx] Failed with exit $exit_code (attempt $attempt/$max_attempts)"
    fi
  done

  if $succeeded; then
    echo "[$task_idx] SUCCESS: $task_name"
    return 0
  else
    echo "[$task_idx] PERMANENTLY FAILED: $task_name"
    return 1
  fi
}

merge_worktree() {
  local task_idx="$1"
  local branch_name="batch/task-${task_idx}-${TIMESTAMP}"
  local wt_dir="$WORKTREE_BASE/task-${task_idx}"

  # Check if branch has commits ahead of main
  local ahead
  ahead=$(git rev-list --count "$MAIN_BRANCH".."$branch_name" 2>/dev/null)
  if [[ "${ahead:-0}" -eq 0 ]]; then
    cleanup_worktree "$task_idx"
    return 0
  fi

  echo "Merging task $task_idx..."
  if git merge --no-edit "$branch_name" 2>/dev/null; then
    echo "Merged task $task_idx successfully"
    cleanup_worktree "$task_idx"
    return 0
  else
    echo "MERGE CONFLICT for task $task_idx — aborting merge, running serially"
    git merge --abort 2>/dev/null
    cleanup_worktree "$task_idx"
    return 1
  fi
}

cleanup_worktree() {
  local task_idx="$1"
  local wt_dir="$WORKTREE_BASE/task-${task_idx}"
  local branch_name="batch/task-${task_idx}-${TIMESTAMP}"

  git worktree remove "$wt_dir" --force 2>/dev/null
  git branch -D "$branch_name" 2>/dev/null
}

# ─── Main ──────────────────────────────────────────────────────────────

TOTAL=$(count_tasks)
echo "Parallel batch runner — $TOTAL tasks, max $MAX_WORKERS workers"
echo "Worktree base: $WORKTREE_BASE"
echo "Progress file: $PROGRESS_FILE"
echo ""

# Detect conflicts and build execution groups
detect_conflicts
echo "Execution groups (tasks within a group run serially, groups can overlap):"
for g in "${!GROUPS[@]}"; do
  echo "  Group $((g + 1)): tasks [${GROUPS[$g]}]"
done
echo ""

if [[ "$MODE" == "--dry-run" ]]; then
  echo "[DRY RUN] Would execute $TOTAL tasks in ${#GROUPS[@]} groups with max $MAX_WORKERS workers"
  for i in $(seq 1 "$TOTAL"); do
    echo "  [$i] [$(get_task_model "$i")] $(get_task_name "$i")"
  done
  exit 0
fi

update_progress "starting" 0 "$TOTAL" 0 0
mkdir -p "$WORKTREE_BASE"

SUCCESS=0
FAILED=0
COMPLETED=0
declare -A TASK_RESULTS

# Process groups: tasks within a group run serially, but we run multiple groups in parallel
run_group() {
  local group_tasks="$1"
  for task_idx in $group_tasks; do
    if run_task_in_worktree "$task_idx"; then
      TASK_RESULTS[$task_idx]="success"
    else
      TASK_RESULTS[$task_idx]="failed"
    fi
  done
}

# Run groups with worker limit using background jobs
ACTIVE_JOBS=0
for group_tasks in "${GROUPS[@]}"; do
  while [[ $ACTIVE_JOBS -ge $MAX_WORKERS ]]; do
    wait -n 2>/dev/null
    ACTIVE_JOBS=$((ACTIVE_JOBS - 1))
  done

  run_group "$group_tasks" &
  ACTIVE_JOBS=$((ACTIVE_JOBS + 1))
done

# Wait for all groups to finish
wait

# Merge results back to main branch
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "All workers done. Merging results..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

MERGE_FAILURES=()
for i in $(seq 1 "$TOTAL"); do
  result="${TASK_RESULTS[$i]:-unknown}"
  if [[ "$result" == "success" ]]; then
    if merge_worktree "$i"; then
      SUCCESS=$((SUCCESS + 1))
    else
      MERGE_FAILURES+=("$i")
    fi
  elif [[ "$result" == "failed" ]]; then
    FAILED=$((FAILED + 1))
    cleanup_worktree "$i"
  else
    cleanup_worktree "$i"
  fi
  COMPLETED=$((COMPLETED + 1))
  update_progress "merging" "$COMPLETED" "$TOTAL" "$SUCCESS" "$FAILED"
done

# Handle merge conflicts: re-run serially
if [[ ${#MERGE_FAILURES[@]} -gt 0 ]]; then
  echo ""
  echo "Re-running ${#MERGE_FAILURES[@]} conflicting tasks serially..."
  for task_idx in "${MERGE_FAILURES[@]}"; do
    task_prompt=$(get_task_prompt "$task_idx")
    model=$(get_task_model "$task_idx")
    task_timeout=$(get_task_timeout "$task_idx")
    task_name=$(get_task_name "$task_idx")
    log_file="$LOG_DIR/${TIMESTAMP}-task-${task_idx}-serial.log"

    echo "Running task $task_idx serially: $task_name"
    record_task_start_state
    exit_code=0
    echo "$task_prompt" | run_claude_task "$model" "$task_timeout" "$log_file" || exit_code=$?

    if [[ $exit_code -eq 0 ]]; then
      SUCCESS=$((SUCCESS + 1))
    else
      if [[ $exit_code -eq 124 ]]; then
        cleanup_escaped_processes "$task_name"
        analyze_timeout "$task_name" "$task_timeout" "$log_file"
      fi
      FAILED=$((FAILED + 1))
    fi
  done
fi

# Cleanup
rmdir "$WORKTREE_BASE" 2>/dev/null || true

update_progress "done" "$TOTAL" "$TOTAL" "$SUCCESS" "$FAILED"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Done. Total: $TOTAL | Success: $SUCCESS | Failed: $FAILED"
echo "Logs: $LOG_DIR/"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
