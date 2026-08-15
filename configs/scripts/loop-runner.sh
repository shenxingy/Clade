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
#   loop-runner.sh --help
#
# Options:
#   --model MODEL         supervisor model (default: claude-sonnet-4-6)
#   --worker-model MODEL  worker model (default: same as supervisor)
#   --max-iter N          max iterations (default: 10)
#   --max-workers N       max parallel workers (default: 4)
#   --supervisor-timeout N  supervisor LLM timeout in seconds (default: 300;
#                           raise further for very large goals)
#   --context FILE        pre-generated context file (passed to supervisor)
#   --state FILE          state file (default: .claude/loop-state.json)
#   --log-dir DIR         log directory (default: logs/loop)
#   --dry-run             preview plan, no claude calls (see run_dry_run_preview)
#   --resume              resume an identity-matched interrupted run

set -euo pipefail

# Allow nested claude calls from within a Claude Code session
unset CLAUDECODE 2>/dev/null || true
# ─── CROSS-PLATFORM HELPERS ─────────────────────────────────────────
# Resolve a companion script (run-tasks.sh etc.) next to THIS copy of
# loop-runner.sh first — repo checkouts and CI have no deployed
# ~/.claude/scripts, and a repo-run loop must not silently execute a stale
# deployed runner (deploy-gap). Falls back to the deployed location.
_SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_sibling_script() {
  if [ -f "$_SELF_DIR/$1" ]; then
    echo "$_SELF_DIR/$1"
  else
    echo "$HOME/.claude/scripts/$1"
  fi
}

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
# ─── PURE-JUDGE CONTAINMENT ─────────────────────────────────────
# Nested `claude -p` calls whose stdout is PARSED (supervisor JSON task
# array, verify JSON, fix-task JSON) must NOT load user settings: a
# prompt-type Stop hook in ~/.claude/settings.json prints its own
# {"ok":true} decision as the -p result, so the supervisor extracts 0
# tasks and verify parses garbage (see commits 386a862 / a6d076a).
# WORKER invocations (node_run_workers → run-tasks*.sh) and the syntax
# FIXER (node_fix_syntax — edits files, commits) deliberately KEEP full
# user settings: commit-discipline hooks are core value.
readonly PURE_JUDGE_FLAGS=(--setting-sources "" --disallowed-tools Edit,Write,Bash)
# ────────────────────────────────────────────────────────────────
# ─── BLUEPRINT HARD LIMITS ──────────────────────────────────────
readonly MAX_CONSECUTIVE_NO_COMMITS=3   # consecutive empty iters → force stop
readonly MAX_CONSECUTIVE_FAILURES=3     # consecutive worker failures (ran but no commits) → force stop
readonly SYNTAX_CHECK_TIMEOUT=30        # syntax check timeout (seconds)
readonly TEST_SAMPLE_TIMEOUT=120        # verify_cmd timeout (seconds)
# NOT readonly: override with --supervisor-timeout N. 120s was the default
# through two stuck runs (align-elites 3×120s; a 10-requirement goal died
# supervisor_failed on iter 1). Planning cost scales with goal size — a measured
# 10KB prompt takes ~76s on sonnet — so 120s had no headroom. The flag existed
# both times and solved neither; the default is the fix.
SUPERVISOR_TIMEOUT=300                  # supervisor LLM call timeout (seconds)
readonly WORKER_TIMEOUT=600             # per-worker timeout (seconds)
readonly MAX_FIX_ATTEMPTS=1             # syntax fix: max 1 LLM call per iter
# ────────────────────────────────────────────────────────────────

# ─── DEFAULTS ───────────────────────────────────────────────────
GOAL_FILE=""
SUPERVISOR_MODEL="claude-sonnet-4-6"
WORKER_MODEL="claude-sonnet-4-6"
MAX_ITER=10
MAX_WORKERS=4
# Wall-clock bound. Iteration count is NOT a time bound — a single iteration
# runs until its workers finish, and worker work is unbounded, so `--max-iter 10`
# happily becomes an overnight run. `/start` exists to run unattended, which is
# exactly when nobody is watching the spend. 0 disables.
MAX_RUNTIME_MIN=480
# Overridable so the wall-clock branch is testable without a test that sleeps a
# minute, and so a caller resuming a run can choose to carry the ORIGINAL start
# time forward rather than silently granting a fresh 8 hours on every --resume.
LOOP_START_EPOCH="${LOOP_START_EPOCH:-$(date +%s)}"
MAX_CONSECUTIVE_FAILURESOverride=""
CONTEXT_FILE=""
STATE_FILE=".claude/loop-state.json"
LOG_DIR="logs/loop"
INTERRUPT_STATE_FILE=".claude/interrupt-state.json"
ITERATION=0
ITERATION_START_COMMIT=""
DRY_RUN=false
RESUME=false
# ────────────────────────────────────────────────────────────────

# ─── LOGGING ────────────────────────────────────────────────────
# Console copies go to STDERR (like log_error): several node functions return
# values via stdout command substitution — tasks_json=$(node_supervisor ...),
# task_file=$(node_score_and_write ...), new_commits=$(node_commit_changes) —
# and stdout log lines were captured into those values, corrupting the JSON
# task pipeline (supervisor tasks never parsed → every iteration "no tasks").
log_info()    { echo "[$(date '+%H:%M:%S')] [INFO]  $*" | tee -a "$LOG_DIR/loop.log" >&2; }
log_success() { echo "[$(date '+%H:%M:%S')] [OK]    $*" | tee -a "$LOG_DIR/loop.log" >&2; }
log_warn()    { echo "[$(date '+%H:%M:%S')] [WARN]  $*" | tee -a "$LOG_DIR/loop.log" >&2; }
log_error()   { echo "[$(date '+%H:%M:%S')] [ERROR] $*" | tee -a "$LOG_DIR/loop.log" >&2; }
# ────────────────────────────────────────────────────────────────
# ─── PARSE ARGS ─────────────────────────────────────────────────
# parse_args + print_usage live in loop_args.sh (this file sits at the
# 1500-line ceiling from CLAUDE.md Code Rules). Sourced, so they set the
# same globals here as when they were inline.
# shellcheck source=loop_args.sh
. "$(_sibling_script loop_args.sh)"

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
except Exception:
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
except Exception:
    sys.exit(1)
" 2>/dev/null; then
      log_warn "Interrupt detected — pausing for human review"
      # Wait for interrupt state to be cleared (resume signal)
      while [ -f "$INTERRUPT_STATE_FILE" ]; do
        if python3 -c "
import json, sys
try:
    d = json.load(open('$INTERRUPT_STATE_FILE'))
    if not d.get('interrupted'):
        sys.exit(0)
except Exception:
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
except Exception:
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

  local identity_tsv
  identity_tsv=$(python3 "$(_sibling_script git_identity.py)" check --repo . --format tsv 2>&1) || { log_error "$identity_tsv"; return 1; }
  IFS=$'\t' read -r GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL <<< "$identity_tsv"
  export GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
  log_success "Pre-flight OK"
}
# ────────────────────────────────────────────────────────────────

# ─── [DET] NODE: HYDRATE CONTEXT ────────────────────────────────
# Generates .claude/loop-context.md with git log + relevant files. No LLM calls.
node_hydrate_context() {
  log_info "[DET] hydrate_context → .claude/loop-context.md"
  mkdir -p .claude

  {
    # Surface a failing baseline first so the supervisor repairs before adding work.
    if [ -f .claude/health-warning.md ]; then
      cat .claude/health-warning.md
      echo ""
    fi
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

    # Include pre-generated context if provided.
    # The whole block redirects into .claude/loop-context.md, so a CONTEXT_FILE
    # pointing at that same path makes cat read its own output target: cat exits
    # non-zero, and under `set -e` the loop dies before the supervisor ever runs.
    # The skill's own documented invocation passes exactly that path, so compare
    # resolved paths and skip the self-include instead of trusting the caller.
    if [ -n "$CONTEXT_FILE" ] && [ -f "$CONTEXT_FILE" ] \
       && [ "$(readlink -f "$CONTEXT_FILE")" != "$(readlink -f .claude/loop-context.md)" ]; then
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
  open_items=$(grep -c '^\- \[ \]' "$GOAL_FILE" 2>/dev/null || true)
  open_items=${open_items:-0}
  local total_items
  total_items=$(grep -c '^\- \[' "$GOAL_FILE" 2>/dev/null || true)
  total_items=${total_items:-0}

  log_info "Goal: $open_items open / $total_items total items"

  # Append to context with provenance tracking (Kiro pattern)
  {
    echo ""
    echo "## Goal TODO Items (from goal file)"
    echo "Open: $open_items / Total: $total_items"
    echo ""
    python3 - "$GOAL_FILE" <<'PYEOF'
import re, sys

goal_file = sys.argv[1] if len(sys.argv) > 1 else None
if not goal_file:
    sys.exit(0)

try:
    content = open(goal_file).read()
except Exception:
    print("(could not read goal file)")
    sys.exit(0)

current_section = "Uncategorized"
items = []

for line_no, line in enumerate(content.splitlines(), 1):
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
            "line": line_no,
            "text": text,
            "section": current_section,
            "from": f"_From: {goal_file} §{section_slug}",
        })

# Output unchecked items first with provenance
for item in items:
    marker = "[x]" if item["checked"] else "[ ]"
    print(f"- {marker} {item['text']}  _Line: {item['line']}  {item['from']}")

if not items:
    print("(no TODO items)")
PYEOF
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

  # Use unquoted heredoc: $var/$(cmd) expand, but literal ``` must be \`\`\`
  # and inner " do NOT toggle string boundaries (heredoc, not double-quoted string).
  # Prior double-quoted form collapsed to "" because of literal ``` + inner "
  # being parsed as bash command substitution + string-boundary toggle.
  local supervisor_prompt
  supervisor_prompt=$(cat <<EOF
You are the supervisor for iteration $iteration of an autonomous improvement loop.
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

\`\`\`json
[
  {
    "description": "One sentence task with exact file paths and what to do. Include: which file, which function, what to implement, how to verify, commit with committer script.",
    "model": "haiku|sonnet|opus",
    "files": ["path/to/file.py"],
    "goal_items": [{"line": 12, "text": "exact unchecked goal item this task fully satisfies"}]
  }
]
\`\`\`

## Convergence is determined by the loop script — not by you

After workers complete, the script checks:
1. How many unchecked items remain in the goal file
2. Whether workers committed changes

You output tasks. The script decides convergence. Do NOT output CONVERGED.

## Rules
- Max $MAX_WORKERS tasks — pick the highest-value ones
- Tasks must be INDEPENDENT (no dependency between tasks in same iteration)
- Model: haiku=mechanical/trivial (<30 lines, rename, delete), sonnet=standard, opus=complex architecture
- Bind only goal items the task fully satisfies, using the exact _Line and text from context; use [] for supporting work
- Never repeat a task already in recent commits
- Workers commit via: committer "type: msg" file1 file2 (NEVER git add .)
- If .claude/blockers.md exists, output an empty tasks array []
EOF
)

  local result supervisor_rc=0 detail
  result=$(_timeout "$SUPERVISOR_TIMEOUT" claude --model "$SUPERVISOR_MODEL" \
    "${PURE_JUDGE_FLAGS[@]}" --tools "" -p "$supervisor_prompt" 2>&1) || supervisor_rc=$?
  printf '%s\n' "$result" > "$LOG_DIR/iter-${iteration}-supervisor.raw.txt"
  if [ "$supervisor_rc" -ne 0 ]; then
    detail=$(printf '%s\n' "$result" | tail -n 1)
    # 124 = timeout(1)'s kill code. Unnamed, this printed "exit 124: Execution
    # error" — the CLI's last line, which never mentions a timeout and sends you
    # debugging the model instead of the budget.
    if [ "$supervisor_rc" -eq 124 ]; then
      log_error "Supervisor timed out after ${SUPERVISOR_TIMEOUT}s while planning (no plan produced)."
      log_error "  Planning cost scales with goal size. Retry with a larger budget:"
      log_error "    --supervisor-timeout $((SUPERVISOR_TIMEOUT * 2))"
      log_error "  or split the goal into fewer requirements. CLI said: ${detail:-none}"
    else
      log_error "Supervisor call failed (exit $supervisor_rc): ${detail:-no output}"
    fi
    echo "[]"
    return "$supervisor_rc"
  fi

  # Extract JSON from result (supervisor may include preamble text).
  echo "$result" \
    | python3 "$(_sibling_script loop_json.py)" --max-tasks "$MAX_WORKERS" \
      2>/dev/null \
    || echo "[]"
}
# ────────────────────────────────────────────────────────────────

# ─── [DET] NODE: SCORE AND WRITE TASKS ──────────────────────────
# Scores tasks, writes task file in ===TASK=== format. No LLM calls.
node_score_and_write() {
  local tasks_json="$1"
  local task_file="${2:-$LOG_DIR/iter-${ITERATION}-tasks.txt}"

  log_info "[DET] score_and_write"

  # Check if tasks is empty array or invalid
  local task_count
  task_count=$(echo "$tasks_json" | python3 -c "
import json, sys
try:
    t = json.load(sys.stdin)
    print(len(t) if isinstance(t, list) else 0)
except Exception:
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
    goal_items = task.get('goal_items', [])
    if not isinstance(goal_items, list):
        goal_items = []
    goal_items = [item for item in goal_items if isinstance(item, dict)
                  and isinstance(item.get('line'), int) and item['line'] > 0
                  and isinstance(item.get('text'), str) and item['text'].strip()]

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
        'goal_items_json: ' + json.dumps(goal_items, separators=(',', ':')),
        '---',
        desc,
        '',
    ]
    if _correction_section:
        task_lines.append(_correction_section)
    task_lines += [
        '## Close the loop (required before finishing)',
        '- Verify your changes pass syntax/compile checks',
        '- Run test/build/verify commands via quiet-run (bash ~/.claude/scripts/quiet-run.sh <cmd>) when installed — full output goes to .claude/logs/, only the verdict + failure tail enters your context, exit code is mirrored',
        '- Re-read every file you changed — catch logic bugs, null cases, missing imports',
        '- Use committer \"type: msg\" file1 file2 to commit (NEVER git add .)',
        '- Substantive commits (feat/fix/refactor/perf) need a 2-4 line body after the subject: mechanism, hazard avoided or root cause, constraint honored — committer accepts multi-line messages',
        '- Do NOT modify the goal file',
        '',
        '## Friction Log',
        'If a tool or harness feature fights you (wrong output, unexpected workaround needed, blocks progress),',
        'append ≤2 lines to BRAINSTORM.md under `## [AI] Friction Log`:',
        '  [YYYY-MM-DD] tool: <what happened> / workaround: <what you did>',
        'Skip if nothing noteworthy.',
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
  local written_count
  written_count=$(grep -c '===TASK===' "$task_file" 2>/dev/null || true)
  log_info "Wrote ${written_count:-0} task(s) to $task_file"
  echo "$task_file"
}
# ────────────────────────────────────────────────────────────────

# ─── [LLM-PAR] NODE: RUN WORKERS ────────────────────────────────
# Runs tasks in parallel using run-tasks-parallel.sh or run-tasks.sh
node_run_workers() {
  local task_file="$1"
  WORKERS_SUCCEEDED=false
  log_info "[LLM-PAR] workers (task_file=$task_file)"

  if [ ! -f "$task_file" ] || [ ! -s "$task_file" ]; then
    log_warn "Task file empty or missing: $task_file"
    return
  fi

  local task_count
  task_count=$(grep -c '===TASK===' "$task_file" 2>/dev/null || true)
  log_info "Executing $task_count task(s) with up to $MAX_WORKERS workers"

  # Clean up leftover worktrees from previous iterations
  git worktree prune 2>/dev/null || true

  local worker_total_timeout=$(( WORKER_TIMEOUT * task_count + 60 ))

  # CLADE_WORKER_TASK_ID → committer.sh appends attribution trailers
  # (Co-Authored-By + X-Clade-Task) so loop commits segment as agent-authored.
  # Workers keep user hooks deliberately; pure judges drop them — see PURE_JUDGE_FLAGS.
  if [ "$MAX_WORKERS" -gt 1 ]; then
    if CLADE_WORKER_TASK_ID="loop-iter${ITERATION}" MAX_WORKERS="$MAX_WORKERS" \
      _timeout "$worker_total_timeout" \
      bash "$(_sibling_script run-tasks-parallel.sh)" "$task_file" 2>&1 \
      | tee -a "$LOG_DIR/loop.log"; then WORKERS_SUCCEEDED=true
    else log_warn "Workers returned non-zero exit (some tasks may have failed)"; fi
  else
    # --keep-logs: run-tasks.sh's success auto-cleanup otherwise deletes the
    # caller-owned iter task file + worker logs (the loop's audit trail, and
    # what tests/test-loop-real.sh asserts). run-tasks-parallel.sh never
    # garbage-collects them — keep both paths consistent.
    if CLADE_WORKER_TASK_ID="loop-iter${ITERATION}" \
      _timeout "$worker_total_timeout" \
      bash "$(_sibling_script run-tasks.sh)" "$task_file" --keep-logs 2>&1 \
      | tee -a "$LOG_DIR/loop.log"; then WORKERS_SUCCEEDED=true
    else log_warn "Worker returned non-zero exit"; fi
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

  # Fixer edits files + commits → keeps user hooks deliberately (no PURE_JUDGE_FLAGS);
  # its stdout is only tee'd to the log, never parsed.
  _timeout "$SUPERVISOR_TIMEOUT" claude --model "$SUPERVISOR_MODEL" -p "$fix_prompt" \
    2>&1 | tee -a "$LOG_DIR/loop.log" || {
      log_warn "Fix syntax attempt failed or timed out"
    }
}
# ────────────────────────────────────────────────────────────────

# ─── Shared: read verify_cmd from CLAUDE.md (YAML or inline label) ──
_read_verify_cmd() {
  local vc
  vc=$(grep -m1 'verify_cmd:' CLAUDE.md 2>/dev/null | sed 's/.*verify_cmd:[[:space:]]*//' || true)
  if [ -z "$vc" ]; then
    vc=$(grep -m1 'Verify command:' CLAUDE.md 2>/dev/null | sed 's/.*Verify command:[[:space:]]*//' || true)
  fi
  printf '%s' "$vc"
}

# ─── #3: parse pytest-style "N failed" from verify output (best-effort) ──
# Echoes the failed+error count, or nothing if the output isn't parseable.
# Always exits 0 (pipefail-safe: grep returns non-zero on no match).
_parse_failed_count() {
  local out="$1" n
  n=$(printf '%s' "$out" | grep -oE '[0-9]+ (failed|error)' 2>/dev/null \
        | grep -oE '^[0-9]+' 2>/dev/null | awk '{s+=$1} END{if(NR)print s}') || true
  # No failure tokens, but a recognizable test summary → 0 failed (suite is green).
  if [ -z "$n" ] && printf '%s' "$out" | grep -qE '[0-9]+ passed'; then
    n=0
  fi
  printf '%s' "$n"
}

# ─── [DET] NODE: HEALTH CHECK (Anthropic: repair broken baseline first) ──
# Runs the verify_cmd at the START of an iteration so the supervisor repairs a
# broken baseline before planning new work. Iteration 1 runs fresh; later
# iterations reuse the prior iteration's test_sample result (no double run).
# On failure, writes .claude/health-warning.md, which node_hydrate_context folds
# into the supervisor's context.
node_health_check() {
  local verify_cmd; verify_cmd=$(_read_verify_cmd)
  rm -f .claude/health-warning.md
  if [ -z "$verify_cmd" ]; then
    return 0  # no verify_cmd → nothing to check
  fi

  local broken=0 out=""
  if [ "${ITERATION:-1}" -le 1 ]; then
    log_info "[DET] health_check (baseline, iter 1)"
    out=$(_timeout "$TEST_SAMPLE_TIMEOUT" bash -c "$verify_cmd" 2>&1) || broken=1
  else
    # Reuse the previous iteration's result — avoids a second full test run.
    [ "${LAST_TEST_RESULT:-0}" -ne 0 ] && broken=1
    out="${LAST_TEST_OUTPUT:-}"
  fi

  if [ "$broken" -ne 0 ]; then
    mkdir -p .claude
    {
      echo "## ⚠️ BASELINE HEALTH: FAILING"
      echo "The project's verify_cmd is currently failing. **Repair the broken"
      echo "baseline before planning any new feature work** (Anthropic harness lever)."
      echo '```'
      printf '%s\n' "$out" | tail -30
      echo '```'
    } > .claude/health-warning.md
    log_warn "[DET] health_check: baseline FAILING — supervisor will repair first"
  else
    log_success "[DET] health_check: baseline healthy"
  fi
  return 0
}
# ────────────────────────────────────────────────────────────────

# ─── [DET] NODE: TEST SAMPLE ────────────────────────────────────
# Runs the project's verify_cmd from CLAUDE.md. No LLM calls.
node_test_sample() {
  log_info "[DET] test_sample"

  local verify_cmd; verify_cmd=$(_read_verify_cmd)
  if [ -z "$verify_cmd" ]; then
    log_info "No verify_cmd in CLAUDE.md — skipping test sample"
    return 0
  fi

  log_info "Running verify: $verify_cmd"
  local tmp_out rc=0
  tmp_out=$(mktemp "${TMPDIR:-/tmp}/loop-verify.XXXXXX")
  _timeout "$TEST_SAMPLE_TIMEOUT" bash -c "$verify_cmd" >"$tmp_out" 2>&1 || rc=$?
  tee -a "$LOG_DIR/loop.log" < "$tmp_out" >&2

  # Carry the result forward so the next iteration's health_check can reuse it
  # rather than running the whole suite a second time.
  LAST_TEST_OUTPUT=$(cat "$tmp_out")
  LAST_TEST_RESULT=$rc

  # #3: per-iteration fix-rate — log the failed-count delta vs the prior iteration.
  local cur_failed; cur_failed=$(_parse_failed_count "$LAST_TEST_OUTPUT")
  if [ -n "$cur_failed" ]; then
    if [ -n "${PREV_FAILED:-}" ]; then
      local repaired=$((PREV_FAILED - cur_failed))
      printf '%s\t%s\t%s\t%s\n' "${ITERATION:-0}" "$PREV_FAILED" "$cur_failed" "$repaired" \
        >> "$LOG_DIR/fix-rate.tsv"
      log_info "[METRIC] iter ${ITERATION:-0} fix-rate: failed ${PREV_FAILED}→${cur_failed} (repaired ${repaired})"
    fi
    PREV_FAILED=$cur_failed
  fi

  rm -f "$tmp_out"
  if [ "$rc" -eq 0 ]; then
    log_success "Test sample passed"
  else
    log_warn "Test sample failed (workers may have introduced issues — continuing)"
  fi
  return "$rc"
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
  changed_files=$({
    git diff --name-only 2>/dev/null || true
    if [ -n "${ITERATION_START_COMMIT:-}" ] \
       && [ "$(git rev-parse HEAD 2>/dev/null || true)" != "$ITERATION_START_COMMIT" ]; then
      git diff --name-only "$ITERATION_START_COMMIT"..HEAD 2>/dev/null || true
    fi
  } | awk 'NF && !seen[$0]++' | head -20)

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
  if ! result=$(_timeout "$SUPERVISOR_TIMEOUT" claude -p "$verify_prompt" --model sonnet "${PURE_JUDGE_FLAGS[@]}" 2>&1); then
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
    except Exception:
        print('{\"passed\": null, \"items\": [], \"summary\": \"parse error\"}')
else:
    print('{\"passed\": null, \"items\": [], \"summary\": \"no json found\"}')
" 2>/dev/null || echo '{"passed": null, "items": [], "summary": "parse error"}')

  echo "$parsed"

  if echo "$parsed" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('passed') is False else 1)" 2>/dev/null; then
    log_warn "Verify found issues: $(echo "$parsed" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("summary",""))' 2>/dev/null || echo "see log")"
  elif _verify_passed "$parsed"; then
    log_success "Verify passed"
  else
    log_warn "Verify unavailable or unparseable"
  fi
}

_verify_passed() {
  printf '%s' "$1" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("passed") is True else 1)' 2>/dev/null
}

node_reconcile_goal() {
  local marked
  if ! marked=$(python3 "$(_sibling_script loop_goal.py)" --goal "$GOAL_FILE" --task-file "$1"); then
    log_warn "Goal reconciliation refused; leaving checklist unchanged"
    return 1
  fi
  log_success "Coordinator reconciled $marked goal item(s)"
}
# ────────────────────────────────────────────────────────────────────

# ─── [DET] NODE: COMMIT CHANGES ─────────────────────────────────
# Commits all uncommitted changes via committer script. No LLM calls.
# Echoes the number of commits created by workers or the sweep.
node_commit_changes() {
  log_info "[DET] commit_changes"
  local committed=0
  if [ -n "${ITERATION_START_COMMIT:-}" ] && git merge-base --is-ancestor "$ITERATION_START_COMMIT" HEAD 2>/dev/null; then
    committed=$(git rev-list --count "$ITERATION_START_COMMIT"..HEAD 2>/dev/null || echo 0)
  fi

  # git status --porcelain sees modified, staged AND worker-CREATED untracked
  # files (git diff --name-only missed untracked entirely, so new files were
  # never swept). .gitignore is respected by porcelain. -uall lists untracked
  # files individually — without it an entirely-untracked directory collapses
  # to "dir/" and the per-file exclusions below cannot match. The loop's own
  # bookkeeping ($STATE_FILE, $LOG_DIR, .claude/) is excluded: update_state
  # dirties $STATE_FILE every iteration, so sweeping it would make every
  # iteration "commit something" and defeat the consecutive-no-commit stuck
  # detection. cut strips the 2-char status + space; sed handles renames
  # ("old -> new" keeps new) and strips porcelain quoting.
  local changed_files="" f
  local uncommitted=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    case "$f" in
      "${LOG_DIR%/}"/*|"$STATE_FILE"|.claude/*) continue ;;
    esac
    # Skip staged-then-deleted transients (run-tasks.sh checkpoints via
    # `git add -A`, cleanup then rm's the files — porcelain still lists the
    # phantom index entry and `git add` on the dead pathspec would abort the
    # whole commit). A path is real if it exists on disk, or is tracked in
    # HEAD (a genuine worker deletion, which git add stages correctly).
    if [ ! -e "$f" ] && ! git cat-file -e "HEAD:$f" 2>/dev/null; then
      continue
    fi
    changed_files="${changed_files}${f} "
    uncommitted=$((uncommitted + 1))
  done < <(git status --porcelain -uall 2>/dev/null | cut -c4- | sed -e 's/.* -> //' -e 's/^"\(.*\)"$/\1/')

  if [ "$uncommitted" -eq 0 ]; then
    log_info "No uncommitted changes"
    echo "$committed"
    return
  fi

  local files_to_commit
  files_to_commit="$changed_files"

  # Conventional-commit subject — committer's checks.sh CONVENTIONAL_RE rejects
  # a "loop:" type, which made every leftover commit fall into the log_warn
  # path. Loop context goes in the body instead.
  local commit_msg="chore: commit loop iteration $ITERATION leftover changes

Swept by loop-runner node_commit_changes: changes left uncommitted by
workers during iteration $ITERATION of goal $GOAL_FILE."

  if command -v committer &>/dev/null; then
    # shellcheck disable=SC2086
    # tee to stderr — this function's stdout is captured (new_commits=$(...))
    committer "$commit_msg" $files_to_commit 2>&1 | tee -a "$LOG_DIR/loop.log" >&2 || {
      log_warn "committer failed — changes remain uncommitted"
      return 1
    }
  else
    # Fallback: direct git commit. Mirror committer.sh semantics: clear any
    # pre-staged index first (run-tasks.sh checkpoints via `git add -A`, and
    # `git commit` would otherwise sweep that whole index in), then stage
    # ONLY the filtered file list.
    git restore --staged :/ 2>/dev/null || true
    # shellcheck disable=SC2086
    git add $files_to_commit
    git commit -m "$commit_msg" 2>&1 | tee -a "$LOG_DIR/loop.log" >&2 || {
      log_warn "git commit failed"
      return 1
    }
  fi

  committed=$(git rev-list --count "$ITERATION_START_COMMIT"..HEAD 2>/dev/null || echo 0)
  log_success "Committed $uncommitted file(s); iteration total is $committed commit(s)"
  echo "$committed"
}
# ────────────────────────────────────────────────────────────────

# ─── [DET] UPDATE STATE ─────────────────────────────────────────
update_state() {
  local iteration="$1"
  local commits="$2"
  mkdir -p "$(dirname "$STATE_FILE")"
  # Quoted heredoc + argv passthrough: bash leaves $(...) and $var alone,
  # python receives values via sys.argv. Prior unquoted heredoc tried to
  # bash-evaluate $(os.path.basename(os.getcwd())), silently corrupting
  # the checkpoint path.
  python3 - "$STATE_FILE" "$iteration" "$commits" "$GOAL_FILE" <<'PYTHON_EOF'
import json, os, sys

state_file = sys.argv[1]
iteration = int(sys.argv[2])
commits = int(sys.argv[3])
goal_file = sys.argv[4]

try:
    state = json.load(open(state_file)) if os.path.exists(state_file) else {}
except Exception:
    state = {}

# Don't overwrite a stop sentinel
if state.get('stop'):
    sys.exit(0)

state['iteration'] = iteration
state['commits_this_iter'] = commits
state['goal_file'] = goal_file
history = state.get('history', [])
history.append({'iter': iteration, 'commits': commits})
state['history'] = history[-20:]  # keep last 20
json.dump(state, open(state_file, 'w'), indent=2)
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
  local tasks_json
  tasks_json=$(
    _timeout "$SUPERVISOR_TIMEOUT" claude --model sonnet \
      "${PURE_JUDGE_FLAGS[@]}" -p "$fix_prompt" 2>&1 \
      | python3 "$(_sibling_script loop_json.py)" --require-nonempty --max-tasks 1
  ) || tasks_json="[]"
  rm -f "$task_file"
  node_score_and_write "$tasks_json" "$task_file" >/dev/null

  local task_count
  task_count=$(grep -c '===TASK===' "$task_file" 2>/dev/null || true)
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

  # Hard stop: wall clock. Checked BETWEEN iterations, so it bounds how long a
  # run keeps starting new work — it cannot interrupt an iteration already in
  # flight. That is what the per-worker timeout in run-tasks-parallel.sh is for;
  # the two together are what make a run actually bounded.
  if [ "${MAX_RUNTIME_MIN:-0}" -gt 0 ]; then
    local elapsed_min=$(( ( $(date +%s) - LOOP_START_EPOCH ) / 60 ))
    if [ "$elapsed_min" -ge "$MAX_RUNTIME_MIN" ]; then
      log_warn "Wall-clock limit reached: ${elapsed_min}m ≥ ${MAX_RUNTIME_MIN}m (--max-runtime)"
      exit_reason="max_runtime"
      return 0
    fi
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
    remaining=$(grep -c '^\- \[ \]' "$GOAL_FILE" 2>/dev/null || true)
    remaining=${remaining:--1}
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

  # #3: per-iteration fix-rate summary (failed-test repairs over the run).
  local fixrate_summary=""
  if [ -f "$LOG_DIR/fix-rate.tsv" ]; then
    fixrate_summary=$(awk -F'\t' '{repaired+=$4} END{
      if(NR) printf "%d failed-tests repaired across %d measured iterations", repaired, NR}' \
      "$LOG_DIR/fix-rate.tsv")
    [ -n "$fixrate_summary" ] && log_info "  Fix-rate:     $fixrate_summary"
  fi
  log_info "═══════════════════════════════════════════════"

  # Write last-progress file for --status command
  mkdir -p "$LOG_DIR"
  {
    echo "Loop completed at $(date '+%Y-%m-%d %H:%M')"
    echo "Iterations: $total_iterations"
    echo "Exit: $exit_reason"
    echo "Goal: $GOAL_FILE"
    [ -n "$fixrate_summary" ] && echo "Fix-rate: $fixrate_summary"
  } > "$LOG_DIR/last-progress"
  return 0
}
# ────────────────────────────────────────────────────────────────

# ─── CHECKPOINT ──────────────────────────────────────────────────
_save_checkpoint() {
  local iteration="$1"
  local phase="$2"
  local extra="${3:-}"
  local ckpt_file
  ckpt_file=$(python3 "$(_sibling_script loop_checkpoint.py)" save \
    --goal "$GOAL_FILE" --iteration "$iteration" --phase "$phase" \
    --extra "$extra" --no-commits "${consecutive_no_commits:-0}" \
    --worker-failures "${consecutive_worker_failures:-0}" \
    --iteration-start-commit "$ITERATION_START_COMMIT")
  log_info "[CHECKPOINT] iter $iteration $phase → $ckpt_file"
}

_recover_checkpoint() {
  local recovered
  if ! recovered=$(python3 "$(_sibling_script loop_checkpoint.py)" recover \
      --goal "$GOAL_FILE" 2>&1); then
    log_error "[RECOVERY] $recovered"
    return 1
  fi
  RECOVERED_ITERATION=$(printf '%s' "$recovered" | python3 -c 'import json,sys; print(json.load(sys.stdin)["iteration"])')
  RECOVERED_PHASE=$(printf '%s' "$recovered" | python3 -c 'import json,sys; print(json.load(sys.stdin)["phase"])')
  RECOVERED_EXTRA=$(printf '%s' "$recovered" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("extra", ""))')
  RECOVERED_NO_COMMITS=$(printf '%s' "$recovered" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("consecutive_no_commits", 0))')
  RECOVERED_WORKER_FAILURES=$(printf '%s' "$recovered" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("consecutive_worker_failures", 0))')
  RECOVERED_START_COMMIT=$(printf '%s' "$recovered" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("iteration_start_commit", ""))')
  local ckpt_file
  ckpt_file=$(printf '%s' "$recovered" | python3 -c 'import json,sys; print(json.load(sys.stdin)["checkpoint_file"])')
  log_info "[RECOVERY] Resuming iteration $RECOVERED_ITERATION after $RECOVERED_PHASE → $ckpt_file"
}

_clear_checkpoints() {
  python3 "$(_sibling_script loop_checkpoint.py)" clear --goal "$GOAL_FILE"
}

# ─── DRY RUN: preview plan, no claude calls, no state writes ────
run_dry_run_preview() {
  [ -f "$GOAL_FILE" ] || { echo "ERROR: Goal file not found: $GOAL_FILE" >&2; return 1; }
  local open total verify plan est
  open=$(grep -c '^\- \[ \]' "$GOAL_FILE" 2>/dev/null || true); open=${open:-0}
  total=$(grep -c '^\- \[' "$GOAL_FILE" 2>/dev/null || true); total=${total:-0}
  verify=$(_read_verify_cmd)
  est=$(( (open + MAX_WORKERS - 1) / MAX_WORKERS )); [ "$est" -gt "$MAX_ITER" ] && est=$MAX_ITER
  if [ "$total" -eq 0 ]; then plan="freeform (no checklist items in goal file)"
  elif [ "$open" -eq 0 ]; then plan="0 -- goal already converged (0 unchecked items)"
  else plan="up to $MAX_WORKERS/iteration, ~$est iteration(s) for $open open item(s) (capped at --max-iter $MAX_ITER)"
  fi
  cat <<EOF
[DRY RUN] Blueprint Loop preview -- no claude calls, no loop-state written
  Goal file:      $GOAL_FILE
  Goal items:     $open open / $total total (unchecked '- [ ]' items)
  Models:         supervisor=$SUPERVISOR_MODEL worker=$WORKER_MODEL
  Iter/workers:   max-iter=$MAX_ITER max-workers=$MAX_WORKERS
  State/log:      $STATE_FILE (would NOT be written) / $LOG_DIR
  Verify cmd:     ${verify:-(none declared in CLAUDE.md)}
  Planned tasks:  $plan
EOF
}
# ────────────────────────────────────────────────────────────────

# ─── MAIN BLUEPRINT LOOP ────────────────────────────────────────
run_blueprint_loop() {
  mkdir -p "$LOG_DIR"
  local iteration=0
  local consecutive_no_commits=0
  local consecutive_worker_failures=0
  local exit_reason="max_iterations"
  local resume_phase=""

  if [ "$RESUME" = "true" ]; then
    _recover_checkpoint || return 2
    iteration=$((RECOVERED_ITERATION - 1))
    consecutive_no_commits=$RECOVERED_NO_COMMITS
    consecutive_worker_failures=$RECOVERED_WORKER_FAILURES
    resume_phase=$RECOVERED_PHASE
    ITERATION_START_COMMIT=$RECOVERED_START_COMMIT
  fi

  log_info "Starting Blueprint Loop"
  log_info "  Goal:         $GOAL_FILE"
  log_info "  Max iter:     $MAX_ITER"
  log_info "  Max workers:  $MAX_WORKERS"
  log_info "  Max worker failures: $MAX_CONSECUTIVE_FAILURES"
  log_info "  Supervisor:   $SUPERVISOR_MODEL"
  log_info "  Workers:      $WORKER_MODEL"
  log_info "  State file:   $STATE_FILE"

  # POST was already completed before the crash: finish its deterministic
  # convergence/state transition once, then continue at the next iteration.
  if [ "$resume_phase" = "post-done" ]; then
    iteration=$RECOVERED_ITERATION
    ITERATION=$iteration
    if _check_convergence "$iteration"; then
      generate_loop_report "$iteration" "$exit_reason"
      _clear_checkpoints
      return
    fi
    update_state "$iteration" "${RECOVERED_EXTRA:-0}"
    resume_phase=""
  fi

  while true; do
    iteration=$((iteration + 1))
    ITERATION=$iteration  # make available to node functions
    local task_file="$LOG_DIR/iter-${iteration}-tasks.txt"
    local all_workers_succeeded=false

    log_info ""
    log_info "═══ Iteration $iteration / $MAX_ITER ═══"

    if [ "$resume_phase" != "workers-done" ]; then
      if check_stop_sentinel; then exit_reason="user_stop"; break; fi
      if ! node_pre_flight; then exit_reason="pre_flight_failed"; break; fi
      ITERATION_START_COMMIT=$(git rev-parse HEAD 2>/dev/null || true)
      if check_interrupt; then exit_reason="interrupted"; break; fi
      node_health_check
      node_hydrate_context
      node_parse_todo
      _save_checkpoint "$iteration" "pre-done"

      local tasks_json task_count=0
      if ! tasks_json=$(node_supervisor "$iteration"); then
        exit_reason="supervisor_failed"
        break
      fi
      node_score_and_write "$tasks_json" "$task_file" >/dev/null
      if [ -n "$task_file" ] && [ -f "$task_file" ]; then
        task_count=$(grep -c '===TASK===' "$task_file" 2>/dev/null || true)
      fi
      if [ "$task_count" -eq 0 ]; then
        consecutive_no_commits=$((consecutive_no_commits + 1))
        log_warn "No executable tasks this iteration (consecutive empty: $consecutive_no_commits / $MAX_CONSECUTIVE_NO_COMMITS)"
        if [ "$consecutive_no_commits" -ge "$MAX_CONSECUTIVE_NO_COMMITS" ]; then
          log_error "$MAX_CONSECUTIVE_NO_COMMITS consecutive empty iterations — loop appears stuck"
          exit_reason="stuck_no_tasks"
          break
        fi
        _check_convergence "$iteration" && break
        update_state "$iteration" 0
        continue
      fi
      node_run_workers "$task_file"
      all_workers_succeeded="$WORKERS_SUCCEEDED"
      _save_checkpoint "$iteration" "workers-done" "$all_workers_succeeded"
    else
      log_info "[RECOVERY] Workers already completed; continuing at POST"
      [ "$RECOVERED_EXTRA" = "true" ] && all_workers_succeeded=true
      resume_phase=""
    fi

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
        [ "$WORKERS_SUCCEEDED" = "true" ] || all_workers_succeeded=false

        # Re-run syntax + test to verify fix
        local fix_syntax_failures
        fix_syntax_failures=$(node_syntax_check)
        syntax_failures="$fix_syntax_failures"
        if [ -n "$fix_syntax_failures" ]; then
          log_warn "Fix introduced syntax errors — reverting"
          while IFS= read -r f; do
            [ -n "$f" ] && git checkout -- "$f" 2>/dev/null || true
          done < <(printf "%b" "$fix_syntax_failures")
        fi

        local fix_test_result=0
        node_test_sample || fix_test_result=$?
        test_result=$fix_test_result
        if [ $fix_test_result -ne 0 ]; then
          log_warn "Mid-iteration fix failed — completion remains unverified"
          consecutive_worker_failures=$((consecutive_worker_failures + 1))
          update_state "$iteration" 0
          # Fall through to convergence_check
        fi
      fi
    fi

    local verify_result
    verify_result=$(node_verify)

    # Workers never edit the goal; the coordinator requires every gate.
    if [ "$all_workers_succeeded" = "true" ] && [ -z "$syntax_failures" ] \
       && [ "$test_result" -eq 0 ] && _verify_passed "$verify_result"; then
      node_reconcile_goal "$task_file" || true
    else
      log_warn "Skipping goal reconciliation because an execution or verification gate did not pass"
    fi

    # [DET] commit_changes
    local new_commits
    if ! new_commits=$(node_commit_changes); then
      exit_reason="commit_failed"
      break
    fi

    if [ "${new_commits:-0}" -eq 0 ]; then
      consecutive_no_commits=$((consecutive_no_commits + 1))
      log_warn "No commits this iteration (consecutive no-commit: $consecutive_no_commits)"
    else
      consecutive_no_commits=0
      log_success "Counted $new_commits commit(s) in iteration $iteration"
    fi
    if [ "$all_workers_succeeded" = "true" ]; then
      consecutive_worker_failures=0
    else
      consecutive_worker_failures=$((consecutive_worker_failures + 1))
      log_warn "Worker execution failed (consecutive: $consecutive_worker_failures)"
      if [ "$consecutive_worker_failures" -ge "$MAX_CONSECUTIVE_FAILURES" ]; then
        log_error "$MAX_CONSECUTIVE_FAILURES consecutive worker failures — all workers failed, writing blocker"
        {
          echo "## Blocker [$(date '+%Y-%m-%d %H:%M')]"
          echo "All $MAX_CONSECUTIVE_FAILURES consecutive worker runs returned failure."
          echo "Likely causes: workers hitting permission errors, wrong working directory, or unresolvable task conflicts."
          echo "Iteration: $iteration"
          echo "Last goal: $GOAL_FILE"
        } >> .claude/blockers.md
        exit_reason="all_workers_failed"
        break
      fi
    fi

    # [DET] checkpoint after POST
    _save_checkpoint "$iteration" "post-done" "${new_commits:-0}"

    # [DET] Deterministic convergence_check
    # Convergence = no more unchecked items in goal file, OR max iterations hit, OR stuck
    _check_convergence "$iteration" && break
    update_state "$iteration" "${new_commits:-0}"
  done

  generate_loop_report "$iteration" "$exit_reason"
  case "$exit_reason" in
    converged|max_iterations|stuck_no_commits|stuck_no_tasks)
      _clear_checkpoints
      ;;
  esac
  case "$exit_reason" in supervisor_failed|commit_failed|pre_flight_failed|all_workers_failed) return 1;; esac
}
# ────────────────────────────────────────────────────────────────

main() {
  parse_args "$@"

  if [ -z "$GOAL_FILE" ]; then
    print_usage
    exit 1
  fi

  if [ "$DRY_RUN" = "true" ]; then run_dry_run_preview; exit $?; fi

  run_blueprint_loop
}

main "$@"
