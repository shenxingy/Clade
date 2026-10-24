#!/usr/bin/env bash
# test-session-scorecard.sh — Tests for configs/scripts/session-scorecard.sh
#
# The counters this guards were structurally 0 for the life of the file: they
# used a 3-argument awk match(), a gawk extension that mawk (the Debian/Ubuntu
# default) and BSD awk both reject, and `2>/dev/null || echo 0` turned the
# syntax error into a plausible zero. Its regex was also spacing-sensitive, so
# even on gawk it saw only the minority `"timestamp":"..."` records. Every
# scorecard on disk read score=1.00, corrections=0.
#
# All state is redirected to a throwaway HOME under /tmp; the real ~/.claude is
# never touched. No API calls.
#
# Usage:
#   bash tests/test-session-scorecard.sh        # Run all tests
#   bash tests/test-session-scorecard.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCORECARD="$REPO_ROOT/configs/scripts/session-scorecard.sh"

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

assert_eq() {
  local got="$1" want="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "$got" == "$want" ]]; then pass "$msg"
  else fail "$msg" "got '$got', want '$want'"; fi
}

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found — skipping (CI installs jq)"; exit 0
fi

TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CASE_N=0

# new_case — fresh throwaway HOME + non-git project dir, assigned to $D.
# Assigns rather than echoes: `new_case` would bump the counter in a
# SUBSHELL, every case would reuse one sandbox, and the cases would contaminate
# each other's history and scorecard files.
new_case() {
  CASE_N=$((CASE_N + 1))
  D="$TMP_ROOT/case$CASE_N"
  mkdir -p "$D/home/.claude/corrections" "$D/proj"
}
# run_scorecard <case_dir> — run the script against that sandbox.
run_scorecard() {
  ( HOME="$1/home" CLAUDE_PROJECT_DIR="$1/proj" bash "$SCORECARD" ) >/dev/null 2>&1
}
last_field() {   # <case_dir> <jq path>
  jq -rs "last | $2" "$1/home/.claude/corrections/scorecards.jsonl" 2>/dev/null
}
rec_spaced()  { printf '{"timestamp": "%s", "prompt": "x", "project": "/p", "type": "%s"}\n' "$1" "$2"; }
rec_compact() { printf '{"timestamp":"%s","prompt":"x","project":"/p","type":"%s"}\n' "$1" "$2"; }

# ─── 1. the spaced serialization is counted ──────────────────────────
# This is the red-phase case: the old awk regex required "timestamp":"…" with no
# space, and on mawk it did not run at all.
section "counting — pretty-spaced records"
new_case; rec_spaced "$NOW" explicit > "$D/home/.claude/corrections/history.jsonl"
run_scorecard "$D"
assert_eq "$(last_field "$D" .corrections)" "1" "a \"timestamp\": \"…\" record is counted"

# ─── 2. the compact serialization is counted ─────────────────────────
section "counting — compact records"
new_case; rec_compact "$NOW" explicit > "$D/home/.claude/corrections/history.jsonl"
run_scorecard "$D"
assert_eq "$(last_field "$D" .corrections)" "1" "a \"timestamp\":\"…\" record is counted"

# ─── 3. both styles in one file ──────────────────────────────────────
section "counting — mixed serializations"
new_case
{ rec_spaced "$NOW" explicit; rec_compact "$NOW" explicit; } > "$D/home/.claude/corrections/history.jsonl"
run_scorecard "$D"
assert_eq "$(last_field "$D" .corrections)" "2" "both serializations counted in one file"

# ─── 4. implicit vs explicit split ───────────────────────────────────
section "counting — implicit vs explicit"
new_case
{ rec_spaced "$NOW" explicit; rec_spaced "$NOW" implicit-revert; } > "$D/home/.claude/corrections/history.jsonl"
run_scorecard "$D"
assert_eq "$(last_field "$D" .corrections)" "1" "explicit counted separately"
assert_eq "$(last_field "$D" .implicit_corrections)" "1" "implicit-revert counted as implicit"

# ─── 4b. a mutation probe is not a correction ────────────────────────
# revert-detector.sh records the mutation test the global CLAUDE.md requires as
# `revert_scope:"probe"` and strips its evidence, because it is not a rejection.
# This counter was the one reader still charging it −0.05: 11 of the 220
# implicit-revert records of 2026-09-22 → 10-22 on the author's machine.
section "counting — a probe is not an implicit correction"
rec_probe() { printf '{"timestamp":"%s","prompt":"x","project":"/p","type":"implicit-revert","revert_scope":"%s"}\n' "$1" "$2"; }
# probe_case <scorecard script> — one probe + one real revert; the implicit
# count lands in PROBE_IMPLICIT. Called directly, never in $(…): new_case must
# bump CASE_N in THIS shell, or the next case reuses this sandbox (see new_case).
probe_case() {
  new_case
  { rec_probe "$NOW" probe; rec_probe "$NOW" paths; } > "$D/home/.claude/corrections/history.jsonl"
  ( HOME="$D/home" CLAUDE_PROJECT_DIR="$D/proj" bash "$1" ) >/dev/null 2>&1
  PROBE_IMPLICIT=$(last_field "$D" .implicit_corrections)
}
probe_case "$SCORECARD"
assert_eq "$PROBE_IMPLICIT" "1" "a probe record is not counted; the real revert beside it is"

# Mutation: the same case against a copy without the filter must count both.
# An anchor that no longer occurs exactly once is a failure, not a skip.
SC_MUT="$TMP_ROOT/scripts-mut/session-scorecard.sh"
mkdir -p "$(dirname "$SC_MUT")"
ln -s "$REPO_ROOT/configs/hooks" "$TMP_ROOT/hooks"   # the script sources ../hooks/lib
if MUT_A='    | select((.revert_scope // "") != "probe")
' awk '
    { buf = buf $0 "\n" }
    END {
      a = ENVIRON["MUT_A"]; s = buf; out = ""; n = 0
      while ((i = index(s, a)) > 0) { out = out substr(s, 1, i - 1); s = substr(s, i + length(a)); n++ }
      if (n != 1) exit 3
      printf "%s", out s
    }' "$SCORECARD" > "$SC_MUT"; then
  probe_case "$SC_MUT"
  assert_eq "$PROBE_IMPLICIT" "2" "mutant without the probe filter counts the probe again"
else
  TESTS_RUN=$((TESTS_RUN + 1))
  fail "mutation 'the probe filter': its anchor no longer matches the script exactly once"
fi

# ─── 5. records outside the window are excluded ──────────────────────
section "window — old records excluded"
new_case
{ rec_spaced "2001-01-01T00:00:00Z" explicit; rec_spaced "$NOW" explicit; } \
  > "$D/home/.claude/corrections/history.jsonl"
run_scorecard "$D"
assert_eq "$(last_field "$D" .corrections)" "1" "a record from 2001 is outside the 4h window"

# ─── 6. a corrupt line does not eat the rest of the file ─────────────
# history.jsonl has been spliced by interleaved concurrent appends before, and a
# whole-stream parse (jq -s) aborts at the first bad byte and silently loses
# every record after it. Forbids that regression.
section "robustness — corrupt line tolerated"
new_case
{ rec_spaced "$NOW" explicit
  printf '{"timestamp": "%s", "prompt": "trunc\n' "$NOW"
  rec_spaced "$NOW" explicit; } > "$D/home/.claude/corrections/history.jsonl"
run_scorecard "$D"
assert_eq "$(last_field "$D" .corrections)" "2" "records after a spliced line still counted"

# ─── 7. the scorecard file is really JSONL ───────────────────────────
section "writer — one line per scorecard"
new_case; rec_spaced "$NOW" explicit > "$D/home/.claude/corrections/history.jsonl"
run_scorecard "$D"
assert_eq "$(wc -l < "$D/home/.claude/corrections/scorecards.jsonl" | tr -d ' ')" "1" \
  "one run appends exactly one line"

# ─── 8. the window advances between runs ─────────────────────────────
# `jq -n` (no -c) made this file pretty-printed, so `tail -1 | jq` saw the single
# character `}` and always failed — SINCE fell back to the 4h default forever.
section "window — advances to the previous scorecard"
new_case; rec_spaced "$NOW" explicit > "$D/home/.claude/corrections/history.jsonl"
run_scorecard "$D"
FIRST_TS=$(last_field "$D" .timestamp)
run_scorecard "$D"
assert_eq "$(last_field "$D" .since)" "$FIRST_TS" "second run windows from the first run's timestamp"

# ─── 9. a legacy pretty-printed scorecard is still readable ──────────
section "window — legacy pretty records still parse"
new_case
printf '{\n  "timestamp": "2030-01-01T00:00:00Z",\n  "since": "2029-01-01T00:00:00Z",\n  "corrections": 0\n}\n' \
  > "$D/home/.claude/corrections/scorecards.jsonl"
run_scorecard "$D"
assert_eq "$(last_field "$D" .since)" "2030-01-01T00:00:00Z" "window picks up a pre-2026-09 pretty record"

# ─── 10. no gawk-only construct reintroduced ─────────────────────────
section "portability — no 3-argument awk match()"
TESTS_RUN=$((TESTS_RUN + 1))
GAWKISM='^[^#]*match\([^)]*,[^)]*,'   # ^[^#]* so the comment explaining the ban does not trip it
if grep -nE "$GAWKISM" "$SCORECARD" >/dev/null 2>&1; then
  fail "no gawk-only 3-argument match()" "$(grep -nE "$GAWKISM" "$SCORECARD" | head -2)"
else pass "no gawk-only 3-argument match()"; fi

# ─── 11. missing history file stays fail-open ────────────────────────
section "fail-open — no history file"
new_case
TESTS_RUN=$((TESTS_RUN + 1))
if run_scorecard "$D"; then pass "exits 0 with no history file"
else fail "exits 0 with no history file" "non-zero exit"; fi
assert_eq "$(last_field "$D" .corrections)" "0" "corrections is 0 with no history file"

# ─── Summary ─────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  Ran: $TESTS_RUN  ${GREEN}Passed: $TESTS_PASSED${NC}  ${RED}Failed: $TESTS_FAILED${NC}"
[[ "$TESTS_FAILED" -eq 0 ]] && { echo -e "  ${GREEN}ALL PASSED${NC}"; exit 0; } || { echo -e "  ${RED}FAILURES${NC}"; exit 1; }
