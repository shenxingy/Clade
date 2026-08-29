#!/usr/bin/env bash
# Tests for configs/scripts/memory-watchdog.sh worker selection.
#
# The script had no tests. Under memory pressure it selected workers with
#   pgrep -f "claude[[:space:]].*[[:space:]]-p[[:space:]]"
# which requires a token BETWEEN "claude" and "-p" — and every command
# worker_provider.py builds puts -p immediately after claude. Measured against
# a live worker-shaped process, that pattern matched nothing, so the watchdog
# logged "No claude worker processes to kill" and freed no memory at all.
#
# The rows below are real `ps -eo pid=,etimes=,comm=,args=` shapes.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=/dev/null
source "$REPO_ROOT/configs/scripts/memory-watchdog.sh"

PASS=0
FAIL=0
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'

pass() { printf "  ${GREEN}✓${NC} %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "  ${RED}✗${NC} %s\n" "$1"; [[ -n "${2:-}" ]] && printf "    ${RED}→ %s${NC}\n" "$2"; FAIL=$((FAIL + 1)); }
section() { printf "\n${YELLOW}── %s ──${NC}\n" "$1"; }

assert_eq() {
  if [[ "$1" == "$2" ]]; then pass "$3"; else fail "$3" "want '$1', got '$2'"; fi
}

# Real command shapes, as ps reports them.
WORKER_ARGS='claude -p "$(cat /home/u/.claude/task-1.md)" --model claude-opus-5 --dangerously-skip-permissions --output-format stream-json --verbose'
WRAPPER_ARGS="/bin/sh -c $WORKER_ARGS"
CONTINUE_ARGS='claude -p --continue "$(cat /home/u/.claude/retry-1.md)" --model claude-opus-5 --dangerously-skip-permissions'
INTERACTIVE_ARGS='claude --dangerously-skip-permissions'

section "The command shapes the orchestrator actually builds"

out=$(printf '%s\n' "4100 300 claude $WORKER_ARGS" | select_worker_pids)
assert_eq "4100" "$out" "a real build_command worker is selected"

out=$(printf '%s\n' "4100 300 claude $CONTINUE_ARGS" | select_worker_pids)
assert_eq "4100" "$out" "a --continue retry worker is selected"

section "What must NOT be selected"

# The shell wrapper carries the identical command line and gets the LOWER pid.
# Signalling it orphans the claude process and frees no memory.
out=$(printf '%s\n%s\n' \
  "4099 301 sh $WRAPPER_ARGS" \
  "4100 300 claude $WORKER_ARGS" | select_worker_pids)
assert_eq "4100" "$out" "the sh -c wrapper is excluded in favour of the real process"

out=$(printf '%s\n' "4200 900 claude $INTERACTIVE_ARGS" | select_worker_pids)
assert_eq "" "$out" "an interactive session is never a kill candidate"

out=$(printf '%s\n' "4300 900 python server.py --model claude -p x" | select_worker_pids)
assert_eq "" "$out" "a non-claude process carrying the flag is ignored"

out=$(printf '%s\n' "4400 999 bash /home/u/.claude/scripts/memory-watchdog.sh" | select_worker_pids)
assert_eq "" "$out" "the watchdog never selects itself"

section "Ordering is by age, not by pid"

# The oldest worker has the largest elapsed time. Pid order is not age order:
# here the oldest (600s) has the highest pid.
out=$(printf '%s\n%s\n%s\n' \
  "5000 100 claude $WORKER_ARGS" \
  "5001 300 claude $WORKER_ARGS" \
  "5002 600 claude $WORKER_ARGS" | select_worker_pids | head -1)
assert_eq "5002" "$out" "oldest-by-elapsed-time is selected, not lowest pid"

out=$(printf '%s\n%s\n%s\n' \
  "5000 100 claude $WORKER_ARGS" \
  "5001 300 claude $WORKER_ARGS" \
  "5002 600 claude $WORKER_ARGS" | select_worker_pids | tr '\n' ' ')
assert_eq "5002 5001 5000 " "$out" "full list is ordered oldest first"

section "Empty and malformed input"

out=$(printf '' | select_worker_pids)
assert_eq "" "$out" "empty process table yields nothing"

out=$(printf '%s\n' "garbage" | select_worker_pids)
assert_eq "" "$out" "a malformed row is skipped rather than crashing"

section "Regression: the pattern that matched nothing"

# Kept as an explicit record of the defect. The old selector was:
#   pgrep -f "claude[[:space:]].*[[:space:]]-p[[:space:]]"
# Applied to the command the orchestrator builds, it finds no match.
if printf '%s' "$WORKER_ARGS" | grep -qE "claude[[:space:]].*[[:space:]]-p[[:space:]]"; then
  fail "the old pattern is documented as non-matching" "it matched — the premise of this fix is wrong"
else
  pass "the old pattern matches none of the commands worker_provider builds"
fi

printf "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
if [[ $FAIL -eq 0 ]]; then
  printf "  ${GREEN}ALL PASSED${NC} (%d/%d)\n" "$PASS" "$((PASS + FAIL))"
else
  printf "  ${RED}%d FAILED${NC} / %d passed / %d total\n" "$FAIL" "$PASS" "$((PASS + FAIL))"
fi
printf "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
exit $((FAIL > 0))
