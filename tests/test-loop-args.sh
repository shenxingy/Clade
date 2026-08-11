#!/usr/bin/env bash
# test-loop-args.sh — Argument parsing + planning-budget defaults for
#   configs/scripts/loop-runner.sh
#
# Both behaviors here were real incidents, not hypotheticals:
#
#   1. `loop-runner.sh --dry-run goal.md` — the order printed in the /loop skill
#      docs — took "$1" as the goal file unconditionally, so GOAL_FILE became
#      "--dry-run" and pre_flight died with "Goal file not found: --dry-run".
#      The goal file must parse from either side of the flags.
#
#   2. The supervisor planning budget defaulted to 120s through two separate
#      stuck runs. Planning cost scales with goal size, so the default has to be
#      big enough that a normal multi-requirement goal plans without a flag.
#
# --dry-run does no LLM calls and writes no loop state, which is what makes
# these assertions safe to run in CI.
#
# Usage:
#   bash tests/test-loop-args.sh        # Run all tests
#   bash tests/test-loop-args.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$REPO_ROOT/configs/scripts/loop-runner.sh"

TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
VERBOSE="${1:-}"
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'
section() { printf "\n${YELLOW}━━━ %s ━━━${NC}\n" "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
GOAL="$WORK/goal.md"
cat > "$GOAL" <<'EOF'
# Goal: fixture

## Requirements
- [ ] first requirement
- [ ] second requirement

## Success criteria
- true
EOF

# run_dry <args...> → captures combined output in $OUT, exit code in $RC
run_dry() {
  OUT=$(cd "$WORK" && timeout 60 bash "$RUNNER" "$@" 2>&1)
  RC=$?
}

check() {
  local label="$1" cond="$2" detail="${3:-}"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "$cond" == "yes" ]]; then
    TESTS_PASSED=$((TESTS_PASSED + 1)); printf "  ${GREEN}✓${NC} %s\n" "$label"
    [[ "$VERBOSE" == "-v" ]] && [[ -n "$detail" ]] && printf "      %s\n" "$detail"
  else
    TESTS_FAILED=$((TESTS_FAILED + 1)); printf "  ${RED}✗${NC} %s\n" "$label"
    [[ -n "$detail" ]] && printf "      %s\n" "$detail"
  fi
  return 0
}

has() { [[ "$OUT" == *"$1"* ]] && echo yes || echo no; }

# ─── Goal file position ──────────────────────────────────────────────
section "Goal file parses from either side of the flags"

run_dry "$GOAL" --dry-run
check "goal BEFORE flags is accepted" "$(has 'Goal file:')" "rc=$RC"
check "goal BEFORE flags finds the 2 open items" "$(has '2 open / 2 total')" \
  "$(grep -o 'Goal items:.*' <<< "$OUT" | head -1)"

run_dry --dry-run "$GOAL"
check "goal AFTER flags is accepted (the documented form)" "$(has 'Goal file:')" "rc=$RC"
check "goal AFTER flags finds the 2 open items" "$(has '2 open / 2 total')" \
  "$(grep -o 'Goal items:.*' <<< "$OUT" | head -1)"
# The exact regression: the flag must never be mistaken for the goal path.
check "flag is not swallowed as the goal file" \
  "$([[ "$OUT" != *"Goal file not found: --dry-run"* ]] && echo yes || echo no)"

run_dry --max-iter 3 "$GOAL" --dry-run
check "goal between flags is accepted" "$(has 'Goal file:')" "rc=$RC"
check "surrounding flags still apply (max-iter=3)" "$(has 'max-iter=3')" \
  "$(grep -o 'Iter/workers:.*' <<< "$OUT" | head -1)"

# ─── Planning budget default ─────────────────────────────────────────
section "Supervisor planning budget"

# Guards the default itself: 120s was too small twice, so a regression to any
# value that low must fail here rather than surface as a stuck run.
DEFAULT=$(grep -E '^SUPERVISOR_TIMEOUT=' "$RUNNER" | head -1 | sed 's/[^0-9]*\([0-9]*\).*/\1/')
check "default supervisor timeout is set" "$([[ -n "$DEFAULT" ]] && echo yes || echo no)" "found: ${DEFAULT:-none}"
check "default supervisor timeout >= 300s" \
  "$([[ -n "$DEFAULT" && "$DEFAULT" -ge 300 ]] && echo yes || echo no)" "default=${DEFAULT}s"

run_dry --help
check "--help documents --supervisor-timeout" "$(has '--supervisor-timeout')" \
  "it was previously absent from the usage text, so nobody knew to raise it"
check "--help documents flexible goal position" "$(has '[options] GOAL_FILE')"

# ─── Timeout failure is self-describing ──────────────────────────────
section "Timeout failure message"

# exit 124 is timeout(1)'s kill code; the run used to print only the CLI's own
# last line ("Execution error"), which never mentions a timeout.
check "runner names the timeout explicitly" \
  "$(grep -q 'Supervisor timed out after' "$RUNNER" && echo yes || echo no)"
check "runner special-cases exit 124" \
  "$(grep -q 'supervisor_rc" -eq 124' "$RUNNER" && echo yes || echo no)"
check "runner suggests a concrete larger budget" \
  "$(grep -q 'supervisor-timeout \$((SUPERVISOR_TIMEOUT \* 2))' "$RUNNER" && echo yes || echo no)"

printf "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
if [[ "$TESTS_FAILED" -eq 0 ]]; then
  printf "  ${GREEN}ALL PASSED${NC} (%d/%d)\n" "$TESTS_PASSED" "$TESTS_RUN"
else
  printf "  ${RED}FAILED${NC} (%d/%d passed, %d failed)\n" "$TESTS_PASSED" "$TESTS_RUN" "$TESTS_FAILED"
fi
printf "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
[[ "$TESTS_FAILED" -eq 0 ]]
