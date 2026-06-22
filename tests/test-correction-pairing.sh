#!/usr/bin/env bash
# test-correction-pairing.sh — Tests for the correction-PAIRING pipeline:
#   edit-shadow-detector.sh  (records files Claude writes, keyed by session_id)
#   revert-detector.sh       (cross-refs the shadow → reverted_files + repeat)
#   correction-detector.sh   (surfaces the rejected files on an EXPLICIT correction)
#   lib/correction-pair.sh   (shared session-key + shadow-read helpers)
#
# All state is redirected to throwaway HOME / project / shadow dirs under /tmp;
# the real ~/.claude is never touched. No API calls.
#
# Usage:
#   bash tests/test-correction-pairing.sh        # Run all tests
#   bash tests/test-correction-pairing.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHADOW_HOOK="$REPO_ROOT/configs/hooks/edit-shadow-detector.sh"
REVERT_HOOK="$REPO_ROOT/configs/hooks/revert-detector.sh"
CORRECTION_HOOK="$REPO_ROOT/configs/hooks/correction-detector.sh"

# ─── Test framework (mirrors tests/test-rule-injector.sh) ────────────
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
assert_not_contains() {
  local haystack="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if grep -qF "$needle" <<< "$haystack"; then
    fail "$msg" "output unexpectedly contains '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -8 <<< "$haystack")"
  else pass "$msg"; fi
}

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found — skipping (CI installs jq)"; exit 0
fi

# ─── Sandbox ─────────────────────────────────────────────────────────
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT
export HOME="$TMP_ROOT/home"
export CP_SHADOW_DIR="$TMP_ROOT/shadows"
mkdir -p "$HOME/.claude" "$CP_SHADOW_DIR"
HISTORY="$HOME/.claude/corrections/history.jsonl"

PROJ="$TMP_ROOT/proj"
mkdir -p "$PROJ/.git"           # makes it a "real" project (project-local rules path)
echo "# proj" > "$PROJ/CLAUDE.md"

SID="11111111-2222-3333-4444-555555555555"

shadow_in()    { jq -n --arg f "$1" --arg s "$2" '{tool_input:{file_path:$f}, session_id:$s}'; }
revert_in()    { jq -n --arg c "$1" --arg s "$2" '{tool_name:"Bash", tool_input:{command:$c}, session_id:$s}'; }
correct_in()   { jq -n --arg p "$1" --arg s "$2" '{prompt:$p, session_id:$s}'; }

# ─── 1. edit-shadow keys by session_id ───────────────────────────────
section "edit-shadow-detector — session_id keying"
shadow_in "$PROJ/src/app.py" "$SID" | bash "$SHADOW_HOOK"
shadow_in "$PROJ/src/util.py" "$SID" | bash "$SHADOW_HOOK"
SFILE="$CP_SHADOW_DIR/session-$SID.jsonl"
TESTS_RUN=$((TESTS_RUN + 1))
if [[ -f "$SFILE" ]]; then pass "shadow file created under session_id key"
else fail "shadow file created under session_id key" "missing $SFILE"; fi
assert_contains "$(cat "$SFILE" 2>/dev/null)" "src/app.py" "shadow records the written file"

# ─── 2. revert-detector pairs the rejected files from the shadow ─────
section "revert-detector — reverted_files (the labeled pair)"
revert_in "git reset --hard HEAD~1" "$SID" | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
LAST=$(tail -n 1 "$HISTORY" 2>/dev/null)
assert_contains "$LAST" '"type":"implicit-revert"' "revert logged as implicit-revert"
assert_contains "$LAST" "src/app.py" "revert record carries the rejected file (app.py)"
assert_contains "$LAST" "src/util.py" "revert record carries the rejected file (util.py)"
assert_contains "$LAST" '"repeat":false' "first revert of these files is not a repeat"

# ─── 3. repeat detection on a second overlapping revert ──────────────
section "revert-detector — repeat flag"
revert_in "git checkout -- src/app.py" "$SID" | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_contains "$(tail -n 1 "$HISTORY")" '"repeat":true' "second revert of app.py flagged repeat=true"

# ─── 4. explicit correction surfaces the concrete pair (gate: open) ──
section "correction-detector — concrete signal on explicit correction"
OUT=$(correct_in "no, that's wrong — revert it, use the config value instead" "$SID" \
        | CLAUDE_PROJECT_DIR="$PROJ" bash "$CORRECTION_HOOK")
CTX=$(jq -r '.hookSpecificOutput.additionalContext // ""' <<< "$OUT" 2>/dev/null)
assert_contains "$CTX" "Concrete signal" "explicit correction injects the concrete-signal block"
assert_contains "$CTX" "src/app.py" "concrete signal lists the rejected file"

# ─── 5. GATE: no recent rejected change → no concrete signal (no noise) ─
section "correction-detector — gate stays shut without a rejected change"
PROJ2="$TMP_ROOT/proj2"; mkdir -p "$PROJ2/.git"; echo "# p2" > "$PROJ2/CLAUDE.md"
OUT2=$(correct_in "no, use tabs instead" "no-shadow-session-xyz" \
        | CLAUDE_PROJECT_DIR="$PROJ2" bash "$CORRECTION_HOOK")
CTX2=$(jq -r '.hookSpecificOutput.additionalContext // ""' <<< "$OUT2" 2>/dev/null)
assert_contains "$CTX2" "A user correction was detected" "correction still fires normally"
assert_not_contains "$CTX2" "Concrete signal" "no concrete-signal block when nothing was rejected"

# ─── 6. session-key fallback when session_id absent ──────────────────
section "lib — \$PPID fallback when session_id missing"
echo '{"tool_input":{"file_path":"/tmp/x/nokey.py"}}' | bash "$SHADOW_HOOK"
TESTS_RUN=$((TESTS_RUN + 1))
if ls "$CP_SHADOW_DIR"/session-pid-*.jsonl >/dev/null 2>&1; then
  pass "falls back to a pid-keyed shadow file without session_id"
else fail "falls back to a pid-keyed shadow file without session_id" "no session-pid-* file"; fi

# ─── Summary ─────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  Ran: $TESTS_RUN  ${GREEN}Passed: $TESTS_PASSED${NC}  ${RED}Failed: $TESTS_FAILED${NC}"
[[ "$TESTS_FAILED" -eq 0 ]] && { echo -e "  ${GREEN}ALL PASSED${NC}"; exit 0; } || { echo -e "  ${RED}FAILURES${NC}"; exit 1; }
