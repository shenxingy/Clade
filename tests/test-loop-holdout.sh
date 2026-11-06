#!/usr/bin/env bash
# test-loop-holdout.sh — /loop --holdout DIR: acceptance scenarios kept outside
# the repository (configs/scripts/loop_holdout.sh), plus the verify_cmd
# snapshot that ships with it (configs/scripts/loop_verify.sh).
#
# Every case drives the real entry point, loop-runner.sh, against a scratch
# repository with a mocked `claude`, and asserts on what the run hands out: its
# exit status, its log, the goal file, and — for the "never in a prompt"
# property — every argv and stdin the mocked claude received.
#
#   positive   a passing holdout lets the iteration reconcile and converge;
#              scenarios run with cwd = the checkout and stdin closed
#   negative   a failing holdout under a green verify_cmd blocks reconciliation,
#              logs "HOLDOUT FAILED — visible verify_cmd passed", and the
#              supervisor's next prompt carries the count but never a name,
#              path or content of a scenario
#   refuse     DIR inside the repository (directly, as ".", through a symlink,
#              as a scenario symlink, inside a sibling worktree), an empty DIR,
#              a missing DIR and an empty --holdout value are all refused
#              before any claude call, in a real run and in --dry-run
#   converge   a worker that ticks the goal itself, or a goal complete before
#              the run, cannot converge while a scenario fails
#   drift      a worker deleting verify_cmd from CLAUDE.md is reported
#   tamper     a scenario edited mid-run is reported
#
# The last suite removes each guard from a copy of the scripts in turn and
# requires the cases that pin it to go red, beside a no-op control that must
# stay green. A mutation whose anchor no longer matches is a failure, not a
# skip.
#
# Usage:
#   bash tests/test-loop-holdout.sh     # all cases, then the mutation suite
#   bash tests/test-loop.sh             # runs this file first (loop-fixture.sh)
# Internal (the mutation suite sets these for each mutant run):
#   LH_SCRIPTS=DIR   run DIR/loop-runner.sh instead of configs/scripts'
#   LH_CASES="a b"   run only these cases
#   LH_MUTANT=1      stop at the first failure; skip the mutation suite

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SELF="$ROOT/tests/$(basename "${BASH_SOURCE[0]}")"
SCRIPTS="${LH_SCRIPTS:-$ROOT/configs/scripts}"
RUNNER="$SCRIPTS/loop-runner.sh"
LH_CASES="${LH_CASES:-}"
LH_MUTANT="${LH_MUTANT:-}"
TEST_ROOT=$(mktemp -d /tmp/test-loop-holdout-XXXXXX)
TEST_ROOT=$(cd "$TEST_ROOT" && pwd -P)
trap 'rm -rf "$TEST_ROOT"' EXIT

# Commit-creating fixtures need a pinned VCS identity; keep a parent's.
if [[ -z "${CLADE_GIT_IDENTITY_FILE:-}" ]]; then
  export CLADE_GIT_IDENTITY_FILE="$TEST_ROOT/git-identity.json"
  python3 "$ROOT/configs/scripts/git_identity.py" \
    pin --name Test --email test@example.com >/dev/null || exit 1
fi

# ─── Framework ───────────────────────────────────────────────────────
PASSED=0
FAILED=0
pass() { PASSED=$((PASSED + 1)); printf '  ✓ %s\n' "$1"; }
fail() {
  FAILED=$((FAILED + 1)); printf '  ✗ %s\n' "$1"
  [[ -n "${2:-}" ]] && printf '      %s\n' "$2"
  if [[ -n "$LH_MUTANT" ]]; then exit 1; fi
  return 0
}
check() {  # LABEL COND(yes/no) [DETAIL]
  if [[ "$2" == "yes" ]]; then pass "$1"; else fail "$1" "${3:-}"; fi
}
has() { [[ "$1" == *"$2"* ]] && echo yes || echo no; }
lacks() { [[ "$1" != *"$2"* ]] && echo yes || echo no; }
want() { [[ -z "$LH_CASES" || " $LH_CASES " == *" $1 "* ]]; }
section() { printf '\n━━━ %s ━━━\n' "$1"; }

# ─── Fixture ─────────────────────────────────────────────────────────
mkdir -p "$TEST_ROOT/bin"
cat > "$TEST_ROOT/bin/claude" <<'EOF'
#!/usr/bin/env bash
# Mocked claude. Records every call's argv and stdin to $LH_PROMPTS — the
# complete set of text any prompt carried — then answers by prompt type.
args="$*"
input=$(cat)
printf '=== ARGS\n%s\n=== STDIN\n%s\n' "$args" "$input" >> "${LH_PROMPTS:-/dev/null}"
if [[ "$args" == *"Verify these changed files"* ]]; then
  echo '{"passed":true,"items":[],"summary":"mock pass"}'
elif [[ "$args" == *"autonomous improvement loop"* ]]; then
  if [[ -n "${MOCK_EMPTY_PLAN:-}" ]]; then echo '[]'; exit 0; fi
  echo '[{"description":"Update README.md and commit it to satisfy the exact item","model":"haiku","files":["README.md"],"goal_items":[{"line":3,"text":"exact item"}]}]'
elif [[ "$args" == *"stream-json"* ]]; then
  printf 'worker\n' >> README.md
  git add README.md
  if [[ "${MOCK_EDIT_VERIFY:-}" == "delete" ]]; then
    printf '# Test\n\nNo verify command any more.\n' > CLAUDE.md
    git add CLAUDE.md
  fi
  if [[ -n "${MOCK_TICK_GOAL:-}" ]]; then
    printf '# Goal\n\n- [x] exact item\n' > "$MOCK_TICK_GOAL"
  fi
  if [[ -n "${MOCK_TAMPER:-}" ]]; then
    printf '# edited by a worker\n' >> "$MOCK_TAMPER"
  fi
  git commit -q -m "test: worker commit"
  echo '{"type":"result","subtype":"success","result":"done"}'
else
  echo '[]'
fi
EOF
chmod +x "$TEST_ROOT/bin/claude"

# new_repo NAME → path of a fresh checkout: verify_cmd `true`, one open item.
new_repo() {
  local repo="$TEST_ROOT/$1"
  mkdir -p "$repo/.claude"
  (
    cd "$repo" || exit 1
    git init -q
    git config user.email test@example.com
    git config user.name Test
    printf '.claude/\nlogs/\n' > .gitignore
    printf 'initial\n' > README.md
    printf '# Test\n\n- Verify command: true\n' > CLAUDE.md
    git add .gitignore README.md CLAUDE.md
    git commit -q -m "test: initialize fixture"
  ) || return 1
  printf '# Goal\n\n- [ ] exact item\n' > "$repo/.claude/goal.md"
  printf '%s' "$repo"
}

# scenario DIR NAME BODY → an executable sh scenario.
scenario() {
  mkdir -p "$1"
  printf '#!/bin/sh\n%s\n' "$3" > "$1/$2"
  chmod +x "$1/$2"
}

PROMPTS="$TEST_ROOT/prompts.log"
# run_loop REPO ARGS... → OUT, RC; every prompt lands in $PROMPTS.
# stdin is /dev/null: the supervisor call inherits the runner's stdin and the
# mock reads it, so an inherited pipe that never closes (a backgrounded shell)
# hangs every call until the 90 s timeout instead of failing anything.
run_loop() {
  local repo="$1"
  shift
  rm -f "$PROMPTS"
  OUT=$(cd "$repo" && PATH="$TEST_ROOT/bin:$PATH" LH_PROMPTS="$PROMPTS" \
    timeout --kill-after=5s 90s bash "$RUNNER" .claude/goal.md --max-workers 1 \
    --state .claude/state.json --log-dir logs/loop "$@" 2>&1 < /dev/null)
  RC=$?
}
prompts() { cat "$PROMPTS" 2>/dev/null || true; }

# A passing holdout with two scenarios and a note. The first drains stdin: if
# the runner left the scenario list on its stdin, the second would never run.
PASS_DIR="$TEST_ROOT/acceptance-pass"
scenario "$PASS_DIR" "a-drains-stdin" 'cat > /dev/null; exit 0'
scenario "$PASS_DIR" "b-readme-grew" \
  "pwd -P > '$TEST_ROOT/cwd-seen'; test \"\$(wc -l < README.md)\" -ge 2"
printf 'notes, not a scenario\n' > "$PASS_DIR/NOTES.md"

# A failing holdout whose name, directory and content are all distinctive, so
# a leak into any prompt is visible.
FAIL_DIR="$TEST_ROOT/holdout-dir-q7x"
scenario "$FAIL_DIR" "zz-secret-scenario" \
  '# HOLDOUT-CONTENT-MARKER-4b1e
exit 3'

# ─── positive ────────────────────────────────────────────────────────
if want positive; then
section "positive: a passing holdout reconciles and converges"
REPO=$(new_repo positive)
run_loop "$REPO" --max-iter 2 --holdout "$PASS_DIR"
check "run converges and exits 0" "$([[ $RC -eq 0 ]] && has "$OUT" "CONVERGED")" "rc=$RC"
check "the iteration reconciled its goal item" "$(has "$OUT" "Coordinator reconciled 1 goal item(s)")"
check "goal item ticked" "$(has "$(cat "$REPO/.claude/goal.md")" "- [x] exact item")"
check "banner names the scenario count" "$(has "$OUT" "2 scenario(s) in $PASS_DIR")"
check "both scenarios ran — the first did not swallow the list on stdin" \
  "$(has "$OUT" "holdout: all 2 scenario(s) passed")" "$(grep -o 'holdout: .*passed' <<< "$OUT" | head -1)"
check "a non-executable file is a note, not a scenario" "$(has "$OUT" "1 non-executable file(s)")"
check "scenario cwd is the checkout root" \
  "$([[ "$(cat "$TEST_ROOT/cwd-seen" 2>/dev/null)" == "$(cd "$REPO" && pwd -P)" ]] && echo yes || echo no)" \
  "saw: $(cat "$TEST_ROOT/cwd-seen" 2>/dev/null)"
check "per-iteration detail log records the pass" \
  "$(has "$(cat "$REPO/logs/loop/iter-1-holdout.log" 2>/dev/null)" "=== b-readme-grew: PASS")"
check "last-progress reports the holdout" \
  "$(has "$(cat "$REPO/logs/loop/last-progress" 2>/dev/null)" "Holdout: all 2 scenario(s) passed at iteration 1")"
check "no divergence reported when both gates agree" "$(lacks "$OUT" "HOLDOUT FAILED")"
check "an unchanged verify_cmd raises no drift warning" "$(lacks "$OUT" "verify_cmd changed mid-run")"
check "an unchanged holdout raises no change warning" "$(lacks "$OUT" "HOLDOUT CHANGED")"
fi

# ─── negative ────────────────────────────────────────────────────────
if want negative; then
section "negative: a failing holdout blocks reconciliation; prompts get counts only"
REPO=$(new_repo negative)
run_loop "$REPO" --max-iter 2 --holdout "$FAIL_DIR"
check "run gives up with exit 2" "$([[ $RC -eq 2 ]] && echo yes || echo no)" "rc=$RC"
check "red holdout under a green verify_cmd is named" \
  "$(has "$OUT" "HOLDOUT FAILED — visible verify_cmd passed")"
check "the human log names the failing scenario" "$(has "$OUT" "holdout FAIL: zz-secret-scenario (exit 3)")"
check "goal reconciliation is skipped" "$(has "$OUT" "Skipping goal reconciliation")"
check "goal item stays unchecked" "$(has "$(cat "$REPO/.claude/goal.md")" "- [ ] exact item")"
check "last-progress reports the failure" \
  "$(has "$(cat "$REPO/logs/loop/last-progress" 2>/dev/null)" "Holdout: 1 of 1 scenario(s) failed at iteration 2")"
P=$(prompts)
NSUP=$(grep -c "autonomous improvement loop" "$PROMPTS" 2>/dev/null || true)
check "the prompt record is not empty (two supervisor prompts captured)" \
  "$([[ "${NSUP:-0}" -ge 2 ]] && echo yes || echo no)" "supervisor prompts: ${NSUP:-0}"
check "the next supervisor prompt carries the failure count" \
  "$(has "$P" "1 of 1 held-out acceptance scenario(s) FAILED")"
check "no prompt carries the scenario name" "$(lacks "$P" "zz-secret-scenario")"
check "no prompt carries the holdout directory" "$(lacks "$P" "holdout-dir-q7x")"
check "no prompt carries scenario content" "$(lacks "$P" "HOLDOUT-CONTENT-MARKER")"
fi

# ─── refuse ──────────────────────────────────────────────────────────
if want refuse; then
section "refuse: a holdout the workers can commit to is not a holdout"
REPO=$(new_repo refuse)
scenario "$REPO/acceptance" "check" 'exit 0'
ln -s "$REPO/acceptance" "$TEST_ROOT/link-into-repo"
scenario "$TEST_ROOT/plain-out" "ok" 'exit 0'
mkdir -p "$TEST_ROOT/scenario-link"
ln -s "$REPO/acceptance/check" "$TEST_ROOT/scenario-link/check"
git -C "$REPO" worktree add -q "$TEST_ROOT/sibling-wt" 2>/dev/null
scenario "$TEST_ROOT/sibling-wt/acceptance" "check" 'exit 0'
mkdir -p "$TEST_ROOT/notes-only"
printf 'a note\n' > "$TEST_ROOT/notes-only/README.md"

# refused LABEL NEEDLE ARGS... — must exit 1 before any claude call or state.
refused() {
  local label="$1" needle="$2"
  shift 2
  rm -rf "$REPO/logs" "$REPO/.claude/state.json"
  run_loop "$REPO" --max-iter 1 "$@"
  check "$label: refused with exit 1" "$([[ $RC -eq 1 ]] && echo yes || echo no)" "rc=$RC"
  check "$label: says why" "$(has "$OUT" "$needle")" "$(head -2 <<< "$OUT")"
  check "$label: no claude call was made" "$([[ ! -s "$PROMPTS" ]] && echo yes || echo no)"
  check "$label: no loop state or log written" \
    "$([[ ! -e "$REPO/.claude/state.json" && ! -e "$REPO/logs" ]] && echo yes || echo no)"
}
refused "directory inside the checkout" "resolves inside the repository" --holdout "$REPO/acceptance"
refused "the checkout root itself" "resolves inside the repository" --holdout .
refused "a symlink into the checkout" "resolves inside the repository" --holdout "$TEST_ROOT/link-into-repo"
refused "a scenario symlinked into the checkout" "scenario check resolves inside the repository" \
  --holdout "$TEST_ROOT/scenario-link"
refused "a sibling worktree of the same repository" "another worktree of this same repository" \
  --holdout "$TEST_ROOT/sibling-wt/acceptance"
refused "a directory with no executable scenario" "holds no executable scenario" --holdout "$TEST_ROOT/notes-only"
refused "a missing directory" "not a directory" --holdout "$TEST_ROOT/does-not-exist"
refused "an empty --holdout value" "needs a directory argument" --holdout ""
refused "dry-run with an in-repo directory" "resolves inside the repository" \
  --dry-run --holdout "$REPO/acceptance"

run_loop "$REPO" --dry-run --holdout "$TEST_ROOT/plain-out"
check "dry-run accepts a holdout outside the repository" "$([[ $RC -eq 0 ]] && echo yes || echo no)" "rc=$RC"
check "dry-run shows it" "$(has "$OUT" "Holdout:        1 scenario(s) in $TEST_ROOT/plain-out")"
check "--help documents --holdout" "$(has "$(bash "$RUNNER" --help 2>&1)" "--holdout DIR")"
fi

# ─── converge ────────────────────────────────────────────────────────
if want converge; then
section "converge: a ticked checklist is not acceptance"
REPO=$(new_repo converge-tick)
MOCK_TICK_GOAL="$REPO/.claude/goal.md" run_loop "$REPO" --max-iter 1
check "control: without a holdout, a worker ticking the goal converges" \
  "$([[ $RC -eq 0 ]] && has "$OUT" "CONVERGED")" "rc=$RC"
REPO=$(new_repo converge-tick-holdout)
MOCK_TICK_GOAL="$REPO/.claude/goal.md" run_loop "$REPO" --max-iter 1 --holdout "$FAIL_DIR"
check "with a failing holdout it does not converge" "$(lacks "$OUT" "CONVERGED:")"
check "and says why" "$(has "$OUT" "held-out acceptance fails (1 of 1) — not converged")"
check "and exits 2" "$([[ $RC -eq 2 ]] && echo yes || echo no)" "rc=$RC"

REPO=$(new_repo converge-done)
printf '# Goal\n\n- [x] exact item\n' > "$REPO/.claude/goal.md"
MOCK_EMPTY_PLAN=1 run_loop "$REPO" --max-iter 1 --holdout "$FAIL_DIR"
check "a goal complete before the run is checked against the holdout too" \
  "$(has "$OUT" "holdout FAIL: zz-secret-scenario")"
check "and does not converge on a failing one" "$([[ $RC -eq 2 ]] && lacks "$OUT" "CONVERGED:")" "rc=$RC"
fi

# ─── drift ───────────────────────────────────────────────────────────
if want drift; then
section "drift: the visible gate rewritten mid-run is reported"
# Two iterations (the failing holdout keeps the run going), so test_sample
# reads the deleted verify_cmd twice and the once-per-change rule is visible.
REPO=$(new_repo drift)
MOCK_EDIT_VERIFY=delete run_loop "$REPO" --max-iter 2 --holdout "$FAIL_DIR"
check "deleting verify_cmd mid-run is reported" \
  "$(has "$OUT" "verify_cmd changed mid-run: pre-flight read 'true', CLAUDE.md now says '(none)'")"
check "reported once per change, not on every read" \
  "$([[ "$(grep -c "verify_cmd changed mid-run" <<< "$OUT")" -eq 1 ]] && echo yes || echo no)" \
  "$(grep -c "verify_cmd changed mid-run" <<< "$OUT") warnings over $(grep -c '\[DET\] test_sample' <<< "$OUT") test_sample runs"
check "test_sample really ran twice after the change" \
  "$([[ "$(grep -c '\[DET\] test_sample' <<< "$OUT")" -ge 2 ]] && echo yes || echo no)"
check "with no verify_cmd left, a red holdout is not called a green visible gate" \
  "$(lacks "$OUT" "visible verify_cmd passed")"
fi

# ─── tamper ──────────────────────────────────────────────────────────
if want tamper; then
section "tamper: a scenario edited mid-run is reported"
REPO=$(new_repo tamper)
TAMPER_DIR="$TEST_ROOT/acceptance-tamper"
scenario "$TAMPER_DIR" "check" 'exit 0'
MOCK_TAMPER="$TAMPER_DIR/check" run_loop "$REPO" --max-iter 1 --holdout "$TAMPER_DIR"
check "the change is reported" "$(has "$OUT" "HOLDOUT CHANGED mid-run")"
fi

# ─── Mutations ───────────────────────────────────────────────────────
# Each entry edits ONE guard out of a copy of the scripts and reruns the cases
# that pin it; they must go red. The first entry is the control: a no-op edit
# must leave every case green, or a red result proves nothing.
# shellcheck disable=SC2016  # anchors are literal source text, not expansions
if [[ -z "$LH_MUTANT" ]]; then
section "Mutations: removing each guard turns its cases red"

MUT_BASE="$TEST_ROOT/mutants"
NMUT=0
MUT_LABELS=()
MUT_EXPECT=()

# mutation EXPECT FILE CASES NAME ANCHOR REPLACEMENT — literal text, exactly once.
mutation() {
  local expect="$1" file="$2" cases="$3" name="$4" anchor="$5" repl="$6"
  local dir="$MUT_BASE/m$NMUT/configs/scripts"
  mkdir -p "$dir"
  cp "$ROOT"/configs/scripts/*.sh "$ROOT"/configs/scripts/*.py "$dir/"
  cp "$ROOT/configs/models.env" "$dir/../"
  if ! LH_A="$anchor" LH_R="$repl" awk '
      { buf = buf (NR > 1 ? "\n" : "") $0 }
      END {
        a = ENVIRON["LH_A"]; r = ENVIRON["LH_R"]; s = buf; out = ""; n = 0
        while ((i = index(s, a)) > 0) { out = out substr(s, 1, i - 1) r; s = substr(s, i + length(a)); n++ }
        if (n != 1) exit 3
        printf "%s\n", out s
      }' "$dir/$file" > "$dir/$file.next"; then
    fail "mutation '$name': its anchor no longer matches $file exactly once"
    return 0
  fi
  mv "$dir/$file.next" "$dir/$file"
  MUT_LABELS[NMUT]="$name"
  MUT_EXPECT[NMUT]="$expect"
  ( LH_SCRIPTS="$dir" LH_CASES="$cases" LH_MUTANT=1 bash "$SELF" \
      < /dev/null > "$MUT_BASE/m$NMUT.out" 2>&1
    echo $? > "$MUT_BASE/m$NMUT.rc" ) &
  NMUT=$((NMUT + 1))
  # Four at a time: each mutant is a handful of loop runs.
  if [[ $((NMUT % 4)) -eq 0 ]]; then wait; fi
}

mutation green loop_holdout.sh "positive negative refuse converge drift tamper" \
  "no-op control (a comment reworded)" \
  "# Names and cksums of the scenario set" "# Names and checksums of the scenario set"
mutation red loop-runner.sh "negative" "the holdout term of the reconcile gate" \
  ' \
       && [ "$holdout_result" -eq 0 ]; then' '; then'
mutation red loop-runner.sh "converge" "the holdout term of the convergence check" \
  'if ! holdout_blocks_convergence; then' 'if true; then'
mutation red loop-runner.sh "negative" "the count in the supervisor context" \
  '    holdout_context_block
' '    true
'
mutation red loop_holdout.sh "negative" "a holdout path leaking into the context (leak detector can fire)" \
  'echo "These scenarios are withheld' 'echo "Scenarios: $LOOP_HOLDOUT_DIR. These scenarios are withheld'
mutation red loop_holdout.sh "negative" "the HOLDOUT FAILED divergence log" \
  'log_error "HOLDOUT FAILED — visible verify_cmd passed:' ': "'
mutation red loop_holdout.sh "refuse" "the in-repository directory refusal" \
  'if _holdout_is_inside "$abs" "$top_abs"; then' 'if false; then'
mutation red loop_holdout.sh "refuse" "physical resolution (pwd -P)" \
  '(cd "$1" 2>/dev/null && pwd -P)' '(cd "$1" 2>/dev/null && pwd -L)'
mutation red loop_holdout.sh "refuse" "the scenario-symlink refusal" \
  'if _holdout_is_inside "$phys" "$root"; then' 'if false; then'
mutation red loop_holdout.sh "refuse" "the same-repository worktree refusal" \
  'if [ -n "$here_common" ] && [ "$here_common" = "$there_common" ]; then' 'if false; then'
mutation red loop_holdout.sh "refuse" "the zero-scenario refusal" \
  'if [ "$n" -eq 0 ]; then' 'if false; then'
mutation red loop_args.sh "refuse" "the empty --holdout refusal" \
  'if [ -z "${2:-}" ]; then' 'if false; then'
mutation red loop_holdout.sh "positive" "stdin closed for scenarios" \
  '      < /dev/null >> "$detail" 2>&1' '      >> "$detail" 2>&1'
mutation red loop_holdout.sh "tamper" "the mid-run change detection" \
  'if [ "$fp" != "$LOOP_HOLDOUT_FINGERPRINT" ]; then' 'if false; then'
mutation red loop_verify.sh "drift" "the verify_cmd drift check" \
  '  _verify_cmd_drift_check "$verify_cmd"
' ''
mutation red loop_holdout.sh "drift" "no divergence claim without a verify_cmd" \
  '  [ -n "$(_read_verify_cmd)" ] || return 0
' ''
mutation red loop_verify.sh "drift" "one warning per change" \
  '  [ "v:$now" = "$LOOP_VERIFY_CMD_WARNED" ] && return 0
' ''
wait

i=0
while [[ $i -lt $NMUT ]]; do
  rc=$(cat "$MUT_BASE/m$i.rc" 2>/dev/null || echo missing)
  if [[ "${MUT_EXPECT[i]}" == "green" ]]; then
    check "mutant stays green: ${MUT_LABELS[i]}" "$([[ "$rc" == "0" ]] && echo yes || echo no)" \
      "rc=$rc; $(grep '✗' "$MUT_BASE/m$i.out" 2>/dev/null | head -2 | tr '\n' ' ')"
  else
    # Name the check that caught it, so a mutant red for the wrong reason (a
    # crash, a missing copy) is visible in the log rather than counted.
    caught=$(grep -m1 '✗' "$MUT_BASE/m$i.out" 2>/dev/null | sed 's/^[[:space:]]*✗[[:space:]]*//')
    check "mutant turns red: ${MUT_LABELS[i]} — caught by: ${caught:-nothing}" \
      "$([[ "$rc" != "0" && "$rc" != "missing" && -n "$caught" ]] && echo yes || echo no)" \
      "rc=$rc — the cases that should pin it stayed green"
  fi
  i=$((i + 1))
done
fi

printf '\nHoldout tests: %d passed, %d failed\n' "$PASSED" "$FAILED"
[[ "$FAILED" -eq 0 ]]
