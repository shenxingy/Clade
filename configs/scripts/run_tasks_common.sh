#!/usr/bin/env bash
# run_tasks_common.sh — task-file parsing, timeout diagnostics, and the claude
# worker runner shared by run-tasks.sh (serial) and run-tasks-parallel.sh.
#
# SOURCED, never executed. The two runners were copies of each other: 176
# shared unique non-trivial lines, 141 of them in 9 byte-identical functions.
# The duplication had already cost real behaviour:
#   - the orphaned-`sleep` fix in run_claude_task (a stray watchdog sleep keeps
#     the caller's pipe open; loop-runner.sh's tee blocked on it for up to
#     WORKER_TIMEOUT seconds) lived in the serial copy only, hand-ported as a
#     NOTE the parallel copy never grew;
#   - the `setsid --wait` guard the comment below calls CRITICAL existed twice;
#   - the legacy branch of run-tasks-parallel.sh's get_task_prompt ran
#     `grep -cvE ... | sed -n "${n}p"` — `grep -c` prints a COUNT, so a
#     legacy-format task file fed the worker the literal string "2" as its
#     prompt while the serial copy returned the task text.
#
# Flat placement beside its callers follows the loop_args.sh / loop_bounds.sh /
# loop_score.sh precedent and keeps this file inside the NON-recursive
# `configs/scripts/*.sh` glob CI lints; a lib/ subdirectory would escape it.
#
# Required in the caller BEFORE the source line (these are read at call time,
# but keeping the source line after the globals block documents the contract):
#   TASK_FILE       — task file path (is_new_format, get_task_field, prompts)
#   CLAUDE_FLAGS    — flags handed to `claude -p` (run_claude_task)
#   DEFAULT_RETRIES — fallback for get_task_retries
# Optional:
#   STALL_THRESHOLD — consecutive stale heartbeat checks before kill (default 10)
#
# Deliberately NOT here — moving either would silently change behaviour:
#   get_task_timeout   serial delegates to $DEFAULT_TIMEOUT; parallel uses
#                      model-aware defaults (haiku=900 / opus=3600 / else=1800)
#   get_task_prompt    the two runners disagree about the LEGACY format on
#                      purpose; each defines its own dispatcher over the shared
#                      new-format body get_task_prompt_new. get_task_name below
#                      calls whichever get_task_prompt its caller defines.

# ─── Cross-platform timeout (macOS: gtimeout from coreutils) ─────────

_timeout() {
  if command -v gtimeout &>/dev/null; then
    gtimeout "$@"
  elif command -v timeout &>/dev/null; then
    timeout "$@"
  else
    # No timeout available, run without
    shift  # remove the timeout duration arg
    "$@"
  fi
}

# ─── Format detection ───────────────────────────────────────────────

is_new_format() {
  grep -q '^===TASK===$' "$TASK_FILE"
}

# ─── New format helpers (===TASK=== delimited) ──────────────────────

# Get a metadata field for Nth task (1-indexed). Usage: get_task_field N "model" "default"
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

get_task_model() {
  get_task_field "$1" "model" "sonnet"
}

get_task_retries() {
  get_task_field "$1" "retries" "$DEFAULT_RETRIES"
}

# Prompt body for the Nth task (1-indexed), NEW FORMAT ONLY. Callers wrap this
# with their own legacy fallback — see the header note on get_task_prompt.
get_task_prompt_new() {
  local n="$1"
  awk -v n="$n" '
    /^===TASK===$/ { count++; in_meta=1; in_body=0; next }
    count == n && in_meta && /^---$/ { in_meta=0; in_body=1; next }
    count == n && in_body && /^===TASK===$/ { exit }
    count == n && in_body { print }
    count > n { exit }
  ' "$TASK_FILE" | awk 'NF{p=1} p'
}

# First non-empty line of the task's prompt. Resolves get_task_prompt in the
# CALLER at call time, so each runner keeps its own format dispatch.
get_task_name() {
  local n="$1"
  get_task_prompt "$n" | awk 'NF { print; exit }'
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
    # Pure judge (stdout captured for the diagnostic box) — drop user settings,
    # or a prompt-type Stop hook prints {"ok":true} instead of the diagnosis
    # (see PURE_JUDGE_FLAGS in loop-runner.sh / start.sh).
    analysis=$(_timeout 90s claude -p --model haiku --dangerously-skip-permissions --setting-sources "" < "$af" 2>/dev/null \
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

# ─── Worker runner ───────────────────────────────────────────────────

# Run a claude task in a new process group session with a watchdog timer.
# Usage: echo "$prompt" | run_claude_task <model> <timeout_sec> <log_file> [workdir]
# Returns: 0=success, 124=timeout, other=claude error
run_claude_task() {
  local model="$1" timeout_sec="$2" log_file="$3" workdir="${4:-$(pwd)}"

  # Write prompt and runner script to temp files (avoids CLAUDE_FLAGS quoting issues)
  local pf runner
  pf=$(mktemp /tmp/claude-task-XXXXXX)
  runner=$(mktemp /tmp/claude-runner-XXXXXX)
  cat > "$pf"   # read prompt from stdin
  # Use stream-json for real-time output (--verbose alone buffers until exit, lost on kill).
  # Workers keep user hooks deliberately (commit discipline); pure judges drop them — see analyze_timeout.
  # GIT_EDITOR=cat (mic92): rebase/amend never hangs an unattended worker on an editor.
  printf '#!/usr/bin/env bash\ncd "%s" || exit 1\nexport GIT_EDITOR=cat GIT_SEQUENCE_EDITOR=cat GIT_PAGER=cat\nexec claude -p --model "%s" %s --verbose --output-format stream-json\n' \
    "$workdir" "$model" "$CLAUDE_FLAGS" > "$runner"
  chmod +x "$runner"

  # CRITICAL: setsid without --wait forks and the parent exits immediately,
  # causing `wait $pid` to return instantly with exit 0. This makes workers
  # appear to succeed without actually running. Use --wait to block until
  # the child process exits. setsid --wait also forwards signals to the child.
  touch "$log_file"
  if command -v setsid &>/dev/null && setsid --help 2>&1 | grep -q "\-\-wait"; then
    setsid --wait "$runner" < "$pf" >> "$log_file" 2>&1 &
  else
    "$runner" < "$pf" >> "$log_file" 2>&1 &
  fi
  local pgid=$!

  # Stall-detecting heartbeat: track log growth, kill worker if stalled
  # NOTE: the trap must kill the backgrounded sleep too — an orphaned
  # `sleep $timeout` inherits our stdout and keeps the caller's pipe open long
  # after this script exits (loop-runner.sh's tee blocked on it for up to
  # WORKER_TIMEOUT seconds).
  local stall_threshold="${STALL_THRESHOLD:-10}"  # consecutive stale checks (10 × 30s = 5min)
  ( _hb_sleep_pid=0
    trap 'kill $_hb_sleep_pid 2>/dev/null; exit 0' TERM INT
    prev_bytes=0; stale_count=0
    while kill -0 "${pgid}" 2>/dev/null; do
      sleep 30 & _hb_sleep_pid=$!; wait $_hb_sleep_pid 2>/dev/null || exit 0
      if kill -0 "${pgid}" 2>/dev/null; then
        # Worktree churn, when the workdir is one (parallel mode): cheap signal
        # that a worker whose log has gone quiet is still editing files.
        local wt_changes=""
        if [[ -d "$workdir/.git" ]] || [[ -f "$workdir/.git" ]]; then
          wt_changes=" changes=$(cd "$workdir" && git diff --stat 2>/dev/null | wc -l)"
        fi
        local log_bytes growth
        log_bytes=$(stat -c%s "$log_file" 2>/dev/null || stat -f%z "$log_file" 2>/dev/null || echo 0)
        growth=$((log_bytes - prev_bytes))
        if [[ $growth -le 100 ]]; then
          stale_count=$((stale_count + 1))
        else
          stale_count=0
        fi
        echo "[heartbeat $(date +%H:%M:%S)] worker alive (PID ${pgid}) log=${log_bytes}b growth=${growth}b stale=${stale_count}/${stall_threshold}${wt_changes}" >> "$log_file"
        prev_bytes=$log_bytes
        if [[ $stale_count -ge $stall_threshold ]]; then
          echo "[heartbeat $(date +%H:%M:%S)] STALL DETECTED — no log growth for $((stale_count * 30))s, killing worker" >> "$log_file"
          # With setsid --wait, SIGTERM is forwarded to the child's process group
          kill "${pgid}" 2>/dev/null || true
          break
        fi
      fi
    done
  ) &
  local heartbeat_pid=$!

  # Watchdog: SIGTERM after timeout (setsid --wait forwards to child group), then SIGKILL after 30s grace
  ( _wd_sleep_pid=0
    trap 'kill $_wd_sleep_pid 2>/dev/null; exit 0' TERM INT
    sleep "${timeout_sec}" & _wd_sleep_pid=$!; wait $_wd_sleep_pid 2>/dev/null || exit 0
    if kill -0 "${pgid}" 2>/dev/null; then
      kill "${pgid}" 2>/dev/null || true
      sleep 30 & _wd_sleep_pid=$!; wait $_wd_sleep_pid 2>/dev/null || exit 0
      kill -KILL "${pgid}" 2>/dev/null || true
    fi
  ) &
  local watchdog_pid=$!

  wait "${pgid}"
  local ec=$?
  kill "${heartbeat_pid}" "${watchdog_pid}" 2>/dev/null
  wait "${heartbeat_pid}" "${watchdog_pid}" 2>/dev/null
  rm -f "${pf}" "${runner}"

  # Normalize SIGTERM(143) / SIGKILL(137) → 124 (same as timeout(1))
  [[ $ec -eq 143 || $ec -eq 137 ]] && ec=124
  return $ec
}
