#!/usr/bin/env bash
# start.sh — Autonomous lifecycle orchestrator
#
# One command starts everything. Runs unattended for any duration until
# done/blocked/budget hit. Human role: set direction + review results.
#
# Usage:
#   start.sh --morning           Morning briefing only (no workers)
#   start.sh [--run]             Autonomous run until done/blocked/budget
#   start.sh --hours N           Autonomous with wall-clock limit
#   start.sh --goal "X"          Targeted run (skip orchestrate, use goal directly)
#   start.sh --budget N          Set cost budget in USD
#   start.sh --resume            Resume from last session-progress.md
#   start.sh --stop              Write stop sentinel
#   start.sh --dry-run           Dry run: show plan and exit without executing
#
# Architecture:
#   start.sh is a pure shell script — consumes zero LLM context.
#   Each worker = independent Claude session via loop-runner.sh.
#   start.sh only orchestrates: plan → filter → loop → verify → repeat.

set -uo pipefail

# Allow nested claude calls
unset CLAUDECODE 2>/dev/null || true

# ─── Configuration ────────────────────────────────────────────────────────────
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SETTINGS_FILE="$HOME/.claude/start-settings.json"
PROGRESS_FILE=".claude/session-progress.md"
STOP_SENTINEL=".claude/stop-start"
REPORT_DIR=".claude"
COST_LOG=".claude/loop-cost.log"

# Defaults
MODE="run"
HOURS=0
GOAL=""
BUDGET=0
DRY_RUN=false
MAX_OUTER_ITER=20
MAX_VERIFY_RETRIES=3
SUPERVISOR_MODEL="sonnet"
WORKER_MODEL="sonnet"
MAX_WORKERS=4

# ─── Argument parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --morning)       MODE="morning";       shift ;;
    --run)           MODE="run";           shift ;;
    --hours)         HOURS="$2";           shift 2 ;;
    --goal)          GOAL="$2";            shift 2 ;;
    --budget)        BUDGET="$2";          shift 2 ;;
    --dry-run)       DRY_RUN=true;         shift ;;
    --resume)        MODE="resume";        shift ;;
    --stop)          MODE="stop";          shift ;;
    --model)         SUPERVISOR_MODEL="$2"; shift 2 ;;
    --worker-model)  WORKER_MODEL="$2";    shift 2 ;;
    --max-workers)   MAX_WORKERS="$2";     shift 2 ;;
    --confirm)       CONFIRM=true;         shift ;;
    *)               echo "Unknown flag: $1" >&2; shift ;;
  esac
done

# Load settings from file (budget, model defaults)
if [[ -f "$SETTINGS_FILE" ]]; then
  _file_budget=$(python3 -c "import json; d=json.load(open('$SETTINGS_FILE')); print(d.get('session_budget_usd', 0))" 2>/dev/null || echo 0)
  [[ "$BUDGET" -eq 0 ]] && BUDGET="$_file_budget"
fi

# Default budget warning
if [[ "$BUDGET" -eq 0 && "$MODE" == "run" ]]; then
  BUDGET=5
  echo "⚠ No budget set — defaulting to \$${BUDGET}. Use --budget N to change."
fi

START_TIME=$(date +%s)
SESSION_ID=$(date +%Y%m%d-%H%M%S)
TOTAL_COST=0
OUTER_ITER=0

# ─── Helper functions ─────────────────────────────────────────────────────────
_safe_cat() { cat "$1" 2>/dev/null || echo ""; }

_log() { echo "[$(date '+%H:%M:%S')] $*"; }

_write_progress() {
  cat > "$PROGRESS_FILE" <<EOF
SESSION_ID=$SESSION_ID
MODE=$MODE
OUTER_ITER=$OUTER_ITER
CURRENT_FEATURE=${CURRENT_FEATURE:-}
TOTAL_COST=$TOTAL_COST
STARTED=$START_TIME
LAST_UPDATE=$(date +%s)
STATUS=$1
VERIFY_RETRIES=${VERIFY_RETRIES:-0}
EOF
}

_read_progress() {
  grep -m1 "^${1}=" "$PROGRESS_FILE" 2>/dev/null | cut -d= -f2- || echo "${2:-}"
}

_check_stop_conditions() {
  # Stop sentinel
  if [[ -f "$STOP_SENTINEL" ]]; then
    _log "Stop sentinel detected. Shutting down."
    rm -f "$STOP_SENTINEL"
    return 1
  fi

  # Blockers
  if [[ -f ".claude/blockers.md" ]]; then
    _log "⚠ Tier 3 blocker detected. See .claude/blockers.md"
    return 1
  fi

  # Wall-clock limit
  if [[ "$HOURS" -gt 0 ]]; then
    local elapsed=$(( $(date +%s) - START_TIME ))
    local limit=$(( HOURS * 3600 ))
    if [[ $elapsed -ge $limit ]]; then
      _log "Wall-clock limit reached (${HOURS}h). Shutting down."
      return 1
    fi
  fi

  # Cost budget
  if [[ "$BUDGET" -gt 0 ]]; then
    local cost_int=${TOTAL_COST%.*}
    cost_int=${cost_int:-0}
    if [[ "$cost_int" -ge "$BUDGET" ]]; then
      _log "Cost budget exceeded (\$${TOTAL_COST} >= \$${BUDGET}). Shutting down."
      return 1
    fi
  fi

  return 0
}

_accumulate_cost() {
  # Read cumulative cost from loop-cost.log (loop-runner.sh tracks running total)
  if [[ -f "$COST_LOG" ]]; then
    local cumulative
    cumulative=$(tail -1 "$COST_LOG" 2>/dev/null | grep -oP 'CUMULATIVE=\$\K[0-9.]+' || echo 0)
    TOTAL_COST=$(python3 -c "print(round($TOTAL_COST + $cumulative, 4))" 2>/dev/null || echo "$TOTAL_COST")
  fi
}

_write_session_report() {
  local end_time duration status
  end_time=$(date '+%Y-%m-%d %H:%M')
  duration=$(( ($(date +%s) - START_TIME) / 60 ))
  status="${1:-completed}"

  local completed_count skipped_count blocker_count
  completed_count=$(git log --oneline --since="@${START_TIME}" 2>/dev/null | wc -l | tr -d ' ')
  skipped_count=0
  [[ -f ".claude/skipped.md" ]] && { skipped_count=$(grep -c "^## " .claude/skipped.md 2>/dev/null) || skipped_count=0; }
  blocker_count=0
  [[ -f ".claude/blockers.md" ]] && { blocker_count=$(grep -c "^## " .claude/blockers.md 2>/dev/null) || blocker_count=0; }

  cat > "${REPORT_DIR}/session-report-${SESSION_ID}.md" <<EOF
## Session: $(date -d "@${START_TIME}" '+%Y-%m-%d %H:%M' 2>/dev/null || date -r "$START_TIME" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "unknown") → ${end_time}  (${duration}min)

### Status: ${status}

### Completed
${completed_count} commits since session start.

### Skipped (${skipped_count} tasks)
$(if [[ -f ".claude/skipped.md" ]]; then cat .claude/skipped.md; else echo "None"; fi)

### Blockers (${blocker_count})
$(if [[ -f ".claude/blockers.md" ]]; then cat .claude/blockers.md; else echo "None"; fi)

### Cost: \$${TOTAL_COST}

### Iterations: ${OUTER_ITER}

### Feature: ${CURRENT_FEATURE:-unknown}
EOF

  _log "Session report written to ${REPORT_DIR}/session-report-${SESSION_ID}.md"
}

# ─── Feature filtering ────────────────────────────────────────────────────────
_filter_by_feature() {
  local proposed="$1" filtered="$2"

  # Extract unique Feature: tags
  local features
  features=$(grep -i "^Feature:" "$proposed" 2>/dev/null | sed 's/^Feature: *//i' | sort -u)

  if [[ -z "$features" ]]; then
    # No Feature: tags — use all tasks as one group
    _log "No Feature: tags found — running all tasks"
    cp "$proposed" "$filtered"
    CURRENT_FEATURE="all"
    return 0
  fi

  # Pick first feature (highest priority = appears first in TODO.md)
  # Simple heuristic: first Feature: tag in the file = highest priority
  CURRENT_FEATURE=$(grep -i -m1 "^Feature:" "$proposed" | sed 's/^Feature: *//i')
  _log "Focusing on feature: $CURRENT_FEATURE"

  # Extract only tasks with this feature tag
  python3 -c "
import sys
blocks = open('$proposed').read().split('===TASK===')
out = []
for b in blocks:
    if b.strip() and '$CURRENT_FEATURE'.lower() in b.lower():
        out.append(b)
if out:
    print('===TASK===' + '===TASK==='.join(out))
else:
    print('')
" > "$filtered"

  local task_count
  task_count=$(grep -c "^===TASK===$" "$filtered" 2>/dev/null) || task_count=0
  _log "Filtered: $task_count task(s) for feature '$CURRENT_FEATURE'"
}

# ─── MORNING BRIEFING MODE ───────────────────────────────────────────────────
if [[ "$MODE" == "morning" ]]; then
  _log "Generating morning briefing..."

  BRIEF_PROMPT="$SCRIPTS_DIR/../skills/start/morning-brief.md"
  [[ -f "$BRIEF_PROMPT" ]] || BRIEF_PROMPT="$HOME/.claude/skills/start/morning-brief.md"

  if [[ ! -f "$BRIEF_PROMPT" ]]; then
    echo "Error: morning-brief.md not found" >&2
    exit 1
  fi

  claude -p --dangerously-skip-permissions \
    "$(printf '%s\n\n---\n\n## VISION / GOALS\n%s\n\n## TODO\n%s\n\n## PROGRESS\n%s\n\n## BRAINSTORM\n%s\n\n## Recent git log\n%s' \
      "$(_safe_cat "$BRIEF_PROMPT")" \
      "$(_safe_cat GOALS.md)$(_safe_cat VISION.md)" \
      "$(_safe_cat TODO.md)" \
      "$(_safe_cat PROGRESS.md)" \
      "$(_safe_cat BRAINSTORM.md)" \
      "$(git log --oneline -20 2>/dev/null || echo '(no git history)')")" \
    2>/dev/null

  exit 0
fi

# ─── STOP MODE ────────────────────────────────────────────────────────────────
if [[ "$MODE" == "stop" ]]; then
  touch "$STOP_SENTINEL"
  echo "Stop sentinel written to $STOP_SENTINEL"
  echo "Running start.sh session will exit after current iteration."
  exit 0
fi

# ─── RESUME MODE ──────────────────────────────────────────────────────────────
if [[ "$MODE" == "resume" ]]; then
  if [[ ! -f "$PROGRESS_FILE" ]]; then
    echo "No session-progress.md found. Nothing to resume."
    exit 1
  fi
  SESSION_ID=$(_read_progress SESSION_ID "$SESSION_ID")
  OUTER_ITER=$(_read_progress OUTER_ITER 0)
  TOTAL_COST=$(_read_progress TOTAL_COST 0)
  CURRENT_FEATURE=$(_read_progress CURRENT_FEATURE "")
  START_TIME=$(_read_progress STARTED "$START_TIME")
  _log "Resuming session $SESSION_ID from iteration $OUTER_ITER (cost: \$$TOTAL_COST)"
  MODE="run"  # Continue as normal run
fi

# ─── AUTONOMOUS RUN MODE ─────────────────────────────────────────────────────
_log "Starting autonomous session $SESSION_ID"
_log "Budget: \$$BUDGET | Max iterations: $MAX_OUTER_ITER | Workers: $MAX_WORKERS"
[[ "$HOURS" -gt 0 ]] && _log "Wall-clock limit: ${HOURS}h"

mkdir -p .claude logs/loop

# Stale blocker check
if [[ -f ".claude/blockers.md" ]]; then
  if [[ -t 0 ]]; then
    echo ""
    echo "⚠ Existing blockers found (.claude/blockers.md):"
    head -5 .claude/blockers.md
    echo ""
    read -t 30 -p "Still blocked? (y/N, auto-N in 30s): " _answer || _answer="n"
    if [[ "${_answer,,}" == "y" ]]; then
      _log "Blockers confirmed. Exiting."
      _write_session_report "blocked"
      exit 1
    else
      _log "Blockers cleared by user. Archiving and continuing."
      cat .claude/blockers.md >> .claude/blockers-archive.md 2>/dev/null
      rm -f .claude/blockers.md
    fi
  else
    _log "⚠ Blockers exist in unattended mode. Exiting."
    _write_session_report "blocked-stale"
    exit 1
  fi
fi

# Interactive plan approval
if [[ -t 0 && "${CONFIRM:-}" != "true" && -z "$GOAL" ]]; then
  echo ""
  echo "╔════════════════════════════════════════════╗"
  echo "║    Claude Code — Autonomous Session        ║"
  echo "╚════════════════════════════════════════════╝"
  echo "  Budget:   \$$BUDGET"
  echo "  Workers:  $MAX_WORKERS × $WORKER_MODEL"
  echo "  Duration: $(if [[ "$HOURS" -gt 0 ]]; then echo "${HOURS}h"; else echo "until done"; fi)"
  echo ""
  echo "  Press Enter to start, Ctrl+C to abort (auto-start in 30s)..."
  read -t 30 || true
fi

# ─── Outer loop ───────────────────────────────────────────────────────────────
while [[ $OUTER_ITER -lt $MAX_OUTER_ITER ]]; do
  OUTER_ITER=$((OUTER_ITER + 1))
  VERIFY_RETRIES=0

  _log "═══ Outer iteration $OUTER_ITER / $MAX_OUTER_ITER ═══"
  _write_progress "planning"

  # ── Check stop conditions ──
  if ! _check_stop_conditions; then
    _write_session_report "stopped"
    exit 0
  fi

  # ── Plan: run /orchestrate ──
  if [[ -n "$GOAL" ]]; then
    # Targeted mode: skip orchestrate, use goal directly as loop-runner goal
    _log "Targeted mode: using goal '$GOAL'"
    if [[ -f "$GOAL" ]]; then
      cp "$GOAL" .claude/filtered-tasks.md
    else
      # Goal is a string, write it as a goal file
      echo "$GOAL" > .claude/filtered-tasks.md
    fi
    CURRENT_FEATURE="targeted"
    # Targeted goals use loop-runner's supervisor for convergence, not ===TASK=== counting
    TARGETED=true
  else
    _log "Running /orchestrate..."

    claude -p --dangerously-skip-permissions \
      "$(printf '%s\n\n---\n\n## CLAUDE.md\n%s\n\n## TODO.md\n%s\n\n## GOALS / VISION\n%s\n\n## PROGRESS.md\n%s\n\n## Skipped tasks\n%s\n\n## BRAINSTORM\n%s' \
        "$(_safe_cat "$HOME/.claude/skills/orchestrate/prompt.md")" \
        "$(_safe_cat CLAUDE.md)" \
        "$(_safe_cat TODO.md)" \
        "$(_safe_cat GOALS.md)$(_safe_cat VISION.md)" \
        "$(_safe_cat PROGRESS.md)" \
        "$(_safe_cat .claude/skipped.md)" \
        "$(_safe_cat BRAINSTORM.md)")" \
      > .claude/proposed-tasks.md 2>/dev/null

    if [[ ! -s .claude/proposed-tasks.md ]] || ! grep -q "^===TASK===$" .claude/proposed-tasks.md 2>/dev/null; then
      _log "⚠ /orchestrate produced no tasks. Stopping."
      _write_session_report "converged"
      exit 0
    fi

    # ── Filter by feature ──
    _filter_by_feature .claude/proposed-tasks.md .claude/filtered-tasks.md
  fi

  # ── Convergence check: any open tasks? ──
  if [[ "${TARGETED:-false}" != "true" ]]; then
    open_tasks=$(grep -c "^===TASK===$" .claude/filtered-tasks.md 2>/dev/null) || open_tasks=0
    if [[ "$open_tasks" -eq 0 ]]; then
      _log "✓ No open tasks — converged!"
      _write_session_report "converged"
      exit 0
    fi
    _log "$open_tasks task(s) to execute"
  else
    _log "Targeted mode — delegating convergence to loop-runner supervisor"
  fi

  # ── Interactive approval window ──
  if [[ -t 0 && "${CONFIRM:-}" != "true" ]]; then
    echo ""
    echo "  Plan:"
    grep -E "^===TASK===|^---$|^[A-Z]" .claude/filtered-tasks.md | head -20
    echo ""
    echo "  Starting in 30s... (Ctrl+C to abort)"
    read -t 30 || true
  fi

  # ── Dry-run exit ──
  if [[ "$DRY_RUN" == "true" ]]; then
    echo ""
    echo "  [DRY RUN] Would execute:"
    echo "    Feature:  ${CURRENT_FEATURE:-all}"
    echo "    Tasks:    ${open_tasks:-0}"
    echo "    Workers:  $MAX_WORKERS × $WORKER_MODEL"
    echo "    Budget:   \$$BUDGET"
    echo ""
    echo "  loop-runner.sh would run with goal: .claude/loop-goal.md"
    echo "  Exiting (dry run — no workers started, no verify run)."
    exit 0
  fi

  # ── Execute: run /loop ──
  _write_progress "executing"
  _log "Running loop (goal: .claude/filtered-tasks.md)..."

  # Inject drift prevention rule into goal
  {
    cat .claude/filtered-tasks.md
    echo ""
    echo "---"
    echo "RULES: If you discover a new approach or direction change, write it to BRAINSTORM.md with [AI] prefix. Never modify GOALS.md or VISION.md directly."
  } > .claude/loop-goal.md

  bash "$SCRIPTS_DIR/loop-runner.sh" .claude/loop-goal.md \
    --model "$SUPERVISOR_MODEL" \
    --worker-model "$WORKER_MODEL" \
    --max-workers "$MAX_WORKERS" \
    --max-iter 5 \
    --state .claude/loop-state-start \
    --log-dir logs/loop 2>&1 | tee -a "logs/loop/start-${SESSION_ID}.log"

  _accumulate_cost
  _log "Cumulative cost: \$$TOTAL_COST"

  # Targeted mode: one outer iteration is enough (loop-runner iterates internally)
  if [[ "${TARGETED:-false}" == "true" ]]; then
    _log "Targeted mode complete."
    _write_session_report "completed"
    exit 0
  fi

  # ── Verify ──
  _write_progress "verifying"
  _log "Running /verify..."

  claude -p --dangerously-skip-permissions \
    "$(_safe_cat "$HOME/.claude/skills/verify/prompt.md")" \
    > .claude/verify-output.txt 2>/dev/null

  VERIFY_RESULT=$(grep -m1 "VERIFY_RESULT:" .claude/verify-output.txt 2>/dev/null | awk '{print $2}' || echo "partial")
  FAILED_ANCHORS=$(grep -m1 "FAILED_ANCHORS:" .claude/verify-output.txt 2>/dev/null | cut -d: -f2- | xargs || echo "none")

  _log "Verify result: $VERIFY_RESULT (failed anchors: $FAILED_ANCHORS)"

  case "$VERIFY_RESULT" in
    pass)
      _log "✓ Verification passed"
      ;;
    partial)
      _log "⚠ Partial verification — logging gaps"
      echo "## [$(date -Iseconds)] Partial verify: unverifiable anchors" >> .claude/skipped.md
      ;;
    fail)
      VERIFY_RETRIES=$((VERIFY_RETRIES + 1))
      _log "✗ Verification failed (retry $VERIFY_RETRIES/$MAX_VERIFY_RETRIES)"

      if [[ $VERIFY_RETRIES -ge $MAX_VERIFY_RETRIES ]]; then
        _log "Max verify retries reached — Tier 2 escalation"
        echo "## [$(date -Iseconds)] Skipped: verify failed after $MAX_VERIFY_RETRIES retries for feature '$CURRENT_FEATURE'" >> .claude/skipped.md
        echo "Failed anchors: $FAILED_ANCHORS" >> .claude/skipped.md
      else
        # Create fix tasks and re-loop
        _log "Creating fix tasks for failed anchors: $FAILED_ANCHORS"
        {
          echo "===TASK==="
          echo "model: sonnet"
          echo "timeout: 900"
          echo "retries: 1"
          echo "Feature: $CURRENT_FEATURE"
          echo "---"
          echo "Fix verification failures for: $FAILED_ANCHORS"
          echo ""
          echo "The /verify skill reported these behavior anchors are broken."
          echo "Read .claude/verify-output.txt for details."
          echo "Fix the regressions and ensure these anchors pass again."
          echo ""
          echo "Commit with: committer \"fix: repair broken anchors\" <files>"
        } > .claude/filtered-tasks.md

        # Go back to loop (don't re-orchestrate)
        continue
      fi
      ;;
  esac

  # ── Sync docs ──
  _write_progress "syncing"
  _log "Syncing docs..."

  claude -p --dangerously-skip-permissions \
    "$(_safe_cat "$HOME/.claude/skills/sync/prompt.md")" \
    > /dev/null 2>&1

  # Commit doc updates
  if [[ -n "$(git status --porcelain TODO.md PROGRESS.md 2>/dev/null)" ]]; then
    bash "$SCRIPTS_DIR/committer.sh" "docs: sync after iteration $OUTER_ITER" TODO.md PROGRESS.md 2>/dev/null || true
  fi

  _write_progress "iteration-complete"
  _log "Iteration $OUTER_ITER complete."
done

# ── Session complete ──────────────────────────────────────────────────────────
if [[ $OUTER_ITER -ge $MAX_OUTER_ITER ]]; then
  _log "Max outer iterations reached ($MAX_OUTER_ITER)"
  _write_session_report "max-iterations"
else
  _write_session_report "completed"
fi

_log "Done. Report: ${REPORT_DIR}/session-report-${SESSION_ID}.md"
