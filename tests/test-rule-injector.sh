#!/usr/bin/env bash
# test-rule-injector.sh — Tests for configs/hooks/rule-injector.sh
#   (PostToolUse Edit|Write: path-scoped rule injection from .claude/rules/)
#
# Pipes fixture hook-input JSON through the hook against throwaway project +
# HOME dirs under /tmp; never touches the real ~/.claude. Covers: project and
# global match, comma + YAML-list `paths:` forms, basename globs, globstar
# semantics ('*' must not cross '/'), once-per-session dedup, missing rules
# dir, malformed frontmatter, and missing input fields.
#
# Usage:
#   bash tests/test-rule-injector.sh        # Run all tests
#   bash tests/test-rule-injector.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$REPO_ROOT/configs/hooks/rule-injector.sh"

# ─── Test framework (mirrors tests/test-audit.sh) ────────────────────
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

# ─── Sandbox ─────────────────────────────────────────────────────────

SANDBOX="$(mktemp -d /tmp/clade-test-rule-injector-XXXXXX)"
case "$SANDBOX" in
  /tmp/clade-test-rule-injector-*) : ;;
  *) echo "FATAL: sandbox '$SANDBOX' not under /tmp — aborting"; exit 1 ;;
esac
cleanup() { rm -rf "$SANDBOX"; }
trap cleanup EXIT

PROJ="$SANDBOX/proj"
FAKE_HOME="$SANDBOX/home"
mkdir -p "$PROJ/.claude/rules" "$FAKE_HOME/.claude/rules"

# Fixture rule files ──────────────────────────────────────────────────

# Project rule, inline comma-separated paths (incl. quoted bare glob)
cat > "$PROJ/.claude/rules/python-style.md" <<'EOF'
---
paths: orchestrator/**/*.py, "tests/*.py"
---
PYTHON-RULE-BODY: type hints on all new functions.
EOF

# Project rule, narrow single-star glob (must NOT match nested dirs)
cat > "$PROJ/.claude/rules/narrow.md" <<'EOF'
---
paths: orchestrator/*.py
---
NARROW-RULE-BODY
EOF

# Project file WITHOUT paths frontmatter — must always be ignored
cat > "$PROJ/.claude/rules/no-frontmatter.md" <<'EOF'
NO-FRONTMATTER-BODY: this file is not path-scoped and must never inject.
EOF

# Project file with unclosed frontmatter — malformed, must never inject
cat > "$PROJ/.claude/rules/malformed.md" <<'EOF'
---
paths: **/*.py
MALFORMED-BODY: frontmatter never closed.
EOF

# Global rule, YAML-list paths with a basename glob
cat > "$FAKE_HOME/.claude/rules/css-rules.md" <<'EOF'
---
paths:
  - "*.css"
  - "*.scss"
---
CSS-RULE-BODY: never overflow:hidden on popover containers.
EOF

# Hook-input fixture: $1=session_id $2=file_path
fixture() {
  printf '{"session_id":"%s","tool_name":"Edit","tool_input":{"file_path":"%s"}}' "$1" "$2"
}

# Run the hook with sandboxed HOME + project
run_hook() {
  HOME="$FAKE_HOME" CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK"
}

# ─── Suite 1: Matching ───────────────────────────────────────────────

section "Glob matching"

OUT=$(fixture s-match "$PROJ/orchestrator/sub/worker.py" | run_hook)
assert_contains "$OUT" "PYTHON-RULE-BODY" "** glob matches nested project file"
assert_contains "$OUT" "hookSpecificOutput" "output is hookSpecificOutput JSON"
assert_contains "$OUT" "additionalContext" "rule body emitted via additionalContext"
assert_not_contains "$OUT" "NARROW-RULE-BODY" "single * does not cross '/' (orchestrator/*.py vs nested file)"
assert_not_contains "$OUT" "CSS-RULE-BODY" "non-matching global rule not injected"
assert_not_contains "$OUT" "NO-FRONTMATTER-BODY" "file without paths frontmatter ignored"
assert_not_contains "$OUT" "MALFORMED-BODY" "unclosed frontmatter never injects"

TESTS_RUN=$((TESTS_RUN + 1))
if command -v jq >/dev/null 2>&1 && jq -e '.hookSpecificOutput.additionalContext' <<< "$OUT" >/dev/null 2>&1; then
  pass "output parses as JSON with .hookSpecificOutput.additionalContext"
else
  fail "output parses as JSON with .hookSpecificOutput.additionalContext"
fi

OUT=$(fixture s-narrow "$PROJ/orchestrator/worker.py" | run_hook)
assert_contains "$OUT" "NARROW-RULE-BODY" "single * matches file directly in the dir"
assert_contains "$OUT" "PYTHON-RULE-BODY" "multiple matching rules injected together"

OUT=$(fixture s-css "$PROJ/web/src/app.css" | run_hook)
assert_contains "$OUT" "CSS-RULE-BODY" "global bare glob (*.css) matches by basename anywhere"
assert_contains "$OUT" "(global)" "global rule labeled with its scope"

OUT=$(fixture s-quoted "$PROJ/tests/test_x.py" | run_hook)
assert_contains "$OUT" "PYTHON-RULE-BODY" "quoted comma-list glob (tests/*.py) matches"

# ─── Suite 2: No match / failure paths ───────────────────────────────

section "No-match and failure paths"

OUT=$(fixture s-nomatch "$PROJ/README.md" | run_hook); RC=$?
assert_empty "$OUT" "non-matching file produces no output"
assert_rc_zero "$RC" "non-matching file exits 0"

OUT=$(printf '{"session_id":"s-nofp","tool_name":"Edit","tool_input":{}}' | run_hook); RC=$?
assert_empty "$OUT" "missing tool_input.file_path produces no output"
assert_rc_zero "$RC" "missing file_path exits 0"

OUT=$(printf 'not json at all' | run_hook); RC=$?
assert_empty "$OUT" "garbage stdin produces no output"
assert_rc_zero "$RC" "garbage stdin exits 0"

# Missing rules dirs entirely (fresh project, fresh HOME)
EMPTY_PROJ="$SANDBOX/empty-proj"
EMPTY_HOME="$SANDBOX/empty-home"
mkdir -p "$EMPTY_PROJ" "$EMPTY_HOME"
OUT=$(fixture s-norules "$EMPTY_PROJ/main.py" \
  | HOME="$EMPTY_HOME" CLAUDE_PROJECT_DIR="$EMPTY_PROJ" bash "$HOOK"); RC=$?
assert_empty "$OUT" "missing rules dirs produce no output"
assert_rc_zero "$RC" "missing rules dirs exit 0"

# ─── Suite 3: Once-per-session dedup ─────────────────────────────────

section "Once-per-session dedup"

OUT1=$(fixture s-dedup "$PROJ/orchestrator/sub/worker.py" | run_hook)
assert_contains "$OUT1" "PYTHON-RULE-BODY" "first edit in session injects the rule"

OUT2=$(fixture s-dedup "$PROJ/orchestrator/sub/other.py" | run_hook); RC=$?
assert_not_contains "$OUT2" "PYTHON-RULE-BODY" "second matching edit in SAME session does not re-inject"
assert_rc_zero "$RC" "deduped invocation exits 0"

OUT3=$(fixture s-dedup2 "$PROJ/orchestrator/sub/worker.py" | run_hook)
assert_contains "$OUT3" "PYTHON-RULE-BODY" "new session id re-injects the rule"

TESTS_RUN=$((TESTS_RUN + 1))
if [[ -f "$PROJ/.claude/sessions/s-dedup.rules-injected" ]]; then
  pass "sentinel file written under .claude/sessions/<sid>.rules-injected"
else
  fail "sentinel file written under .claude/sessions/<sid>.rules-injected"
fi

# Dedup is per rule file: css rule still injects in a session that already
# consumed the python rule
OUT4=$(fixture s-dedup "$PROJ/web/app.css" | run_hook)
assert_contains "$OUT4" "CSS-RULE-BODY" "dedup is per rule file, not per session globally"

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
