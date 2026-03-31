#!/usr/bin/env bash
# loop-runner.sh — Blueprint Loop: deterministic + LLM hybrid state machine
# Architecture inspired by Stripe Minions blueprints
#
# Each iteration flows through deterministic (DET) and LLM nodes:
#   [DET] pre_flight        — goal file exists, syntax check
#   [DET] hydrate_context   — git log + status → .claude/loop-context.md
#   [LLM] supervisor        — plans tasks OR returns CONVERGED
#   [DET] score_and_write   — skips low-score tasks, writes task file
#   [LLM] workers (par)     — executes planned tasks in parallel
#   [DET] syntax_check      — validates all changed .py/.sh/.ts files
#   [LLM] fix_syntax        — one attempt to fix failures; else revert
#   [DET] test_sample       — runs CLAUDE.md verify_cmd if present
#   [DET] commit_changes    — commits all worker output
#   [DET] convergence_check — CONVERGED? max_iter? 3x no-commits?
#
# Usage:
#   loop-runner.sh GOAL_FILE [options]
#   loop-runner.sh --status
#   loop-runner.sh --stop
#
# Options:
#   --model MODEL         supervisor model (default: claude-sonnet-4-6)
#   --worker-model MODEL  worker model (default: same as supervisor)
#   --max-iter N          max iterations (default: 10)
#   --max-workers N       max parallel workers (default: 4)
#   --context FILE        pre-generated context file (passed to supervisor)
#   --state FILE          state file (default: .claude/loop-state.json)
#   --log-dir DIR         log directory (default: logs/loop)

set -euo pipefail

# Allow nested claude calls from within a Claude Code session
unset CLAUDECODE 2>/dev/null || true

# ─── CROSS-PLATFORM HELPERS ─────────────────────────────────────────
# macOS lacks GNU timeout; use gtimeout (brew install coreutils) or fallback
_timeout() {
  if command -v gtimeout &>/dev/null; then
    gtimeout "$@"
  elif command -v timeout &>/dev/null; then
    timeout "$@"
  else
    shift  # remove the timeout duration arg
    "$@"
  fi
}
# ────────────────────────────────────────────────────────────────────

# ─── BLUEPRINT HARD LIMITS ──────────────────────────────────────
readonly MAX_CONSECUTIVE_NO_COMMITS=3   # consecutive empty iters → force stop
readonly SYNTAX_CHECK_TIMEOUT=30        # syntax check timeout (seconds)
readonly TEST_SAMPLE_TIMEOUT=120        # verify_cmd timeout (seconds)
readonly SUPERVISOR_TIMEOUT=120         # supervisor LLM call timeout (seconds)
readonly WORKER_TIMEOUT=600             # per-worker timeout (seconds)
readonly MAX_FIX_ATTEMPTS=1             # syntax fix: max 1 LLM call per iter
# ────────────────────────────────────────────────────────────────

# ─── DEFAULTS ───────────────────────────────────────────────────
GOAL_FILE=""
SUPERVISOR_MODEL="claude-sonnet-4-6"
WORKER_MODEL="claude-sonnet-4-6"
MAX_ITER=10
MAX_WORKERS=4
CONTEXT_FILE=""
STATE_FILE=".claude/loop-state.json"
LOG_DIR="logs/loop"
ITERATION=0
# ────────────────────────────────────────────────────────────────

# ─── LOGGING ────────────────────────────────────────────────────
log_info()    { echo "[$(date '+%H:%M:%S')] [INFO]  $*" | tee -a "$LOG_DIR/loop.log"; }
log_success() { echo "[$(date '+%H:%M:%S')] [OK]    $*" | tee -a "$LOG_DIR/loop.log"; }
log_warn()    { echo "[$(date '+%H:%M:%S')] [WARN]  $*" | tee -a "$LOG_DIR/loop.log"; }
log_error()   { echo "[$(date '+%H:%M:%S')] [ERROR] $*" | tee -a "$LOG_DIR/loop.log" >&2; }
# ────────────────────────────────────────────────────────────────

# ─── PARSE ARGS ─────────────────────────────────────────────────
parse_args() {
  # Handle --status and --stop before GOAL_FILE is required
  for arg in "$@"; do
    case "$arg" in
      --status) show_status; exit 0 ;;
      --stop)   write_stop_sentinel; exit 0 ;;
    esac
  done

  GOAL_FILE="${1:-}"
  [ $# -gt 0 ] && shift || true

  while [ $# -gt 0 ]; do
    case "$1" in
      --model)        SUPERVISOR_MODEL="$2"; shift 2 ;;
      --worker-model) WORKER_MODEL="$2"; shift 2 ;;
      --max-iter)     MAX_ITER="$2"; shift 2 ;;
      --max-workers)  MAX_WORKERS="$2"; shift 2 ;;
      --context)      CONTEXT_FILE="$2"; shift 2 ;;
      --state)        STATE_FILE="$2"; shift 2 ;;
      --log-dir)      LOG_DIR="$2"; shift 2 ;;
      --resume)       shift ;;  # no-op: Blueprint loop always resumes from state
      --budget)       shift 2 ;;  # accepted but not used in Blueprint mode
      --exit-gate)    shift 2 ;;  # accepted but not used in Blueprint mode
      *) log_warn "Unknown arg: $1"; shift ;;
    esac
  done
}
# ────────────────────────────────────────────────────────────────

# ─── STOP SENTINEL ──────────────────────────────────────────────
write_stop_sentinel() {
  mkdir -p "$(dirname "$STATE_FILE")"
  echo '{"stop":true}' > "$STATE_FILE"
  echo "[INFO] Stop sentinel written to $STATE_FILE"
  echo "[INFO] Loop will exit after current iteration completes."
}

check_stop_sentinel() {
  if [ -f "$STATE_FILE" ]; then
    if python3 -c "
import json, sys
try:
    d = json.load(open('$STATE_FILE'))
    sys.exit(0 if d.get('stop') else 1)
except:
    sys.exit(1)
" 2>/dev/null; then
      log_info "Stop sentinel detected — exiting gracefully"
      return 0
    fi
  fi
  return 1
}

show_status() {
  local progress_file
  progress_file=$(ls -t "$LOG_DIR"/last-progress 2>/dev/null | head -1 || true)
  if [ -n "$progress_file" ] && [ -f "$progress_file" ]; then
    cat "$progress_file"
  elif [ -f "$STATE_FILE" ]; then
    python3 -c "
import json, sys
try:
    d = json.load(open('$STATE_FILE'))
    print('Loop state:', json.dumps(d, indent=2))
except:
    print('State file unreadable: $STATE_FILE')
" 2>/dev/null || echo "State file unreadable."
  else
    echo "No loop status found. Is a loop running?"
  fi
}
# ────────────────────────────────────────────────────────────────

# ─── [DET] NODE: PRE-FLIGHT ─────────────────────────────────────
# Validates goal file exists, checks for blocker file. No LLM calls.
node_pre_flight() {
  log_info "[DET] pre_flight"

  # Validate goal file
  if [ ! -f "$GOAL_FILE" ]; then
    log_error "Goal file not found: $GOAL_FILE"
    return 1
  fi

  # Check for Tier 3 blocker written by a previous worker
  if [ -f ".claude/blockers.md" ]; then
    log_error "Blocker detected (.claude/blockers.md exists). Stopping loop."
    log_error "Resolve the blocker and delete .claude/blockers.md to continue."
    return 1
  fi

  log_success "Pre-flight OK"
}
# ────────────────────────────────────────────────────────────────

# ─── [DET] NODE: HYDRATE CONTEXT ────────────────────────────────
# Generates .claude/loop-context.md with git log + relevant files. No LLM calls.
node_hydrate_context() {
  log_info "[DET] hydrate_context → .claude/loop-context.md"
  mkdir -p .claude

  {
    echo "# Loop Context: $(date '+%Y-%m-%d %H:%M')"
    echo "## Goal File: $GOAL_FILE"
    echo ""
    echo "## Recent Git History"
    git log --oneline -20 2>/dev/null || echo "(no git history)"
    echo ""
    echo "## Changed Files (last 5 commits)"
    git diff --stat HEAD~5..HEAD 2>/dev/null || true
    echo ""
    echo "## Current Branch"
    git branch --show-current 2>/dev/null || echo "unknown"
    echo ""
    echo "## Uncommitted Changes"
    git status -sb 2>/dev/null || echo "none"

    # Include pre-generated context if provided
    if [ -n "$CONTEXT_FILE" ] && [ -f "$CONTEXT_FILE" ]; then
      echo ""
      echo "## Additional Context"
      cat "$CONTEXT_FILE"
    fi
  } > .claude/loop-context.md

  log_success "Context hydrated ($(wc -l < .claude/loop-context.md) lines)"
}
# ────────────────────────────────────────────────────────────────

# ─── [LLM] NODE: SUPERVISOR ─────────────────────────────────────
# Plans tasks for this iteration. Returns JSON array or CONVERGED signal.
node_supervisor() {
  local iteration="$1"
  log_info "[LLM] supervisor (iter $iteration)"

  local goal_content
  goal_content=$(cat "$GOAL_FILE")

  local context_content
  context_content=$(cat .claude/loop-context.md 2>/dev/null || echo "no context")

  local state_content
  state_content=$(cat "$STATE_FILE" 2>/dev/null || echo "none")

  local supervisor_prompt
  supervisor_prompt="You are the supervisor for iteration $iteration of an autonomous improvement loop.
Read the goal and context, then plan at most $MAX_WORKERS tasks for this iteration.

## GOAL FILE: $GOAL_FILE
$goal_content

## CONTEXT
$context_content

## ITERATION HISTORY
$state_content

## 3-Tier Issue Handling (for workers)

Each task description MUST include these rules:

**Tier 1 — Uncertainty (pick a default, keep going):**
When unsure about a minor choice, pick the reversible default and log to .claude/decisions.md:
  ## [timestamp] Decision: [what]
  Context: [why unsure] / Choice: [what and why]

**Tier 2 — Task failure (skip, log, continue):**
If task fails after reasonable attempts, log to .claude/skipped.md:
  ## [timestamp] Skipped: [task]
  Reason: [what failed] / Attempted: [what tried]
Commit any partial work, then stop. Do NOT loop retrying.

**Tier 3 — True blocker (stop everything):**
Only for: destructive ops, needs secrets you don't have, mutually exclusive directions.
Write to .claude/blockers.md, then stop immediately.

## Output format

Output EXACTLY ONE of these two formats:

FORMAT 1 — Tasks to execute (JSON array):
[
  {
    \"description\": \"One sentence task with exact file paths and what to do. Include: which file, which function, what to implement, how to verify, commit with committer script.\",
    \"model\": \"haiku|sonnet|opus\",
    \"files\": [\"path/to/file.py\"]
  }
]

FORMAT 2 — Goal achieved (convergence signal):
{\"status\": \"CONVERGED\", \"reason\": \"All requirements met: ...\"}

## Rules
- CONVERGED only when ALL goal requirements are demonstrably met (verify via git history)
- Max $MAX_WORKERS tasks — pick the highest-value ones
- Tasks must be INDEPENDENT (no dependency between tasks in same iteration)
- Model: haiku=mechanical/trivial (<30 lines, rename, delete), sonnet=standard, opus=complex architecture
- Never repeat a task already in recent commits
- Workers commit via: committer \"type: msg\" file1 file2 (NEVER git add .)
- If .claude/blockers.md appears in recent diff, output CONVERGED immediately"

  local result
  if ! result=$(_timeout "$SUPERVISOR_TIMEOUT" claude --model "$SUPERVISOR_MODEL" -p "$supervisor_prompt" 2>&1); then
    log_error "Supervisor call failed or timed out"
    echo "[]"
    return
  fi

  # Extract JSON from result (supervisor may include preamble text)
  echo "$result" | python3 -c "
import sys, json, re
text = sys.stdin.read()
# Try to find JSON array or CONVERGED object
for pattern in [r'\[[\s\S]*\]', r'\{[\s\S]*\}']:
    matches = re.findall(pattern, text)
    for m in reversed(matches):
        try:
            parsed = json.loads(m)
            print(json.dumps(parsed))
            sys.exit(0)
        except:
            pass
print('[]')
" 2>/dev/null || echo "[]"
}
# ────────────────────────────────────────────────────────────────

# ─── [DET] NODE: SCORE AND WRITE TASKS ──────────────────────────
# Scores tasks, writes task file in ===TASK=== format. No LLM calls.
node_score_and_write() {
  local tasks_json="$1"
  local task_file="$LOG_DIR/iter-${ITERATION}-tasks.txt"

  log_info "[DET] score_and_write"

  # Check if tasks is empty array or invalid
  local task_count
  task_count=$(echo "$tasks_json" | python3 -c "
import json, sys
try:
    t = json.load(sys.stdin)
    print(len(t) if isinstance(t, list) else 0)
except:
    print(0)
" 2>/dev/null || echo "0")

  if [ "$task_count" -eq 0 ]; then
    log_warn "Supervisor returned no tasks"
    echo ""
    return
  fi

  # Write task file in ===TASK=== format with scoring
  local output
  output=$(echo "$tasks_json" | python3 -c "
import json, sys

tasks = json.load(sys.stdin)
output_tasks = []
skipped = 0

for task in tasks:
    if not isinstance(task, dict):
        continue
    desc = task.get('description', '').strip()
    model = task.get('model', 'sonnet')
    files = task.get('files', [])

    if not desc:
        continue

    # Score based on specificity
    score = 40  # base
    if files:
        score += 20  # has file targets
    if any(char in desc for char in [':', '.', '/']):
        score += 15  # specific enough
    if len(desc) > 30:
        score += 15  # substantive description
    if model in ['haiku', 'sonnet', 'opus']:
        score += 10  # valid model selected

    if score < 50:
        skipped += 1
        print(f'[SKIP score={score}] {desc[:80]}', file=sys.stderr)
        continue

    # Build task entry
    task_lines = [
        '===TASK===',
        f'model: {model}',
        'timeout: 600',
        'retries: 2',
        '---',
        desc,
        '',
        '## Close the loop (required before finishing)',
        '- Verify your changes pass syntax/compile checks',
        '- Re-read every file you changed — catch logic bugs, null cases, missing imports',
        '- Use committer \"type: msg\" file1 file2 to commit (NEVER git add .)',
        '- Do NOT modify the goal file',
        '',
    ]
    output_tasks.append('\n'.join(task_lines))

if skipped:
    print(f'[Skipped {skipped} low-score tasks]', file=sys.stderr)

print('\n'.join(output_tasks))
" 2>>"$LOG_DIR/loop.log")

  if [ -z "$output" ]; then
    log_warn "All tasks scored below threshold"
    echo ""
    return
  fi

  mkdir -p "$LOG_DIR"
  echo "$output" > "$task_file"
  log_info "Wrote $(grep -c '===TASK===' "$task_file" 2>/dev/null || echo 0) task(s) to $task_file"
  echo "$task_file"
}
# ────────────────────────────────────────────────────────────────

# ─── [LLM-PAR] NODE: RUN WORKERS ────────────────────────────────
# Runs tasks in parallel using run-tasks-parallel.sh or run-tasks.sh
node_run_workers() {
  local task_file="$1"
  log_info "[LLM-PAR] workers (task_file=$task_file)"

  if [ ! -f "$task_file" ] || [ ! -s "$task_file" ]; then
    log_warn "Task file empty or missing: $task_file"
    return
  fi

  local task_count
  task_count=$(grep -c '===TASK===' "$task_file" 2>/dev/null || echo "0")
  log_info "Executing $task_count task(s) with up to $MAX_WORKERS workers"

  # Clean up leftover worktrees from previous iterations
  git worktree prune 2>/dev/null || true

  local worker_total_timeout=$(( WORKER_TIMEOUT * task_count + 60 ))

  if [ "$MAX_WORKERS" -gt 1 ]; then
    MAX_WORKERS="$MAX_WORKERS" _timeout "$worker_total_timeout" \
      bash ~/.claude/scripts/run-tasks-parallel.sh "$task_file" 2>&1 \
      | tee -a "$LOG_DIR/loop.log" || {
        log_warn "Workers returned non-zero exit (some tasks may have failed)"
      }
  else
    _timeout "$worker_total_timeout" \
      bash ~/.claude/scripts/run-tasks.sh "$task_file" 2>&1 \
      | tee -a "$LOG_DIR/loop.log" || {
        log_warn "Worker returned non-zero exit"
      }
  fi
}
# ────────────────────────────────────────────────────────────────

# ─── [DET] NODE: SYNTAX CHECK ───────────────────────────────────
# Checks syntax of all files changed since HEAD. No LLM calls.
node_syntax_check() {
  log_info "[DET] syntax_check"

  local changed_files
  changed_files=$(git diff --name-only 2>/dev/null || true)
  if [ -z "$changed_files" ]; then
    changed_files=$(git diff --name-only HEAD~1..HEAD 2>/dev/null || true)
  fi

  if [ -z "$changed_files" ]; then
    log_info "No changed files to check"
    echo ""
    return
  fi

  local failures=""

  while IFS= read -r f; do
    [ -f "$f" ] || continue
    case "$f" in
      *.py)
        if ! _timeout "$SYNTAX_CHECK_TIMEOUT" python3 -m py_compile "$f" 2>/dev/null; then
          failures="${failures}${f}\n"
          log_warn "Python syntax error: $f"
        fi
        ;;
      *.sh)
        if ! _timeout 10 bash -n "$f" 2>/dev/null; then
          failures="${failures}${f}\n"
          log_warn "Shell syntax error: $f"
        fi
        ;;
      *.ts|*.tsx)
        # Only check if npx tsc available and tsconfig exists
        if command -v npx &>/dev/null && [ -f "tsconfig.json" ]; then
          if ! _timeout "$SYNTAX_CHECK_TIMEOUT" npx tsc --noEmit 2>/dev/null; then
            failures="${failures}${f}\n"
            log_warn "TypeScript error: $f"
          fi
        fi
        ;;
    esac
  done <<< "$changed_files"

  printf "%b" "$failures"
}
# ────────────────────────────────────────────────────────────────

# ─── [LLM] NODE: FIX SYNTAX ─────────────────────────────────────
# Attempts to fix syntax errors. Called at most MAX_FIX_ATTEMPTS times per iteration.
node_fix_syntax() {
  local failing_files="$1"
  local files_list
  files_list=$(printf "%b" "$failing_files" | tr '\n' ' ')
  log_info "[LLM] fix_syntax (files: $files_list)"

  local fix_prompt="Fix syntax errors in these files: $files_list

Steps:
1. Run syntax check on each file to understand the exact errors
2. Fix only the syntax errors — do not refactor or add functionality
3. Verify each file passes its syntax check after fixing
4. Commit fixes with: committer \"fix: syntax errors\" $files_list

Only fix syntax errors. Do not change logic or add features."

  _timeout "$SUPERVISOR_TIMEOUT" claude --model "$SUPERVISOR_MODEL" -p "$fix_prompt" \
    2>&1 | tee -a "$LOG_DIR/loop.log" || {
      log_warn "Fix syntax attempt failed or timed out"
    }
}
# ────────────────────────────────────────────────────────────────

# ─── [DET] NODE: TEST SAMPLE ────────────────────────────────────
# Runs the project's verify_cmd from CLAUDE.md. No LLM calls.
node_test_sample() {
  log_info "[DET] test_sample"

  # Try reading verify_cmd from CLAUDE.md (handles both YAML front-matter and inline)
  local verify_cmd
  verify_cmd=$(grep -m1 'verify_cmd:' CLAUDE.md 2>/dev/null | sed 's/.*verify_cmd:[[:space:]]*//' || true)

  if [ -z "$verify_cmd" ]; then
    # Also try the "Verify command:" label style
    verify_cmd=$(grep -m1 'Verify command:' CLAUDE.md 2>/dev/null | sed 's/.*Verify command:[[:space:]]*//' || true)
  fi

  if [ -z "$verify_cmd" ]; then
    log_info "No verify_cmd in CLAUDE.md — skipping test sample"
    return
  fi

  log_info "Running verify: $verify_cmd"
  if _timeout "$TEST_SAMPLE_TIMEOUT" bash -c "$verify_cmd" 2>&1 | tee -a "$LOG_DIR/loop.log"; then
    log_success "Test sample passed"
  else
    log_warn "Test sample failed (workers may have introduced issues — continuing)"
  fi
}
# ────────────────────────────────────────────────────────────────

# ─── [DET] NODE: COMMIT CHANGES ─────────────────────────────────
# Commits all uncommitted changes via committer script. No LLM calls.
# Echoes number of files committed.
node_commit_changes() {
  log_info "[DET] commit_changes"

  local uncommitted
  uncommitted=$(git diff --name-only 2>/dev/null | wc -l | tr -d ' ')
  uncommitted=${uncommitted:-0}

  if [ "$uncommitted" -eq 0 ]; then
    log_info "No uncommitted changes"
    echo 0
    return
  fi

  local files_to_commit
  files_to_commit=$(git diff --name-only 2>/dev/null | tr '\n' ' ')

  if command -v committer &>/dev/null; then
    # shellcheck disable=SC2086
    committer "loop: iter $ITERATION changes" $files_to_commit 2>&1 | tee -a "$LOG_DIR/loop.log" || {
      log_warn "committer failed — changes remain uncommitted"
      echo 0
      return
    }
  else
    # Fallback: direct git commit
    # shellcheck disable=SC2086
    git add $files_to_commit
    git commit -m "loop: iter $ITERATION changes" 2>&1 | tee -a "$LOG_DIR/loop.log" || {
      log_warn "git commit failed"
      echo 0
      return
    }
  fi

  log_success "Committed $uncommitted file(s)"
  echo "$uncommitted"
}
# ────────────────────────────────────────────────────────────────

# ─── [DET] UPDATE STATE ─────────────────────────────────────────
update_state() {
  local iteration="$1"
  local commits="$2"
  mkdir -p "$(dirname "$STATE_FILE")"
  python3 - <<PYTHON_EOF
import json, os, sys
state_file = "$STATE_FILE"
try:
    state = json.load(open(state_file)) if os.path.exists(state_file) else {}
except Exception:
    state = {}

# Don't overwrite a stop sentinel
if state.get('stop'):
    sys.exit(0)

state['iteration'] = $iteration
state['commits_this_iter'] = $commits
state['goal_file'] = "$GOAL_FILE"
history = state.get('history', [])
history.append({'iter': $iteration, 'commits': $commits})
state['history'] = history[-20:]  # keep last 20
json.dump(state, open(state_file, 'w'), indent=2)
PYTHON_EOF
}
# ────────────────────────────────────────────────────────────────

# ─── GENERATE LOOP REPORT ───────────────────────────────────────
generate_loop_report() {
  local total_iterations="$1"
  local exit_reason="$2"

  log_info ""
  log_info "═══════════════════════════════════════════════"
  log_info "Blueprint Loop Complete"
  log_info "  Iterations:   $total_iterations"
  log_info "  Exit reason:  $exit_reason"
  log_info "  Goal file:    $GOAL_FILE"
  log_info "═══════════════════════════════════════════════"

  # Write last-progress file for --status command
  mkdir -p "$LOG_DIR"
  {
    echo "Loop completed at $(date '+%Y-%m-%d %H:%M')"
    echo "Iterations: $total_iterations"
    echo "Exit: $exit_reason"
    echo "Goal: $GOAL_FILE"
  } > "$LOG_DIR/last-progress"
}
# ────────────────────────────────────────────────────────────────

# ─── MAIN BLUEPRINT LOOP ────────────────────────────────────────
run_blueprint_loop() {
  local iteration=0
  local consecutive_no_commits=0
  local exit_reason="max_iterations"

  mkdir -p "$LOG_DIR"
  log_info "Starting Blueprint Loop"
  log_info "  Goal:         $GOAL_FILE"
  log_info "  Max iter:     $MAX_ITER"
  log_info "  Max workers:  $MAX_WORKERS"
  log_info "  Supervisor:   $SUPERVISOR_MODEL"
  log_info "  Workers:      $WORKER_MODEL"
  log_info "  State file:   $STATE_FILE"

  while true; do
    iteration=$((iteration + 1))
    ITERATION=$iteration  # make available to node functions

    log_info ""
    log_info "═══ Iteration $iteration / $MAX_ITER ═══"

    # [DET] Check stop sentinel first
    if check_stop_sentinel; then
      exit_reason="user_stop"
      break
    fi

    # [DET] pre_flight
    if ! node_pre_flight; then
      exit_reason="pre_flight_failed"
      break
    fi

    # [DET] hydrate_context
    node_hydrate_context

    # [LLM] supervisor
    local tasks_json
    tasks_json=$(node_supervisor "$iteration")

    # Check CONVERGED signal
    if echo "$tasks_json" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    sys.exit(0 if isinstance(d, dict) and d.get('status') == 'CONVERGED' else 1)
except:
    sys.exit(1)
" 2>/dev/null; then
      local reason
      reason=$(echo "$tasks_json" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('reason', 'goal achieved'))
" 2>/dev/null || echo "goal achieved")
      log_success "CONVERGED: $reason"
      exit_reason="converged"
      break
    fi

    # [DET] score + write task file
    local task_file
    task_file=$(node_score_and_write "$tasks_json")

    local task_count=0
    if [ -n "$task_file" ] && [ -f "$task_file" ]; then
      task_count=$(grep -c '===TASK===' "$task_file" 2>/dev/null || echo "0")
    fi

    if [ "$task_count" -eq 0 ]; then
      consecutive_no_commits=$((consecutive_no_commits + 1))
      log_warn "No executable tasks this iteration (consecutive empty: $consecutive_no_commits / $MAX_CONSECUTIVE_NO_COMMITS)"
      if [ "$consecutive_no_commits" -ge "$MAX_CONSECUTIVE_NO_COMMITS" ]; then
        log_error "$MAX_CONSECUTIVE_NO_COMMITS consecutive empty iterations — loop appears stuck"
        exit_reason="stuck_no_tasks"
        break
      fi
      update_state "$iteration" 0
      continue
    fi

    # [LLM-PAR] workers
    node_run_workers "$task_file"

    # [DET] syntax_check
    local syntax_failures
    syntax_failures=$(node_syntax_check)

    # [LLM] fix_node — only if needed, at most MAX_FIX_ATTEMPTS times per iter
    if [ -n "$syntax_failures" ]; then
      log_warn "Syntax failures detected — calling fix node (attempt 1/$MAX_FIX_ATTEMPTS)"
      node_fix_syntax "$syntax_failures"

      # Re-check after fix attempt
      syntax_failures=$(node_syntax_check)
      if [ -n "$syntax_failures" ]; then
        log_warn "Syntax still failing after fix — reverting broken files"
        while IFS= read -r f; do
          if [ -n "$f" ]; then
            git checkout -- "$f" 2>/dev/null && log_warn "Reverted: $f" || true
          fi
        done < <(printf "%b" "$syntax_failures")
      fi
    fi

    # [DET] test_sample
    node_test_sample

    # [DET] commit_changes
    local new_commits
    new_commits=$(node_commit_changes)

    if [ "${new_commits:-0}" -eq 0 ]; then
      consecutive_no_commits=$((consecutive_no_commits + 1))
      log_warn "No commits this iteration (consecutive no-commit: $consecutive_no_commits)"
    else
      consecutive_no_commits=0
      log_success "Committed $new_commits change(s) in iteration $iteration"
    fi

    # [DET] convergence_check
    if [ "$iteration" -ge "$MAX_ITER" ]; then
      log_warn "Max iterations ($MAX_ITER) reached"
      exit_reason="max_iterations"
      break
    fi

    if [ "$consecutive_no_commits" -ge "$MAX_CONSECUTIVE_NO_COMMITS" ]; then
      log_error "$MAX_CONSECUTIVE_NO_COMMITS consecutive iterations with no commits — loop stuck"
      exit_reason="stuck_no_commits"
      break
    fi

    update_state "$iteration" "${new_commits:-0}"
  done

  generate_loop_report "$iteration" "$exit_reason"
}
# ────────────────────────────────────────────────────────────────

# ─── ENTRY POINT ────────────────────────────────────────────────
main() {
  parse_args "$@"

  if [ -z "$GOAL_FILE" ]; then
    echo "Usage: loop-runner.sh GOAL_FILE [options]"
    echo "       loop-runner.sh --status"
    echo "       loop-runner.sh --stop"
    echo ""
    echo "Options:"
    echo "  --model MODEL         supervisor model (default: claude-sonnet-4-6)"
    echo "  --worker-model MODEL  worker model (default: same as supervisor)"
    echo "  --max-iter N          max iterations (default: 10)"
    echo "  --max-workers N       max parallel workers (default: 4)"
    echo "  --context FILE        pre-generated context file"
    echo "  --state FILE          state file (default: .claude/loop-state.json)"
    echo "  --log-dir DIR         log directory (default: logs/loop)"
    exit 1
  fi

  run_blueprint_loop
}

main "$@"
