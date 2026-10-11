#!/usr/bin/env bash
# test-session-context.sh — SessionStart context-budget tests, split out of
# tests/test-hooks.sh when the combined file crossed the 1500-line rule.
#
#   session-context.sh      SessionStart context BUDGET: rules tail, whole
#                           lines, drop notice, file caps, ceiling warning,
#                           conversation-mode projects
#
# Every path is redirected to throwaway dirs under /tmp; the real ~/.claude is
# never touched. No API calls.
#
# Usage:
#   bash tests/test-session-context.sh        # Run all tests
#   bash tests/test-session-context.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION_CONTEXT="$REPO_ROOT/configs/hooks/session-context.sh"

# ─── Test framework (mirrors tests/test-hooks.sh) ────────────────────
TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
VERBOSE="${1:-}"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'

pass() { TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
  return 0
}
section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }

assert_eq() {
  local got="$1" want="$2" msg="$3"
  if [[ "$got" == "$want" ]]; then pass "$msg"
  else fail "$msg" "got '$got', want '$want'"; fi
}
assert_contains() {
  local haystack="$1" needle="$2" msg="$3"
  if grep -qF "$needle" <<< "$haystack"; then pass "$msg"
  else
    fail "$msg" "output does not contain '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -8 <<< "$haystack")"
  fi
}
assert_not_contains() {
  local haystack="$1" needle="$2" msg="$3"
  if grep -qF "$needle" <<< "$haystack"; then
    fail "$msg" "output unexpectedly contains '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -8 <<< "$haystack")"
  else pass "$msg"; fi
}

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found — skipping (CI installs jq)"; exit 0
fi

# ─── Sandbox ─────────────────────────────────────────────────────────
TMP_ROOT="$(mktemp -d /tmp/clade-session-context-test-XXXXXX)"
case "$TMP_ROOT" in
  /tmp/clade-session-context-test-*) : ;;
  *) echo "FATAL: sandbox '$TMP_ROOT' is not under /tmp — aborting"; exit 1 ;;
esac
trap 'rm -rf "$TMP_ROOT"' EXIT
export HOME="$TMP_ROOT/home"
mkdir -p "$HOME/.claude"

# ─── session-context.sh — SessionStart context budget ────────────────
# A real 2026-09-02 injection measured 24,057 chars, 82.7% of it the
# correction-rules block (`tail -25` of a file with no byte cap). The 20KB
# skill catalog deleted in 8406ed4 pushed hook output past the harness inline
# limit (30.8KB) and the WHOLE additionalContext was silently written to a file
# instead of entering context. These assertions are what keeps that measured.

section "session-context.sh — context budget"

BUDGET_HOME="$TMP_ROOT/budget-home"
mkdir -p "$BUDGET_HOME/.claude/corrections"
# Freeze the audit clock: run_auto_audit rewrites rules.md when .last-audit is
# stale, which would make every assertion below depend on wall time.
touch "$BUDGET_HOME/.claude/corrections/.last-audit"
GRULES="$BUDGET_HOME/.claude/corrections/rules.md"

BPROJ="$TMP_ROOT/budget-proj"
mkdir -p "$BPROJ"
git -C "$BPROJ" init -q -b main . >/dev/null 2>&1
git -C "$BPROJ" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init >/dev/null 2>&1

ctx() {  # extra env as KEY=VAL args
  echo '{}' | env "$@" HOME="$BUDGET_HOME" CLAUDE_PROJECT_DIR="$BPROJ" \
    bash "$SESSION_CONTEXT" | jq -r '.hookSpecificOutput.additionalContext // empty'
}

# 200 rules × ~500 bytes ≈ 100KB. Each ends in a unique sentinel so a
# mid-sentence cut is detectable.
: > "$GRULES"
for i in $(seq -w 1 200); do
  printf -- '- [2026-09-01] domain-%s (edge-case): %s #RULE-%s-END\n' \
    "$i" "$(head -c 440 < /dev/zero | tr '\0' 'x')" "$i" >> "$GRULES"
done

OUT=$(ctx CLADE_X=1)
assert_eq "$?" "0" "session-context exits 0 with a 100KB rules file"

# BUDGET HOLDS — without the fix this is ~24,000 and the assertion fails by an
# order of magnitude.
if [[ ${#OUT} -lt 12000 ]]; then
  pass "a 100KB rules.md yields an injection under 12,000 chars (${#OUT})"
else
  fail "a 100KB rules.md yields an injection under 12,000 chars" "got ${#OUT}"
fi

# WHOLE LINES ONLY: every rule that starts also ends. A byte cut would leave a
# started rule with no sentinel.
starts=$(grep -o -- '- \[2026-09-01\] domain-[0-9]*' <<< "$OUT" | wc -l | tr -d ' ')
ends=$(grep -o '#RULE-[0-9]*-END' <<< "$OUT" | wc -l | tr -d ' ')
assert_eq "$ends" "$starts" "every emitted rule is a whole line (no mid-rule byte cut)"
[[ "$ends" -gt 0 ]] \
  && pass "the budget keeps at least one rule ($ends kept)" \
  || fail "the budget keeps at least one rule" "kept none"

# NEWEST KEPT: recency is the whole point of a tail.
assert_contains "$OUT" "#RULE-200-END" "the newest rule survives the budget"
if grep -q '#RULE-001-END' <<< "$OUT"; then
  fail "the oldest rule is dropped" "RULE-001 is still injected"
else
  pass "the oldest rule is dropped"
fi

# DROP NOTICE, with the count and the tool that fixes the cause.
notice=$(grep -oE '\([0-9]+ older rules not shown[^)]*\)' <<< "$OUT" | head -1)
if [[ -n "$notice" ]]; then
  pass "the dropped rules are reported, not silently discarded"
else
  fail "the dropped rules are reported, not silently discarded" "no notice in output"
fi
assert_contains "$notice" "/audit" "the drop notice names the tool that fixes the cause"
dropped=$(sed -E 's/^\(([0-9]+).*/\1/' <<< "$notice")
assert_eq "$dropped" "$(( 200 - ends ))" "the reported drop count matches what was withheld"

# ENV OVERRIDE is wired (settings/wiring is the failure pattern this repo keeps hitting).
OUT_SMALL=$(ctx CLADE_RULES_BUDGET_BYTES=800)
small_ends=$(grep -o '#RULE-[0-9]*-END' <<< "$OUT_SMALL" | wc -l | tr -d ' ')
if [[ "$small_ends" -lt "$ends" && "$small_ends" -gt 0 ]]; then
  pass "CLADE_RULES_BUDGET_BYTES=800 shrinks the block ($ends → $small_ends rules)"
else
  fail "CLADE_RULES_BUDGET_BYTES=800 shrinks the block" "$ends → $small_ends"
fi

# NO NOTICE WHEN IT FITS, and every rule is verbatim.
: > "$GRULES"
for i in 1 2 3; do
  printf -- '- [2026-09-01] tiny-%s (edge-case): short rule %s #RULE-00%s-END\n' "$i" "$i" "$i" >> "$GRULES"
done
OUT=$(ctx CLADE_X=1)
if grep -q 'older rules not shown' <<< "$OUT"; then
  fail "no drop notice when everything fits" "notice present with only 3 rules"
else
  pass "no drop notice when everything fits"
fi
for i in 1 2 3; do
  assert_contains "$OUT" "#RULE-00$i-END" "small rules.md is injected in full (rule $i)"
done

# BOTH SOURCES REPRESENTED: the project file must not starve the global one.
mkdir -p "$BPROJ/.claude/corrections"
touch "$BPROJ/.claude/corrections/.last-audit"
: > "$GRULES"
: > "$BPROJ/.claude/corrections/rules.md"
for i in $(seq -w 1 60); do
  printf -- '- [2026-09-01] g-%s (edge-case): %s #RULE-%s-END\n' \
    "$i" "$(head -c 440 < /dev/zero | tr '\0' 'g')" "$i" >> "$GRULES"
  printf -- '- [2026-09-01] p-%s (edge-case): %s #PROJ-%s-END\n' \
    "$i" "$(head -c 440 < /dev/zero | tr '\0' 'p')" "$i" >> "$BPROJ/.claude/corrections/rules.md"
done
OUT=$(ctx CLADE_X=1)
assert_contains "$OUT" "#PROJ-60-END" "the newest project rule is injected"
assert_contains "$OUT" "#RULE-60-END" "the global file is not starved to zero by the project half"

# HANDOFF CAP: an unbounded handoff was the next overflow waiting to happen.
# The /pickup imperative is appended AFTER the body, so it must survive.
mkdir -p "$BPROJ/.claude"
head -c 40000 < /dev/zero | tr '\0' 'y' > "$BPROJ/.claude/handoff-2026-09-02.md"
printf '\nHANDOFF-TAIL-SENTINEL\n' >> "$BPROJ/.claude/handoff-2026-09-02.md"
OUT=$(ctx CLADE_X=1)
if [[ ${#OUT} -lt 12000 ]]; then
  pass "a 40KB handoff stays inside the ceiling (${#OUT} chars)"
else
  fail "a 40KB handoff stays inside the ceiling" "got ${#OUT}"
fi
assert_contains "$OUT" "/pickup" "the /pickup imperative survives handoff truncation"
assert_contains "$OUT" "truncated:" "truncation is marked, not silent"
if grep -q 'HANDOFF-TAIL-SENTINEL' <<< "$OUT"; then
  fail "the handoff body is actually capped" "the 40KB tail was injected in full"
else
  pass "the handoff body is actually capped"
fi
rm -f "$BPROJ/.claude/handoff-2026-09-02.md"

# CEILING WARNING: warn, never truncate — the guidance blocks are appended last.
OUT=$(ctx CLADE_CTX_CEILING_BYTES=100)
assert_contains "$OUT" "over the 100 budget" "an over-ceiling payload says so"
assert_contains "$OUT" "Close the loop" "the ceiling warning does not truncate the trailing sections"

# CONVERSATION MODE: a repository that is a conversation, not a codebase,
# declares it with .claude/conversation-mode. It keeps its own lessons and the
# language rule and loses the engineering scaffolding, other projects' rules and
# automatic promotion. Measured on one such repository before the marker
# existed: 103 promoted rules (90,172 chars) loaded into every chat.
section "session-context.sh — conversation-mode projects"
printf -- '- [2026-09-01] g-1 (edge-case): a global engineering rule #GLOBAL-RULE-END\n' > "$GRULES"
# Ten rules: run_auto_audit does nothing below ten (auto-audit.sh, count_rules).
: > "$BPROJ/.claude/corrections/rules.md"
for i in $(seq -w 1 10); do
  printf -- '- [2020-01-01] p-old-%s (deploy-gap): an old project lesson #PROJECT-RULE-END\n' "$i" \
    >> "$BPROJ/.claude/corrections/rules.md"
done
rm -f "$BPROJ/.claude/corrections/.last-audit"   # the project audit is due
printf '# proj\n' > "$BPROJ/CLAUDE.md"
printf 'Tailscale IP: 100.64.0.99\n' > "$BUDGET_HOME/.claude/.env-fingerprint"   # fresh cache
touch "$BPROJ/.claude/conversation-mode"
OUT=$(ctx CLADE_X=1)
assert_contains "$OUT" "#PROJECT-RULE-END" "conversation mode keeps the project's own lessons"
assert_contains "$OUT" "same language the user writes in" "conversation mode keeps the language rule"
if grep -qxF "$BPROJ" "$BUDGET_HOME/.claude/private-projects" 2>/dev/null; then
  pass "conversation mode registers the project as private for sync-push"
else
  fail "conversation mode registers the project as private for sync-push" "not in ~/.claude/private-projects"
fi
for absent in "#GLOBAL-RULE-END" "Model guide" "Close the loop" "Recommended workflow" "Environment Fingerprint"; do
  if grep -qF "$absent" <<< "$OUT"; then
    fail "conversation mode leaves out: $absent" "still injected"
  else
    pass "conversation mode leaves out: $absent"
  fi
done
if grep -q 'Auto-Promoted Rules' "$BPROJ/CLAUDE.md"; then
  fail "conversation mode does not promote project rules into CLAUDE.md" "CLAUDE.md gained the block"
else
  pass "conversation mode does not promote project rules into CLAUDE.md"
fi
# Control: the same tree without the marker gets all of it back, so the
# assertions above cannot pass because the sections were simply absent.
rm -f "$BPROJ/.claude/conversation-mode"
OUT=$(ctx CLADE_X=1)
assert_contains "$OUT" "#GLOBAL-RULE-END" "control: without the marker, other projects' rules are injected"
assert_contains "$OUT" "Close the loop" "control: without the marker, the engineering guidance is back"
assert_contains "$OUT" "Environment Fingerprint" "control: without the marker, the host fingerprint is back"
grep -q 'Auto-Promoted Rules' "$BPROJ/CLAUDE.md" \
  && pass "control: without the marker, the due project audit promotes the rule" \
  || fail "control: without the marker, the due project audit promotes the rule" "no promotion happened"
rm -f "$BUDGET_HOME/.claude/.env-fingerprint"


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
