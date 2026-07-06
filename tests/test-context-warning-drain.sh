#!/usr/bin/env bash
# test-context-warning-drain.sh — Tests for configs/hooks/context-warning-drain.sh
#   (PostToolUse all-tools: delivers worker.py's context-budget nudge)
#
# Round-4 dead-code fix (fennu2333): worker.py's poll_all() wrote
# .claude/context-warning-<task_id>.md once a worker crossed ~80% context, but
# nothing ever delivered that file into the worker's own session. This hook
# closes the loop, mirroring mailbox-drain.sh's safety pattern exactly.
#
# Usage:
#   bash tests/test-context-warning-drain.sh        # Run all tests
#   bash tests/test-context-warning-drain.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$REPO_ROOT/configs/hooks/context-warning-drain.sh"

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
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -5 <<< "$haystack")"
  fi
}
assert_empty() {
  local out="$1" msg="$2"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -z "$out" ]]; then pass "$msg"
  else fail "$msg" "expected no output, got: $(head -2 <<< "$out")"; fi
}
assert_file_gone() {
  local f="$1" msg="$2"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ ! -e "$f" ]]; then pass "$msg"
  else fail "$msg" "file still exists: $f"; fi
}

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found — skipping (CI installs jq)"; exit 0
fi

# ─── Sandbox ─────────────────────────────────────────────────────────

SANDBOX="$(mktemp -d /tmp/clade-test-context-warning-XXXXXX)"
case "$SANDBOX" in
  /tmp/clade-test-context-warning-*) : ;;
  *) echo "FATAL: sandbox '$SANDBOX' not under /tmp — aborting"; exit 1 ;;
esac
cleanup() { rm -rf "$SANDBOX"; }
trap cleanup EXIT

PROJ="$SANDBOX/proj"
mkdir -p "$PROJ/.claude"

TASK="task-42"
WARN_FILE="$PROJ/.claude/context-warning-$TASK.md"
FIXTURE='{"session_id":"s1","tool_name":"Bash","tool_input":{"command":"ls"}}'

run_hook() {
  printf '%s' "$FIXTURE" \
    | CLADE_WORKER_TASK_ID="$TASK" CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK"
}

# ─── 1. Drain happy path ──────────────────────────────────────────────
section "Drain"

printf 'CONTEXT WARNING: ~80%% context window used. Run /compact now.\n' > "$WARN_FILE"
OUT=$(run_hook)
assert_contains "$OUT" "Context budget warning" "framing header present"
assert_contains "$OUT" "Run /compact now" "warning content emitted"
assert_contains "$OUT" "hookSpecificOutput" "output is hookSpecificOutput JSON"
assert_file_gone "$WARN_FILE" "warning file consumed after drain"

TESTS_RUN=$((TESTS_RUN + 1))
if jq -e '.hookSpecificOutput.additionalContext' <<< "$OUT" >/dev/null 2>&1; then
  pass "output parses as valid JSON"
else
  fail "output parses as valid JSON"
fi

# ─── 2. At-most-once: second call after drain finds nothing ──────────
section "At-most-once"
OUT2=$(run_hook)
assert_empty "$OUT2" "second call after drain is silent"

TESTS_RUN=$((TESTS_RUN + 1))
leftover=$(ls "$PROJ/.claude/"*.draining.* 2>/dev/null | wc -l | tr -d ' ')
[[ "$leftover" == "0" ]] && pass "no .draining temp files left behind" \
  || fail "no .draining temp files left behind" "$leftover leftover files"

# ─── 3. No env var → silent no-op (non-worker session) ────────────────
section "No CLADE_WORKER_TASK_ID"
printf 'stale content\n' > "$WARN_FILE"
OUT3=$(printf '%s' "$FIXTURE" | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK")
assert_empty "$OUT3" "no task id env var → silent"
TESTS_RUN=$((TESTS_RUN + 1))
[[ -f "$WARN_FILE" ]] && pass "file untouched without a task id" \
  || fail "file untouched without a task id" "file was consumed anyway"
rm -f "$WARN_FILE"

# ─── 4. No warning file → silent no-op ────────────────────────────────
section "No warning file"
OUT4=$(run_hook)
assert_empty "$OUT4" "missing warning file → silent"

# ─── 5. Task-id sanitizer rejects path-unsafe values ──────────────────
section "Task-id sanitizer"
OUT5=$(printf '%s' "$FIXTURE" \
  | CLADE_WORKER_TASK_ID="../escape" CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK")
assert_empty "$OUT5" "path-traversal task id rejected"

# ─── 6. Symlink refusal ────────────────────────────────────────────────
section "Symlink refusal"
REAL_SECRET="$SANDBOX/secret.md"
printf 'top secret\n' > "$REAL_SECRET"
ln -sf "$REAL_SECRET" "$WARN_FILE"
OUT6=$(run_hook)
assert_empty "$OUT6" "symlinked warning file refused"
TESTS_RUN=$((TESTS_RUN + 1))
[[ -L "$WARN_FILE" ]] && pass "symlink left untouched (not consumed)" \
  || fail "symlink left untouched (not consumed)" "symlink was removed"
rm -f "$WARN_FILE"

# ─── 7. Garbage stdin does not crash the hook ─────────────────────────
section "Garbage stdin"
printf 'CONTEXT WARNING test\n' > "$WARN_FILE"
OUT7=$(printf 'not json at all' \
  | CLADE_WORKER_TASK_ID="$TASK" CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK")
assert_contains "$OUT7" "hookSpecificOutput" "garbage stdin does not break delivery (stdin is drained, not parsed)"
rm -f "$WARN_FILE" "$WARN_FILE".draining.* 2>/dev/null

# ─── Summary ─────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  Ran: $TESTS_RUN  ${GREEN}Passed: $TESTS_PASSED${NC}  ${RED}Failed: $TESTS_FAILED${NC}"
[[ "$TESTS_FAILED" -eq 0 ]] && { echo -e "  ${GREEN}ALL PASSED${NC}"; exit 0; } || { echo -e "  ${RED}FAILURES${NC}"; exit 1; }
