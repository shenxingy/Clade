#!/usr/bin/env bash
# test-post-compact-reinject.sh — Tests for post-compact-reinject.sh
#
# The SessionStart(compact) hook that re-injects the PreCompact-saved task goal
# and re-arms path-scoped rules after context compaction. Verifies the wiring
# hole is closed: a startup-only matcher misses source=compact, so this hook is
# the "after" half of the save/reload pair.
#
# All state is redirected to a throwaway project dir under /tmp; the real
# ~/.claude is never touched. No API calls.
#
# Usage:
#   bash tests/test-post-compact-reinject.sh        # Run all tests
#   bash tests/test-post-compact-reinject.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$REPO_ROOT/configs/hooks/post-compact-reinject.sh"

# ─── Test framework (mirrors tests/test-correction-pairing.sh) ───────
TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
VERBOSE="${1:-}"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'

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
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -8 <<< "$haystack")"
  fi
}
assert_empty() {
  local haystack="$1" msg="$2"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -z "$haystack" ]]; then pass "$msg"
  else
    fail "$msg" "expected no output, got: $(head -3 <<< "$haystack")"
  fi
}

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found — skipping (CI installs jq)"; exit 0
fi

# ─── Sandbox ─────────────────────────────────────────────────────────
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

PROJ="$TMP_ROOT/proj"
mkdir -p "$PROJ/.claude/sessions"
SID="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
STATE="$PROJ/.claude/compact-state.md"
SENTINEL="$PROJ/.claude/sessions/${SID}.rules-injected"

compact_in() { jq -n --arg s "$1" --arg src "$2" '{session_id:$s, source:$src}'; }
ctx_of()     { jq -r '.hookSpecificOutput.additionalContext // ""' 2>/dev/null; }

write_state() {
  cat > "$STATE" <<'EOF'
# Pre-compact State: 2026-07-05 12:00

## Current Task
Implement the widget frobnicator per GOAL-42.

## Next Step
Wire frobnicate() into the dispatch table at dispatch.py:88.
EOF
}

# ─── 1. compact source with fresh state → goal re-injected ───────────
section "re-injects the saved goal on source=compact"
write_state
OUT=$(compact_in "$SID" "compact" | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK")
CTX=$(ctx_of <<< "$OUT")
assert_contains "$CTX" "Post-compaction restore" "emits the restore header"
assert_contains "$CTX" "GOAL-42" "carries the verbatim saved task goal"
assert_contains "$CTX" "dispatch.py:88" "carries the verbatim next-step detail"

# ─── 2. clears the path-scoped rule sentinel (re-arm on next edit) ───
section "re-arms path-scoped rules by clearing the sentinel"
printf '%s\n' "$PROJ/.claude/rules/py.md" > "$SENTINEL"
TESTS_RUN=$((TESTS_RUN + 1))
[[ -f "$SENTINEL" ]] && pass "sentinel exists before compaction" \
  || fail "sentinel exists before compaction" "setup failed"
compact_in "$SID" "compact" | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK" >/dev/null
TESTS_RUN=$((TESTS_RUN + 1))
[[ ! -f "$SENTINEL" ]] && pass "sentinel cleared so rules re-inject on next edit" \
  || fail "sentinel cleared so rules re-inject on next edit" "$SENTINEL still present"

# ─── 3. non-compact source (startup) → silent (defensive guard) ──────
section "ignores non-compact sources"
write_state
OUT3=$(compact_in "$SID" "startup" | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK")
assert_empty "$OUT3" "startup source produces no output (startup hook owns that path)"

# ─── 4. stale compact-state (> 2h) → silent (no resurrection) ────────
section "does not resurface stale state"
write_state
if ! touch -d '3 hours ago' "$STATE" 2>/dev/null; then
  touch -t 202001010000 "$STATE" 2>/dev/null || true
fi
OUT4=$(compact_in "$SID" "compact" | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK")
assert_empty "$OUT4" "state older than 2h is not re-injected"

# ─── 5. no compact-state file → silent ───────────────────────────────
section "silent when there is nothing to restore"
rm -f "$STATE"
OUT5=$(compact_in "$SID" "compact" | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK")
assert_empty "$OUT5" "missing compact-state.md produces no output"

# ─── Summary ─────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  Ran: $TESTS_RUN  ${GREEN}Passed: $TESTS_PASSED${NC}  ${RED}Failed: $TESTS_FAILED${NC}"
[[ "$TESTS_FAILED" -eq 0 ]] && { echo -e "  ${GREEN}ALL PASSED${NC}"; exit 0; } || { echo -e "  ${RED}FAILURES${NC}"; exit 1; }
