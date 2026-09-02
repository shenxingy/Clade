#!/usr/bin/env bash
# test-ci-local.sh — the local CI runner must be able to go red.
#
# The failure mode this guards is specific and this repository has shipped it
# twice in other instruments: a checker that cannot fire reports a clean run
# exactly like a clean codebase. Here it would be worse than useless — a runner
# that silently executes nothing and exits 0 is a green light for a broken push.
#
# Every assertion runs against a SYNTHETIC workflow under /tmp, never the real
# one, so the test is fast and cannot be confused by the repository's own state.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$REPO_ROOT/configs/scripts/ci-local.py"
VERBOSE="${1:-}"

TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'

pass() { TESTS_RUN=$((TESTS_RUN+1)); TESTS_PASSED=$((TESTS_PASSED+1)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() {
  TESTS_RUN=$((TESTS_RUN+1)); TESTS_FAILED=$((TESTS_FAILED+1))
  echo -e "  ${RED}✗${NC} $1"; [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
}
section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }
assert_eq() {
  local got="$1" want="$2" msg="$3"
  if [[ "$got" == "$want" ]]; then pass "$msg"; else fail "$msg" "expected '$want', got '$got'"; fi
}
assert_contains() {
  local hay="$1" needle="$2" msg="$3"
  if grep -qF -- "$needle" <<< "$hay"; then pass "$msg"
  else fail "$msg" "output lacks '$needle'"; [[ "$VERBOSE" == "-v" ]] && echo "$hay" | head -20; fi
}

command -v python3 >/dev/null 2>&1 || { echo "python3 not found — skipping"; exit 0; }

SANDBOX="$(mktemp -d /tmp/clade-ci-local-XXXXXX)"
case "$SANDBOX" in /tmp/clade-ci-local-*) : ;; *) echo "FATAL: sandbox not under /tmp"; exit 1 ;; esac
trap 'rm -rf "$SANDBOX"' EXIT

FAKE="$SANDBOX/repo"
mkdir -p "$FAKE/.github/workflows"
cat > "$FAKE/.github/workflows/ci.yml" <<'YAML'
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  good:
    name: Good Job
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Say hello
        run: echo hello-from-good
      - name: Multi line block
        run: |
          echo first
          echo second

  bad:
    name: Bad Job
    runs-on: ubuntu-latest
    steps:
      - name: This one fails
        run: |
          echo about-to-fail
          exit 3
      - name: Never reached
        run: echo SHOULD-NOT-RUN

  gated:
    name: Gated Job
    if: github.event_name == 'schedule'
    runs-on: ubuntu-latest
    steps:
      - name: Only on a schedule
        run: echo gated-ran

  mac_only:
    name: Mac Only
    runs-on: macos-latest
    steps:
      - name: Mac step
        run: echo mac-ran

  secretive:
    name: Needs A Secret
    runs-on: ubuntu-latest
    steps:
      - name: Uses a secret
        env:
          TOKEN: ${{ secrets.SOME_TOKEN }}
        run: echo secret-step-ran
YAML

run_it() { python3 "$RUNNER" --repo "$FAKE" "$@" 2>&1; }

# ─── 1. The plan ─────────────────────────────────────────────────────
section "the plan names what runs and what does not"
OUT="$(run_it --list)"
assert_contains "$OUT" "Good Job"  "a runnable job is listed"
assert_contains "$OUT" "Bad Job"   "a failing job is still listed (it runs)"
assert_contains "$OUT" "conditional" "a schedule-gated job is skipped as conditional"
assert_contains "$OUT" "needs Darwin" "a macOS job says which platform it needs"
# Count the listed jobs rather than grepping for the digit — the first version
# of this assertion looked for the string "5" anywhere in the output, which is
# a proxy, not a check, and it failed for the right reason.
LISTED=$(grep -cE '^  \[(run |skip)\] ' <<< "$OUT" || true)
assert_eq "$LISTED" "5" "exactly the 5 real jobs are listed, not the on: triggers"
PHANTOM=$(grep -cE '\] (push|pull_request|schedule|workflow_dispatch) ' <<< "$OUT" || true)
assert_eq "$PHANTOM" "0" "no trigger name is parsed as a job"

# ─── 2. It can go red ────────────────────────────────────────────────
section "it can go red, and says exactly where"
OUT="$(run_it)"; RC=$?
assert_eq "$RC" "1" "a failing step makes the whole run exit non-zero"
assert_contains "$OUT" "FAILED  Bad Job" "the failing job is named"
assert_contains "$OUT" "This one fails"  "the failing STEP is named"
assert_contains "$OUT" "exit 3"          "the real exit code is reported, not just failure"
assert_contains "$OUT" "about-to-fail"   "the step's own output is shown"

# GitHub stops a job at its first failed step; so must this.
if grep -q "SHOULD-NOT-RUN" <<< "$OUT"; then
  fail "a job stops at its first failed step" "the later step ran anyway"
else
  pass "a job stops at its first failed step"
fi

# ─── 3. It can go green ──────────────────────────────────────────────
section "it can go green on a job that passes"
OUT="$(run_it --job "Good Job")"; RC=$?
assert_eq "$RC" "0" "a passing job exits 0"
assert_contains "$OUT" "1/1 job(s) passed" "the count reflects what actually ran"

# ─── 4. Skips are reported, never silent ─────────────────────────────
section "nothing-ran must not look like everything-passed"
OUT="$(run_it --job "Mac Only")"; RC=$?
assert_eq "$RC" "0" "a job that cannot run here is not a failure"
assert_contains "$OUT" "skipped Mac Only" "the skip is reported in the summary"
assert_contains "$OUT" "0/0 job(s) passed" "zero jobs ran, and the summary says zero"

# A job whose every step is skipped executed NOTHING. Reporting it as passed is
# the exact lie this tool exists to prevent, and the first version did it.
OUT="$(run_it --job "Needs A Secret")"
assert_contains "$OUT" "0/0 job(s) passed" "a job with no runnable step is not counted as passed"
assert_contains "$OUT" "every step skipped" "and the reason names why it ran nothing"

# ─── 5. JSON is usable by an automatic fixer ─────────────────────────
section "the JSON carries what a fixer needs"
JSON="$(run_it --json)"
for field in '"job": "Bad Job"' '"step": "This one fails"' '"exit_code": 3' '"command"' '"output_tail"'; do
  assert_contains "$JSON" "$field" "json carries $field"
done
if python3 -c "import json,sys; json.load(sys.stdin)" <<< "$JSON" 2>/dev/null; then
  pass "the JSON parses"
else
  fail "the JSON parses" "invalid JSON on a failing run"
fi
SKIPPED=$(python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['skipped']))" <<< "$JSON" 2>/dev/null || echo -1)
if [[ "$SKIPPED" -ge 2 ]]; then pass "the JSON lists skipped jobs too ($SKIPPED)"
else fail "the JSON lists skipped jobs too" "got $SKIPPED"; fi

# ─── 6. A repository with no workflows is an error, not a pass ───────
section "no workflows is an error, not a silent success"
EMPTY="$SANDBOX/empty"; mkdir -p "$EMPTY"
python3 "$RUNNER" --repo "$EMPTY" >/dev/null 2>&1
assert_eq "$?" "1" "a repo with no .github/workflows exits non-zero"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL PASSED${NC} ($TESTS_PASSED/$TESTS_RUN)"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
exit "$TESTS_FAILED"
