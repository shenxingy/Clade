#!/usr/bin/env bash
# Deterministic Loop coordinator reconciliation and commit-accounting coverage.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER="$ROOT/configs/scripts/loop-runner.sh"
HELPER="$ROOT/configs/scripts/loop_goal.py"
TEST_ROOT=$(mktemp -d /tmp/test-loop-goal-XXXXXX)
trap 'rm -rf "$TEST_ROOT"' EXIT
PASSED=0
FAILED=0

pass() { PASSED=$((PASSED + 1)); printf '  ✓ %s\n' "$1"; }
fail() { FAILED=$((FAILED + 1)); printf '  ✗ %s\n' "$1"; }
contains() {
  if printf '%s' "$1" | grep -qF -- "$2"; then pass "$3"; else fail "$3"; fi
}

printf '\n━━━ Loop coordinator reconciliation ━━━\n'

mkdir -p "$TEST_ROOT/unit"
printf '# Goal\n\n- [ ] exact item\n' > "$TEST_ROOT/unit/goal.md"
printf 'goal_items_json: [{"line":3,"text":"exact item"}]\n---\nwork\n' > "$TEST_ROOT/unit/tasks.txt"
marked=$(python3 "$HELPER" --goal "$TEST_ROOT/unit/goal.md" --task-file "$TEST_ROOT/unit/tasks.txt")
contains "$marked" "1" "exact line/text evidence marks one item"
contains "$(cat "$TEST_ROOT/unit/goal.md")" "- [x] exact item" "coordinator writes the checked marker"
marked=$(python3 "$HELPER" --goal "$TEST_ROOT/unit/goal.md" --task-file "$TEST_ROOT/unit/tasks.txt")
contains "$marked" "0" "reconciliation is idempotent"
printf 'goal_items_json: [{"line":3,"text":"wrong item"}]\n' > "$TEST_ROOT/unit/bad-tasks.txt"
if python3 "$HELPER" --goal "$TEST_ROOT/unit/goal.md" --task-file "$TEST_ROOT/unit/bad-tasks.txt" >/dev/null 2>&1; then
  fail "stale evidence fails closed"
else
  pass "stale evidence fails closed"
fi

REPO="$TEST_ROOT/repo"
mkdir -p "$REPO/.claude" "$TEST_ROOT/bin"
(
  cd "$REPO" || exit
  git init -q
  git config user.email test@example.com
  git config user.name Test
  printf '.claude/\nlogs/\n' > .gitignore
  printf 'initial\n' > README.md
  printf '# Test\n\n- Verify command: true\n' > CLAUDE.md
  printf '# Goal\n\n- [ ] exact item\n' > .claude/goal.md
  git add .gitignore README.md CLAUDE.md
  git commit -q -m "test: initialize fixture"
)

cat > "$TEST_ROOT/bin/claude" <<'EOF'
#!/usr/bin/env bash
args="$*"
input=$(cat)
if [[ "$args" == *"Verify these changed files"* ]]; then
  echo '{"passed":true,"items":[],"summary":"mock pass"}'
elif [[ "$args" == *"autonomous improvement loop"* ]]; then
  echo '[{"description":"Update README.md and commit it to satisfy the exact item","model":"haiku","files":["README.md"],"goal_items":[{"line":3,"text":"exact item"}]}]'
elif [[ "$args" == *"stream-json"* ]]; then
  [[ "${MOCK_WORKER_FAIL:-false}" == "true" ]] && exit 9
  printf 'worker\n' >> README.md
  git add README.md
  git commit -q -m "test: worker commit"
  echo '{"type":"result","subtype":"success","result":"done"}'
else
  echo '[]'
fi
EOF
chmod +x "$TEST_ROOT/bin/claude"

output=$(
  cd "$REPO" || exit
  PATH="$TEST_ROOT/bin:$PATH" timeout --kill-after=5s 60s \
    bash "$RUNNER" .claude/goal.md --max-iter 2 --max-workers 1 \
    --state .claude/state.json --log-dir logs/loop 2>&1
) || true
contains "$output" "Coordinator reconciled 1 goal item(s)" "verified worker evidence is reconciled by the coordinator"
contains "$output" "Counted 1 commit(s) in iteration 1" "worker-created commit is counted without leftover files"
contains "$output" "CONVERGED" "reconciled goal converges in the same iteration"
contains "$(cat "$REPO/.claude/goal.md")" "- [x] exact item" "worker never needed to edit the goal file"

printf '# Goal\n\n- [ ] exact item\n' > "$REPO/.claude/fail-goal.md"
output=$(
  cd "$REPO" || exit
  PATH="$TEST_ROOT/bin:$PATH" MOCK_WORKER_FAIL=true timeout --kill-after=5s 60s \
    bash "$RUNNER" .claude/fail-goal.md --max-iter 1 --max-workers 1 \
    --state .claude/fail-state.json --log-dir logs/fail-loop 2>&1
) || true
contains "$output" "Skipping goal reconciliation" "failed worker blocks coordinator reconciliation"
contains "$(cat "$REPO/.claude/fail-goal.md")" "- [ ] exact item" "failed task leaves goal evidence unchecked"

printf '===TASK===\nmodel: haiku\nretries: 0\n---\nFail deliberately\n' > "$REPO/.claude/fail-task.txt"
if (cd "$REPO" && PATH="$TEST_ROOT/bin:$PATH" MOCK_WORKER_FAIL=true bash "$ROOT/configs/scripts/run-tasks.sh" .claude/fail-task.txt --keep-logs >/dev/null 2>&1); then
  fail "serial worker runner propagates task failure"
else
  pass "serial worker runner propagates task failure"
fi
if (cd "$REPO" && PATH="$TEST_ROOT/bin:$PATH" MOCK_WORKER_FAIL=true MAX_WORKERS=1 bash "$ROOT/configs/scripts/run-tasks-parallel.sh" .claude/fail-task.txt >/dev/null 2>&1); then
  fail "parallel worker runner propagates task failure"
else
  pass "parallel worker runner propagates task failure"
fi

printf '\nGoal reconciliation tests: %d passed, %d failed\n' "$PASSED" "$FAILED"
[[ "$FAILED" -eq 0 ]]
