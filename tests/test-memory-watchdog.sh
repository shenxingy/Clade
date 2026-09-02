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
#
# Also covers the runtime paths: the pid file moved off the fixed
# /tmp/memory-watchdog.pid (first-writer-wins on a shared host) into this
# user's private runtime dir, and the pid write + EXIT trap moved BELOW the
# source guard — sourcing this file used to write and then delete the pid file
# of whatever watchdog was actually live on the machine.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WATCHDOG="$REPO_ROOT/configs/scripts/memory-watchdog.sh"

MW_SANDBOX="$(mktemp -d /tmp/clade-mw-test-XXXXXX)"
case "$MW_SANDBOX" in
  /tmp/clade-mw-test-*) : ;;
  *) echo "FATAL: sandbox '$MW_SANDBOX' is not under /tmp — aborting"; exit 1 ;;
esac
trap 'rm -rf "$MW_SANDBOX"' EXIT
export MW_PID_FILE="$MW_SANDBOX/watchdog.pid"
export MW_LOG_FILE="$MW_SANDBOX/watchdog.log"

# shellcheck source=/dev/null
source "$WATCHDOG"

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

section "Sourcing must not touch live watchdog state"

# The regression: `echo $$ > "$PID_FILE"` and `trap 'rm -f "$PID_FILE"' EXIT`
# ran at file scope, above the source guard. This suite sources the script, so
# every run wrote and then deleted a real watchdog's pid file.
if [[ -e "$MW_PID_FILE" ]]; then
  fail "sourcing writes no pid file" "created $MW_PID_FILE"
else
  pass "sourcing writes no pid file"
fi
if [[ -e "$MW_LOG_FILE" ]]; then
  fail "sourcing writes no log file" "created $MW_LOG_FILE"
else
  pass "sourcing writes no log file"
fi

# Structural guard on the same defect, independent of MW_PID_FILE: the old code
# ignored every override, so an assertion phrased only in terms of the sandbox
# path could not see it. The pid write must sit BELOW the source guard.
_guard_ln=$(grep -n 'BASH_SOURCE\[0\]}" != "\${0}' "$WATCHDOG" | head -1 | cut -d: -f1)
_write_ln=$(grep -n 'echo \$\$ > "\$PID_FILE"' "$WATCHDOG" | head -1 | cut -d: -f1)
if [[ -n "$_guard_ln" && -n "$_write_ln" && "$_write_ln" -gt "$_guard_ln" ]]; then
  pass "the pid write is below the source guard (line $_write_ln > $_guard_ln)"
else
  fail "the pid write is below the source guard" \
    "guard at '${_guard_ln:-?}', write at '${_write_ln:-?}'"
fi

section "Runtime paths are per-user, not a fixed /tmp path"

if grep -qE '^(PID_FILE|LOG_FILE)="?/tmp/' "$WATCHDOG"; then
  fail "no state path is hardcoded under /tmp" "a fixed /tmp assignment survives"
else
  pass "no state path is hardcoded under /tmp"
fi

assert_eq "$MW_PID_FILE" "$(_mw_pid_file)" "MW_PID_FILE overrides the derived path"

# With no override, the pid file lands under the private runtime root.
MW_RT="$MW_SANDBOX/rt"
out=$( MW_PID_FILE= CLADE_RUNTIME_DIR="$MW_RT" _mw_pid_file )
assert_eq "$MW_RT/memory-watchdog.pid" "$out" "the pid file derives from the runtime root"

# A squatted (symlinked) root is refused by the helper, so the watchdog falls
# back to $HOME rather than writing into a directory it does not own.
mkdir -p "$MW_SANDBOX/elsewhere"
ln -s "$MW_SANDBOX/elsewhere" "$MW_SANDBOX/squat"
out=$( MW_PID_FILE= CLADE_RUNTIME_DIR="$MW_SANDBOX/squat" HOME="$MW_SANDBOX/fakehome" _mw_pid_file )
assert_eq "$MW_SANDBOX/fakehome/.claude/memory-watchdog.pid" "$out" \
  "an unusable runtime root falls back to \$HOME, never to a shared /tmp path"

# The log is long-lived, so it belongs in $HOME — not a runtime dir systemd
# reaps on last logout.
if grep -q 'LOG_FILE="${MW_LOG_FILE:-$HOME/.claude/memory-watchdog.log}"' "$WATCHDOG"; then
  pass "the log defaults under \$HOME, not the runtime dir"
else
  fail "the log defaults under \$HOME, not the runtime dir"
fi

section "--stop resolves the same path the daemon wrote"

out=$(MW_PID_FILE="$MW_SANDBOX/absent.pid" bash "$WATCHDOG" --stop 2>&1); rc=$?
assert_eq "1" "$rc" "--stop exits 1 when no watchdog is running"
if grep -q 'No running memory watchdog' <<< "$out"; then
  pass "--stop names the pid file it looked for"
else
  fail "--stop names the pid file it looked for" "got: $out"
fi

sleep 60 &
VICTIM=$!
printf '%s\n' "$VICTIM" > "$MW_SANDBOX/live.pid"
MW_PID_FILE="$MW_SANDBOX/live.pid" bash "$WATCHDOG" --stop >/dev/null 2>&1
assert_eq "0" "$?" "--stop exits 0 when it stops a running watchdog"
wait "$VICTIM" 2>/dev/null
if kill -0 "$VICTIM" 2>/dev/null; then
  fail "--stop actually signals the recorded pid" "pid $VICTIM is still alive"
else
  pass "--stop actually signals the recorded pid"
fi

printf "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
if [[ $FAIL -eq 0 ]]; then
  printf "  ${GREEN}ALL PASSED${NC} (%d/%d)\n" "$PASS" "$((PASS + FAIL))"
else
  printf "  ${RED}%d FAILED${NC} / %d passed / %d total\n" "$FAIL" "$PASS" "$((PASS + FAIL))"
fi
printf "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
exit $((FAIL > 0))
