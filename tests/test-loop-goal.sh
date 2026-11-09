#!/usr/bin/env bash
# Deterministic Loop coordinator reconciliation and commit-accounting coverage.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER="$ROOT/configs/scripts/loop-runner.sh"
HELPER="$ROOT/configs/scripts/loop_goal.py"
ATTEMPTS="$ROOT/configs/scripts/loop_attempts.py"
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
  [[ -n "${MOCK_PROMPT_LOG:-}" ]] && printf '=====PROMPT=====\n%s\n' "$args" >> "$MOCK_PROMPT_LOG"
  if [[ "${MOCK_TWO_TASKS:-false}" == "true" ]]; then
    echo '[{"description":"Create work file and commit it to satisfy the first item","model":"haiku","files":["work.txt"],"goal_items":[{"line":3,"text":"exact item"}]},{"description":"NOOP: try the second item, change nothing and exit cleanly","model":"haiku","files":["other.txt"],"goal_items":[{"line":4,"text":"second item"}]}]'
  else
    echo '[{"description":"Update README.md and commit it to satisfy the exact item","model":"haiku","files":["README.md"],"goal_items":[{"line":3,"text":"exact item"}]}]'
  fi
elif [[ "$args" == *"stream-json"* ]]; then
  [[ "${MOCK_WORKER_FAIL:-false}" == "true" ]] && exit 9
  # A worker that gives up the Tier-2 way: logs, changes nothing, exits 0.
  if [[ "${MOCK_WORKER_NOOP:-false}" == "true" || "$input" == *"NOOP:"* ]]; then
    [[ -n "${MOCK_WORKER_LOG:-}" ]] && echo noop >> "$MOCK_WORKER_LOG"
    echo '{"type":"result","subtype":"success","result":"skipped: could not do it"}'
    exit 0
  fi
  [[ -n "${MOCK_WORKER_LOG:-}" ]] && echo work >> "$MOCK_WORKER_LOG"
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

printf '\n━━━ Loop attempt ledger ━━━\n'

# Unit: loop_attempts.py over a hand-built iteration.
U="$TEST_ROOT/attempts"
mkdir -p "$U"
printf '# Goal\n\n- [ ] stuck item\n- [ ] other item\n' > "$U/goal.md"
printf '===TASK===\nmodel: haiku\ngoal_items_json: [{"line":3,"text":"stuck item"}]\n---\nTry the stuck item via approach A\n\n===TASK===\nmodel: haiku\ngoal_items_json: []\n---\nSupporting refactor\n' > "$U/tasks.txt"
printf '{"type":"assistant"}\n[heartbeat 01:00:00] worker alive\n{"type":"result","subtype":"success","result":"gave up: the API needs a key"}\n' > "$U/worker.log"
printf '1\tunchanged\t%s\n2\tchanged\n' "$U/worker.log" > "$U/outcomes.tsv"
record() { python3 "$ATTEMPTS" record --ledger "$U/ledger.jsonl" --goal "$U/goal.md" --task-file "$U/tasks.txt" --outcomes "$U/outcomes.tsv" --iteration "$1" --skipped "$U/skipped.md"; }
filter() { printf '%s' '[{"description":"again A","goal_items":[{"line":3,"text":"stuck item"}]},{"description":"unbound","goal_items":[]}]' | python3 "$ATTEMPTS" filter --ledger "$U/ledger.jsonl" --goal "$U/goal.md" 2>/dev/null; }

record 1 2>/dev/null
first=$(head -1 "$U/ledger.jsonl")
contains "$first" '"landed": false' "a task that changed nothing is recorded as not landed"
contains "$first" '"reason": "worker changed nothing"' "the ledger says why it did not land"
contains "$first" 'gave up: the API needs a key' "the worker's own last message is captured from its stream-json log"
contains "$(sed -n 2p "$U/ledger.jsonl")" '"landed": true' "a changed task with no goal items is recorded as landed"
ctx=$(python3 "$ATTEMPTS" context --ledger "$U/ledger.jsonl" --goal "$U/goal.md")
contains "$ctx" '"stuck item" — 1 of 3 attempts used' "context names the open item and its attempt count"
contains "$ctx" 'Try the stuck item via approach A' "context shows the approach that was tried"
contains "$(filter)" '"again A"' "an item with attempts left is not filtered"
record 2 2>/dev/null
parked_msg=$(record 3 2>&1)
contains "$parked_msg" "parked goal item after 3 attempts: stuck item" "the third miss parks the item"
filtered=$(filter)
if printf '%s' "$filtered" | grep -qF '"again A"'; then fail "a task bound to a parked item is dropped"; else pass "a task bound to a parked item is dropped"; fi
contains "$filtered" '"unbound"' "unbound work survives the filter"
record 4 2>/dev/null
park_entries=$(grep -c 'Skipped: goal item "stuck item"' "$U/skipped.md" 2>/dev/null || true)
if [[ "$park_entries" == "1" ]]; then pass "the item is parked in skipped.md once, not per later miss"; else fail "the item is parked in skipped.md once, not per later miss (got $park_entries)"; fi
printf '# Goal\n\n- [x] stuck item\n- [ ] other item\n' > "$U/goal.md"
contains "$(filter)" '"again A"' "an item checked since no longer counts as parked"
if [[ -z "$(python3 "$ATTEMPTS" context --ledger "$U/ledger.jsonl" --goal "$U/goal.md")" ]]; then
  pass "context is empty when no open item has a miss"
else
  fail "context is empty when no open item has a miss"
fi

# The supervisor prompt's own rules mention "Prior attempts that did not land",
# so only the rendered heading proves the ledger reached the prompt.
LEDGER_HEADING="## Prior attempts that did not land"
nth_prompt() { awk -v want="$2" '/^=====PROMPT=====$/{n++} n==want' "$1"; }

# End to end, parallel runner: one item lands every iteration so the run keeps
# going, its sibling never lands. The sibling's worker must run 3 times, not
# once per iteration. (--max-workers also caps tasks per iteration, so this
# mixed shape needs two workers.) The ledger is pre-seeded with three misses for
# the same item: a fresh run that inherited them would drop the task from
# iteration 1 and run it 0 times.
printf '# Goal\n\n- [ ] exact item\n- [ ] second item\n' > "$REPO/.claude/ledger-goal.md"
seed='{"iteration":1,"task":1,"description":"old run","goal_items":["second item"],"outcome":"failed","landed":false,"reason":"worker failed"}'
printf '%s\n%s\n%s\n' "$seed" "$seed" "$seed" > "$REPO/.claude/ledger-state-attempts.jsonl"
rm -f "$REPO/.claude/skipped.md"
output=$(
  cd "$REPO" || exit
  PATH="$TEST_ROOT/bin:$PATH" MOCK_TWO_TASKS=true \
    MOCK_PROMPT_LOG="$TEST_ROOT/prompts.log" MOCK_WORKER_LOG="$TEST_ROOT/workers.log" \
    timeout --kill-after=5s 180s \
    bash "$RUNNER" .claude/ledger-goal.md --max-iter 4 --max-workers 2 \
    --state .claude/ledger-state.json --log-dir logs/ledger-loop 2>&1
) || true
noop_runs=$(grep -c '^noop$' "$TEST_ROOT/workers.log" 2>/dev/null || true)
work_runs=$(grep -c '^work$' "$TEST_ROOT/workers.log" 2>/dev/null || true)
if [[ "$noop_runs" == "3" ]]; then
  pass "an item that never lands is attempted 3 times in 4 iterations"
else
  fail "an item that never lands is attempted 3 times in 4 iterations (got $noop_runs)"
fi
if [[ "$work_runs" == "4" ]]; then
  pass "its landing sibling keeps running every iteration"
else
  fail "its landing sibling keeps running every iteration (got $work_runs)"
fi
contains "$output" 'dropped task bound to parked goal item "second item"' "the drop is logged"
contains "$(cat "$REPO/.claude/skipped.md" 2>/dev/null)" 'Skipped: goal item "second item"' "the parked item lands in skipped.md"
if nth_prompt "$TEST_ROOT/prompts.log" 1 | grep -qF "$LEDGER_HEADING"; then
  fail "a fresh run starts from an empty ledger"
else
  pass "a fresh run starts from an empty ledger"
fi
prompt2=$(nth_prompt "$TEST_ROOT/prompts.log" 2)
contains "$prompt2" "$LEDGER_HEADING" "iteration 2's supervisor sees iteration 1's miss"
contains "$prompt2" "skipped: could not do it" "iteration 2's supervisor sees the worker's own reason"

# Serial runner (--max-workers 1): its outcome line carries a relative,
# per-attempt log path; the worker's reason must still reach iteration 2.
printf '# Goal\n\n- [ ] exact item\n' > "$REPO/.claude/ledger-serial-goal.md"
output=$(
  cd "$REPO" || exit
  PATH="$TEST_ROOT/bin:$PATH" MOCK_WORKER_NOOP=true MOCK_PROMPT_LOG="$TEST_ROOT/prompts-serial.log" \
    timeout --kill-after=5s 90s \
    bash "$RUNNER" .claude/ledger-serial-goal.md --max-iter 2 --max-workers 1 \
    --state .claude/ledger-serial-state.json --log-dir logs/ledger-serial-loop 2>&1
) || true
prompt2=$(nth_prompt "$TEST_ROOT/prompts-serial.log" 2)
contains "$prompt2" "$LEDGER_HEADING" "serial: iteration 2's supervisor sees iteration 1's miss"
contains "$prompt2" "skipped: could not do it" "serial: the worker's reason is read from its per-attempt log"

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
