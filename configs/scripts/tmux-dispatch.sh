#!/usr/bin/env bash
set -euo pipefail

# Cross-platform sed -i (macOS needs '' after -i)
_sed_i() {
  if [[ "$(uname)" == "Darwin" ]]; then
    sed -i '' "$@"
  else
    sed -i "$@"
  fi
}

# ─── Usage ───────────────────────────────────────────────────────────────────
usage() {
    cat <<'EOF'
Usage: tmux-dispatch.sh <tasks.txt> [--workers N]

Run claude tasks in parallel tmux panes.

Arguments:
  tasks.txt      Task file with ===TASK=== delimited blocks
  --workers N    Number of parallel workers (default: 4)
  --help         Show this help

Task file format:
  ===TASK===
  id: task-id        # optional metadata fields
  ---
  Task prompt text here...

  ===TASK===
  ---
  Another task prompt...

Output:
  X success / Y failed / Z total

Notes:
  - Falls back to sequential execution if tmux is not installed
  - Creates tmux session 'claude-fleet' (kills existing if present)
  - Each pane loops over tasks via flock-protected atomic counter
EOF
    exit 0
}

# ─── Arg parsing ─────────────────────────────────────────────────────────────
if [[ $# -eq 0 || "${1:-}" == "--help" ]]; then
    usage
fi

TASK_FILE="$1"
N_WORKERS=4
shift

while [[ $# -gt 0 ]]; do
    case "$1" in
        --workers)
            N_WORKERS="${2:?--workers requires a value}"
            shift 2
            ;;
        --help) usage ;;
        *)
            echo "Error: unknown argument: $1" >&2
            usage
            ;;
    esac
done

if [[ ! -f "$TASK_FILE" ]]; then
    echo "Error: task file '$TASK_FILE' not found" >&2
    exit 1
fi

# ─── Task parsing ─────────────────────────────────────────────────────────────
count_tasks() {
    local n
    n=$(grep -c '^===TASK===$' "$TASK_FILE" 2>/dev/null) || n=0
    echo "$n"
}

# Extract the prompt body (text after the --- line) for task N (1-indexed)
get_task_prompt() {
    local n="$1"
    awk -v n="$n" '
        /^===TASK===$/ { count++; in_meta=1; in_body=0; next }
        count == n && in_meta && /^---$/ { in_meta=0; in_body=1; next }
        count == n && in_body && /^===TASK===$/ { exit }
        count == n && in_body { print }
        count > n { exit }
    ' "$TASK_FILE" | awk 'NF{p=1} p'
}

TOTAL=$(count_tasks)
if [[ "$TOTAL" -eq 0 ]]; then
    echo "Error: no ===TASK=== blocks found in '$TASK_FILE'" >&2
    exit 1
fi

echo "tmux-dispatch: $TOTAL tasks | $N_WORKERS workers"

# ─── Temp workspace ──────────────────────────────────────────────────────────
WORK_DIR=$(mktemp -d /tmp/claude-fleet-XXXXXX)
COUNTER_FILE="$WORK_DIR/counter"
RESULTS_FILE="$WORK_DIR/results"

cleanup() {
    tmux kill-session -t claude-fleet 2>/dev/null || true
    rm -rf "$WORK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

# Counter starts at 1 (tasks are 1-indexed)
echo 1 > "$COUNTER_FILE"

# Pre-extract all task prompts to individual files
for i in $(seq 1 "$TOTAL"); do
    get_task_prompt "$i" > "$WORK_DIR/task-${i}.txt"
done

# ─── Worker script ────────────────────────────────────────────────────────────
# Written to WORK_DIR so tmux panes can exec it independently
WORKER_SCRIPT="$WORK_DIR/worker.sh"
cat > "$WORKER_SCRIPT" << 'WORKER_TMPL'
#!/usr/bin/env bash
set -uo pipefail

WORK_DIR="@WORK_DIR@"
TOTAL=@TOTAL@
COUNTER_FILE="$WORK_DIR/counter"
RESULTS_FILE="$WORK_DIR/results"

# Allow launching claude -p from within a Claude Code session
unset CLAUDECODE 2>/dev/null || true

while true; do
    # Atomically claim the next task index via flock on a lock file.
    # COUNTER_FILE holds the next available index; .lock is the lock target.
    task_idx=$(
        {
            if command -v flock &>/dev/null; then
                flock -x 9
            else
                # macOS fallback: mkdir-based atomic lock
                while ! mkdir "${COUNTER_FILE}.lockdir" 2>/dev/null; do sleep 0.05; done
                trap 'rmdir "${COUNTER_FILE}.lockdir" 2>/dev/null' EXIT
            fi
            current=$(cat "$COUNTER_FILE")
            if [[ "$current" -gt "$TOTAL" ]]; then
                echo ""
            else
                echo $((current + 1)) > "$COUNTER_FILE"
                echo "$current"
            fi
        } 9>"${COUNTER_FILE}.lock"
    )

    if [[ -z "$task_idx" ]]; then
        echo "[$$] no more tasks, exiting"
        break
    fi

    echo "[$$] starting task $task_idx/$TOTAL"
    task_file="$WORK_DIR/task-${task_idx}.txt"
    log_file="$WORK_DIR/task-${task_idx}.log"

    exit_code=0
    claude --dangerously-skip-permissions -p "$(cat "$task_file")" \
        >> "$log_file" 2>&1 || exit_code=$?

    if [[ $exit_code -eq 0 ]]; then
        echo "[$$] task $task_idx SUCCESS"
        echo "success" >> "$RESULTS_FILE"
    else
        echo "[$$] task $task_idx FAILED (exit $exit_code)"
        echo "failed" >> "$RESULTS_FILE"
    fi
done
WORKER_TMPL

_sed_i "s|@WORK_DIR@|${WORK_DIR}|g" "$WORKER_SCRIPT"
_sed_i "s|@TOTAL@|${TOTAL}|g"       "$WORKER_SCRIPT"
chmod +x "$WORKER_SCRIPT"

# ─── Sequential fallback ──────────────────────────────────────────────────────
run_sequential() {
    echo "tmux not available — running tasks sequentially"
    unset CLAUDECODE 2>/dev/null || true

    local i exit_code
    for i in $(seq 1 "$TOTAL"); do
        echo "Task $i/$TOTAL..."
        exit_code=0
        claude --dangerously-skip-permissions -p "$(cat "$WORK_DIR/task-${i}.txt")" \
            >> "$WORK_DIR/task-${i}.log" 2>&1 || exit_code=$?

        if [[ $exit_code -eq 0 ]]; then
            echo "  SUCCESS"
            echo "success" >> "$RESULTS_FILE"
        else
            echo "  FAILED (exit $exit_code)"
            echo "failed" >> "$RESULTS_FILE"
        fi
    done
}

# ─── Tmux dispatch ────────────────────────────────────────────────────────────
run_tmux() {
    local session="claude-fleet"

    # Kill any existing session with the same name
    tmux kill-session -t "$session" 2>/dev/null || true

    # Create a new detached session (first pane is created automatically)
    tmux new-session -d -s "$session" -x 220 -y 50

    # Add N-1 more panes by splitting; apply tiled layout for even distribution
    local i
    for i in $(seq 2 "$N_WORKERS"); do
        tmux split-window -t "$session" -v 2>/dev/null || true
        tmux select-layout -t "$session" tiled 2>/dev/null || true
    done
    tmux select-layout -t "$session" tiled 2>/dev/null || true

    local pane_count
    pane_count=$(tmux list-panes -t "$session" | awk 'END{print NR}')
    echo "Launched $pane_count panes in session '$session'"
    echo "Attach: tmux attach -t $session"

    # Send the worker loop command to every pane
    for i in $(seq 0 $((pane_count - 1))); do
        tmux send-keys -t "${session}:0.${i}" "bash '$WORKER_SCRIPT'" Enter
    done

    # Poll the results file until every task has recorded an outcome
    local done_count elapsed=0 poll_interval=2 timeout_sec=3600

    while true; do
        done_count=0
        if [[ -f "$RESULTS_FILE" ]]; then
            done_count=$(awk 'END{print NR}' "$RESULTS_FILE" 2>/dev/null || echo 0)
        fi

        if [[ "$done_count" -ge "$TOTAL" ]]; then
            break
        fi

        if [[ $elapsed -ge $timeout_sec ]]; then
            echo "Warning: timeout after ${timeout_sec}s ($done_count/$TOTAL tasks done)" >&2
            break
        fi

        printf "\r  Progress: %d/%d tasks done" "$done_count" "$TOTAL"
        sleep "$poll_interval"
        elapsed=$((elapsed + poll_interval))
    done
    printf "\n"

    tmux kill-session -t "$session" 2>/dev/null || true
}

# ─── Main ─────────────────────────────────────────────────────────────────────
if command -v tmux &>/dev/null; then
    run_tmux
else
    run_sequential
fi

# ─── Summary ─────────────────────────────────────────────────────────────────
SUCCESS=0
FAILED=0
if [[ -f "$RESULTS_FILE" ]]; then
    SUCCESS=$(grep -c '^success$' "$RESULTS_FILE" 2>/dev/null) || SUCCESS=0
    FAILED=$(grep -c  '^failed$'  "$RESULTS_FILE" 2>/dev/null) || FAILED=0
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "$SUCCESS success / $FAILED failed / $TOTAL total"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
