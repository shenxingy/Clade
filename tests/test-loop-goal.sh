#!/usr/bin/env bash
# Deterministic Loop coordinator reconciliation and commit-accounting coverage.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER="$ROOT/configs/scripts/loop-runner.sh"
HELPER="$ROOT/configs/scripts/loop_goal.py"
TEST_ROOT=$(mktemp -d /tmp/test-loop-goal-XXXXXX)
trap 'rm -rf "$TEST_ROOT"' EXIT

# Commit-creating fixtures need a pinned VCS identity (see configs/scripts/
# git_identity.py). test-loop.sh pins one before calling this file, so this
# suite passed there while failing 5 cases whenever it was run on its own —
# and CI only ever invokes it through test-loop.sh, so the standalone break
# stayed invisible. Pin our own when the parent has not already, keeping the
# parent's identity authoritative when it has.
if [[ -z "${CLADE_GIT_IDENTITY_FILE:-}" ]]; then
  LOOP_GOAL_IDENTITY_DIR=$(mktemp -d /tmp/test-loop-goal-identity-XXXXXX)
  trap 'rm -rf "$TEST_ROOT" "$LOOP_GOAL_IDENTITY_DIR"' EXIT
  export CLADE_GIT_IDENTITY_FILE="$LOOP_GOAL_IDENTITY_DIR/git-identity.json"
  python3 "$ROOT/configs/scripts/git_identity.py" \
    pin --name Test --email test@example.com >/dev/null || exit 1
fi

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
printf '===TASK===\ngoal_items_json: [{"line":3,"text":"exact item"}]\n---\nwork\n' > "$TEST_ROOT/unit/tasks.txt"
printf '1\tchanged\n' > "$TEST_ROOT/unit/changed.tsv"
printf '1\tunchanged\n' > "$TEST_ROOT/unit/unchanged.tsv"
# Last line per index wins: a merge conflict re-run is recorded after the first.
printf '1\tfailed\n1\tchanged\n' > "$TEST_ROOT/unit/rerun.tsv"
reconcile() { python3 "$HELPER" --goal "$TEST_ROOT/unit/goal.md" --task-file "$TEST_ROOT/unit/$1" --outcomes "$TEST_ROOT/unit/$2"; }

marked=$(reconcile tasks.txt unchanged.tsv 2>/dev/null)
contains "$marked" "0" "a task that changed nothing marks no item"
contains "$(cat "$TEST_ROOT/unit/goal.md")" "- [ ] exact item" "an unchanged task leaves the item unchecked"
if reconcile tasks.txt missing.tsv >/dev/null 2>&1; then
  fail "reconciliation without an outcomes file fails closed"
else
  pass "reconciliation without an outcomes file fails closed"
fi
contains "$(cat "$TEST_ROOT/unit/goal.md")" "- [ ] exact item" "a refused reconciliation writes nothing"
marked=$(reconcile tasks.txt rerun.tsv)
contains "$marked" "1" "the last recorded outcome for a task is the one read"
printf '# Goal\n\n- [ ] exact item\n' > "$TEST_ROOT/unit/goal.md"
marked=$(reconcile tasks.txt changed.tsv)
contains "$marked" "1" "exact line/text evidence marks one item"
contains "$(cat "$TEST_ROOT/unit/goal.md")" "- [x] exact item" "coordinator writes the checked marker"
marked=$(reconcile tasks.txt changed.tsv)
contains "$marked" "0" "reconciliation is idempotent"
printf '===TASK===\ngoal_items_json: [{"line":3,"text":"wrong item"}]\n' > "$TEST_ROOT/unit/bad-tasks.txt"
if reconcile bad-tasks.txt changed.tsv >/dev/null 2>&1; then
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
  if [[ "${MOCK_TWO_TASKS:-false}" == "true" ]]; then
    echo '[{"description":"Create work file and commit it to satisfy the first item","model":"haiku","files":["work.txt"],"goal_items":[{"line":3,"text":"exact item"}]},{"description":"NOOP: try the second item, change nothing and exit cleanly","model":"haiku","files":["other.txt"],"goal_items":[{"line":4,"text":"second item"}]}]'
  else
    echo '[{"description":"Update README.md and commit it to satisfy the exact item","model":"haiku","files":["README.md"],"goal_items":[{"line":3,"text":"exact item"}]}]'
  fi
elif [[ "$args" == *"stream-json"* ]]; then
  [[ "${MOCK_WORKER_FAIL:-false}" == "true" ]] && exit 9
  # A worker that gives up the Tier-2 way: logs, changes nothing, exits 0.
  if [[ "${MOCK_WORKER_NOOP:-false}" == "true" || "$input" == *"NOOP:"* ]]; then
    echo '{"type":"result","subtype":"success","result":"skipped: could not do it"}'
    exit 0
  fi
  f="work-$$.txt"
  printf 'worker\n' >> "$f"
  git add "$f"
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

# A worker that exits 0 having changed nothing — the Tier-2 "skip, log,
# continue" path every task brief prescribes — used to count as a success. With
# no changed files node_verify returns "no changes" as a pass, every gate is
# green, and the coordinator checked the item off: the loop could report
# CONVERGED having done nothing. Both worker runners are covered, because the
# loop picks run-tasks.sh at --max-workers 1 and run-tasks-parallel.sh above it.
for workers in 1 2; do
  printf '# Goal\n\n- [ ] exact item\n' > "$REPO/.claude/noop-goal-$workers.md"
  output=$(
    cd "$REPO" || exit
    PATH="$TEST_ROOT/bin:$PATH" MOCK_WORKER_NOOP=true timeout --kill-after=5s 60s \
      bash "$RUNNER" ".claude/noop-goal-$workers.md" --max-iter 1 --max-workers "$workers" \
      --state ".claude/noop-state-$workers.json" --log-dir "logs/noop-loop-$workers" 2>&1
  ) || true
  contains "$(cat "$REPO/.claude/noop-goal-$workers.md")" "- [ ] exact item" \
    "a task that changed nothing leaves its goal item unchecked (--max-workers $workers)"
  if printf '%s' "$output" | grep -qF "CONVERGED:"; then
    fail "a no-op iteration does not converge (--max-workers $workers)"
  else
    pass "a no-op iteration does not converge (--max-workers $workers)"
  fi
  contains "$output" "changed nothing" "the withheld item is named in the log (--max-workers $workers)"
done

# Per task, not per iteration: one task lands, its sibling changes nothing, and
# only the landed task's item is checked.
printf '# Goal\n\n- [ ] exact item\n- [ ] second item\n' > "$REPO/.claude/mixed-goal.md"
output=$(
  cd "$REPO" || exit
  PATH="$TEST_ROOT/bin:$PATH" MOCK_TWO_TASKS=true timeout --kill-after=5s 90s \
    bash "$RUNNER" .claude/mixed-goal.md --max-iter 1 --max-workers 2 \
    --state .claude/mixed-state.json --log-dir logs/mixed-loop 2>&1
) || true
mixed_goal=$(cat "$REPO/.claude/mixed-goal.md")
contains "$mixed_goal" "- [x] exact item" "the task that committed work reconciles its item"
contains "$mixed_goal" "- [ ] second item" "its no-op sibling's item stays unchecked"

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
