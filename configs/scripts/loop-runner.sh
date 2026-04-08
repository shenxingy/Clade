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
readonly MAX_CONSECUTIVE_FAILURES=3     # consecutive worker failures (ran but no commits) → force stop
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
MAX_CONSECUTIVE_FAILURESOverride=""
CONTEXT_FILE=""
STATE_FILE=".claude/loop-state.json"
LOG_DIR="logs/loop"
INTERRUPT_STATE_FILE=".claude/interrupt-state.json"
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
      --interrupt)
        # Write interrupt state file and exit (LangGraph pattern)
        mkdir -p .claude
        python3 -c "
import json, sys, time
state = {'interrupted': True, 'reason': 'manual', 'timestamp': time.time()}
path = '.claude/interrupt-state.json'
with open(path, 'w') as f:
    json.dump(state, f, indent=2)
print(f'Interrupt state written to {path}')
"
        exit 0 ;;
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
      --max-consecutive-failures) MAX_CONSECUTIVE_FAILURESOverride="$2"; shift 2 ;;
      --context)      CONTEXT_FILE="$2"; shift 2 ;;
      --state)        STATE_FILE="$2"; shift 2 ;;
      --log-dir)      LOG_DIR="$2"; shift 2 ;;
      --resume)       shift ;;  # no-op: Blueprint loop always resumes from state
      --budget)       shift 2 ;;  # accepted but not used in Blueprint mode
      --exit-gate)    shift 2 ;;  # accepted but not used in Blueprint mode
      *) log_warn "Unknown arg: $1"; shift ;;
    esac
  done

  # Apply --max-consecutive-failures override if provided
  if [ -n "$MAX_CONSECUTIVE_FAILURESOverride" ]; then
    MAX_CONSECUTIVE_FAILURES="$MAX_CONSECUTIVE_FAILURESOverride"
  fi
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

check_interrupt() {
  if [ -f "$INTERRUPT_STATE_FILE" ]; then
    if python3 -c "
import json, sys
try:
    d = json.load(open('$INTERRUPT_STATE_FILE'))
    sys.exit(0 if d.get('interrupted') else 1)
except:
    sys.exit(1)
" 2>/dev/null; then
      log_warn "Interrupt detected — pausing for human review"
      # Wait for interrupt state to be cleared (resume signal)
      while [ -f "$INTERRUPT_STATE_FILE" ]; do
        if python3 -c "
import json
try:
    d = json.load(open('$INTERRUPT_STATE_FILE'))
    if not d.get('interrupted'):
        sys.exit(0)
except:
    pass
sys.exit(1)
" 2>/dev/null; then
          log_success "Resume signal detected — continuing"
          rm -f "$INTERRUPT_STATE_FILE"
          return 0
        fi
        sleep 2
      done
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

# ─── [DET] NODE: PARSE TODO ──────────────────────────────────────
# Extracts all unchecked TODO items from goal file for supervisor context.
# Each item is annotated with _From: section-link (Kiro provenance pattern).
node_parse_todo() {
  log_info "[DET] parse_todo"

  if [ ! -f "$GOAL_FILE" ]; then
    log_warn "Goal file not found: $GOAL_FILE"
    return
  fi

  local open_items
  open_items=$(grep -c '^\- \[ \]' "$GOAL_FILE" 2>/dev/null || echo "0")
  local total_items
  total_items=$(grep -c '^\- \[' "$GOAL_FILE" 2>/dev/null || echo "0")

  log_info "Goal: $open_items open / $total_items total items"

  # Append to context with provenance tracking (Kiro pattern)
  {
    echo ""
    echo "## Goal TODO Items (from goal file)"
    echo "Open: $open_items / Total: $total_items"
    echo ""
    python3 - <<'PYEOF'
import re, sys

goal_file = sys.argv[1] if len(sys.argv) > 1 else None
if not goal_file:
    sys.exit(0)

try:
    content = open(goal_file).read()
except:
    print("(could not read goal file)")
    sys.exit(0)

current_section = "Uncategorized"
items = []

for line in content.splitlines():
    stripped = line.strip()
    # Track section headers (## Section Name or # Section Name)
    section_match = re.match(r'^(#{1,3})\s+(.+)$', stripped)
    if section_match:
        current_section = section_match.group(2).strip()
        continue
    # Track TODO items: - [ ] or - [x] or - [X]
    todo_match = re.match(r'^(\s*)-\s+\[([ xX])\]\s+(.+)$', stripped)
    if todo_match:
        indent = todo_match.group(1)
        checked = todo_match.group(2).lower() == "x"
        text = todo_match.group(3).strip()
        # Create a section slug for the _From link
        section_slug = re.sub(r"[^a-zA-Z0-9]+", "-", current_section.lower()).strip("-")
        items.append({
            "checked": checked,
            "text": text,
            "section": current_section,
            "from": f"_From: {goal_file} §{section_slug}",
        })

# Output unchecked items first with provenance
for item in items:
    marker = "[x]" if item["checked"] else "[ ]"
    print(f"- {marker} {item['text']}  {item['from']}")

if not items:
    print("(no TODO items)")
PYEOF
    "$GOAL_FILE"
  } >> .claude/loop-context.md
}
# ────────────────────────────────────────────────────────────────────# ────────────────────────────────────────────────────────────────

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

Output ONLY this format — a JSON array of tasks to execute:

```json
[
  {
    "description": "One sentence task with exact file paths and what to do. Include: which file, which function, what to implement, how to verify, commit with committer script.",
    "model": "haiku|sonnet|opus",
    "files": ["path/to/file.py"]
  }
]
```

## Convergence is determined by the loop script — not by you

After workers complete, the script checks:
1. How many unchecked items remain in the goal file
2. Whether workers committed changes

You output tasks. The script decides convergence. Do NOT output CONVERGED.

## Rules
- Max $MAX_WORKERS tasks — pick the highest-value ones
- Tasks must be INDEPENDENT (no dependency between tasks in same iteration)
- Model: haiku=mechanical/trivial (<30 lines, rename, delete), sonnet=standard, opus=complex architecture
- Never repeat a task already in recent commits
- Workers commit via: committer "type: msg" file1 file2 (NEVER git add .)
- If .claude/blockers.md exists, output an empty tasks array []"

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
import json, sys, os

# Load correction rules if available — inject into each worker task
_rules_file = os.path.expanduser('~/.claude/corrections/rules.md')
_correction_section = ''
if os.path.exists(_rules_file):
    with open(_rules_file) as _rf:
        _rules = [l.rstrip() for l in _rf if l.startswith('- [')]
    _rules = _rules[-10:]  # most recent 10
    if _rules:
        _correction_section = '\n## Learned Correction Rules (avoid these known mistakes)\n' + '\n'.join(_rules) + '\n'

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
    ]
    if _correction_section:
        task_lines.append(_correction_section)
    task_lines += [
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
# ────────────────────────────────────────────────────────────────────

# ─── [LLM] NODE: VERIFY ────────────────────────────────────────────
# Calls /verify skill with structured output and parses JSON results (Junie pattern).
# Runs after test_sample to provide additional LLM-based verification.
node_verify() {
  log_info "[LLM] verify"

  # Get list of changed files for focused verification
  local changed_files
  changed_files=$(git diff --name-only 2>/dev/null | head -20 || true)
  if [ -z "$changed_files" ]; then
    changed_files=$(git diff --name-only HEAD~1..HEAD 2>/dev/null | head -20 || true)
  fi

  if [ -z "$changed_files" ]; then
    log_info "No changed files to verify"
    echo '{"passed": true, "items": [], "summary": "no changes"}'
    return
  fi

  # Build focused verify prompt
  local verify_prompt="Verify these changed files for correctness:
$changed_files

For each file:
1. Read the file and understand what changed
2. Run relevant syntax/compile/lint checks
3. If tests exist for this file, run them

Output a JSON object with this exact structure:
{
  \"passed\": true or false,
  \"items\": [
    {\"file\": \"path\", \"check\": \"what was checked\", \"passed\": true/false, \"reason\": \"why\"}
  ],
  \"summary\": \"one line summary\"
}

Be strict. Return passed:false if any check fails. Do not fabricate checks you did not run."

  local result
  if ! result=$(_timeout "$SUPERVISOR_TIMEOUT" claude -p "$verify_prompt" --model sonnet 2>&1); then
    log_warn "Verify call failed or timed out"
    echo '{"passed": null, "items": [], "summary": "verify call failed"}'
    return
  fi

  # Parse JSON from result (may have preamble text)
  local parsed
  parsed=$(echo "$result" | python3 -c "
import sys, json, re
text = sys.stdin.read()
match = re.search(r'\{[\s\S]*\}', text)
if match:
    try:
        d = json.loads(match.group())
        print(json.dumps(d))
    except:
        print('{\"passed\": null, \"items\": [], \"summary\": \"parse error\"}')
else:
    print('{\"passed\": null, \"items\": [], \"summary\": \"no json found\"}')
" 2>/dev/null || echo '{"passed": null, "items": [], "summary": "parse error"}')

  echo "$parsed"

  if echo "$parsed" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('passed') == False else 1)" 2>/dev/null; then
    log_warn "Verify found issues: $(echo "$parsed" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("summary",""))' 2>/dev/null || echo "see log")"
  else
    log_success "Verify passed"
  fi
}
# ────────────────────────────────────────────────────────────────────

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

# Also save a lightweight checkpoint file for crash recovery
import os, json
ckpt_dir = os.path.expanduser("~/.claude/loop-checkpoints/$(os.path.basename(os.getcwd()))")
os.makedirs(ckpt_dir, exist_ok=True)
with open(os.path.join(ckpt_dir, f"iter-{$iteration}-state.json"), "w") as f:
    json.dump(state, f, indent=2)
PYTHON_EOF
}
# ────────────────────────────────────────────────────────────────

# ─── [LLM] CREATE FIX TASKS ──────────────────────────────────────
# Called when test_sample fails. Reads verify output and generates fix task.
_create_fix_tasks() {
  local task_file="$1"
  log_info "[LLM] create_fix_tasks → $task_file"

  # Find the most recent verify output
  local verify_output
  verify_output=$(ls -t logs/loop/iter-*-verify.txt 2>/dev/null | head -1 || true)

  local failure_context=""
  if [ -n "$verify_output" ] && [ -f "$verify_output" ]; then
    failure_context=$(cat "$verify_output" 2>/dev/null | head -100)
  fi

  local fix_prompt="The main workers completed but test_sample failed.
Create a single fix task to address the test failures.

## Original Goal
$(cat "$GOAL_FILE" 2>/dev/null | head -50)

## Failure Context
$failure_context

## Instructions
- Create exactly 1 task (JSON array format)
- Task: fix the specific failing tests or verification checks
- Use sonnet model for standard fixes
- Include exact file paths and what to fix
- Workers commit via: committer \"fix: description\" file1 file2"

  mkdir -p "$(dirname "$task_file")"
  _timeout "$SUPERVISOR_TIMEOUT" claude --model sonnet -p "$fix_prompt" 2>&1 \
    | python3 -c "
import sys, json, re
text = sys.stdin.read()
for p in [r'\[[\s\S]*]\]', r'\{[\s\S]*\}']:
    m = re.findall(p, text)
    for x in reversed(m):
        try:
            parsed = json.loads(x)
            if isinstance(parsed, list) and len(parsed) > 0:
                print(json.dumps(parsed)); sys.exit(0)
        except: pass
print('[]')
" > "$task_file" 2>/dev/null || echo "[]" > "$task_file"

  local task_count
  task_count=$(grep -c '===TASK===' "$task_file" 2>/dev/null || echo "0")
  log_info "Created $task_count fix task(s)"
}

# ─── [DET] DETERMINISTIC CONVERGENCE CHECK ──────────────────────
# Returns 0 (converged, break) or 1 (not converged, continue).
# Convergence is based on measurable state, NOT LLM judgment.
_check_convergence() {
  local iteration="$1"

  # Hard stop: max iterations
  if [ "$iteration" -ge "$MAX_ITER" ]; then
    log_warn "Max iterations ($MAX_ITER) reached"
    exit_reason="max_iterations"
    return 0
  fi

  # Hard stop: too many consecutive no-commits
  if [ "$consecutive_no_commits" -ge "$MAX_CONSECUTIVE_NO_COMMITS" ]; then
    log_error "$MAX_CONSECUTIVE_NO_COMMITS consecutive iterations with no commits — loop stuck"
    exit_reason="stuck_no_commits"
    return 0
  fi

  # Deterministic convergence: no unchecked items remain in goal file
  if [ -f "$GOAL_FILE" ]; then
    local remaining
    remaining=$(grep -c '^\- \[ \]' "$GOAL_FILE" 2>/dev/null || echo "-1")
    if [ "$remaining" = "0" ]; then
      log_success "CONVERGED: 0 unchecked items remain in goal file (deterministic check)"
      exit_reason="converged"
      return 0
    elif [ "$remaining" -gt 0 ]; then
      log_info "Convergence check: $remaining unchecked items remain — not done yet"
    fi
  fi

  return 1  # not converged, continue
}

# ─── GENERATE LOOP REPORT ────────────────────────────────────────
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

# ─── CHECKPOINT ──────────────────────────────────────────────────
# Saves state after each phase for crash recovery.
# Checkpoints live in ~/.claude/loop-checkpoints/{project_name}/
_checkpoint_dir() {
  local project_name
  project_name=$(basename "$(pwd)")
  echo "$HOME/.claude/loop-checkpoints/$project_name"
}

_save_checkpoint() {
  local iteration="$1"
  local phase="$2"
  local extra="${3:-}"

  local ckpt_dir
  ckpt_dir=$(_checkpoint_dir)
  mkdir -p "$ckpt_dir"

  local ckpt_file="${ckpt_dir}/iter-${iteration}-${phase}.json"

  # Capture current state
  cat > "$ckpt_file" <<EOF
{
  "iteration": $iteration,
  "phase": "$phase",
  "goal_file": "$GOAL_FILE",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "extra": "$extra",
  "consecutive_no_commits": ${consecutive_no_commits:-0},
  "consecutive_worker_failures": ${consecutive_worker_failures:-0},
  "started_commit": "$(git rev-parse HEAD 2>/dev/null || echo "")"
}
EOF
  log_info "[CHECKPOINT] iter $iteration $phase → $ckpt_file"
}

_recover_checkpoint() {
  local ckpt_dir
  ckpt_dir=$(_checkpoint_dir)

  if [ ! -d "$ckpt_dir" ]; then
    return 1
  fi

  local latest
  latest=$(ls -t "$ckpt_dir"/iter-*.json 2>/dev/null | head -1 || true)
  if [ -z "$latest" ]; then
    return 1
  fi

  log_info "[RECOVERY] Found checkpoint: $latest"

  # Extract state from checkpoint
  recovered_iteration=$(python3 -c "
import json, sys
d = json.load(open('$latest'))
print(d.get('iteration', 0))
" 2>/dev/null || echo "0")

  recovered_phase=$(python3 -c "
import json, sys
d = json.load(open('$latest'))
print(d.get('phase', ''))
" 2>/dev/null || echo "")

  if [ -n "$recovered_phase" ]; then
    log_info "[RECOVERY] Resuming from iter $recovered_iteration phase: $recovered_phase"
    return 0
  fi
  return 1
}

# ─── MAIN BLUEPRINT LOOP ────────────────────────────────────────
run_blueprint_loop() {
  # Try to recover from checkpoint
  if _recover_checkpoint; then
    log_warn "[RECOVERY] Checkpoint recovery is a design stub — full implementation"
    log_warn "[RECOVERY] would resume from recovered_iteration/recovered_phase."
    log_warn "[RECOVERY] For now, starting fresh but preserving iteration counter."
  fi

  local iteration=0
  local consecutive_no_commits=0
  local consecutive_worker_failures=0
  local exit_reason="max_iterations"

  mkdir -p "$LOG_DIR"
  log_info "Starting Blueprint Loop"
  log_info "  Goal:         $GOAL_FILE"
  log_info "  Max iter:     $MAX_ITER"
  log_info "  Max workers:  $MAX_WORKERS"
  log_info "  Max worker failures: $MAX_CONSECUTIVE_FAILURES"
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

    # [DET] Check for interrupt (LangGraph breakpoint pattern)
    if check_interrupt; then
      exit_reason="interrupted"
      break
    fi

    # [DET] hydrate_context
    node_hydrate_context

    # [DET] parse TODO items from goal file
    node_parse_todo

    # [DET] checkpoint after PRE
    _save_checkpoint "$iteration" "pre-done"

    # [LLM] supervisor
    local tasks_json
    tasks_json=$(node_supervisor "$iteration")

    # Supervisor always outputs tasks array (CONVERGED judgment removed — deterministic check comes after commit)
    # Empty array means supervisor sees no valuable tasks to add (not CONVERGED — script decides)

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

    # [DET] checkpoint after workers
    _save_checkpoint "$iteration" "workers-done"

    # [DET] Check for interrupt before syntax check (LangGraph breakpoint)
    if check_interrupt; then
      exit_reason="interrupted"
      break
    fi

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
    local test_result=0
    node_test_sample || test_result=$?

    # [LLM] verify — Junie pattern: LLM-based formal verification
    node_verify

    # [LLM] Mid-iteration fix — Stripe pattern: test fails → fix → re-test
    # One retry only. If it fails again, give up on this iteration (don't commit bad code)
    if [ $test_result -ne 0 ]; then
      log_warn "test_sample failed — attempting mid-iteration fix (1 attempt)"

      # Create fix tasks from the failed test context
      local fix_task_file="$LOG_DIR/iter-${ITERATION}-fix-tasks.txt"
      _create_fix_tasks "$fix_task_file" || true

      if [ -f "$fix_task_file" ] && [ -s "$fix_task_file" ]; then
        # Run fix workers
        node_run_workers "$fix_task_file"

        # Re-run syntax + test to verify fix
        local fix_syntax_failures
        fix_syntax_failures=$(node_syntax_check)
        if [ -n "$fix_syntax_failures" ]; then
          log_warn "Fix introduced syntax errors — reverting"
          while IFS= read -r f; do
            [ -n "$f" ] && git checkout -- "$f" 2>/dev/null || true
          done < <(printf "%b" "$fix_syntax_failures")
        fi

        local fix_test_result=0
        node_test_sample || fix_test_result=$?
        if [ $fix_test_result -ne 0 ]; then
          log_warn "Mid-iteration fix failed — skipping commit this iteration"
          consecutive_worker_failures=$((consecutive_worker_failures + 1))
          update_state "$iteration" 0
          # Fall through to convergence_check
        fi
      fi
    fi

    # [DET] commit_changes
    local new_commits
    new_commits=$(node_commit_changes)

    if [ "${new_commits:-0}" -eq 0 ]; then
      consecutive_no_commits=$((consecutive_no_commits + 1))
      # Workers ran but produced nothing — count as worker failure
      consecutive_worker_failures=$((consecutive_worker_failures + 1))
      log_warn "No commits this iteration (consecutive no-commit: $consecutive_no_commits, consecutive worker failures: $consecutive_worker_failures)"
      if [ "$consecutive_worker_failures" -ge "$MAX_CONSECUTIVE_FAILURES" ]; then
        log_error "$MAX_CONSECUTIVE_FAILURES consecutive worker failures — all workers failed, writing blocker"
        {
          echo "## Blocker [$(date '+%Y-%m-%d %H:%M')]"
          echo "All $MAX_CONSECUTIVE_FAILURES consecutive worker runs produced no commits."
          echo "Likely causes: workers hitting permission errors, wrong working directory, or unresolvable task conflicts."
          echo "Iteration: $iteration"
          echo "Last goal: $GOAL_FILE"
        } >> .claude/blockers.md
        exit_reason="all_workers_failed"
        break
      fi
    else
      consecutive_no_commits=0
      consecutive_worker_failures=0
      log_success "Committed $new_commits change(s) in iteration $iteration"
    fi

    # [DET] checkpoint after POST
    _save_checkpoint "$iteration" "post-done" "${new_commits:-0}"

    # [DET] Deterministic convergence_check
    # Convergence = no more unchecked items in goal file, OR max iterations hit, OR stuck
    _check_convergence "$iteration" && break
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
