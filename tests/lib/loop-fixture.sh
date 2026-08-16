#!/usr/bin/env bash
# loop-fixture.sh — shared harness for the loop test suites.
#
# Holds the assertion helpers and the mocked `claude`/`committer` binaries that
# let loop tests exercise real bash logic with no API calls. Extracted so
# test-loop.sh and test-loop-bounds.sh share one definition instead of the
# second suite duplicating ~80 lines of fixture (and so test-loop.sh stays
# under the 1500-line rule).
#
# Callers must define nothing first; source it and use the helpers.

# ─── Test framework ──────────────────────────────────────────────────
# REAL-API tier lives in its own script (1500-line cap on this one): the mock
# suites below never spend money; --real runs exactly one live-CLI scenario.
if [[ "${1:-}" == "--real" ]]; then
  shift
  exec bash "$(cd "$(dirname "$0")" && pwd)/test-loop-real.sh" "$@"
fi

# Keep every nested Loop fixture on one explicit VCS identity.
LOOP_IDENTITY_DIR=$(mktemp -d /tmp/test-loop-identity-XXXXXX)
trap 'rm -rf "$LOOP_IDENTITY_DIR"' EXIT
export CLADE_GIT_IDENTITY_FILE="$LOOP_IDENTITY_DIR/git-identity.json"
python3 "$(cd "$(dirname "$0")/.." && pwd)/configs/scripts/git_identity.py" \
  pin --name Test --email test@example.com >/dev/null || exit 1
if [[ -z "${1:-}" || "${1:-}" == "checkpoint" ]]; then
  bash "$(cd "$(dirname "$0")" && pwd)/test-loop-checkpoint.sh" || exit 1
fi
if [[ -z "${1:-}" || "${1:-}" == "goal" ]]; then
  bash "$(cd "$(dirname "$0")" && pwd)/test-loop-goal.sh" || exit 1
fi

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
VERBOSE="${1:-}"
FILTER="${1:-}"
[[ "$FILTER" == "-v" ]] && FILTER="" && VERBOSE="-v"

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

assert_eq() {
  local expected="$1" actual="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "$expected" == "$actual" ]]; then
    pass "$msg"
  else
    fail "$msg" "expected '$expected', got '$actual'"
  fi
}

assert_contains() {
  local haystack="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if echo "$haystack" | grep -qF "$needle"; then
    pass "$msg"
  else
    fail "$msg" "output does not contain '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(echo "$haystack" | head -5)"
  fi
}

assert_not_contains() {
  local haystack="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if echo "$haystack" | grep -qF "$needle"; then
    fail "$msg" "output unexpectedly contains '$needle'"
  else
    pass "$msg"
  fi
}

assert_file_exists() {
  local path="$1" msg="$2"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -f "$path" ]]; then
    pass "$msg"
  else
    fail "$msg" "file not found: $path"
  fi
}

assert_file_contains() {
  local path="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -f "$path" ]] && grep -qF "$needle" "$path"; then
    pass "$msg"
  else
    fail "$msg" "file '$path' missing or doesn't contain '$needle'"
  fi
}

assert_exit_code() {
  local expected="$1" actual="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "$expected" == "$actual" ]]; then
    pass "$msg"
  else
    fail "$msg" "expected exit $expected, got $actual"
  fi
}

should_run() {
  [[ -z "$FILTER" ]] || echo "$1" | grep -qi "$FILTER"
}

section() {
  echo ""
  echo -e "${YELLOW}━━━ $1 ━━━${NC}"
}

# ─── Setup ────────────────────────────────────────────────────────────

SCRIPTS_DIR="$(cd "$(dirname "$0")/../configs/scripts" && pwd)"
TEST_DIR=$(mktemp -d /tmp/test-loop-XXXXXX)
ORIG_DIR=$(pwd)
MOCK_BIN="$TEST_DIR/mock-bin"

# Create mock claude binary that returns predictable output
mkdir -p "$MOCK_BIN"
cat > "$MOCK_BIN/claude" <<'MOCKEOF'
#!/usr/bin/env bash
# Mock claude — reads stdin, returns based on MOCK_CLAUDE_RESPONSE env var
# If MOCK_CLAUDE_RESPONSE is a file path, cat it; otherwise echo the string
# If MOCK_CLAUDE_TOUCH is set, append a line to that file (simulates a worker
# modifying a tracked file so loop-runner's commit_changes has work to do)
# If MOCK_CLAUDE_ARGS_LOG is set, record argv (one line per invocation) so
# tests can assert which flags each caller passed (e.g. --setting-sources)
if [[ -n "${MOCK_CLAUDE_ARGS_LOG:-}" ]]; then
  printf 'ARGS: %s\n' "$*" >> "$MOCK_CLAUDE_ARGS_LOG"
fi
mock_input=$(cat)
if [[ -n "${MOCK_CLAUDE_FIX_MARKER:-}" ]] \
    && [[ "$mock_input" == *"${MOCK_CLAUDE_FIX_TRIGGER:-Repair verification marker}"* ]]; then
  touch "$MOCK_CLAUDE_FIX_MARKER"
fi
if [[ -n "${MOCK_CLAUDE_TOUCH:-}" ]]; then
  echo "mock worker output" >> "$MOCK_CLAUDE_TOUCH"
fi
if [[ -n "${MOCK_CLAUDE_FIX_RESPONSE:-}" ]] \
    && [[ "$*" == *"The main workers completed but test_sample failed"* ]]; then
  echo "$MOCK_CLAUDE_FIX_RESPONSE"
elif [[ -f "${MOCK_CLAUDE_RESPONSE:-}" ]]; then
  cat "$MOCK_CLAUDE_RESPONSE"
else
  echo "${MOCK_CLAUDE_RESPONSE:-STATUS: CONVERGED}"
fi
exit "${MOCK_CLAUDE_EXIT:-0}"
MOCKEOF
chmod +x "$MOCK_BIN/claude"

# Mock committer — enforces the same conventional-commit regex as the real
# committer (checks.sh CONVENTIONAL_RE), so callers passing non-conventional
# subjects (e.g. the old "loop: iter N changes") fail here like in production.
cat > "$MOCK_BIN/committer" <<'MOCKEOF'
#!/usr/bin/env bash
msg="${1:-batch commit}"
shift
CONVENTIONAL_RE='^(feat|fix|refactor|test|chore|docs|perf|style|ci|build)(\(.+\))?: .+'
if ! printf '%s\n' "$msg" | head -1 | grep -qE "$CONVENTIONAL_RE"; then
  echo "checks: commit message must follow conventional commit format." >&2
  exit 1
fi
# Like the real committer: clear any pre-staged files (e.g. run-tasks.sh's
# git add -A checkpoint), then stage ONLY the named files.
git restore --staged :/ 2>/dev/null || true
git add "$@" 2>/dev/null
git commit -m "$msg" --allow-empty --no-verify 2>/dev/null
MOCKEOF
chmod +x "$MOCK_BIN/committer"

export PATH="$MOCK_BIN:$PATH"

# Initialize a test git repo
setup_test_repo() {
  local repo_dir="$TEST_DIR/repo-$$-$RANDOM"
  mkdir -p "$repo_dir"
  cd "$repo_dir"
  git init -q
  git config user.email "test@example.com"
  git config user.name "Test"
  echo "init" > README.md
  git add README.md
  git commit -q -m "init"
  echo "$repo_dir"
}

cleanup() {
  cd "$ORIG_DIR"
  rm -rf "$TEST_DIR"
  rm -rf "$LOOP_IDENTITY_DIR"
}
trap cleanup EXIT


# ─── Isolation (safety, not convenience) ─────────────────────────────
# A suite that calls loop-runner.sh without first entering a scratch checkout
# runs it against the REAL repository — it will plan tasks, spawn workers, and
# write logs/ and .claude/state into your working tree. That happened once
# while splitting these suites; the mocked claude is the only reason it was
# harmless. Isolation therefore belongs to the fixture, not to each caller
# remembering.
loop_fixture_isolate() {
  cd "$TEST_DIR" || exit 1
  git init -q . 2>/dev/null || true
  git config user.email "test@example.com" 2>/dev/null || true
  git config user.name "Loop Test" 2>/dev/null || true
  mkdir -p .claude logs
  [[ -f README.md ]] || { echo "# fixture" > README.md; git add README.md 2>/dev/null; \
    git commit -qm "chore: fixture baseline" 2>/dev/null || true; }
  export PATH="$MOCK_BIN:$PATH"
}
