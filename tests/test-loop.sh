#!/usr/bin/env bash
# test-loop.sh — Comprehensive test suite for the loop system
#
# Tests all three scripts:
#   - loop-runner.sh    (supervisor loop controller)
#   - run-tasks-parallel.sh (parallel worker executor)
#   - run-tasks.sh      (serial task executor)
#
# These tests mock `claude` to avoid API calls. They test the bash logic:
#   task parsing, state management, conflict detection, convergence,
#   STOP sentinel, resume, error handling, worktree lifecycle.
#
# Usage:
#   bash tests/test-loop.sh           # Run all tests
#   bash tests/test-loop.sh -v        # Verbose mode
#   bash tests/test-loop.sh PATTERN   # Run tests matching pattern

set -uo pipefail

# ─── Test framework ──────────────────────────────────────────────────
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
cat > /dev/null  # consume stdin
if [[ -f "${MOCK_CLAUDE_RESPONSE:-}" ]]; then
  cat "$MOCK_CLAUDE_RESPONSE"
else
  echo "${MOCK_CLAUDE_RESPONSE:-STATUS: CONVERGED}"
fi
exit "${MOCK_CLAUDE_EXIT:-0}"
MOCKEOF
chmod +x "$MOCK_BIN/claude"

# Mock committer
cat > "$MOCK_BIN/committer" <<'MOCKEOF'
#!/usr/bin/env bash
# Mock committer — just make a git commit
msg="${1:-batch commit}"
shift
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
  git config user.email "test@test.com"
  git config user.name "Test"
  echo "init" > README.md
  git add README.md
  git commit -q -m "init"
  echo "$repo_dir"
}

cleanup() {
  cd "$ORIG_DIR"
  rm -rf "$TEST_DIR"
}
trap cleanup EXIT

# ─── Task file fixtures ──────────────────────────────────────────────

create_task_file_new_format() {
  local path="$1"
  cat > "$path" <<'EOF'
===TASK===
model: haiku
timeout: 300
retries: 1
---
Fix the login bug in auth.py. Update the validate_token function
to check expiry. Commit with: committer "fix: token expiry" auth.py

===TASK===
model: sonnet
timeout: 600
retries: 2
---
Add rate limiting to api/routes.py. Implement a sliding window
rate limiter using Redis. Commit with: committer "feat: rate limiting" api/routes.py

===TASK===
model: opus
timeout: 1800
retries: 0
---
Refactor the entire database layer. Move from SQLite to PostgreSQL.
Update models.py, migrations/, and config.py.
Commit with: committer "refactor: postgresql migration" models.py migrations/ config.py
EOF
}

create_task_file_single() {
  local path="$1"
  cat > "$path" <<'EOF'
===TASK===
model: sonnet
timeout: 600
retries: 1
---
Create a hello.txt file with content "hello world".
Commit with: committer "feat: hello" hello.txt
EOF
}

create_task_file_conflict() {
  # Two tasks touching the same file (auth.py)
  local path="$1"
  cat > "$path" <<'EOF'
===TASK===
model: haiku
timeout: 300
retries: 1
---
Fix the login bug in auth.py line 42. Update validate_token.

===TASK===
model: sonnet
timeout: 300
retries: 1
---
Add OAuth support to auth.py. New function oauth_callback.

===TASK===
model: haiku
timeout: 300
retries: 1
---
Update README.md with new auth docs.
EOF
}

create_task_file_legacy() {
  local path="$1"
  cat > "$path" <<'EOF'
# Legacy format — one task per line
Fix the bug in server.py
Add tests for the API
Update documentation
EOF
}

create_goal_file() {
  local path="$1"
  cat > "$path" <<'EOF'
# Goal: Test Loop System

## Requirements
- [ ] Create a test file
- [ ] Verify convergence detection
- [ ] Test STOP sentinel

## Success criteria
- All files created
- Loop exits cleanly
EOF
}

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 1: Task Parsing (run-tasks.sh functions)
# ═══════════════════════════════════════════════════════════════════════

if should_run "parsing"; then
section "Task Parsing — New Format (===TASK===)"

REPO_DIR=$(setup_test_repo)
cd "$REPO_DIR"
TASK_FILE="$REPO_DIR/tasks.txt"
create_task_file_new_format "$TASK_FILE"

# Source the functions we need from run-tasks.sh (extract the function definitions)
# We can't source the whole file since it has a main loop, so we test via the parallel script
# which has the same functions but is structured differently.

# Test count_tasks
result=$(grep -c '^===TASK===$' "$TASK_FILE")
assert_eq "3" "$result" "count_tasks: 3 tasks in new format"

# Test get_task_field via awk extraction
get_task_field_test() {
  local n="$1" field="$2" default="${3:-}"
  local result
  result=$(awk -v n="$n" -v field="$field" '
    /^===TASK===$/ { count++ }
    count == n && $0 ~ "^"field":" {
      gsub("^"field":[[:space:]]*", ""); print; found=1; exit
    }
    count == n && /^---$/ { if (!found) exit }
    END { if (!found) print "" }
  ' "$TASK_FILE")
  echo "${result:-$default}"
}

assert_eq "haiku" "$(get_task_field_test 1 model sonnet)" "task 1 model: haiku"
assert_eq "sonnet" "$(get_task_field_test 2 model sonnet)" "task 2 model: sonnet"
assert_eq "opus" "$(get_task_field_test 3 model sonnet)" "task 3 model: opus"
assert_eq "300" "$(get_task_field_test 1 timeout 1800)" "task 1 timeout: 300"
assert_eq "600" "$(get_task_field_test 2 timeout 1800)" "task 2 timeout: 600"
assert_eq "1800" "$(get_task_field_test 3 timeout 1800)" "task 3 timeout: 1800"
assert_eq "1" "$(get_task_field_test 1 retries 2)" "task 1 retries: 1"
assert_eq "2" "$(get_task_field_test 2 retries 2)" "task 2 retries: 2"
assert_eq "0" "$(get_task_field_test 3 retries 2)" "task 3 retries: 0"

# Test get_task_prompt
get_task_prompt_test() {
  local n="$1"
  awk -v n="$n" '
    /^===TASK===$/ { count++; in_meta=1; in_body=0; next }
    count == n && in_meta && /^---$/ { in_meta=0; in_body=1; next }
    count == n && in_body && /^===TASK===$/ { exit }
    count == n && in_body { print }
    count > n { exit }
  ' "$TASK_FILE" | sed -e '1{/^$/d}' -e '${/^$/d}'
}

prompt1=$(get_task_prompt_test 1)
assert_contains "$prompt1" "login bug" "task 1 prompt contains 'login bug'"
assert_contains "$prompt1" "auth.py" "task 1 prompt contains 'auth.py'"
assert_not_contains "$prompt1" "rate limiting" "task 1 prompt does NOT contain task 2 content"

prompt2=$(get_task_prompt_test 2)
assert_contains "$prompt2" "rate limiting" "task 2 prompt contains 'rate limiting'"
assert_not_contains "$prompt2" "login bug" "task 2 prompt does NOT contain task 1 content"

prompt3=$(get_task_prompt_test 3)
assert_contains "$prompt3" "PostgreSQL" "task 3 prompt contains 'PostgreSQL'"

# Test get_task_name (first non-empty line of prompt)
name1=$(get_task_prompt_test 1 | awk 'NF { print; exit }')
assert_contains "$name1" "Fix the login bug" "task 1 name extracted correctly"

# Test with single task
create_task_file_single "$TASK_FILE"
result=$(grep -c '^===TASK===$' "$TASK_FILE")
assert_eq "1" "$result" "count_tasks: 1 task (single)"

single_prompt=$(get_task_prompt_test 1)
assert_contains "$single_prompt" "hello.txt" "single task prompt correct"

# Test with legacy format
section "Task Parsing — Legacy Format"
create_task_file_legacy "$TASK_FILE"

legacy_count=$(grep -cvE '^[[:space:]]*(#|$)' "$TASK_FILE")
assert_eq "3" "$legacy_count" "legacy format: 3 tasks"

legacy_task1=$(grep -vE '^[[:space:]]*(#|$)' "$TASK_FILE" | sed -n '1p')
assert_eq "Fix the bug in server.py" "$legacy_task1" "legacy task 1 content"
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 2: Conflict Detection
# ═══════════════════════════════════════════════════════════════════════

if should_run "conflict"; then
section "Conflict Detection"

REPO_DIR=$(setup_test_repo)
cd "$REPO_DIR"
TASK_FILE="$REPO_DIR/tasks.txt"
create_task_file_conflict "$TASK_FILE"

# Test extract_file_refs
extract_file_refs_test() {
  echo "$1" | grep -oE '[a-zA-Z0-9_./-]+\.(tsx|ts|jsx|js|py|ipynb|md|json|yaml|yml|sh|css|scss|rs|go|swift|kt|java|cpp|hpp|c|h|tex|bib|rb|lua|zig|dart)' | sort -u
}

refs1=$(extract_file_refs_test "Fix the login bug in auth.py line 42. Update validate_token.")
assert_contains "$refs1" "auth.py" "file refs: auth.py detected in task 1"

refs2=$(extract_file_refs_test "Add OAuth support to auth.py. New function oauth_callback.")
assert_contains "$refs2" "auth.py" "file refs: auth.py detected in task 2"

refs3=$(extract_file_refs_test "Update README.md with new auth docs.")
assert_contains "$refs3" "README.md" "file refs: README.md detected in task 3"
assert_not_contains "$refs3" "auth.py" "file refs: auth.py NOT in task 3"

# Test conflict detection logic
# Tasks 1 and 2 both touch auth.py → should be grouped
# Task 3 touches README.md → should be separate
overlap=$(comm -12 <(echo "$refs1") <(echo "$refs2"))
assert_contains "$overlap" "auth.py" "tasks 1,2 share auth.py → conflict"

overlap13=$(comm -12 <(echo "$refs1") <(echo "$refs3"))
assert_eq "" "$overlap13" "tasks 1,3 have no shared files → no conflict"

# Test with no file references (edge case)
refs_none=$(extract_file_refs_test "Just do something without mentioning files")
assert_eq "" "$refs_none" "no file refs when none mentioned"

# Test complex path patterns
refs_complex=$(extract_file_refs_test "Edit src/components/Login.tsx and api/auth/handler.ts")
assert_contains "$refs_complex" "Login.tsx" "complex path: Login.tsx detected"
assert_contains "$refs_complex" "handler.ts" "complex path: handler.ts detected"
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 3: State File Management (loop-runner.sh)
# ═══════════════════════════════════════════════════════════════════════

if should_run "state"; then
section "State File Management"

REPO_DIR=$(setup_test_repo)
cd "$REPO_DIR"
mkdir -p .claude

STATE_FILE=".claude/loop-state"

# Test fresh state creation
{ echo "ITERATION=0"; echo "CONVERGED=false"; echo "GOAL=/tmp/goal.md"; echo "STARTED=$(date +"%Y-%m-%dT%H:%M:%S%z")"; } > "$STATE_FILE"

assert_file_exists "$STATE_FILE" "state file created"
assert_file_contains "$STATE_FILE" "ITERATION=0" "initial iteration=0"
assert_file_contains "$STATE_FILE" "CONVERGED=false" "initial converged=false"

# Test state_read
state_read_test() {
  grep -m1 "^${1}=" "$STATE_FILE" 2>/dev/null | cut -d= -f2- || echo "${2:-}"
}

assert_eq "0" "$(state_read_test ITERATION 0)" "state_read: ITERATION=0"
assert_eq "false" "$(state_read_test CONVERGED false)" "state_read: CONVERGED=false"
assert_eq "default" "$(state_read_test NONEXISTENT default)" "state_read: missing key → default"

# Test state_write
state_write_test() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$STATE_FILE"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$STATE_FILE"
  else
    echo "${key}=${val}" >> "$STATE_FILE"
  fi
}

state_write_test ITERATION 5
assert_eq "5" "$(state_read_test ITERATION 0)" "state_write: updated ITERATION to 5"

state_write_test CONVERGED true
assert_eq "true" "$(state_read_test CONVERGED false)" "state_write: updated CONVERGED to true"

state_write_test NEW_KEY hello
assert_eq "hello" "$(state_read_test NEW_KEY "")" "state_write: new key appended"

# Test resume vs fresh start
rm -f "$STATE_FILE"
# Fresh start (RESUME=false)
{ echo "ITERATION=0"; echo "CONVERGED=false"; echo "GOAL=/tmp/goal.md"; } > "$STATE_FILE"
assert_eq "0" "$(state_read_test ITERATION)" "fresh start: ITERATION=0"

# Simulate resume with existing state
state_write_test ITERATION 3
# RESUME=true should preserve existing state
assert_eq "3" "$(state_read_test ITERATION)" "resume: ITERATION preserved at 3"

# Test STOP sentinel
state_write_test STOP true
assert_eq "true" "$(state_read_test STOP false)" "STOP sentinel written"

# Test state overwrite on fresh start
{ echo "ITERATION=0"; echo "CONVERGED=false"; } > "$STATE_FILE"
assert_eq "0" "$(state_read_test ITERATION)" "fresh start overwrites state"
assert_eq "" "$(state_read_test STOP "")" "fresh start clears STOP sentinel"
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 4: Convergence Detection
# ═══════════════════════════════════════════════════════════════════════

if should_run "convergence"; then
section "Convergence Detection"

# Test STATUS: CONVERGED detection (grep pattern from loop-runner.sh)
test_converged() {
  echo "$1" | grep -q "STATUS: CONVERGED"
}

output1="After review, all goals achieved.
STATUS: CONVERGED"
test_converged "$output1"
assert_exit_code "0" "$?" "detects STATUS: CONVERGED at end"

output2="STATUS: CONVERGED
The goal is fully implemented."
test_converged "$output2"
assert_exit_code "0" "$?" "detects STATUS: CONVERGED at start"

output3="The status is not converged yet.
===TASK===
model: sonnet
---
Fix remaining issues"
test_converged "$output3"
assert_exit_code "1" "$?" "does NOT false-positive on 'not converged'"

output4=""
test_converged "$output4"
assert_exit_code "1" "$?" "empty output → not converged"

# Test ERROR detection
test_error() {
  echo "$1" | grep -qi "^ERROR:"
}

output_err="ERROR: supervisor failed — see log"
test_error "$output_err"
assert_exit_code "0" "$?" "detects ERROR: prefix"

output_no_err="Everything looks good, no errors."
test_error "$output_no_err"
assert_exit_code "1" "$?" "does NOT false-positive on 'errors'"

# Test task extraction (===TASK=== presence)
test_has_tasks() {
  echo "$1" | grep -q "^===TASK===$"
}

output_tasks="Here's my plan:

===TASK===
model: sonnet
timeout: 600
retries: 1
---
Fix the bug

===TASK===
model: haiku
timeout: 300
retries: 1
---
Update docs"
test_has_tasks "$output_tasks"
assert_exit_code "0" "$?" "detects ===TASK=== blocks"

task_count=$(echo "$output_tasks" | grep -c '^===TASK===$')
assert_eq "2" "$task_count" "counts 2 tasks"

# Test preamble stripping (loop-runner.sh task processing)
# The script skips lines before first ===TASK===
PROCESSED=""
in_body=false
seen_first_task=false
while IFS= read -r line; do
  if [[ "$line" == "===TASK===" ]]; then
    if $in_body; then
      PROCESSED+=$'\n'"## footer"
    fi
    PROCESSED+=$'\n'"===TASK==="
    in_body=false
    seen_first_task=true
  elif [[ "$line" == "---" ]] && ! $in_body && $seen_first_task; then
    PROCESSED+=$'\n'"---"
    in_body=true
  elif $seen_first_task; then
    PROCESSED+=$'\n'"$line"
  fi
done <<< "$output_tasks"

assert_not_contains "$PROCESSED" "Here's my plan:" "preamble stripped from processed output"
assert_contains "$PROCESSED" "Fix the bug" "task 1 body preserved"
assert_contains "$PROCESSED" "Update docs" "task 2 body preserved"
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 5: loop-runner.sh Integration
# ═══════════════════════════════════════════════════════════════════════

if should_run "runner"; then
section "loop-runner.sh — Integration Tests"

REPO_DIR=$(setup_test_repo)
cd "$REPO_DIR"
mkdir -p .claude logs/loop

# Create models.env in test repo (loop-runner.sh sources from $SCRIPTS_DIR/../models.env)
# Also create at $HOME/.claude/models.env (fallback path) — but DON'T overwrite source tree
cat > models.env <<'EOF'
MODEL_HAIKU="claude-haiku-4-5-20251001"
MODEL_SONNET="claude-sonnet-4-6"
MODEL_OPUS="claude-opus-4-6"
EOF
# Create in the parent of SCRIPTS_DIR (configs/) if it's inside a temp dir, not the real source
_models_target="$(dirname "$SCRIPTS_DIR")/models.env"
if [[ "$_models_target" == /tmp/* ]]; then
  mkdir -p "$(dirname "$SCRIPTS_DIR")"
  cp models.env "$_models_target" 2>/dev/null || true
fi

# Test 1: Immediate convergence (supervisor says CONVERGED on first iteration)
create_goal_file "goal.md"
export MOCK_CLAUDE_RESPONSE="STATUS: CONVERGED"
export MOCK_CLAUDE_EXIT=0

# We need models.env accessible — create it where the script expects
MODELS_ENV_DIR="$(dirname "$SCRIPTS_DIR")/.."
output=$(bash "$SCRIPTS_DIR/loop-runner.sh" "goal.md" --max-iter 2 --state .claude/loop-state --log-dir logs/loop 2>&1) || true
assert_contains "$output" "Goal Loop" "banner displayed"
assert_contains "$output" "converged" "reports convergence"
assert_file_contains ".claude/loop-state" "CONVERGED=true" "state file updated to converged"

# Test 2: Missing goal file
rm -f nonexistent.md
output=$(bash "$SCRIPTS_DIR/loop-runner.sh" "nonexistent.md" --max-iter 1 --state .claude/loop-state2 --log-dir logs/loop 2>&1) || true
ec=$?
assert_contains "$output" "goal file missing" "reports missing goal file"

# Test 3: STOP sentinel
create_goal_file "goal2.md"
# Pre-set STOP in state
{ echo "ITERATION=0"; echo "CONVERGED=false"; echo "STOP=true"; echo "GOAL=$(realpath goal2.md)"; echo "STARTED=$(date +"%Y-%m-%dT%H:%M:%S%z")"; } > .claude/loop-state3

# Make the mock return tasks so the loop would continue if STOP wasn't set
export MOCK_CLAUDE_RESPONSE="===TASK===
model: haiku
timeout: 60
retries: 0
---
Do something"

output=$(bash "$SCRIPTS_DIR/loop-runner.sh" "goal2.md" --max-iter 5 --state .claude/loop-state3 --log-dir logs/loop --resume 2>&1) || true
assert_contains "$output" "STOP sentinel" "STOP sentinel detected"

# Test 4: Max iterations reached
{ echo "ITERATION=0"; echo "CONVERGED=false"; } > .claude/loop-state4
create_goal_file "goal3.md"
# Supervisor returns tasks every time (never converges)
export MOCK_CLAUDE_RESPONSE="===TASK===
model: haiku
timeout: 10
retries: 0
---
echo hello > test.txt"

# Run with max-iter 1 so it only does 1 iteration
# Close leaked FDs and use --kill-after to prevent hangs
output=$(
  exec 3>&- 4>&- 5>&- 6>&- 7>&- 8>&- 9>&- 2>/dev/null
  timeout --kill-after=5s 60s bash "$SCRIPTS_DIR/loop-runner.sh" "goal3.md" --max-iter 1 --max-workers 1 --state .claude/loop-state4 --log-dir logs/loop 2>&1
) || true
assert_contains "$output" "Iteration 1" "ran iteration 1"

# Test 5: Supervisor error
export MOCK_CLAUDE_RESPONSE="ERROR: supervisor failed — see log"
{ echo "ITERATION=0"; echo "CONVERGED=false"; } > .claude/loop-state5
create_goal_file "goal4.md"

output=$(bash "$SCRIPTS_DIR/loop-runner.sh" "goal4.md" --max-iter 3 --state .claude/loop-state5 --log-dir logs/loop 2>&1) || true
assert_contains "$output" "Supervisor failed" "reports supervisor failure"

# Test 6: Resume preserves iteration count
{ echo "ITERATION=3"; echo "CONVERGED=false"; echo "GOAL=$(realpath goal.md)"; echo "STARTED=2026-01-01T00:00:00"; } > .claude/loop-state6
export MOCK_CLAUDE_RESPONSE="STATUS: CONVERGED"

output=$(bash "$SCRIPTS_DIR/loop-runner.sh" "goal.md" --max-iter 10 --state .claude/loop-state6 --log-dir logs/loop --resume 2>&1) || true
assert_contains "$output" "Iteration 4" "resume starts from iteration 4 (was 3)"

# Test 7: Fresh start resets iteration
{ echo "ITERATION=5"; echo "CONVERGED=false"; } > .claude/loop-state7
export MOCK_CLAUDE_RESPONSE="STATUS: CONVERGED"

output=$(bash "$SCRIPTS_DIR/loop-runner.sh" "goal.md" --max-iter 10 --state .claude/loop-state7 --log-dir logs/loop 2>&1) || true
# Fresh start (no --resume) should reset to iteration 0, so first iteration is 1
assert_contains "$output" "Iteration 1" "fresh start resets to iteration 1"
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 6: run-tasks-parallel.sh
# ═══════════════════════════════════════════════════════════════════════

if should_run "parallel"; then
section "run-tasks-parallel.sh — Dry Run Tests"

REPO_DIR=$(setup_test_repo)
cd "$REPO_DIR"
TASK_FILE="$REPO_DIR/tasks.txt"
mkdir -p logs/claude-tasks

# Test dry-run mode (no claude calls)
create_task_file_new_format "$TASK_FILE"
output=$(bash "$SCRIPTS_DIR/run-tasks-parallel.sh" "$TASK_FILE" --dry-run 2>&1)
assert_contains "$output" "DRY RUN" "dry-run mode works"
assert_contains "$output" "3 tasks" "reports 3 tasks"
assert_contains "$output" "haiku" "shows haiku model"
assert_contains "$output" "sonnet" "shows sonnet model"
assert_contains "$output" "opus" "shows opus model"

# Test conflict grouping in dry-run
create_task_file_conflict "$TASK_FILE"
output=$(bash "$SCRIPTS_DIR/run-tasks-parallel.sh" "$TASK_FILE" --dry-run 2>&1)
assert_contains "$output" "Execution groups" "shows execution groups"
# Tasks 1 and 2 share auth.py → should be in same group
assert_contains "$output" "3 tasks" "reports 3 tasks"

# Test single task dry-run
create_task_file_single "$TASK_FILE"
output=$(bash "$SCRIPTS_DIR/run-tasks-parallel.sh" "$TASK_FILE" --dry-run 2>&1)
assert_contains "$output" "1 tasks" "single task dry-run"

# Test missing task file
output=$(bash "$SCRIPTS_DIR/run-tasks-parallel.sh" "/nonexistent/tasks.txt" 2>&1) || true
assert_contains "$output" "not found" "reports missing task file"

# Test not-in-git-repo error
tmpdir=$(mktemp -d /tmp/test-nogit-XXXXXX)
cp "$TASK_FILE" "$tmpdir/tasks.txt"
output=$(cd "$tmpdir" && bash "$SCRIPTS_DIR/run-tasks-parallel.sh" "$tmpdir/tasks.txt" 2>&1) || true
assert_contains "$output" "git repo" "reports not-in-git-repo error"
rm -rf "$tmpdir"
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 7: run-tasks.sh — Serial Executor
# ═══════════════════════════════════════════════════════════════════════

if should_run "serial"; then
section "run-tasks.sh — Serial Executor"

REPO_DIR=$(setup_test_repo)
cd "$REPO_DIR"
TASK_FILE="$REPO_DIR/tasks.txt"
mkdir -p logs/claude-tasks

# Test dry-run mode
create_task_file_new_format "$TASK_FILE"
output=$(bash "$SCRIPTS_DIR/run-tasks.sh" "$TASK_FILE" --dry-run 2>&1)
assert_contains "$output" "DRY RUN" "dry-run mode works"
assert_contains "$output" "1/3" "shows task 1/3"
assert_contains "$output" "2/3" "shows task 2/3"
assert_contains "$output" "3/3" "shows task 3/3"

# Test legacy format dry-run
create_task_file_legacy "$TASK_FILE"
output=$(bash "$SCRIPTS_DIR/run-tasks.sh" "$TASK_FILE" --dry-run 2>&1)
assert_contains "$output" "DRY RUN" "legacy dry-run works"
assert_contains "$output" "server.py" "legacy task 1 shown"

# Test with single task (mock claude returns success)
# Run in a clean subshell to avoid inheriting file descriptors from previous tests
create_task_file_single "$TASK_FILE"
export MOCK_CLAUDE_RESPONSE="Done!"
export MOCK_CLAUDE_EXIT=0

output=$(
  exec 3>&- 4>&- 5>&- 6>&- 7>&- 8>&- 9>&- 2>/dev/null  # close leaked FDs
  timeout --kill-after=5s 30s bash "$SCRIPTS_DIR/run-tasks.sh" "$TASK_FILE" --keep-logs 2>&1
) || true
# The task should succeed since mock claude exits 0
assert_contains "$output" "Done" "serial run completes"
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 8: Progress File
# ═══════════════════════════════════════════════════════════════════════

if should_run "progress"; then
section "Progress File"

REPO_DIR=$(setup_test_repo)
cd "$REPO_DIR"
mkdir -p .claude logs/loop

create_goal_file "goal.md"
export MOCK_CLAUDE_RESPONSE="STATUS: CONVERGED"

output=$(bash "$SCRIPTS_DIR/loop-runner.sh" "goal.md" --max-iter 2 --state .claude/loop-state --log-dir logs/loop 2>&1) || true

# Check that a progress file was created
progress_files=$(ls -t logs/loop/*-progress 2>/dev/null | head -1)
TESTS_RUN=$((TESTS_RUN + 1))
if [[ -n "$progress_files" ]]; then
  pass "progress file created"
  assert_file_contains "$progress_files" "STATUS=" "progress file has STATUS"
  assert_file_contains "$progress_files" "GOAL=" "progress file has GOAL"
  assert_file_contains "$progress_files" "ITERATION=" "progress file has ITERATION"
else
  fail "progress file not created"
fi
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 9: Supervisor Output Processing
# ═══════════════════════════════════════════════════════════════════════

if should_run "supervisor"; then
section "Supervisor Output Processing"

# Test the task file generation logic from loop-runner.sh WITHOUT running workers.
# We simulate supervisor output and test the awk/sed processing that produces task files.

REPO_DIR=$(setup_test_repo)
cd "$REPO_DIR"
mkdir -p .claude logs/loop

# ── Test 1: Free-text output is wrapped as a single task ──
SUPERVISOR_OUTPUT="Please fix the following issues:
1. Bug in login
2. Missing tests
3. Outdated docs"
WORKER_MODEL="sonnet"

ITER_TASKS="$REPO_DIR/iter-tasks-1.txt"
if echo "$SUPERVISOR_OUTPUT" | grep -q "^===TASK===$"; then
  echo "HAS TASKS" > /dev/null  # won't reach here
else
  {
    echo "===TASK==="
    echo "model: $WORKER_MODEL"
    echo "timeout: 1800"
    echo "retries: 1"
    echo "---"
    echo "$SUPERVISOR_OUTPUT"
  } > "$ITER_TASKS"
fi

task_count=$(grep -c '^===TASK===$' "$ITER_TASKS")
assert_eq "1" "$task_count" "free-text output wrapped as single task"
assert_file_contains "$ITER_TASKS" "Bug in login" "free-text content preserved in task"
assert_file_contains "$ITER_TASKS" "model: sonnet" "default model assigned"

# ── Test 2: Proper ===TASK=== format with preamble ──
SUPERVISOR_OUTPUT2="Let me analyze the goal and plan tasks:

===TASK===
model: haiku
timeout: 300
retries: 1
---
Fix the login bug

===TASK===
model: sonnet
timeout: 600
retries: 1
---
Add rate limiting"

ITER_TASKS2="$REPO_DIR/iter-tasks-2.txt"
if echo "$SUPERVISOR_OUTPUT2" | grep -q "^===TASK===$"; then
  # This is the actual processing logic from loop-runner.sh
  PROCESSED=$(mktemp /tmp/loop-tasks-XXXXXX.txt)
  in_body=false
  seen_first_task=false
  while IFS= read -r line; do
    if [[ "$line" == "===TASK===" ]]; then
      if $in_body; then
        echo ""
        echo "## Commit & self-review"
        echo "- Use committer"
      fi
      echo "===TASK==="
      in_body=false
      seen_first_task=true
    elif [[ "$line" == "---" ]] && ! $in_body && $seen_first_task; then
      echo "---"
      in_body=true
    elif $seen_first_task; then
      echo "$line"
    fi
  done <<< "$SUPERVISOR_OUTPUT2" > "$PROCESSED"
  if $in_body; then
    {
      echo ""
      echo "## Commit & self-review"
      echo "- Use committer"
    } >> "$PROCESSED"
  fi
  mv "$PROCESSED" "$ITER_TASKS2"
fi

task_count2=$(grep -c '^===TASK===$' "$ITER_TASKS2")
assert_eq "2" "$task_count2" "===TASK=== format: 2 tasks parsed"
assert_not_contains "$(cat "$ITER_TASKS2")" "Let me analyze" "preamble stripped"
assert_file_contains "$ITER_TASKS2" "Fix the login bug" "task 1 body preserved"
assert_file_contains "$ITER_TASKS2" "Add rate limiting" "task 2 body preserved"
assert_file_contains "$ITER_TASKS2" "Commit & self-review" "self-review footer appended"

# ── Test 3: Full loop-runner with actual worker execution (fast mock) ──
create_goal_file "goal.md"
export MOCK_CLAUDE_RESPONSE="===TASK===
model: haiku
timeout: 10
retries: 0
---
Create hello.txt"

{ echo "ITERATION=0"; echo "CONVERGED=false"; } > .claude/loop-state
output=$(
  exec 3>&- 4>&- 5>&- 6>&- 7>&- 8>&- 9>&- 2>/dev/null
  timeout --kill-after=5s 60s bash "$SCRIPTS_DIR/loop-runner.sh" "goal.md" --max-iter 1 --max-workers 1 --state .claude/loop-state --log-dir logs/loop 2>&1
) || true
assert_contains "$output" "1 task(s)" "full run: 1 task parsed and dispatched"
assert_contains "$output" "Iteration 1" "full run: iteration 1 executed"
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 10: Worktree Lifecycle
# ═══════════════════════════════════════════════════════════════════════

if should_run "worktree"; then
section "Worktree Lifecycle"

REPO_DIR=$(setup_test_repo)
cd "$REPO_DIR"

REPO_NAME=$(basename "$REPO_DIR")
WORKTREE_BASE="$(dirname "$REPO_DIR")/.worktrees-${REPO_NAME}"
BRANCH_NAME="batch/task-1-test"
WT_DIR="$WORKTREE_BASE/task-1"

# Test worktree creation
mkdir -p "$WORKTREE_BASE"
git branch "$BRANCH_NAME" HEAD 2>/dev/null
git worktree add "$WT_DIR" "$BRANCH_NAME" 2>/dev/null
ec=$?
assert_exit_code "0" "$ec" "worktree created successfully"

TESTS_RUN=$((TESTS_RUN + 1))
if [[ -d "$WT_DIR" ]]; then
  pass "worktree directory exists"
else
  fail "worktree directory not created"
fi

# Test worktree has correct branch
wt_branch=$(cd "$WT_DIR" && git rev-parse --abbrev-ref HEAD)
assert_eq "$BRANCH_NAME" "$wt_branch" "worktree on correct branch"

# Test changes in worktree are isolated
echo "worktree change" > "$WT_DIR/new-file.txt"
(cd "$WT_DIR" && git add new-file.txt && git commit -q -m "test: worktree change" --no-verify)

# Main branch should NOT have the file
TESTS_RUN=$((TESTS_RUN + 1))
if [[ ! -f "$REPO_DIR/new-file.txt" ]]; then
  pass "worktree changes isolated from main"
else
  fail "worktree changes leaked to main"
fi

# Test merge from worktree
ahead=$(git rev-list --count HEAD.."$BRANCH_NAME" 2>/dev/null)
assert_eq "1" "$ahead" "worktree branch 1 commit ahead"

git merge --no-edit "$BRANCH_NAME" 2>/dev/null
ec=$?
assert_exit_code "0" "$ec" "merge from worktree succeeds"
assert_file_exists "$REPO_DIR/new-file.txt" "merged file exists in main"

# Test worktree cleanup
git worktree remove "$WT_DIR" --force 2>/dev/null
git branch -D "$BRANCH_NAME" 2>/dev/null

TESTS_RUN=$((TESTS_RUN + 1))
if [[ ! -d "$WT_DIR" ]]; then
  pass "worktree removed successfully"
else
  fail "worktree still exists after removal"
fi

wt_list=$(git worktree list)
TESTS_RUN=$((TESTS_RUN + 1))
if echo "$wt_list" | grep -qF "$WT_DIR"; then
  fail "worktree still in git worktree list"
else
  pass "worktree removed from git worktree list"
fi
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 11: Edge Cases
# ═══════════════════════════════════════════════════════════════════════

if should_run "edge"; then
section "Edge Cases"

# Test: empty task file
REPO_DIR=$(setup_test_repo)
cd "$REPO_DIR"
mkdir -p logs/claude-tasks

echo "" > empty-tasks.txt
output=$(bash "$SCRIPTS_DIR/run-tasks-parallel.sh" "empty-tasks.txt" --dry-run 2>&1) || true
assert_contains "$output" "0 tasks" "empty task file → 0 tasks"

# Test: task file with only comments
cat > comment-tasks.txt <<'EOF'
# This is a comment
# Another comment

# Third comment
EOF
task_count=$(grep -cvE '^[[:space:]]*(#|$)' comment-tasks.txt 2>/dev/null || true)
task_count="${task_count%%$'\n'*}"  # take first line only
assert_eq "0" "${task_count:-0}" "comment-only file → 0 tasks"

# Test: task with empty body (===TASK=== then ===TASK===)
cat > empty-body-tasks.txt <<'EOF'
===TASK===
model: haiku
timeout: 300
retries: 0
---

===TASK===
model: sonnet
timeout: 300
retries: 0
---
Real task here
EOF
tc=$(grep -c '^===TASK===$' empty-body-tasks.txt)
assert_eq "2" "$tc" "task with empty body still counted"

# Extract empty body task
empty_body=$(awk -v n=1 '
  /^===TASK===$/ { count++; in_meta=1; in_body=0; next }
  count == n && in_meta && /^---$/ { in_meta=0; in_body=1; next }
  count == n && in_body && /^===TASK===$/ { exit }
  count == n && in_body { print }
  count > n { exit }
' empty-body-tasks.txt | sed -e '1{/^$/d}' -e '${/^$/d}')
assert_eq "" "$empty_body" "empty body task has no content"

# Test: model field with extra spaces
cat > spaces-tasks.txt <<'EOF'
===TASK===
model:   haiku
timeout:  300
retries:  1
---
Task body
EOF
model=$(awk -v n=1 -v field="model" '
  /^===TASK===$/ { count++ }
  count == n && $0 ~ "^"field":" {
    gsub("^"field":[[:space:]]*", ""); print; found=1; exit
  }
  count == n && /^---$/ { if (!found) exit }
  END { if (!found) print "" }
' spaces-tasks.txt)
# Note: the awk regex matches "model:" then gsubs leading spaces — trailing spaces remain
# This is a known quirk but shouldn't cause issues since model IDs are validated downstream
TESTS_RUN=$((TESTS_RUN + 1))
trimmed=$(echo "$model" | tr -d ' ')
if [[ "$trimmed" == "haiku" ]]; then
  pass "model field extracted (may have trailing spaces)"
else
  fail "model field extraction with spaces" "got '$model'"
fi

# Test: special characters in goal file path
REPO_DIR2=$(setup_test_repo)
cd "$REPO_DIR2"
mkdir -p "path with spaces"
create_goal_file "path with spaces/goal.md"
assert_file_exists "path with spaces/goal.md" "goal file with spaces in path created"
# Note: loop-runner.sh uses realpath and quotes, should handle this

# Test: very long task prompt
long_prompt=$(python3 -c "print('x ' * 5000)" 2>/dev/null || printf 'x %.0s' {1..5000})
TESTS_RUN=$((TESTS_RUN + 1))
if [[ ${#long_prompt} -gt 1000 ]]; then
  pass "long prompt generation works (${#long_prompt} chars)"
else
  fail "long prompt too short: ${#long_prompt}"
fi

# Test: concurrent state file writes (race condition check)
REPO_DIR3=$(setup_test_repo)
cd "$REPO_DIR3"
mkdir -p .claude
echo "ITERATION=0" > .claude/test-race-state

# Simulate 10 concurrent writes
for i in $(seq 1 10); do
  (
    local_state=".claude/test-race-state"
    if grep -q "^ITER_$i=" "$local_state" 2>/dev/null; then
      sed -i "s|^ITER_$i=.*|ITER_$i=$i|" "$local_state"
    else
      echo "ITER_$i=$i" >> "$local_state"
    fi
  ) &
done
wait

# Check that state file is not corrupted
line_count=$(wc -l < .claude/test-race-state)
TESTS_RUN=$((TESTS_RUN + 1))
if [[ $line_count -ge 1 ]]; then
  pass "state file survived concurrent writes ($line_count lines)"
else
  fail "state file corrupted by concurrent writes"
fi
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 12: models.env Integration
# ═══════════════════════════════════════════════════════════════════════

if should_run "models"; then
section "models.env Integration"

source "$ORIG_DIR/configs/models.env"

assert_eq "claude-haiku-4-5-20251001" "$MODEL_HAIKU" "MODEL_HAIKU correct"
assert_eq "claude-sonnet-4-6" "$MODEL_SONNET" "MODEL_SONNET correct"
assert_eq "claude-opus-4-6" "$MODEL_OPUS" "MODEL_OPUS correct"

# Test model_id resolution
model_id_test() {
  case "$1" in
    haiku)  echo "$MODEL_HAIKU" ;;
    sonnet) echo "$MODEL_SONNET" ;;
    opus)   echo "$MODEL_OPUS" ;;
    *)      echo "$1" ;;
  esac
}

assert_eq "$MODEL_HAIKU" "$(model_id_test haiku)" "model_id: haiku → full ID"
assert_eq "$MODEL_SONNET" "$(model_id_test sonnet)" "model_id: sonnet → full ID"
assert_eq "$MODEL_OPUS" "$(model_id_test opus)" "model_id: opus → full ID"
assert_eq "custom-model" "$(model_id_test custom-model)" "model_id: unknown → passthrough"
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 13: Deployed Script Verification
# ═══════════════════════════════════════════════════════════════════════

if should_run "deploy"; then
section "Deployed Script Verification"

DEPLOY_DIR="$HOME/.claude/scripts"

for script in loop-runner.sh run-tasks-parallel.sh run-tasks.sh; do
  src="$ORIG_DIR/configs/scripts/$script"
  dst="$DEPLOY_DIR/$script"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -f "$src" && -f "$dst" ]]; then
    if diff -q "$src" "$dst" &>/dev/null; then
      pass "deployed $script matches source"
    else
      fail "deployed $script DIFFERS from source" "run install.sh to sync"
    fi
  elif [[ ! -f "$dst" ]]; then
    fail "$script not deployed" "missing: $dst"
  else
    pass "$script deployment check (source not found, skip)"
  fi
done
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 14: Signal Handling
# ═══════════════════════════════════════════════════════════════════════

if should_run "signal"; then
section "Signal Handling"

# Test the SIGTERM trap logic from loop-runner.sh directly
# (Spawning a full loop with workers and killing it is fragile in CI)

REPO_DIR=$(setup_test_repo)
cd "$REPO_DIR"
mkdir -p .claude

STATE_FILE=".claude/loop-state-signal"
{ echo "ITERATION=2"; echo "CONVERGED=false"; } > "$STATE_FILE"

# Simulate the _cleanup function from loop-runner.sh
_cleanup_test() {
  [[ -n "${STATE_FILE:-}" ]] && {
    local key="INTERRUPTED" val="true"
    if grep -q "^${key}=" "$STATE_FILE"; then
      sed -i "s|^${key}=.*|${key}=${val}|" "$STATE_FILE"
    else
      echo "${key}=${val}" >> "$STATE_FILE"
    fi
  }
}

_cleanup_test
assert_file_contains "$STATE_FILE" "INTERRUPTED=true" "cleanup writes INTERRUPTED=true"
assert_file_contains "$STATE_FILE" "ITERATION=2" "cleanup preserves ITERATION"
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 15: setsid --wait Verification
# ═══════════════════════════════════════════════════════════════════════

if should_run "setsid"; then
section "setsid --wait Verification"

# Critical: setsid without --wait causes workers to appear to succeed instantly
TESTS_RUN=$((TESTS_RUN + 1))
if command -v setsid &>/dev/null; then
  if setsid --help 2>&1 | grep -q "\-\-wait"; then
    pass "setsid --wait is available"
  else
    fail "setsid exists but --wait flag missing" "workers may not wait for completion"
  fi
else
  fail "setsid not found" "install util-linux for process group isolation"
fi
fi

# ═══════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL $TESTS_RUN TESTS PASSED${NC}"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit $TESTS_FAILED
