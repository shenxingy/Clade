#!/usr/bin/env bash
# Deterministic crash-recovery coverage for loop-runner.sh.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER="$ROOT/configs/scripts/loop-runner.sh"
HELPER="$ROOT/configs/scripts/loop_checkpoint.py"
TEST_ROOT=$(mktemp -d /tmp/test-loop-checkpoint-XXXXXX)
ORIGINAL_HOME="$HOME"
export HOME="$TEST_ROOT/home"
mkdir -p "$HOME" "$TEST_ROOT/bin"
PASSED=0
FAILED=0

cleanup() {
  export HOME="$ORIGINAL_HOME"
  rm -rf "$TEST_ROOT"
}
trap cleanup EXIT

pass() { PASSED=$((PASSED + 1)); printf '  ✓ %s\n' "$1"; }
fail() { FAILED=$((FAILED + 1)); printf '  ✗ %s\n' "$1"; }
contains() {
  if printf '%s' "$1" | grep -qF "$2"; then pass "$3"; else fail "$3"; fi
}
not_contains() {
  if printf '%s' "$1" | grep -qF "$2"; then fail "$3"; else pass "$3"; fi
}

cat > "$TEST_ROOT/bin/claude" <<'EOF'
#!/usr/bin/env bash
input=$(cat)
if [[ -n "${MOCK_CALLS:-}" ]]; then
  printf 'CALL\n' >> "$MOCK_CALLS"
fi
if [[ "$input" == *'"passed": true or false'* ]]; then
  echo '{"passed":true,"items":[],"summary":"mock pass"}'
else
  echo '[]'
fi
EOF
chmod +x "$TEST_ROOT/bin/claude"
export PATH="$TEST_ROOT/bin:$PATH"

new_repo() {
  local name="$1"
  local repo="$TEST_ROOT/$name"
  mkdir -p "$repo"
  (
    cd "$repo" || exit
    git init -q
    git config user.email test@example.com
    git config user.name Test
    printf 'init\n' > README.md
    printf '# Goal\n\n- [x] complete\n' > goal.md
    git add README.md goal.md
    git commit -q -m "test: initialize fixture"
  )
  printf '%s\n' "$repo"
}

printf '\n━━━ Loop checkpoint recovery ━━━\n'

output=$(cd "$TEST_ROOT" && bash "$RUNNER" --help 2>&1)
contains "$output" "Usage: loop-runner.sh" "--help prints usage"
if [[ ! -e "$HOME/.claude" ]]; then pass "--help has no checkpoint side effects"; else fail "--help has no checkpoint side effects"; fi

repo=$(new_repo fresh)
(
  cd "$repo" || exit
  python3 "$HELPER" save --goal goal.md --iteration 7 --phase pre-done >/dev/null
)
output=$(cd "$repo" && bash "$RUNNER" goal.md --max-iter 2 --max-workers 1 --state .claude/state --log-dir logs/loop 2>&1)
contains "$output" "Iteration 1" "fresh run starts at iteration 1"
not_contains "$output" "[RECOVERY]" "fresh run ignores old checkpoint"

repo=$(new_repo resume-pre)
(
  cd "$repo" || exit
  python3 "$HELPER" save --goal goal.md --iteration 4 --phase pre-done >/dev/null
)
output=$(cd "$repo" && bash "$RUNNER" goal.md --resume --max-iter 4 --max-workers 1 --state .claude/state --log-dir logs/loop 2>&1)
contains "$output" "Iteration 4" "pre-done resumes the recorded iteration"
not_contains "$output" "Iteration 1" "pre-done does not restart at iteration 1"

repo=$(new_repo resume-workers)
export MOCK_CALLS="$TEST_ROOT/worker-resume-calls"
(
  cd "$repo" || exit
  python3 "$HELPER" save --goal goal.md --iteration 2 --phase workers-done >/dev/null
)
output=$(cd "$repo" && bash "$RUNNER" goal.md --resume --max-iter 2 --max-workers 1 --state .claude/state --log-dir logs/loop 2>&1)
contains "$output" "Workers already completed; continuing at POST" "workers-done skips PRE and workers"
call_count=$(grep -c . "$MOCK_CALLS" 2>/dev/null || true)
if [[ "${call_count:-0}" -eq 0 ]]; then pass "workers-done does not repeat LLM work"; else fail "workers-done does not repeat LLM work"; fi
not_contains "$output" "[LLM] supervisor" "workers-done skips supervisor"
unset MOCK_CALLS

repo=$(new_repo resume-post)
export MOCK_CALLS="$TEST_ROOT/post-resume-calls"
(
  cd "$repo" || exit
  python3 "$HELPER" save --goal goal.md --iteration 2 --phase post-done --extra 0 >/dev/null
)
output=$(cd "$repo" && bash "$RUNNER" goal.md --resume --max-iter 5 --state .claude/state --log-dir logs/loop 2>&1)
contains "$output" "Iterations:   2" "post-done finishes the recorded convergence transition"
if [[ ! -e "$MOCK_CALLS" ]]; then pass "post-done does not repeat LLM work"; else fail "post-done does not repeat LLM work"; fi
if ! (cd "$repo" && python3 "$HELPER" recover --goal goal.md >/dev/null 2>&1); then
  pass "terminal run clears its checkpoints"
else
  fail "terminal run clears its checkpoints"
fi
unset MOCK_CALLS

repo=$(new_repo mismatch)
(
  cd "$repo" || exit
  python3 "$HELPER" save --goal goal.md --iteration 1 --phase pre-done >/dev/null
  printf 'later\n' >> README.md
  git add README.md
  git commit -q -m "test: move head"
)
set +e
output=$(cd "$repo" && bash "$RUNNER" goal.md --resume --max-iter 2 --state .claude/state --log-dir logs/loop 2>&1)
exit_code=$?
set -e
if [[ "$exit_code" -eq 2 ]]; then pass "mismatched HEAD fails closed"; else fail "mismatched HEAD fails closed"; fi
contains "$output" "head_sha" "mismatch names the rejected identity field"
not_contains "$output" "Iteration 1" "mismatch does not start fresh"

repo=$(new_repo missing)
set +e
output=$(cd "$repo" && bash "$RUNNER" goal.md --resume --max-iter 2 --state .claude/state --log-dir logs/loop 2>&1)
exit_code=$?
set -e
if [[ "$exit_code" -eq 2 ]]; then pass "resume without checkpoint fails closed"; else fail "resume without checkpoint fails closed"; fi
contains "$output" "no checkpoint exists" "missing checkpoint reports the cause"

printf '\nCheckpoint tests: %d passed, %d failed\n' "$PASSED" "$FAILED"
[[ "$FAILED" -eq 0 ]]
