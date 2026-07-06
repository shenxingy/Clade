#!/usr/bin/env bash
# test-quiet-run.sh — Tests for configs/scripts/quiet-run.sh
#   (Round-4 gap: per-line timestamps for a merged, time-correlatable log —
#   Thorsten Ball's log-merging pattern; /verify appends browser console
#   output to the same file tagged [browser])
#
# Usage:
#   bash tests/test-quiet-run.sh        # Run all tests
#   bash tests/test-quiet-run.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$REPO_ROOT/configs/scripts/quiet-run.sh"

# ─── Test framework (mirrors tests/test-mailbox-drain.sh) ────────────
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
VERBOSE="${1:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass() { TESTS_PASSED=$((TESTS_PASSED + 1)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() {
  TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
}
section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }

assert_contains() {
  local haystack="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if grep -qF "$needle" <<< "$haystack"; then pass "$msg"
  else
    fail "$msg" "output does not contain '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $haystack"
  fi
}
assert_matches() {
  local haystack="$1" pattern="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if grep -qE "$pattern" <<< "$haystack"; then pass "$msg"
  else
    fail "$msg" "output does not match /$pattern/"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $haystack"
  fi
}
assert_eq() {
  local actual="$1" expected="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "$actual" == "$expected" ]]; then pass "$msg"
  else fail "$msg" "expected '$expected', got '$actual'"; fi
}

# ─── Sandbox ─────────────────────────────────────────────────────────

SANDBOX="$(mktemp -d /tmp/clade-test-quiet-run-XXXXXX)"
case "$SANDBOX" in
  /tmp/clade-test-quiet-run-*) : ;;
  *) echo "FATAL: sandbox '$SANDBOX' not under /tmp — aborting"; exit 1 ;;
esac
cleanup() { rm -rf "$SANDBOX"; }
trap cleanup EXIT
cd "$SANDBOX"

# ─── 1. Success: exit 0, verdict line, timestamped log ────────────────
section "Success case"

OUT1=$(bash "$SCRIPT" bash -c 'echo hello; echo world')
RC1=$?
assert_eq "$RC1" "0" "success mirrors exit code 0"
assert_contains "$OUT1" "quiet-run: OK (exit 0, 2 lines)" "verdict line reports OK + line count"
LOG1=$(grep -oE '\.claude/logs/quiet-[0-9-]+\.log' <<< "$OUT1" | head -1)
TESTS_RUN=$((TESTS_RUN + 1))
[[ -f "$LOG1" ]] && pass "log file exists at the printed path" \
  || fail "log file exists at the printed path" "missing $LOG1"
LOG1_CONTENT=$(cat "$LOG1" 2>/dev/null)
assert_matches "$LOG1_CONTENT" '^\[[0-9]{2}:[0-9]{2}:[0-9]{2}\] hello$' "each line gets an [HH:MM:SS] timestamp prefix"
assert_matches "$LOG1_CONTENT" '^\[[0-9]{2}:[0-9]{2}:[0-9]{2}\] world$' "second line also timestamped"

# ─── 2. Failure: exit code mirrored, failed-test names extracted ──────
section "Failure case — exit code + failed-name extraction survives the timestamp prefix"

OUT2=$(bash "$SCRIPT" bash -c 'echo "1 passed"; echo "FAILED tests/test_x.py::test_y - assert 1 == 2"; exit 1')
RC2=$?
assert_eq "$RC2" "1" "failure mirrors the original nonzero exit code"
assert_contains "$OUT2" "quiet-run: FAILED (exit 1, 2 lines)" "verdict line reports FAILED"
assert_contains "$OUT2" "failed:" "failed-section header present"
assert_contains "$OUT2" "FAILED tests/test_x.py::test_y" "failed-test name extracted despite the [HH:MM:SS] prefix"

# ─── 3. A different nonzero exit code is mirrored exactly (not just "failed") ─
section "Exit code fidelity"

bash "$SCRIPT" bash -c 'exit 7' >/dev/null
RC3=$?
assert_eq "$RC3" "7" "a specific nonzero exit code (7) is mirrored exactly, not coerced to 1"

# ─── 4. Tail section respects QUIET_RUN_TAIL ──────────────────────────
section "QUIET_RUN_TAIL"

OUT4=$(QUIET_RUN_TAIL=2 bash "$SCRIPT" bash -c 'for i in 1 2 3 4 5; do echo "line $i"; done; exit 1')
TAIL_BLOCK=$(sed -n '/── last 2 lines ──/,$p' <<< "$OUT4")
TESTS_RUN=$((TESTS_RUN + 1))
if grep -q "line 5" <<< "$TAIL_BLOCK" && ! grep -q "line 3" <<< "$TAIL_BLOCK"; then
  pass "QUIET_RUN_TAIL=2 shows only the last 2 lines"
else
  fail "QUIET_RUN_TAIL=2 shows only the last 2 lines" "$TAIL_BLOCK"
fi

# ─── 5. Missing/uncreatable log dir falls back, never blocks the run ──
section "Log-dir fallback"

# A file (not a dir) at the log-dir path makes mkdir -p fail.
BLOCKED_DIR="$SANDBOX/blocked-logdir"
touch "$BLOCKED_DIR"
OUT5=$(QUIET_RUN_LOG_DIR="$BLOCKED_DIR" bash "$SCRIPT" bash -c 'echo ok')
RC5=$?
assert_eq "$RC5" "0" "uncreatable log dir does not block the run"
assert_contains "$OUT5" "quiet-run: OK" "verdict still printed with a fallback log dir"
rm -f "$BLOCKED_DIR"

# ─── Summary ─────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  Ran: $TESTS_RUN  ${GREEN}Passed: $TESTS_PASSED${NC}  ${RED}Failed: $TESTS_FAILED${NC}"
[[ "$TESTS_FAILED" -eq 0 ]] && { echo -e "  ${GREEN}ALL PASSED${NC}"; exit 0; } || { echo -e "  ${RED}FAILURES${NC}"; exit 1; }
