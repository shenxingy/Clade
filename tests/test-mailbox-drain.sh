#!/usr/bin/env bash
# test-mailbox-drain.sh — Tests for configs/hooks/mailbox-drain.sh
#   (PostToolUse all-tools: mid-flight worker steering via inbox drain)
#
# Pipes fixture hook-input JSON through the hook against throwaway project
# dirs under /tmp; never touches the real ~/.claude. Covers: drain + JSON
# shape, delete-after-drain (at-most-once per file), no-inbox / no-env
# no-ops, empty inbox, garbage stdin, task-id sanitizer, symlink refusal,
# byte cap, and concurrent-drain safety (atomic mv claim → exactly one
# delivery).
#
# Usage:
#   bash tests/test-mailbox-drain.sh        # Run all tests
#   bash tests/test-mailbox-drain.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$REPO_ROOT/configs/hooks/mailbox-drain.sh"

# ─── Test framework (mirrors tests/test-rule-injector.sh) ────────────
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
VERBOSE="${1:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass() {
  TESTS_PASSED=$((TESTS_PASSED + 1))
  echo -e "  ${GREEN}✓${NC} $1"
}

fail() {
  TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
}

section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }

assert_contains() {
  local haystack="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if grep -qF "$needle" <<< "$haystack"; then
    pass "$msg"
  else
    fail "$msg" "output does not contain '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -5 <<< "$haystack")"
  fi
}

assert_not_contains() {
  local haystack="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if grep -qF "$needle" <<< "$haystack"; then
    fail "$msg" "output unexpectedly contains '$needle'"
  else
    pass "$msg"
  fi
}

assert_empty() {
  local out="$1" msg="$2"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -z "$out" ]]; then
    pass "$msg"
  else
    fail "$msg" "expected no output, got: $(head -2 <<< "$out")"
  fi
}

assert_rc_zero() {
  local rc="$1" msg="$2"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "$rc" -eq 0 ]]; then
    pass "$msg"
  else
    fail "$msg" "exit code $rc"
  fi
}

assert_file_gone() {
  local f="$1" msg="$2"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ ! -e "$f" ]]; then
    pass "$msg"
  else
    fail "$msg" "file still exists: $f"
  fi
}

assert_file_exists() {
  local f="$1" msg="$2"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -e "$f" ]]; then
    pass "$msg"
  else
    fail "$msg" "file missing: $f"
  fi
}

# ─── Sandbox ─────────────────────────────────────────────────────────

SANDBOX="$(mktemp -d /tmp/clade-test-mailbox-drain-XXXXXX)"
case "$SANDBOX" in
  /tmp/clade-test-mailbox-drain-*) : ;;
  *) echo "FATAL: sandbox '$SANDBOX' not under /tmp — aborting"; exit 1 ;;
esac
cleanup() { rm -rf "$SANDBOX"; }
trap cleanup EXIT

PROJ="$SANDBOX/proj"
mkdir -p "$PROJ/.claude"

TASK="task-42"
INBOX="$PROJ/.claude/worker-inbox-$TASK.md"

# Hook-input fixture (content unused by the hook — stdin is just drained)
FIXTURE='{"session_id":"s1","tool_name":"Bash","tool_input":{"command":"ls"}}'

# Run the hook as a worker session would: env var + project dir set
run_hook() {
  printf '%s' "$FIXTURE" \
    | CLADE_WORKER_TASK_ID="$TASK" CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK"
}

# ─── Suite 1: Drain happy path ───────────────────────────────────────

section "Drain"

printf '[from supervisor] STEER-BODY: focus on routes only.\n' > "$INBOX"
OUT=$(run_hook); RC=$?
assert_rc_zero "$RC" "drain exits 0"
assert_contains "$OUT" "STEER-BODY" "inbox content emitted"
assert_contains "$OUT" "hookSpecificOutput" "output is hookSpecificOutput JSON"
assert_contains "$OUT" "additionalContext" "content emitted via additionalContext"
assert_contains "$OUT" "mid-flight steering" "framing header present"
assert_file_gone "$INBOX" "inbox file deleted after drain"

TESTS_RUN=$((TESTS_RUN + 1))
if command -v jq >/dev/null 2>&1 && jq -e '.hookSpecificOutput.additionalContext' <<< "$OUT" >/dev/null 2>&1; then
  pass "output parses as JSON with .hookSpecificOutput.additionalContext"
else
  fail "output parses as JSON with .hookSpecificOutput.additionalContext"
fi

TESTS_RUN=$((TESTS_RUN + 1))
leftover=$(ls "$PROJ/.claude/"*.draining.* 2>/dev/null | wc -l | tr -d ' ')
if [[ "$leftover" == "0" ]]; then
  pass "no .draining temp files left behind"
else
  fail "no .draining temp files left behind" "$leftover leftover files"
fi

# At-most-once: second invocation after drain finds nothing
OUT=$(run_hook); RC=$?
assert_empty "$OUT" "second invocation after drain emits nothing (at-most-once)"
assert_rc_zero "$RC" "second invocation exits 0"

# ─── Suite 2: No-op paths ────────────────────────────────────────────

section "No-op and failure paths"

OUT=$(run_hook); RC=$?
assert_empty "$OUT" "no inbox file produces no output"
assert_rc_zero "$RC" "no inbox file exits 0"

# Env var unset → never drains, file left intact for the next spawn
printf 'WAITING-BODY\n' > "$INBOX"
OUT=$(printf '%s' "$FIXTURE" | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK"); RC=$?
assert_empty "$OUT" "no CLADE_WORKER_TASK_ID produces no output (non-worker session)"
assert_rc_zero "$RC" "no CLADE_WORKER_TASK_ID exits 0"
assert_file_exists "$INBOX" "inbox left intact when env var unset"
rm -f "$INBOX"

# Empty inbox file → silently consumed, no injection
: > "$INBOX"
OUT=$(run_hook); RC=$?
assert_empty "$OUT" "empty inbox file produces no output"
assert_rc_zero "$RC" "empty inbox file exits 0"
assert_file_gone "$INBOX" "empty inbox file still consumed"

# Garbage stdin — drain decision is env+fs keyed, stdin content irrelevant
printf 'GARBAGE-OK-BODY\n' > "$INBOX"
OUT=$(printf 'not json at all' \
  | CLADE_WORKER_TASK_ID="$TASK" CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK"); RC=$?
assert_contains "$OUT" "GARBAGE-OK-BODY" "garbage stdin still drains the inbox"
assert_rc_zero "$RC" "garbage stdin exits 0"

# ─── Suite 3: Safety rails ───────────────────────────────────────────

section "Safety rails"

# Task-id sanitizer: path metacharacters → hard no-op
printf 'SECRET-BODY\n' > "$PROJ/secret.md"
OUT=$(printf '%s' "$FIXTURE" \
  | CLADE_WORKER_TASK_ID='../../secret' CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK"); RC=$?
assert_empty "$OUT" "task id with path traversal chars produces no output"
assert_rc_zero "$RC" "task id with path traversal chars exits 0"
assert_file_exists "$PROJ/secret.md" "traversal target untouched"

# Symlink inbox → refused (no arbitrary file content into context)
ln -s "$PROJ/secret.md" "$INBOX"
OUT=$(run_hook); RC=$?
assert_empty "$OUT" "symlinked inbox produces no output"
assert_rc_zero "$RC" "symlinked inbox exits 0"
rm -f "$INBOX"

# Byte cap: content beyond 10000 bytes never reaches the context
{ head -c 12000 /dev/zero | tr '\0' 'A'; printf 'TAIL-MARKER\n'; } > "$INBOX"
OUT=$(run_hook); RC=$?
assert_rc_zero "$RC" "oversized inbox exits 0"
assert_contains "$OUT" "additionalContext" "oversized inbox still injects (capped)"
assert_not_contains "$OUT" "TAIL-MARKER" "content past the 10000-byte cap is dropped"
assert_file_gone "$INBOX" "oversized inbox consumed"

# ─── Suite 4: Concurrent-drain safety ────────────────────────────────

section "Concurrent-drain safety"

# Two drainers race on one inbox: the atomic mv claim means exactly one
# delivers the content; the loser exits silently.
printf 'RACE-BODY\n' > "$INBOX"
OUT_A_FILE="$SANDBOX/out-a"
OUT_B_FILE="$SANDBOX/out-b"
run_hook > "$OUT_A_FILE" 2>/dev/null &
PID_A=$!
run_hook > "$OUT_B_FILE" 2>/dev/null &
PID_B=$!
wait "$PID_A" "$PID_B"

winners=0
grep -qF "RACE-BODY" "$OUT_A_FILE" && winners=$((winners + 1))
grep -qF "RACE-BODY" "$OUT_B_FILE" && winners=$((winners + 1))
TESTS_RUN=$((TESTS_RUN + 1))
if [[ "$winners" -eq 1 ]]; then
  pass "concurrent drainers deliver the message exactly once"
else
  fail "concurrent drainers deliver the message exactly once" "winners=$winners (want 1)"
fi
assert_file_gone "$INBOX" "inbox consumed after concurrent drain"

# Writer-side race shape: a new inbox dropped right after a drain is simply
# picked up by the next invocation (no loss across drain boundaries).
printf 'FIRST-BODY\n' > "$INBOX"
OUT1=$(run_hook)
printf 'SECOND-BODY\n' > "$INBOX"
OUT2=$(run_hook)
assert_contains "$OUT1" "FIRST-BODY" "first drain delivers first message"
assert_not_contains "$OUT1" "SECOND-BODY" "first drain does not see the later message"
assert_contains "$OUT2" "SECOND-BODY" "next tool call drains the re-written inbox"

# ─── Summary ─────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL PASSED${NC} ($TESTS_PASSED/$TESTS_RUN)"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit "$TESTS_FAILED"
