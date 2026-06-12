#!/usr/bin/env bash
# test-loop-real.sh — key-gated REAL-API tier for the loop harness
#
# Two-tier pattern: tests/test-loop.sh runs the full mock suites for free on
# every push; this tier runs EXACTLY ONE cheap live scenario against the real
# claude CLI (trivial goal, haiku supervisor, max-iter 1, ~$0.05) to catch
# mock-vs-real drift: CLI flag changes, `claude -p` output framing, supervisor
# JSON extraction — the failure class previously only detectable mid-paid-
# overnight-run.
#
# Usage:
#   bash tests/test-loop.sh --real        # delegates here
#   bash tests/test-loop-real.sh [-v]
#
# Gating (relic two-tier semantics, exit 0 on skip so keyless CI stays green):
#   - no real `claude` on PATH                          → SKIP, exit 0
#   - no ANTHROPIC_API_KEY and no ~/.claude/.credentials.json → SKIP, exit 0
#
# KNOWN INTERFERENCE (machines with Clade hooks deployed): a Stop hook of
# type "prompt" makes nested `claude -p` print the hook's own evaluation
# (e.g. {"ok":true}) as the final message instead of the model reply, so the
# supervisor task array never reaches loop-runner. A supervisor-leg failure
# on such a machine is a REAL local finding (overnight /loop supervisor calls
# are equally affected) — not CLI drift. Bare CI runners are unaffected.

set -uo pipefail

VERBOSE="${1:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

pass() { TESTS_PASSED=$((TESTS_PASSED + 1)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() {
  TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
}

assert_contains() {
  TESTS_RUN=$((TESTS_RUN + 1))
  if echo "$1" | grep -qF "$2"; then pass "$3"; else fail "$3" "output does not contain '$2'"; fi
}

assert_file_exists() {
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -f "$1" ]]; then pass "$2"; else fail "$2" "file not found: $1"; fi
}

assert_file_contains() {
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -f "$1" ]] && grep -qF "$2" "$1"; then pass "$3"; else fail "$3" "file '$1' missing or doesn't contain '$2'"; fi
}

echo ""
echo -e "${YELLOW}━━━ REAL-API tier — live claude CLI loop smoke ━━━${NC}"

# ─── Gates ───────────────────────────────────────────────────────────
if ! command -v claude >/dev/null 2>&1; then
  echo "SKIP: claude CLI not on PATH — real-API tier requires Claude Code installed"
  exit 0
fi
if [[ -z "${ANTHROPIC_API_KEY:-}" && ! -f "$HOME/.claude/.credentials.json" ]]; then
  echo "SKIP: no credentials (ANTHROPIC_API_KEY unset and ~/.claude/.credentials.json missing)"
  exit 0
fi

# ─── Setup: throwaway repo + mock committer (claude stays REAL) ──────
SCRIPTS_DIR="$(cd "$(dirname "$0")/../configs/scripts" && pwd)"
TEST_DIR=$(mktemp -d /tmp/test-loop-real-XXXXXX)
ORIG_DIR=$(pwd)
MOCK_BIN="$TEST_DIR/mock-bin"
mkdir -p "$MOCK_BIN"

# The committer is harness plumbing, not the surface under test — mock it so
# the live worker can commit without the deployed ~/.local/bin/committer.
cat > "$MOCK_BIN/committer" <<'MOCKEOF'
#!/usr/bin/env bash
msg="${1:-batch commit}"
shift
git restore --staged :/ 2>/dev/null || true
git add "$@" 2>/dev/null
git commit -m "$msg" --allow-empty --no-verify 2>/dev/null
MOCKEOF
chmod +x "$MOCK_BIN/committer"
export PATH="$MOCK_BIN:$PATH"

# shellcheck disable=SC2329  # invoked via trap
cleanup() { cd "$ORIG_DIR" || return; rm -rf "$TEST_DIR"; }
trap cleanup EXIT

REPO_DIR="$TEST_DIR/repo"
mkdir -p "$REPO_DIR"
cd "$REPO_DIR" || exit 1
git init -q
git config user.email "test@test.com"
git config user.name "Test"
echo "init" > README.md
git add README.md
git commit -q -m "init"
mkdir -p .claude logs/loop

cat > goal.md <<'EOF'
# Goal: hello file

- [ ] Create hello.txt in the repo root containing exactly the line: hello
EOF

# ─── One cheap live scenario ─────────────────────────────────────────
echo "  (live run: supervisor=haiku, max-iter=1, max-workers=1, ~\$0.05)"
output=$(
  timeout --kill-after=10s 600s bash "$SCRIPTS_DIR/loop-runner.sh" goal.md \
    --model haiku --max-iter 1 --max-workers 1 \
    --state .claude/loop-state-real --log-dir logs/loop 2>&1
) || true
[[ "$VERBOSE" == "-v" ]] && echo "$output"

# Harness ran end-to-end against the live CLI
assert_contains "$output" "Blueprint Loop" "live run shows Blueprint banner"

# Supervisor round-trip: live `claude -p` text parsed into a JSON task array
# and serialized to ===TASK=== format — the exact surface that drifts when
# CLI flags or output framing change underneath the mocks
assert_file_exists "logs/loop/iter-1-tasks.txt" "supervisor output parsed from live CLI → task file written"
assert_file_contains "logs/loop/iter-1-tasks.txt" "===TASK===" "task file round-trips ===TASK=== format"
assert_file_contains "logs/loop/iter-1-tasks.txt" "model:" "task file carries a model header"

# Loop status parsing: a recognized exit reason was recorded
assert_file_exists "logs/loop/last-progress" "loop wrote last-progress status"
exit_line=$(grep -E '^Exit: ' logs/loop/last-progress 2>/dev/null || true)
TESTS_RUN=$((TESTS_RUN + 1))
if echo "$exit_line" | grep -qE '^Exit: (converged|max_iterations)$'; then
  pass "exit reason recognized ($exit_line)"
else
  fail "exit reason unrecognized" "last-progress says: '${exit_line:-<missing>}'"
fi

# Diagnostic hint for the known Stop-prompt-hook interference (header note)
if echo "$output" | grep -q "Supervisor returned no tasks"; then
  echo "  (hint) supervisor replied but no task array was extracted — on a machine"
  echo "         with Clade's Stop prompt-hook deployed, nested claude -p prints the"
  echo "         hook evaluation ({\"ok\":true}) instead of the model reply. That is a"
  echo "         real local finding (overnight /loop is equally affected), not CLI drift."
fi

# Informational only (LLM-dependent — never fails the tier): worker efficacy
if [[ -f hello.txt ]]; then
  echo "  (info) worker created hello.txt — goal achieved end-to-end"
else
  echo "  (info) hello.txt not created — worker leg incomplete (not asserted)"
fi
# Surface cost if stream-json worker logs captured it
real_cost=$(grep -rhoE '"total_cost_usd":[0-9.]+' logs .claude 2>/dev/null \
  | grep -oE '[0-9.]+' | paste -sd+ - | bc 2>/dev/null || true)
[[ -n "$real_cost" ]] && echo "  (info) reported worker cost: \$${real_cost}"

# ─── Summary ─────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}REAL-API TIER: ALL $TESTS_RUN TESTS PASSED${NC}"
else
  echo -e "  ${RED}REAL-API TIER: $TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
exit $TESTS_FAILED
