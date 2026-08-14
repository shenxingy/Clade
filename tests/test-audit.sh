#!/usr/bin/env bash
# test-audit.sh — Tests for the auto-audit escalation path:
#   configs/hooks/auto-audit.sh (3+-hit rules → REQUIRED structural escalation)
#
# Verifies the Nth-strike doctrine: rules with 3+ effectiveness hits surface
# in AUDIT_SUMMARY as a REQUIRED action (convert to hook, retire the prose
# rule), not a take-it-or-leave-it suggestion. Uses a throwaway $HOME under
# /tmp; never touches the real ~/.claude.
#
# Usage:
#   bash tests/test-audit.sh        # Run all tests
#   bash tests/test-audit.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUTO_AUDIT="$REPO_ROOT/configs/hooks/auto-audit.sh"

# ─── Test framework (mirrors tests/test-checks.sh) ───────────────────
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
VERBOSE="${1:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
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

# ─── Helpers ─────────────────────────────────────────────────────────

# Build a throwaway $HOME with 10 recent rules (recent = no promote/archive
# churn during the run) and an effectiveness file with the given JSON body.
# Echoes the fake HOME path.
make_home() {
  local effectiveness_json="$1"
  local d
  d="$(mktemp -d /tmp/clade-test-audit.XXXXXX)"
  mkdir -p "$d/.claude/corrections"
  local recent
  recent="$(date -d '2 days ago' +%Y-%m-%d 2>/dev/null || date -v-2d +%Y-%m-%d)"
  local i
  for i in $(seq 1 10); do
    echo "- [$recent] domain$i (edge-case): test rule number $i, unique text" \
      >> "$d/.claude/corrections/rules.md"
  done
  : > "$d/.claude/CLAUDE.md"
  echo "$effectiveness_json" > "$d/.claude/corrections/rule-effectiveness.json"
  echo "$d"
}

# Source auto-audit.sh under the fake HOME (must be exported BEFORE sourcing —
# rule-effectiveness.sh resolves EFFECTIVENESS_FILE at source time), run the
# global audit, and print the resulting AUDIT_SUMMARY.
run_audit() {
  local fake_home="$1"
  (
    export HOME="$fake_home"
    # shellcheck source=/dev/null
    source "$AUTO_AUDIT"
    run_auto_audit "global" 2>/dev/null
    echo -e "${AUDIT_SUMMARY:-}"
  )
}

# ─── 3+ hits → REQUIRED escalation ───────────────────────────────────
echo "── 3+ hits → REQUIRED structural escalation ──"

H="$(make_home '{"abcd1234": {"hits": 4, "misses": 0, "last_event": "2026-06-10T00:00:00Z"}}')"
OUT="$(run_audit "$H")"
assert_contains "$OUT" "[REQUIRED]" "3+-hit rule surfaces as REQUIRED, not advisory"
assert_contains "$OUT" "abcd1234" "escalation names the rule hash"
assert_contains "$OUT" "/generate-hook" "escalation instructs running /generate-hook"
assert_contains "$OUT" "retire the prose rule to retired-rules.md" "escalation instructs retiring the prose rule"
assert_contains "$OUT" "REQUIRED — escalate to structural enforcement" "summary header frames the block as required action"
rm -rf "$H"

# ─── Below threshold → no escalation ─────────────────────────────────
echo "── below threshold → no escalation ──"

# 2 total events: under the 3-event floor in get_effective_rules
H="$(make_home '{"beef0001": {"hits": 2, "misses": 0, "last_event": "2026-06-10T00:00:00Z"}}')"
OUT="$(run_audit "$H")"
assert_not_contains "$OUT" "[REQUIRED]" "2-hit rule does not trigger escalation"
assert_contains "$OUT" "Auto-audit" "audit still runs and reports without escalation"
rm -rf "$H"

# Low hit-rate rule (effective-rules filter requires >= 70% hits)
H="$(make_home '{"cafe0002": {"hits": 1, "misses": 4, "last_event": "2026-06-10T00:00:00Z"}}')"
OUT="$(run_audit "$H")"
assert_not_contains "$OUT" "[REQUIRED]" "low hit-rate rule does not trigger escalation"
rm -rf "$H"

# ─── Summary ─────────────────────────────────────────────────────────


# ─── Severity gate on CLAUDE.md promotion ────────────────────────────
# Age used to be the entire promotion test, so surviving 14 days wrote a rule
# into every future session's context. 28 of 42 promoted rules were the weakest
# class (`edge-case`) before this gate existed.
echo "── severity gate: only damaging root causes reach CLAUDE.md ──"

make_aged_home() {
  local d; d="$(mktemp -d)"
  mkdir -p "$d/.claude/corrections"
  local old ancient i
  old="$(date -d '30 days ago' +%Y-%m-%d 2>/dev/null || date -v-30d +%Y-%m-%d)"
  ancient="$(date -d '70 days ago' +%Y-%m-%d 2>/dev/null || date -v-70d +%Y-%m-%d)"
  {
    echo "- [$old] auth (security): sanitize the token before logging it"
    echo "- [$old] deploy (deploy-gap): config defined is not config loaded"
    echo "- [$old] race (async-race): kill and drain the subprocess on timeout"
    echo "- [$old] wiring (settings-disconnect): setting defined but never read"
    echo "- [$old] ui (edge-case): remember sidebar width across reloads"
    echo "- [$ancient] style (edge-case): ancient low-severity rule that ages out"
    for i in $(seq 1 8); do
      echo "- [$old] filler$i (edge-case): filler rule number $i, unique text"
    done
  } > "$d/.claude/corrections/rules.md"
  : > "$d/.claude/CLAUDE.md"
  echo "$d"
}

H="$(make_aged_home)"
OUT="$(run_audit "$H")"
PROMOTED="$(grep -cE '^- \[' "$H/.claude/CLAUDE.md" 2>/dev/null || echo 0)"

assert_contains "$OUT" "withheld (low-severity)" "reports withheld count instead of silently dropping"
[[ "$PROMOTED" -eq 4 ]] \
  && pass "exactly the 4 damaging root causes reached CLAUDE.md" \
  || fail "expected 4 promotions, got $PROMOTED"
grep -q "security" "$H/.claude/CLAUDE.md" \
  && pass "security rule promoted" || fail "security rule was not promoted"
grep -q "edge-case" "$H/.claude/CLAUDE.md" \
  && fail "edge-case rule leaked into CLAUDE.md" \
  || pass "edge-case refused, not promoted"
grep -q "sidebar width" "$H/.claude/corrections/rules.md" \
  && pass "withheld rule stays in rules.md for /audit" \
  || fail "withheld rule vanished instead of awaiting human review"
grep -q "ancient low-severity" "$H/.claude/corrections/rules-archive.md" 2>/dev/null \
  && pass "60-day withheld rule still ages out (withholding cannot pin it)" \
  || fail "withheld rule was never archived — rules.md would grow forever"
rm -rf "$H"


echo ""
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL $TESTS_RUN TESTS PASSED${NC}"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
exit $TESTS_FAILED