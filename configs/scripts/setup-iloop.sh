#!/usr/bin/env bash
# setup-iloop.sh — Create state file for an in-session iterative loop
#
# Usage:
#   setup-iloop.sh "task description" [--max-iterations N] [--completion-promise "TEXT"]
#
# This creates .claude/iloop.local.md which the iloop-hook.sh Stop hook reads to
# keep Claude looping until the task is complete or max iterations is reached.
#
# Signals (Claude outputs these to control the loop):
#   <loop-abort>reason</loop-abort>   — terminate immediately
#   <loop-pause>what needed</loop-pause>  — pause for manual intervention
#   <promise>TEXT</promise>           — signal completion (when --completion-promise set)
#
# Adapted from pua (MIT) — https://github.com/tanweai/pua

set -euo pipefail

PROMPT_PARTS=()
MAX_ITERATIONS=20
COMPLETION_PROMISE="null"

while [[ $# -gt 0 ]]; do
  case $1 in
    --max-iterations)
      [[ -z "${2:-}" || ! "$2" =~ ^[0-9]+$ ]] && { echo "Error: --max-iterations requires a number" >&2; exit 1; }
      MAX_ITERATIONS="$2"; shift 2 ;;
    --completion-promise)
      [[ -z "${2:-}" ]] && { echo "Error: --completion-promise requires text" >&2; exit 1; }
      COMPLETION_PROMISE="$2"; shift 2 ;;
    --help|-h)
      cat <<'EOF'
setup-iloop.sh — In-session iterative loop

USAGE:
  setup-iloop.sh "task description" [--max-iterations N] [--completion-promise "TEXT"]

SIGNALS (output in Claude's response to control the loop):
  <loop-abort>reason</loop-abort>     Terminate loop immediately
  <loop-pause>what needed</loop-pause> Pause for manual intervention, resume later
  <promise>TEXT</promise>             Signal completion (when --completion-promise set)

EXAMPLES:
  setup-iloop.sh "Fix all failing tests" --max-iterations 15
  setup-iloop.sh "Build the auth feature" --completion-promise "DONE" --max-iterations 25

MONITORING:
  head -8 .claude/iloop.local.md      # View current state
EOF
      exit 0 ;;
    *) PROMPT_PARTS+=("$1"); shift ;;
  esac
done

PROMPT="${PROMPT_PARTS[*]:-}"
if [[ -z "$PROMPT" ]]; then
  echo "Error: No task description provided. Usage: setup-iloop.sh \"task description\"" >&2
  exit 1
fi

mkdir -p .claude

# Quote completion promise for YAML (handle special characters)
if [[ "$COMPLETION_PROMISE" != "null" && -n "$COMPLETION_PROMISE" ]]; then
  PROMISE_YAML="\"$COMPLETION_PROMISE\""
  PROTOCOL_COMPLETION="5. Only output <promise>${COMPLETION_PROMISE//\"/}</promise> when ALL success criteria are genuinely met and verified"
else
  PROMISE_YAML="null"
  PROTOCOL_COMPLETION="5. No completion signal configured — loop runs until max iterations or <loop-abort>"
fi

cat > .claude/iloop.local.md <<EOF
---
active: true
iteration: 1
session_id: ${CLAUDE_CODE_SESSION_ID:-}
max_iterations: $MAX_ITERATIONS
completion_promise: $PROMISE_YAML
started_at: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
---

$PROMPT

== Loop Protocol (follow each iteration) ==
1. Read project files and git log to understand what was done last iteration
2. Run build/test/verify to check current state before making changes
3. Make focused progress on the task
4. Run build/test/verify after changes — do NOT claim done without evidence
5. Scan for related issues (fix A, check if B and C are also affected)
$PROTOCOL_COMPLETION

Signals (output anywhere in your response):
- <loop-abort>reason</loop-abort>  — use when task is impossible or needs human decision
- <loop-pause>what needed</loop-pause>  — use when human action is required (e.g. API key, login)

Prohibited:
- Do NOT call AskUserQuestion (loop runs unattended)
- Do NOT say "I suggest the user handle this manually" — exhaust automated options first
- Do NOT claim done without running verification and showing output
EOF

cat <<EOF

🔄 iloop activated — iterating until done

  Task: $PROMPT
  Max iterations: $(if [[ $MAX_ITERATIONS -gt 0 ]]; then echo $MAX_ITERATIONS; else echo "unlimited"; fi)
  Completion: $(if [[ "$COMPLETION_PROMISE" != "null" ]]; then echo "when <promise>${COMPLETION_PROMISE//\"/}</promise> is output"; else echo "max iterations"; fi)

  Monitor: head -8 .claude/iloop.local.md
  Cancel: rm .claude/iloop.local.md

EOF

echo "$PROMPT"

if [[ "$COMPLETION_PROMISE" != "null" ]]; then
  printf '\n  ⚠  Only output <promise>%s</promise> when genuinely TRUE\n\n' "$COMPLETION_PROMISE"
fi
