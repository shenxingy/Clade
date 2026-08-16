#!/usr/bin/env bash
# loop_score.sh — [DET] scoring + task-file emission for one iteration.
#
# Extracted from loop-runner.sh to keep it under the 1500-line ceiling that
# test_conventions.py enforces. Scoring is a self-contained deterministic node:
# it takes the supervisor's task JSON and emits the ===TASK=== file workers
# read. No LLM calls, no loop-control state.
#
# Reads:  LOG_DIR, ITERATION
# Uses:   log_info, log_warn from loop-runner.sh

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
