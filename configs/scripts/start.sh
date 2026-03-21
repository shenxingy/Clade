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
#   start.sh --max-iter N        Max outer iterations (default: 20)
#   start.sh --max-inner-iter N  Max inner loop iterations per outer (default: 5)
#   start.sh --resume            Resume from last session-progress.md
#   start.sh --stop              Write stop sentinel
#   start.sh --patrol            Cross-project scan (report only, no workers)
#   start.sh --research          Auto-research based on project context
#   start.sh --dry-run           Dry run: show plan and exit without executing
#
# Architecture:
#   start.sh is a pure shell script — consumes zero LLM context.
#   Each worker = independent Claude session via loop-runner.sh.
#   start.sh only orchestrates: plan → filter → loop → verify → repeat.

set -uo pipefail

# Allow nested claude calls
unset CLAUDECODE 2>/dev/null || true

# Cross-platform timeout (macOS: gtimeout from coreutils)
_timeout() {
  if command -v gtimeout &>/dev/null; then
    gtimeout "$@"
  elif command -v timeout &>/dev/null; then
    timeout "$@"
  else
    shift  # remove duration arg, run without timeout
    "$@"
  fi
}

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
MAX_INNER_ITER=5
MAX_VERIFY_RETRIES=3
SUPERVISOR_MODEL="sonnet"
WORKER_MODEL="sonnet"
MAX_WORKERS=4
BATCH_FEEDBACK_PENDING=false

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
    --max-iter)      MAX_OUTER_ITER="$2";  shift 2 ;;
    --max-inner-iter) MAX_INNER_ITER="$2"; shift 2 ;;
    --patrol)        MODE="patrol";        shift ;;
    --research)      MODE="research";      shift ;;
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

_notify() {
  # Fire-and-forget notification via loop-runner's notify hook (if available)
  local status="$1" msg="$2"
  for hook in "${SCRIPTS_DIR}/../hooks/notify-telegram.sh" "$HOME/.claude/hooks/notify-telegram.sh"; do
    if [[ -x "$hook" ]]; then
      bash "$hook" "$status" "$msg" &>/dev/null &
      return
    fi
  done
}

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
BUDGET=$BUDGET
HOURS=$HOURS
MAX_WORKERS=$MAX_WORKERS
SUPERVISOR_MODEL=$SUPERVISOR_MODEL
WORKER_MODEL=$WORKER_MODEL
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
    cumulative=$(tail -1 "$COST_LOG" 2>/dev/null | grep -o 'CUMULATIVE=\$[0-9.]*' | sed 's/CUMULATIVE=\$//' || echo 0)
    # Skip python3 call if cumulative is zero or empty (file exists but no data yet)
    if [[ -n "$cumulative" && "$cumulative" != "0" ]]; then
      TOTAL_COST=$(python3 -c "print(round($TOTAL_COST + $cumulative, 4))" 2>/dev/null || echo "$TOTAL_COST")
    fi
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

# Graceful shutdown on SIGTERM/SIGINT
_shutdown() {
  echo ""
  _log "Signal received — shutting down..."
  _write_session_report "interrupted"
  _notify "interrupted" "Session $SESSION_ID interrupted (${OUTER_ITER:-0} iters, \$$TOTAL_COST)"
  exit 130
}
trap _shutdown SIGTERM SIGINT
trap '' PIPE  # Ignore SIGPIPE — prevents death when piped through head/tail

# ─── Post-convergence scan ────────────────────────────────────────────────────
# Run task factory scripts to discover more work before declaring "done".
# Returns 0 if findings exist (tasks written to .claude/scan-findings.md), 1 if clean.
_POST_CONVERGENCE_DONE=false  # Only scan once per session (prevent infinite loops)

_post_convergence_scan() {
  if [[ "$_POST_CONVERGENCE_DONE" == "true" ]]; then
    return 1
  fi
  _POST_CONVERGENCE_DONE=true

  _log "Running post-convergence work discovery scans..."
  local findings=""
  local scan_scripts=(
    "$SCRIPTS_DIR/scan-ci-failures.sh"
    "$SCRIPTS_DIR/scan-coverage.sh"
    "$SCRIPTS_DIR/scan-deps.sh"
    "$SCRIPTS_DIR/scan-health.sh"
    "$SCRIPTS_DIR/scan-verify-issues.sh"
  )

  for script in "${scan_scripts[@]}"; do
    if [[ -x "$script" ]]; then
      local output
      output=$(_timeout 120s bash "$script" . 2>/dev/null || true)
      if echo "$output" | grep -q "^===TASK===$"; then
        findings="${findings}${output}"$'\n'
      fi
    fi
  done

  if [[ -n "$findings" ]] && echo "$findings" | grep -q "^===TASK===$"; then
    local finding_count
    finding_count=$(echo "$findings" | grep -c "^===TASK===$") || finding_count=0
    _log "Post-convergence scan found $finding_count new task(s) — injecting into next iteration"
    echo "$findings" > .claude/filtered-tasks.md
    CURRENT_FEATURE="post-convergence"
    return 0
  else
    _log "Post-convergence scan: clean — no new issues found"
    return 1
  fi
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

  # Extract only tasks with this feature tag (use env var to avoid shell injection)
  _FILTER_FEATURE="$CURRENT_FEATURE" _FILTER_INPUT="$proposed" python3 -c "
import os
feat = os.environ['_FILTER_FEATURE'].lower()
blocks = open(os.environ['_FILTER_INPUT']).read().split('===TASK===')
out = [b for b in blocks if b.strip() and feat in b.lower()]
print('===TASK===' + '===TASK==='.join(out) if out else '')
" > "$filtered"

  local task_count
  task_count=$(grep -c "^===TASK===$" "$filtered" 2>/dev/null) || task_count=0
  _log "Filtered: $task_count task(s) for feature '$CURRENT_FEATURE'"
}

# ─── PATROL MODE ─────────────────────────────────────────────────────────────
# Scan all ~/projects/*/ with CLAUDE.md, run task factories, aggregate report.
# Report-only — no workers, no /verify per project.
_patrol() {
  local patrol_date
  patrol_date=$(date +%Y-%m-%d)
  local report_file="$HOME/.claude/patrol-report-${patrol_date}.md"
  local total_tasks=0
  local project_count=0
  local summary_table="| Project | Issues | Details |"$'\n'"| --- | --- | --- |"
  local all_findings=""

  _log "Starting cross-project patrol scan..."

  local scan_scripts=(
    "$SCRIPTS_DIR/scan-ci-failures.sh"
    "$SCRIPTS_DIR/scan-coverage.sh"
    "$SCRIPTS_DIR/scan-deps.sh"
    "$SCRIPTS_DIR/scan-health.sh"
    "$SCRIPTS_DIR/scan-verify-issues.sh"
  )

  for project_dir in "$HOME"/projects/*/; do
    [[ -f "${project_dir}CLAUDE.md" ]] || continue
    local project_name
    project_name=$(basename "$project_dir")
    project_count=$((project_count + 1))

    _log "  Scanning: $project_name"
    local project_findings=""
    local project_task_count=0

    for script in "${scan_scripts[@]}"; do
      [[ -x "$script" ]] || continue
      local output
      output=$(_timeout 120s bash "$script" "$project_dir" 2>/dev/null || true)
      if echo "$output" | grep -q "^===TASK===$"; then
        # Tag tasks with project
        local tagged
        tagged=$(echo "$output" | sed "s/^===TASK===$/===TASK===\nproject: ${project_name}/")
        project_findings="${project_findings}${tagged}"$'\n'
        local script_tasks
        script_tasks=$(echo "$output" | grep -c "^===TASK===$") || script_tasks=0
        project_task_count=$((project_task_count + script_tasks))
      fi
    done

    # Build summary row
    if [[ $project_task_count -gt 0 ]]; then
      local detail_summary
      detail_summary=$(echo "$project_findings" | grep -E "^(fix|refactor|test|chore):" | head -3 | tr '\n' '; ' | sed 's/; $//')
      summary_table="${summary_table}"$'\n'"| ${project_name} | ${project_task_count} | ${detail_summary:-scan issues found} |"
      total_tasks=$((total_tasks + project_task_count))
      all_findings="${all_findings}"$'\n'"### ${project_name}"$'\n'"${project_findings}"
    else
      summary_table="${summary_table}"$'\n'"| ${project_name} | 0 | clean |"
    fi
  done

  # Write report
  {
    echo "# Patrol Report — ${patrol_date}"
    echo ""
    echo "Scanned ${project_count} project(s), found ${total_tasks} issue(s)."
    echo ""
    echo "## Summary"
    echo ""
    echo "${summary_table}"
  } > "$report_file"

  # Append raw findings
  if [[ $total_tasks -gt 0 ]]; then
    {
      echo ""
      echo "## Raw Findings"
      echo "$all_findings"
    } >> "$report_file"
  fi

  _log "Patrol complete: ${project_count} projects, ${total_tasks} issues"
  _log "Report: $report_file"

  # Print summary to stdout
  echo ""
  echo "═══ Patrol Report — ${patrol_date} ═══"
  echo ""
  echo "${summary_table}"
  echo ""
  echo "Total: ${total_tasks} issue(s) across ${project_count} project(s)"
  echo "Full report: ${report_file}"
}

if [[ "$MODE" == "patrol" ]]; then
  _patrol
  exit 0
fi

# ─── RESEARCH MODE ──────────────────────────────────────────────────────────
# Auto-research: gather project context and run /research skill
if [[ "$MODE" == "research" ]]; then
  _log "Running automated research..."

  RESEARCH_PROMPT="$SCRIPTS_DIR/../skills/research/prompt.md"
  [[ -f "$RESEARCH_PROMPT" ]] || RESEARCH_PROMPT="$HOME/.claude/skills/research/prompt.md"

  if [[ ! -f "$RESEARCH_PROMPT" ]]; then
    echo "Error: research prompt not found" >&2
    exit 1
  fi

  # Auto-generate topic from project context
  TOPIC=$(python3 -c "
import re
vision = open('VISION.md', 'r').read() if __import__('os').path.exists('VISION.md') else ''
goals = open('GOALS.md', 'r').read() if __import__('os').path.exists('GOALS.md') else ''
todo = open('TODO.md', 'r').read() if __import__('os').path.exists('TODO.md') else ''
brainstorm = open('BRAINSTORM.md', 'r').read() if __import__('os').path.exists('BRAINSTORM.md') else ''
# Extract unchecked items as research focus areas
unchecked = re.findall(r'- \[ \] (.+)', todo + brainstorm)
if unchecked:
    print('; '.join(unchecked[:5]))
elif vision:
    lines = [l.strip() for l in vision.splitlines() if l.strip() and not l.startswith('#')]
    print('; '.join(lines[:3]))
else:
    print('project improvement opportunities')
" 2>/dev/null || echo "project improvement opportunities")

  _log "Research topic: $TOPIC"

  # Build context and run research
  printf '%s\n\n---\n\nResearch topic: %s\n\n## VISION / GOALS\n%s\n\n## TODO\n%s\n\n## BRAINSTORM\n%s\n\n## Recent git log\n%s' \
    "$(_safe_cat "$RESEARCH_PROMPT")" \
    "$TOPIC" \
    "$(_safe_cat GOALS.md)$(_safe_cat VISION.md)" \
    "$(_safe_cat TODO.md)" \
    "$(_safe_cat BRAINSTORM.md)" \
    "$(git log --oneline -20 2>/dev/null || echo '(no git history)')" \
  | _timeout 300s claude -p --dangerously-skip-permissions \
    2>/dev/null

  exit 0
fi

# ─── MORNING BRIEFING MODE ───────────────────────────────────────────────────
if [[ "$MODE" == "morning" ]]; then
  _log "Generating morning briefing..."

  BRIEF_PROMPT="$SCRIPTS_DIR/../skills/start/morning-brief.md"
  [[ -f "$BRIEF_PROMPT" ]] || BRIEF_PROMPT="$HOME/.claude/skills/start/morning-brief.md"

  if [[ ! -f "$BRIEF_PROMPT" ]]; then
    echo "Error: morning-brief.md not found" >&2
    exit 1
  fi

  printf '%s\n\n---\n\n## VISION / GOALS\n%s\n\n## TODO\n%s\n\n## PROGRESS\n%s\n\n## BRAINSTORM\n%s\n\n## Recent git log\n%s' \
    "$(_safe_cat "$BRIEF_PROMPT")" \
    "$(_safe_cat GOALS.md)$(_safe_cat VISION.md)" \
    "$(_safe_cat TODO.md)" \
    "$(_safe_cat PROGRESS.md)" \
    "$(_safe_cat BRAINSTORM.md)" \
    "$(git log --oneline -20 2>/dev/null || echo '(no git history)')" \
  | _timeout 300s claude -p --dangerously-skip-permissions \
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
  # Restore settings from previous session (CLI flags override if provided)
  [[ "$BUDGET" -eq 0 || "$BUDGET" -eq 5 ]] && BUDGET=$(_read_progress BUDGET "$BUDGET")
  [[ "$HOURS" -eq 0 ]] && HOURS=$(_read_progress HOURS "$HOURS")
  [[ "$MAX_WORKERS" -eq 4 ]] && MAX_WORKERS=$(_read_progress MAX_WORKERS "$MAX_WORKERS")
  [[ "$SUPERVISOR_MODEL" == "sonnet" ]] && SUPERVISOR_MODEL=$(_read_progress SUPERVISOR_MODEL "$SUPERVISOR_MODEL")
  [[ "$WORKER_MODEL" == "sonnet" ]] && WORKER_MODEL=$(_read_progress WORKER_MODEL "$WORKER_MODEL")
  _log "Resuming session $SESSION_ID from iteration $OUTER_ITER (cost: \$$TOTAL_COST, budget: \$$BUDGET)"
  MODE="run"  # Continue as normal run
fi

# ─── AUTONOMOUS RUN MODE ─────────────────────────────────────────────────────
_log "Starting autonomous session $SESSION_ID"
_log "Budget: \$$BUDGET | Max iterations: $MAX_OUTER_ITER | Workers: $MAX_WORKERS"
[[ "$HOURS" -gt 0 ]] && _log "Wall-clock limit: ${HOURS}h"

mkdir -p .claude logs/loop

# Session-wide logging — capture ALL output (including planning failures)
SESSION_LOG="logs/loop/start-${SESSION_ID}.log"
exec > >(tee -a "$SESSION_LOG") 2>&1

# Prevent concurrent start.sh instances on the same project
LOCK_FILE=".claude/start.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Error: another start.sh is already running in this project." >&2
  echo "  (lock: $LOCK_FILE)" >&2
  exit 1
fi
# Lock released automatically on exit (fd 9 closes)

# ── Startup health check (disk/memory) ──
_check_startup_health() {
  # Disk pressure check
  local disk_usage
  disk_usage=$(df -P . 2>/dev/null | awk 'NR==2 {gsub(/%/,"",$5); print $5}')
  if [[ -n "$disk_usage" ]]; then
    if [[ "$disk_usage" -ge 95 ]]; then
      echo "ERROR: Disk usage at ${disk_usage}% — aborting to prevent data loss." >&2
      echo "  Free up space and retry." >&2
      exit 1
    elif [[ "$disk_usage" -ge 90 ]]; then
      echo "⚠ Disk usage at ${disk_usage}% — running low."
      if [[ -t 0 ]]; then
        read -t 15 -p "  Continue anyway? (Y/n, auto-Y in 15s): " _answer || _answer="y"
        if [[ "${_answer,,}" == "n" ]]; then
          echo "Aborted by user."
          exit 1
        fi
      else
        echo "  (non-TTY: continuing with warning)"
      fi
    fi
  fi

  # Low memory warning (optional, best-effort)
  if command -v free &>/dev/null; then
    local avail_mb
    avail_mb=$(free -m 2>/dev/null | awk '/^Mem:/ {print $7}')
    if [[ -n "$avail_mb" && "$avail_mb" -lt 512 ]]; then
      echo "⚠ Low memory: ${avail_mb}MB available. Workers may OOM."
    fi
  fi

  # Stale kit detection — source configs/ changed since last install.sh
  local _kit_source="$HOME/.claude/.kit-source-dir"
  local _kit_checksum="$HOME/.claude/.kit-checksum"
  if [[ -f "$_kit_source" && -f "$_kit_checksum" ]]; then
    local _kit_dir _current _installed
    _kit_dir=$(cat "$_kit_source")
    if [[ -d "$_kit_dir/configs" ]]; then
      _current=$(find "$_kit_dir/configs" -type f | LC_ALL=C sort | xargs sha256sum 2>/dev/null | sha256sum | cut -d' ' -f1)
      _installed=$(cat "$_kit_checksum")
      if [[ "$_current" != "$_installed" ]]; then
        echo "⚠ Kit scripts are stale — configs/ changed since last install.sh"
        if [[ -t 0 ]]; then
          read -t 15 -p "  Auto-reinstall now? (Y/n, auto-Y in 15s): " _answer || _answer="y"
          if [[ "${_answer,,}" != "n" ]]; then
            bash "$_kit_dir/install.sh"
            echo "✓ Kit reinstalled."
          else
            echo "  Continuing with stale scripts (results may be unexpected)."
          fi
        else
          echo "ERROR: Stale kit in unattended mode. Run install.sh first." >&2
          exit 1
        fi
      fi
    fi
  fi
}
_check_startup_health

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
  # Reset verify retries only on fresh orchestrate (not on verify-fix re-loop)
  [[ "${VERIFY_FIX_PENDING:-false}" != "true" ]] && VERIFY_RETRIES=0

  _log "═══ Outer iteration $OUTER_ITER / $MAX_OUTER_ITER ═══"
  _write_progress "planning"

  # ── Check stop conditions ──
  if ! _check_stop_conditions; then
    _write_session_report "stopped"
    exit 0
  fi

  # ── Check for batch feedback (annotated verify-issues.md) ──
  if [[ "${VERIFY_FIX_PENDING:-false}" != "true" && -f .claude/verify-issues.md ]] \
     && grep -qE '\[fix\]' .claude/verify-issues.md 2>/dev/null; then
    _log "Found [fix] annotations in verify-issues.md — processing batch feedback"
    local bf_output
    bf_output=$(bash "$SCRIPTS_DIR/scan-verify-issues.sh" . 2>/dev/null || true)
    if echo "$bf_output" | grep -q "^===TASK===$"; then
      echo "$bf_output" > .claude/filtered-tasks.md
      BATCH_FEEDBACK_PENDING=true
      CURRENT_FEATURE="batch-feedback"
    fi
  fi

  # ── Plan: run /orchestrate (skip if verify-fail or batch-feedback created fix tasks) ──
  if [[ "${VERIFY_FIX_PENDING:-false}" == "true" ]]; then
    _log "Skipping orchestrate — running verify-fail fix tasks"
    VERIFY_FIX_PENDING=false
  elif [[ "${BATCH_FEEDBACK_PENDING:-false}" == "true" ]]; then
    _log "Skipping orchestrate — running batch feedback fix tasks"
    BATCH_FEEDBACK_PENDING=false
  elif [[ -n "$GOAL" ]]; then
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

    # Use stdin (pipe) to pass large prompts — avoids CLI hang on >100KB command-line args
    printf '%s\n\n---\n\n## CLAUDE.md\n%s\n\n## TODO.md\n%s\n\n## GOALS / VISION\n%s\n\n## PROGRESS.md\n%s\n\n## Skipped tasks\n%s\n\n## BRAINSTORM\n%s' \
      "$(_safe_cat "$HOME/.claude/skills/orchestrate/prompt.md")" \
      "$(_safe_cat CLAUDE.md)" \
      "$(_safe_cat TODO.md)" \
      "$(_safe_cat GOALS.md)$(_safe_cat VISION.md)" \
      "$(_safe_cat PROGRESS.md)" \
      "$(_safe_cat .claude/skipped.md)" \
      "$(_safe_cat BRAINSTORM.md)" \
    | _timeout 300s claude -p --dangerously-skip-permissions \
      > .claude/proposed-tasks.md 2>.claude/orchestrate-err.log
    ORCH_EXIT=$?

    # Log diagnostics on failure
    if [[ $ORCH_EXIT -ne 0 ]]; then
      _log "⚠ /orchestrate exit code: $ORCH_EXIT"
      [[ -s .claude/orchestrate-err.log ]] && _log "  stderr: $(head -5 .claude/orchestrate-err.log)"
    fi

    if [[ ! -s .claude/proposed-tasks.md ]] || ! grep -q "^===TASK===$" .claude/proposed-tasks.md 2>/dev/null; then
      _log "⚠ /orchestrate produced no ===TASK=== blocks — retrying with format enforcement..."

      # Retry once with explicit format instruction prepended
      {
        printf 'CRITICAL: You MUST output ONLY ===TASK=== blocks. No prose, no explanation. If there is truly nothing to do, output exactly "STATUS: CONVERGED" on its own line.\n\n'
        printf '%s\n\n---\n\n## CLAUDE.md\n%s\n\n## TODO.md\n%s\n\n## GOALS / VISION\n%s\n\n## PROGRESS.md\n%s\n\n## Skipped tasks\n%s\n\n## BRAINSTORM\n%s' \
          "$(_safe_cat "$HOME/.claude/skills/orchestrate/prompt.md")" \
          "$(_safe_cat CLAUDE.md)" \
          "$(_safe_cat TODO.md)" \
          "$(_safe_cat GOALS.md)$(_safe_cat VISION.md)" \
          "$(_safe_cat PROGRESS.md)" \
          "$(_safe_cat .claude/skipped.md)" \
          "$(_safe_cat BRAINSTORM.md)"
      } | _timeout 300s claude -p --dangerously-skip-permissions \
        > .claude/proposed-tasks.md 2>.claude/orchestrate-err.log

      if grep -q "^===TASK===$" .claude/proposed-tasks.md 2>/dev/null; then
        _log "Retry succeeded — found tasks"
      elif grep -q "STATUS: CONVERGED" .claude/proposed-tasks.md 2>/dev/null; then
        _log "✓ Explicit convergence declared by /orchestrate"
        if _post_convergence_scan; then
          _log "Continuing with post-convergence findings..."
        else
          _write_session_report "converged"
          exit 0
        fi
      else
        # Empty output without explicit CONVERGED — likely a flake/timeout, not real convergence
        EMPTY_RETRIES=$((${EMPTY_RETRIES:-0} + 1))
        if [[ "$EMPTY_RETRIES" -ge 3 ]]; then
          _log "⚠ /orchestrate empty 3 times — giving up"
          _write_session_report "error-orchestrate"
          exit 1
        fi
        _log "⚠ /orchestrate returned empty (attempt $EMPTY_RETRIES/3) — retrying next iteration"
        [[ -s .claude/orchestrate-err.log ]] && _log "  stderr: $(head -3 .claude/orchestrate-err.log)"
        continue
      fi
    fi

    # ── Filter by feature ──
    _filter_by_feature .claude/proposed-tasks.md .claude/filtered-tasks.md
  fi

  # ── Convergence check: any open tasks? ──
  if [[ "${TARGETED:-false}" != "true" ]]; then
    open_tasks=$(grep -c "^===TASK===$" .claude/filtered-tasks.md 2>/dev/null) || open_tasks=0
    if [[ "$open_tasks" -eq 0 ]]; then
      _log "✓ No open tasks — feature converged!"
      # Try post-convergence scan before declaring session done
      if _post_convergence_scan; then
        _log "Continuing with post-convergence findings..."
      else
        _write_session_report "converged"
        exit 0
      fi
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

  # Clear stale loop state from previous outer iteration
  rm -f .claude/loop-state-start

  # Inject drift prevention rule into goal
  {
    cat .claude/filtered-tasks.md
    echo ""
    echo "---"
    echo "RULES: If you discover a new approach or direction change, write it to BRAINSTORM.md with [AI] prefix. Never modify GOALS.md or VISION.md directly."
  } > .claude/loop-goal.md

  # Calculate remaining budget for inner loop
  LOOP_BUDGET_ARGS=()
  if [[ "$BUDGET" -gt 0 ]]; then
    BUDGET_REMAINING=$(python3 -c "print(max(0, round($BUDGET - $TOTAL_COST, 4)))" 2>/dev/null || echo "$BUDGET")
    LOOP_BUDGET_ARGS=(--budget "$BUDGET_REMAINING")
  fi

  bash "$SCRIPTS_DIR/loop-runner.sh" .claude/loop-goal.md \
    --model "$SUPERVISOR_MODEL" \
    --worker-model "$WORKER_MODEL" \
    --max-workers "$MAX_WORKERS" \
    --max-iter "$MAX_INNER_ITER" \
    --state .claude/loop-state-start \
    --log-dir logs/loop \
    ${LOOP_BUDGET_ARGS[@]+"${LOOP_BUDGET_ARGS[@]}"}

  _accumulate_cost
  _log "Cumulative cost: \$$TOTAL_COST"

  # Targeted mode: one outer iteration is enough (loop-runner iterates internally)
  if [[ "${TARGETED:-false}" == "true" ]]; then
    _log "Targeted mode complete."
    # Try post-convergence scan before declaring session done
    if _post_convergence_scan; then
      _log "Continuing with post-convergence findings..."
      TARGETED=false  # Switch to normal mode for scan findings
      continue
    fi
    _write_session_report "completed"
    exit 0
  fi

  # ── Verify ──
  _write_progress "verifying"
  _log "Running /verify..."

  rm -f .claude/playwright-issues.md .claude/verify-issues.md
  VERIFY_EXIT=0
  MCP_ARGS=()
  [[ -f .claude/mcp.json ]] && MCP_ARGS=(--mcp-config .claude/mcp.json)
  _safe_cat "$HOME/.claude/skills/verify/prompt.md" \
  | _timeout 300s claude -p --dangerously-skip-permissions ${MCP_ARGS[@]+"${MCP_ARGS[@]}"} \
    > .claude/verify-output.txt 2>.claude/verify-err.log || VERIFY_EXIT=$?

  if [[ $VERIFY_EXIT -eq 124 ]]; then
    _log "⚠ /verify timed out (300s) — treating as partial"
    VERIFY_RESULT="partial"
    FAILED_ANCHORS="none"
    INTERACTION_RESULT="skipped"
  elif [[ ! -s .claude/verify-output.txt ]]; then
    _log "⚠ /verify produced empty output (exit $VERIFY_EXIT) — treating as partial"
    VERIFY_RESULT="partial"
    FAILED_ANCHORS="none"
    INTERACTION_RESULT="skipped"
  else
    VERIFY_RESULT=$(grep -m1 "VERIFY_RESULT:" .claude/verify-output.txt 2>/dev/null | awk '{print $2}')
    VERIFY_RESULT=${VERIFY_RESULT:-partial}
    FAILED_ANCHORS=$(grep -m1 "FAILED_ANCHORS:" .claude/verify-output.txt 2>/dev/null | cut -d: -f2- | xargs)
    FAILED_ANCHORS=${FAILED_ANCHORS:-none}
    INTERACTION_RESULT=$(grep -m1 "INTERACTION_RESULT:" .claude/verify-output.txt 2>/dev/null | awk '{print $2}')
    INTERACTION_RESULT=${INTERACTION_RESULT:-skipped}
  fi

  _log "Verify result: $VERIFY_RESULT (failed anchors: $FAILED_ANCHORS, interaction: $INTERACTION_RESULT)"

  case "$VERIFY_RESULT" in
    pass)
      _log "✓ Verification passed"
      ;;
    partial)
      _log "⚠ Partial verification — logging gaps"
      echo "## [$(date +"%Y-%m-%dT%H:%M:%S%z")] Partial verify: unverifiable anchors" >> .claude/skipped.md
      ;;
    fail)
      VERIFY_RETRIES=$((VERIFY_RETRIES + 1))
      _log "✗ Verification failed (retry $VERIFY_RETRIES/$MAX_VERIFY_RETRIES)"

      if [[ $VERIFY_RETRIES -ge $MAX_VERIFY_RETRIES ]]; then
        _log "Max verify retries reached — Tier 2 escalation"
        echo "## [$(date +"%Y-%m-%dT%H:%M:%S%z")] Skipped: verify failed after $MAX_VERIFY_RETRIES retries for feature '$CURRENT_FEATURE'" >> .claude/skipped.md
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

        # Go back to loop — skip orchestrate next iteration
        VERIFY_FIX_PENDING=true
        continue
      fi
      ;;
  esac

  # ── Handle INTERACTION_RESULT ──
  case "$INTERACTION_RESULT" in
    fail)
      _log "⚠ UI interaction failures detected"
      if [[ -f .claude/playwright-issues.md ]]; then
        # [BUG] items → create fix tasks (same as FAILED_ANCHORS flow)
        bug_items=$(grep -c "^\[BUG\]" .claude/playwright-issues.md 2>/dev/null) || bug_items=0
        if [[ "$bug_items" -gt 0 && "$VERIFY_RESULT" != "fail" ]]; then
          _log "Found $bug_items UI bug(s) — creating fix tasks"
          {
            echo "===TASK==="
            echo "model: sonnet"
            echo "timeout: 900"
            echo "retries: 1"
            echo "Feature: $CURRENT_FEATURE"
            echo "---"
            echo "Fix UI bugs found by Playwright interaction testing."
            echo ""
            echo "Read .claude/playwright-issues.md for [BUG] items."
            echo "Each [BUG] describes a broken UI element or flow."
            echo "Fix the issues and verify they work."
            echo ""
            echo "Commit with: committer \"fix: UI interaction bugs\" <files>"
          } > .claude/filtered-tasks.md
          VERIFY_FIX_PENDING=true
        elif [[ "$bug_items" -eq 0 ]]; then
          _log "⚠ INTERACTION_RESULT=fail but no [BUG] items in playwright-issues.md — treating as partial"
          echo "## [$(date +"%Y-%m-%dT%H:%M:%S%z")] Partial UI interaction: fail reported but no [BUG] items" >> .claude/skipped.md
        fi
        # [UX] items → append to BRAINSTORM.md
        ux_items=$(grep "^\[UX\]" .claude/playwright-issues.md 2>/dev/null || true)
        if [[ -n "$ux_items" ]]; then
          _log "Appending UX suggestions to BRAINSTORM.md"
          {
            echo ""
            echo "## [AI] UI/UX issues from Playwright testing ($(date +"%Y-%m-%dT%H:%M:%S%z"))"
            echo "$ux_items" | sed 's/^\[UX\]/- [AI]/'
          } >> BRAINSTORM.md
        fi
      else
        _log "⚠ INTERACTION_RESULT=fail but .claude/playwright-issues.md missing — treating as partial"
        echo "## [$(date +"%Y-%m-%dT%H:%M:%S%z")] Partial UI interaction: fail reported but no issues file" >> .claude/skipped.md
      fi
      ;;
    partial)
      echo "## [$(date +"%Y-%m-%dT%H:%M:%S%z")] Partial UI interaction: some flows unverifiable" >> .claude/skipped.md
      ;;
  esac

  # UI interaction fix loop — only fires when interaction (not verify) set VERIFY_FIX_PENDING,
  # because VERIFY_RESULT=fail already `continue`d above and never reaches here.
  if [[ "${VERIFY_FIX_PENDING:-false}" == "true" ]]; then
    VERIFY_RETRIES=$((VERIFY_RETRIES + 1))
    if [[ $VERIFY_RETRIES -ge $MAX_VERIFY_RETRIES ]]; then
      _log "Max verify retries reached (including UI fixes) — skipping"
      echo "## [$(date +"%Y-%m-%dT%H:%M:%S%z")] Skipped: UI interaction fixes exhausted retries" >> .claude/skipped.md
      VERIFY_FIX_PENDING=false
    else
      continue
    fi
  fi

  # ── Sync docs ──
  _write_progress "syncing"
  _log "Syncing docs..."

  _safe_cat "$HOME/.claude/skills/sync/prompt.md" \
  | _timeout 120s claude -p --dangerously-skip-permissions \
    > /dev/null 2>.claude/sync-err.log || true

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

_notify "done" "Session $SESSION_ID complete (${OUTER_ITER} iters, \$$TOTAL_COST)"
_log "Done. Report: ${REPORT_DIR}/session-report-${SESSION_ID}.md"
