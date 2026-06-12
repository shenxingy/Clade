#!/usr/bin/env bash
# test-scan-deps.sh — Tests for configs/scripts/scan-deps.sh
#
# Covers Bug #2 fix: npm export of OUTDATED_JSON/MAX_TASKS, proper handling
# of npm outdated exit code, and f-string escapes for backtick commands.
#
# Usage:
#   bash tests/test-scan-deps.sh        # Run all tests
#   bash tests/test-scan-deps.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCAN_DEPS="$REPO_ROOT/configs/scripts/scan-deps.sh"

# ─── Test framework ─────────────────────────────────────────────
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
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -10 <<< "$haystack")"
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

# ─── Helpers ─────────────────────────────────────────────────────

CLEANUP_DIRS=()
cleanup() {
  local d
  for d in "${CLEANUP_DIRS[@]:-}"; do
    [[ -n "$d" && -d "$d" ]] && rm -rf "$d"
  done
}
trap cleanup EXIT

# Create a temporary project directory with stub npm/pip
make_project() {
  local d
  d="$(mktemp -d /tmp/clade-scan-deps-test.XXXXXX)"
  CLEANUP_DIRS+=("$d")
  echo "$d"
}

# Create mock npm outdated command that outputs valid JSON with exit code 1
# (mimics real npm behavior: exit 1 when packages ARE outdated)
mock_npm_outdated_with_packages() {
  local dir="$1"
  local bin_dir="$dir/bin"
  mkdir -p "$bin_dir"

  cat > "$bin_dir/npm" <<'MOCK'
#!/usr/bin/env bash
# Mock npm that passes through to real npm, OR returns outdated JSON for testing
if [[ "$1" == "outdated" && "$2" == "--json" ]]; then
  # Return a sample outdated packages response and exit 1 (real npm behavior)
  cat <<'JSON'
{
  "lodash": {
    "current": "4.17.19",
    "wanted": "4.17.21",
    "latest": "4.17.21",
    "location": "node_modules/lodash"
  },
  "express": {
    "current": "4.17.1",
    "wanted": "5.0.0",
    "latest": "5.0.0",
    "location": "node_modules/express"
  }
}
JSON
  exit 1
fi

# For other npm commands, fail
echo "Mock npm: unsupported command: $*" >&2
exit 127
MOCK
  chmod +x "$bin_dir/npm"
}

# Create mock npm outdated command that outputs empty (no outdated packages)
mock_npm_outdated_no_packages() {
  local dir="$1"
  local bin_dir="$dir/bin"
  mkdir -p "$bin_dir"

  cat > "$bin_dir/npm" <<'MOCK'
#!/usr/bin/env bash
# Mock npm that returns empty when no outdated packages
if [[ "$1" == "outdated" && "$2" == "--json" ]]; then
  echo "{}"
  exit 0
fi

# For other npm commands, fail
echo "Mock npm: unsupported command: $*" >&2
exit 127
MOCK
  chmod +x "$bin_dir/npm"
}

# ─── scan-deps.sh npm export (Bug #2) ────────────────────────────
echo "── scan-deps.sh npm export fix (Bug #2) ──"

# Test 1: npm-only project with outdated packages should emit tasks
D="$(make_project)"
mock_npm_outdated_with_packages "$D"
mkdir -p "$D/node_modules"
touch "$D/package.json"

OUT=$( PATH="$D/bin:$PATH" bash "$SCAN_DEPS" "$D" 5 2>&1; echo "exit=$?" )
assert_contains "$OUT" "===TASK===" "npm-only project with outdated packages emits task blocks"
assert_contains "$OUT" "chore: upgrade lodash 4.17.19 → 4.17.21" "npm task contains upgrade instruction"
assert_contains "$OUT" "\`npm install lodash@4.17.21\`" "npm task command uses backticks (not escaped)"
assert_not_contains "$OUT" "express" "major version bump (4→5) is skipped"

# Test 2: npm-only project with no outdated packages should emit nothing (no crash)
D="$(make_project)"
mock_npm_outdated_no_packages "$D"
mkdir -p "$D/node_modules"
touch "$D/package.json"

OUT=$( PATH="$D/bin:$PATH" bash "$SCAN_DEPS" "$D" 5 2>&1; echo "exit=$?" )
assert_contains "$OUT" "exit=0" "npm-only project with no outdated packages exits cleanly"
assert_not_contains "$OUT" "===TASK===" "no task blocks when no packages are outdated"

# Test 3: npm task template includes properly-escaped backtick commands
D="$(make_project)"
mock_npm_outdated_with_packages "$D"
mkdir -p "$D/node_modules"
touch "$D/package.json"

OUT=$( PATH="$D/bin:$PATH" bash "$SCAN_DEPS" "$D" 5 2>&1 )
# Verify the task template has backticks (not \` escapes which would render as backslash-backtick)
assert_contains "$OUT" "1. Update lodash: \`npm install lodash@4.17.21\`" "npm task has correct backtick syntax in step 1"
assert_contains "$OUT" "4. Commit with \`committer" "npm task has correct backtick syntax in step 4"

# Test 4: Verify OUTDATED_JSON env var is exported before heredoc runs
# (This is implicit in Test 1 — if OUTDATED_JSON wasn't exported, the heredoc
#  would read the default '{}' and emit no tasks. Since Test 1 passes, the export
#  is working.)

# ─── scan-deps.sh pip section (sanity check after refactor) ────────
echo "── scan-deps.sh pip section sanity check ──"

# Test 5: pip task template includes properly-escaped backtick commands
D="$(make_project)"
touch "$D/requirements.txt"
# Can't easily mock pip, so just check that the script handles missing pip gracefully
OUT=$( bash "$SCAN_DEPS" "$D" 5 2>&1; echo "exit=$?" )
assert_contains "$OUT" "exit=0" "script exits cleanly with missing pip"
# The pip section should print header even if pip isn't found
assert_contains "$OUT" "Dependency Update Tasks — Python" "pip section header is printed"

# ─── Summary ─────────────────────────────────────────────────────
echo ""
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL $TESTS_RUN TESTS PASSED${NC}"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
exit $TESTS_FAILED
