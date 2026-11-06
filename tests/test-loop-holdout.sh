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
#   tamper     a scenario rewritten mid-run is reported, its pass does not count
#              in the iteration that changed it, and the report says so
#   resume     a run killed after its workers-done checkpoint cannot be resumed
#              without its --holdout, or with another one; resumed with it, a
#              scenario edited before the crash is still reported
#   gone       a worker deleting the scenarios or dropping their exec bit gets
#              no pass: reconciliation is skipped and the run does not converge
#   timeout    with timeout and gtimeout hidden from PATH, a scenario that
#              hangs is cut off at CLADE_LOOP_HOLDOUT_TIMEOUT, and a child it
#              left running is killed with it
#   checkout   what a scenario writes into the checkout is put back: no commit
#              and no prompt carries it, and a worker's leftover change survives
#   index      a scenario that stages a file gets the git index put back byte
#              for byte: skip-worktree and intent-to-add entries survive, so no
#              commit deletes a file a sparse checkout left out
#   leak       with nothing git-ignored, no file in the checkout and no commit
#              names a scenario or DIR or carries a scenario's output; the
#              holdout log outside the repository does
#   fixture    a fixture under DIR (nested, not executable) edited mid-run is
#              reported, and that iteration's pass does not count
#   named      a goal or --context file naming DIR (as given, its physical
#              path, or its ~/ form) gets a warning; a bare name does not
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
# The PATH the runner gets after the stub bin/ (the timeout and refuse cases
# swap in one with commands hidden), and an absolute outer bound for each run,
# so hiding timeout from the runner does not take it from the harness too.
LH_SYS_PATH="$PATH"
LH_TIMEOUT=$(command -v timeout || command -v gtimeout || true)
# Resume checkpoints live under $HOME/.claude/loop-checkpoints; keep every one
# this suite writes (and the one the resume case leaves) out of the real HOME.
export HOME="$TEST_ROOT/home"
mkdir -p "$HOME"

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
  if [[ -n "${MOCK_REWRITE_PASS:-}" ]]; then
    printf '#!/bin/sh\nexit 0\n' > "$MOCK_REWRITE_PASS"
  fi
  case "${MOCK_GONE:-}" in
    delete:*) rm -f "${MOCK_GONE#delete:}"/* ;;
    chmod:*)  chmod -x "${MOCK_GONE#chmod:}"/* ;;
  esac
  if [[ -n "${MOCK_FIXTURE:-}" ]]; then
    printf 'worker\n' > "$MOCK_FIXTURE"
  fi
  if [[ -n "${MOCK_INTERRUPT:-}" ]]; then
    printf '{"interrupted": true}\n' > .claude/interrupt-state.json
  fi
  git commit -q -m "test: worker commit"
  if [[ -n "${MOCK_ITA:-}" ]]; then
    printf 'note\n' > "$MOCK_ITA"
    git add -N -f "$MOCK_ITA"
  fi
  if [[ -n "${MOCK_LEFTOVER:-}" ]]; then
    printf 'leftover\n' >> README.md
  fi
  echo '{"type":"result","subtype":"success","result":"done"}'
else
  echo '[]'
fi
EOF
chmod +x "$TEST_ROOT/bin/claude"
# The leftover sweep prefers a `committer` on PATH. The installed one needs a
# kit under $HOME, which this suite replaces, and CI has none at all, so pin a
# stand-in that commits exactly the files it is given.
cat > "$TEST_ROOT/bin/committer" <<'EOF'
#!/usr/bin/env bash
msg="$1"
shift
git restore --staged :/ 2>/dev/null || true
git add -- "$@" && git commit -q -m "$msg"
EOF
chmod +x "$TEST_ROOT/bin/committer"

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
  OUT=$(cd "$repo" && PATH="$TEST_ROOT/bin:$LH_SYS_PATH" LH_PROMPTS="$PROMPTS" \
    ${LH_TIMEOUT:+"$LH_TIMEOUT" --kill-after=5s 90s} bash "$RUNNER" .claude/goal.md --max-workers 1 \
    --state .claude/state.json --log-dir logs/loop "$@" 2>&1 < /dev/null)
  RC=$?
}
prompts() { cat "$PROMPTS" 2>/dev/null || true; }
# The last supervisor prompt recorded (argv and stdin): what the iteration
# that started last was told.
last_supervisor_prompt() {
  awk '/^=== ARGS$/ { if (rec ~ /autonomous improvement loop/) last = rec; rec = "" }
       { rec = rec $0 "\n" }
       END { if (rec ~ /autonomous improvement loop/) last = rec; printf "%s", last }' \
    "$PROMPTS" 2>/dev/null
}
# hlog REPO N → iteration N's holdout log, from its default place outside the
# repository: $HOME/.claude/loop-holdout/<checkout name>-<12 hex>.
hlog() {
  local f
  for f in "$HOME/.claude/loop-holdout/$(basename "$1")"-????????????/"iter-$2-holdout.log"; do
    [[ -f "$f" ]] && cat "$f"
  done
  return 0
}
# path_without TAG NAME... → a directory of symlinks to every command on the
# suite's PATH except NAME..., first match winning as in a lookup. Bulk ln per
# PATH directory: one process each, not one per command.
path_without() {
  local dir="$TEST_ROOT/path-without-$1" d n
  shift
  if [[ ! -d "$dir" ]]; then
    mkdir -p "$dir"
    local IFS=:
    for d in $PATH; do
      [[ -d "$d" && "$d" != "$TEST_ROOT"/* ]] || continue
      ln -s "$d"/* "$dir"/ 2>/dev/null
    done
    unset IFS
    for n in "$@"; do rm -f "$dir/$n"; done
  fi
  printf '%s' "$dir"
}

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
check "banner names the scenario count, and not the directory" \
  "$([[ "$OUT" == *"Holdout:      2 scenario(s), outside the repository"* ]] \
     && lacks "$(cat "$REPO/logs/loop/loop.log" 2>/dev/null)" "$PASS_DIR")"
check "both scenarios ran — the first did not swallow the list on stdin" \
  "$(has "$OUT" "holdout: all 2 scenario(s) passed")" "$(grep -o 'holdout: .*passed' <<< "$OUT" | head -1)"
check "a non-executable file is a note, not a scenario" "$(has "$OUT" "1 non-executable file(s)")"
check "scenario cwd is the checkout root" \
  "$([[ "$(cat "$TEST_ROOT/cwd-seen" 2>/dev/null)" == "$(cd "$REPO" && pwd -P)" ]] && echo yes || echo no)" \
  "saw: $(cat "$TEST_ROOT/cwd-seen" 2>/dev/null)"
check "the holdout log outside the repository records the pass by name" \
  "$(has "$(hlog "$REPO" 1)" "=== b-readme-grew: PASS")"
check "loop.log records it by position only" \
  "$([[ "$(cat "$REPO/logs/loop/loop.log" 2>/dev/null)" == *"holdout scenario 2 of 2: PASS"* ]] \
     && lacks "$(cat "$REPO/logs/loop/loop.log" 2>/dev/null)" "b-readme-grew")"
check "nothing is left under logs/loop named after the holdout" \
  "$([[ ! -e "$REPO/logs/loop/iter-1-holdout.log" ]] && echo yes || echo no)"
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
check "the holdout log names the failing scenario and its exit code" \
  "$(has "$(hlog "$REPO" 1)" "=== zz-secret-scenario: FAIL (exit 3)")"
check "the terminal is told where that log is" \
  "$(has "$OUT" "holdout: names, exit codes and output in $HOME/.claude/loop-holdout/negative-")"
check "loop.log counts the failure without the name" \
  "$([[ "$(cat "$REPO/logs/loop/loop.log" 2>/dev/null)" == *"holdout scenario 1 of 1: FAIL"* ]] \
     && lacks "$(cat "$REPO/logs/loop/loop.log" 2>/dev/null)" "zz-secret-scenario")"
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
mkdir -p "$TEST_ROOT/scenario-link-wt"
ln -s "$TEST_ROOT/sibling-wt/acceptance/check" "$TEST_ROOT/scenario-link-wt/check"
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
refused "a scenario symlinked into a sibling worktree" \
  "scenario check resolves into another worktree of this same repository" \
  --holdout "$TEST_ROOT/scenario-link-wt"
CLADE_LOOP_HOLDOUT_TIMEOUT=abc refused "a scenario timeout that is not a number" \
  "CLADE_LOOP_HOLDOUT_TIMEOUT must be a whole number" --holdout "$TEST_ROOT/plain-out"
CLADE_LOOP_HOLDOUT_TIMEOUT=0 refused "a scenario timeout of 0, which GNU timeout reads as none" \
  "CLADE_LOOP_HOLDOUT_TIMEOUT must be a whole number" --holdout "$TEST_ROOT/plain-out"
refused "a directory with no executable scenario" "holds no executable scenario" --holdout "$TEST_ROOT/notes-only"
refused "a missing directory" "not a directory" --holdout "$TEST_ROOT/does-not-exist"
refused "an empty --holdout value" "needs a directory argument" --holdout ""
# The holdout log names every scenario: never inside the checkout, and not in
# DIR either, where each write would read as a changed scenario set.
CLADE_LOOP_HOLDOUT_LOG_DIR="$REPO/holdout-logs" refused "a holdout log directory inside the checkout" \
  "the holdout log (it names every scenario and keeps their output) would be written inside the repository" \
  --holdout "$TEST_ROOT/plain-out"
CLADE_LOOP_HOLDOUT_LOG_DIR="$TEST_ROOT/plain-out/logs" refused "a holdout log directory inside DIR" \
  "would be written inside the holdout directory" --holdout "$TEST_ROOT/plain-out"
HOME="$REPO/home" refused "the default holdout log under a HOME inside the checkout" \
  "the holdout log (it names every scenario and keeps their output) would be written inside the repository" \
  --holdout "$TEST_ROOT/plain-out"
HOME="$REPO/home" CLADE_LOOP_HOLDOUT_LOG_DIR="$TEST_ROOT/logs-outside" \
  refused "a resume checkpoint, which records DIR, under a HOME inside the checkout" \
  "the resume checkpoint (it records the holdout directory) would be written inside the repository" \
  --holdout "$TEST_ROOT/plain-out"
check "no refusal created a holdout log directory" \
  "$([[ ! -e "$REPO/holdout-logs" && ! -e "$TEST_ROOT/plain-out/logs" && ! -e "$TEST_ROOT/logs-outside" ]] && echo yes || echo no)"
NOPY_PATH=$(path_without nopython python3)
check "precondition: python3 is hidden from that PATH" \
  "$(PATH="$NOPY_PATH" command -v python3 >/dev/null 2>&1 && echo no || echo yes)"
LH_SYS_PATH="$NOPY_PATH" refused "no python3, so no watchdog to bound a scenario" \
  "needs python3" --holdout "$TEST_ROOT/plain-out"
refused "dry-run with an in-repo directory" "resolves inside the repository" \
  --dry-run --holdout "$REPO/acceptance"

run_loop "$REPO" --dry-run --holdout "$TEST_ROOT/plain-out"
check "dry-run accepts a holdout outside the repository" "$([[ $RC -eq 0 ]] && echo yes || echo no)" "rc=$RC"
check "dry-run shows it" "$(has "$OUT" "Holdout:        1 scenario(s) in $TEST_ROOT/plain-out")"
check "dry-run says where the holdout log goes, and creates nothing there" \
  "$([[ "$OUT" == *"holdout log in $HOME/.claude/loop-holdout/refuse-"* ]] \
     && ! compgen -G "$HOME/.claude/loop-holdout/refuse-*" >/dev/null && echo yes || echo no)"
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
  "$(has "$OUT" "holdout scenario 1 of 1: FAIL")"
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
section "tamper: a scenario rewritten to pass does not count in the iteration it changed"
# The worker rewrites a failing scenario to `exit 0` in every iteration; from
# the second on, the content is the same, so the set is unchanged.
REPO=$(new_repo tamper)
TAMPER_DIR="$TEST_ROOT/acceptance-tamper"
scenario "$TAMPER_DIR" "check-rw" 'exit 1'
MOCK_REWRITE_PASS="$TAMPER_DIR/check-rw" run_loop "$REPO" --max-iter 2 --holdout "$TAMPER_DIR"
LP=$(cat "$REPO/logs/loop/last-progress" 2>/dev/null)
check "it reconciles once, on the next iteration's unchanged set" \
  "$([[ "$(grep -c "Coordinator reconciled" <<< "$OUT")" -eq 1 ]] && echo yes || echo no)" \
  "$(grep -c "Coordinator reconciled" <<< "$OUT") reconciliations"
check "the run converges at iteration 2, not 1" \
  "$([[ $RC -eq 0 ]] && has "$LP" "Iterations: 2")" "rc=$RC; $LP"
check "the change is reported" "$(has "$OUT" "HOLDOUT CHANGED mid-run")"
check "the iteration that changed it says it does not count" \
  "$(has "$OUT" "the scenario set changed in this iteration — not counted as acceptance")"
check "last-progress (what --status prints) carries the change" \
  "$(has "$LP" "scenario set CHANGED mid-run at iteration 1")"
check "the end-of-run report carries it" \
  "$(has "$OUT" "Holdout:      all 1 scenario(s) passed at iteration 2; scenario set CHANGED mid-run at iteration 1")"
check "the next supervisor prompt is told the pass did not count, by count only" \
  "$(has "$(prompts)" "but the held-out set changed during that iteration")"
check "and never the scenario's name" "$(lacks "$(prompts)" "check-rw")"

REPO=$(new_repo tamper-tick)
TAMPER2_DIR="$TEST_ROOT/acceptance-tamper-tick"
scenario "$TAMPER2_DIR" "check-rw" 'exit 1'
MOCK_REWRITE_PASS="$TAMPER2_DIR/check-rw" MOCK_TICK_GOAL="$REPO/.claude/goal.md" \
  run_loop "$REPO" --max-iter 1 --holdout "$TAMPER2_DIR"
check "rewrite plus a ticked goal does not converge in the same iteration" \
  "$([[ $RC -eq 2 ]] && lacks "$OUT" "CONVERGED:")" "rc=$RC"
check "and says why" "$(has "$OUT" "held-out scenario set changed in this iteration — not converged")"
fi

# ─── resume ──────────────────────────────────────────────────────────
if want resume; then
section "resume: a resumed run keeps the holdout it started with"
# crash_after_workers REPO ARGS... — the worker raises the interrupt flag, so
# the runner pauses right after its workers-done checkpoint; the test kills it
# there with SIGKILL, the way a crash would, and clears the flag.
crash_after_workers() {
  local repo="$1" pid deadline
  shift
  rm -f "$PROMPTS"
  ( cd "$repo" && PATH="$TEST_ROOT/bin:$PATH" LH_PROMPTS="$PROMPTS" MOCK_INTERRUPT=1 \
      exec bash "$RUNNER" .claude/goal.md --max-workers 1 --state .claude/state.json \
      --log-dir logs/loop "$@" ) > "$TEST_ROOT/crash.out" 2>&1 < /dev/null &
  pid=$!
  deadline=$((SECONDS + 90))
  while ! grep -q "Interrupt detected" "$repo/logs/loop/loop.log" 2>/dev/null; do
    if [[ $SECONDS -ge $deadline ]] || ! kill -0 "$pid" 2>/dev/null; then break; fi
    sleep 0.2
  done
  kill -9 "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null
  rm -f "$repo/.claude/interrupt-state.json"
}
REPO=$(new_repo resume)
RESUME_DIR="$TEST_ROOT/acceptance-resume"
scenario "$RESUME_DIR" "check" 'exit 1'
# The worker also edits the scenario before the crash: the resumed run must
# compare against the fingerprint the interrupted run had, not take a new one.
MOCK_TAMPER="$RESUME_DIR/check" crash_after_workers "$REPO" --max-iter 2 --holdout "$RESUME_DIR"
check "the crash left a workers-done checkpoint" \
  "$(compgen -G "$HOME/.claude/loop-checkpoints/*/*/iter-000001-workers-done.json" >/dev/null && echo yes || echo no)" \
  "$(tail -3 "$TEST_ROOT/crash.out" 2>/dev/null | tr '\n' ' ')"

run_loop "$REPO" --resume --max-iter 2
check "resume without --holdout is refused (exit 2)" "$([[ $RC -eq 2 ]] && echo yes || echo no)" "rc=$RC"
check "it names the field and the fix" \
  "$([[ "$OUT" == *"holdout_dir"* && "$OUT" == *"the interrupted run had --holdout $RESUME_DIR"* ]] && echo yes || echo no)" \
  "$(grep -m2 -i 'holdout' <<< "$OUT")"
check "it does not resume" "$(lacks "$OUT" "[RECOVERY] Resuming")"
check "it does not converge" "$(lacks "$OUT" "CONVERGED")"
check "the goal item stays unchecked" "$(has "$(cat "$REPO/.claude/goal.md")" "- [ ] exact item")"
check "no claude call was made" "$([[ ! -s "$PROMPTS" ]] && echo yes || echo no)"

run_loop "$REPO" --resume --max-iter 2 --holdout "$PASS_DIR"
check "resume with a different --holdout is refused (exit 2)" "$([[ $RC -eq 2 ]] && echo yes || echo no)" "rc=$RC"
check "and names the one the run had" "$(has "$OUT" "the interrupted run had --holdout $RESUME_DIR, not $PASS_DIR")"
check "loop.log, inside the checkout, keeps the refusal but not the directory it names" \
  "$([[ "$(cat "$REPO/logs/loop/loop.log" 2>/dev/null)" == *"[RECOVERY] checkpoint does not match current run (holdout_dir)"* ]] \
     && lacks "$(cat "$REPO/logs/loop/loop.log" 2>/dev/null)" "$RESUME_DIR")" \
  "$(grep -m1 'RECOVERY' "$REPO/logs/loop/loop.log" 2>/dev/null)"

run_loop "$REPO" --resume --max-iter 1 --holdout "$RESUME_DIR"
check "resume with the same --holdout continues at POST" \
  "$(has "$OUT" "[RECOVERY] Resuming iteration 1 after workers-done")" "rc=$RC"
check "the edit made before the crash is reported on resume" "$(has "$OUT" "HOLDOUT CHANGED mid-run")"
check "the holdout still gates it: no convergence, exit 2" \
  "$([[ $RC -eq 2 ]] && lacks "$OUT" "CONVERGED")" "rc=$RC"
fi

# ─── gone ────────────────────────────────────────────────────────────
if want gone; then
section "gone: a worker that removes the scenarios gets no pass"
REPO=$(new_repo gone-delete)
GONE_DIR="$TEST_ROOT/acceptance-gone-delete"
scenario "$GONE_DIR" "check" 'exit 0'
MOCK_GONE="delete:$GONE_DIR" run_loop "$REPO" --max-iter 1 --holdout "$GONE_DIR"
check "delete: goal item stays unchecked" "$(has "$(cat "$REPO/.claude/goal.md")" "- [ ] exact item")"
check "delete: no convergence, exit 2" "$([[ $RC -eq 2 ]] && lacks "$OUT" "CONVERGED")" "rc=$RC"
check "delete: counted as failed" "$(has "$OUT" "the scenario set can no longer be run")"
check "delete: goal reconciliation is skipped" "$(has "$OUT" "Skipping goal reconciliation")"
check "delete: no '1 of 0' arithmetic in any message" "$(lacks "$OUT" "1 of 0")"
check "delete: the divergence log says the scenarios cannot be run" \
  "$(has "$OUT" "HOLDOUT FAILED — visible verify_cmd passed: the held-out scenarios cannot be run")"
check "delete: last-progress says so too" \
  "$(has "$(cat "$REPO/logs/loop/last-progress" 2>/dev/null)" "the scenarios could not be run at iteration 1")"

REPO=$(new_repo gone-chmod)
GONE2_DIR="$TEST_ROOT/acceptance-gone-chmod"
scenario "$GONE2_DIR" "check" 'exit 0'
MOCK_GONE="chmod:$GONE2_DIR" MOCK_TICK_GOAL="$REPO/.claude/goal.md" \
  run_loop "$REPO" --max-iter 1 --holdout "$GONE2_DIR"
check "chmod -x plus a ticked goal: no convergence, exit 2" \
  "$([[ $RC -eq 2 ]] && lacks "$OUT" "CONVERGED:")" "rc=$RC"
check "chmod -x: says the scenarios cannot be run" \
  "$(has "$OUT" "the held-out acceptance scenarios cannot be run — not converged")"
fi

# ─── timeout ─────────────────────────────────────────────────────────
if want timeout; then
section "timeout: with no timeout or gtimeout on PATH, a scenario that hangs is cut off"
# Stock macOS has neither binary; the bound must hold without them. The
# scenario also leaves a child running that would write a marker 3 s in: the
# watchdog has to take the whole process group, not only the scenario.
NOTO_PATH=$(path_without notimeout timeout gtimeout)
check "precondition: timeout and gtimeout are hidden from that PATH" \
  "$( (PATH="$NOTO_PATH"; command -v timeout || command -v gtimeout) >/dev/null 2>&1 && echo no || echo yes)"
REPO=$(new_repo timeout)
SLOW_DIR="$TEST_ROOT/acceptance-slow"
scenario "$SLOW_DIR" "hangs" "( sleep 3; : > '$TEST_ROOT/orphan-wrote' ) &
exec sleep 60"
T0=$SECONDS
LH_SYS_PATH="$NOTO_PATH" CLADE_LOOP_HOLDOUT_TIMEOUT=2 run_loop "$REPO" --max-iter 1 --holdout "$SLOW_DIR"
ELAPSED=$((SECONDS - T0))
# Past the child's 3 s whatever the run took, so a survivor would have written.
sleep 4
check "the run did not wait the scenario out" "$([[ $ELAPSED -lt 45 ]] && echo yes || echo no)" "${ELAPSED}s"
check "counted as failed: no convergence, exit 2" "$([[ $RC -eq 2 ]] && lacks "$OUT" "CONVERGED")" "rc=$RC"
check "the child it left running was killed with it" \
  "$([[ ! -e "$TEST_ROOT/orphan-wrote" ]] && echo yes || echo no)"
check "loop.log: cut off at the configured bound, by position" \
  "$(has "$OUT" "holdout scenario 1 of 1: FAIL (cut off after 2s)")"
check "the holdout log names it" "$(has "$(hlog "$REPO" 1)" "=== hangs: FAIL (cut off after 2s)")"
fi

# ─── checkout ────────────────────────────────────────────────────────
if want checkout; then
section "checkout: what a scenario writes there reaches no commit and no prompt"
REPO=$(new_repo checkout-write)
# Nothing ignored, so the loop's own files (logs/loop, .claude/, a root
# --state file) are in the captures and the bookkeeping exclusions are
# exercised. Then five seed commits, so the context's
# `git diff --stat HEAD~5..HEAD` has a range in iteration 2 and would show a
# swept file's name.
: > "$REPO/.gitignore"
git -C "$REPO" commit -q -am "test: ignore nothing"
for i in 1 2 3 4; do git -C "$REPO" commit -q --allow-empty -m "test: seed $i"; done
WRITE_DIR="$TEST_ROOT/acceptance-writes"
# Every run: edit a tracked file, create a file and a directory, and write
# under .claude/ (standing in for a human editing there meanwhile). The second
# run also raises the stop sentinel, standing in for a human `--stop`.
scenario "$WRITE_DIR" "scribbles" "printf 'scenario-scribble\n' >> README.md
echo report > heldout-report-w3k.txt
mkdir -p build-w3k/out && echo o > build-w3k/out/artifact.txt
echo note > .claude/human-note.txt
echo run >> '$TEST_ROOT/scribble-runs'
if [ \"\$(wc -l < '$TEST_ROOT/scribble-runs')\" -eq 2 ]; then printf '{\"stop\":true}\n' > loop-state.json; fi
exit 1"
MOCK_LEFTOVER=1 run_loop "$REPO" --max-iter 3 --state loop-state.json --holdout "$WRITE_DIR"
# What the consumers receive first (worktree, commits, prompts, the loop's own
# files), the log message last: the mutation suite names the first check that
# goes red, and that should be an effect, not a sentence.
check "the file it created is gone" "$([[ ! -e "$REPO/heldout-report-w3k.txt" ]] && echo yes || echo no)"
check "and the directory it made" "$([[ ! -e "$REPO/build-w3k" ]] && echo yes || echo no)"
# Paths, not log text: with nothing ignored, run-tasks.sh's `git add -A` lets
# the mock worker's commit carry logs/loop, whose detail log names them.
PATHS=$(git -C "$REPO" log --name-only --format=)
README_HIST=$(git -C "$REPO" log -p --format= -- README.md)
check "no commit carries the created file" "$(lacks "$PATHS" "heldout-report-w3k")"
check "or the directory it made" "$(lacks "$PATHS" "build-w3k")"
check "no commit carries the scenario's edit to a tracked file" "$(lacks "$README_HIST" "scenario-scribble")"
check "the worker's leftover change was still committed" "$(has "$README_HIST" "+leftover")"
check "the worktree keeps no scenario edit" "$(lacks "$(cat "$REPO/README.md")" "scenario-scribble")"
NSUP=$(grep -c "autonomous improvement loop" "$PROMPTS" 2>/dev/null || true)
check "a second supervisor prompt was captured" "$([[ "${NSUP:-0}" -ge 2 ]] && echo yes || echo no)" "${NSUP:-0}"
check "no prompt carries the created file's name" "$(lacks "$(prompts)" "heldout-report-w3k")"
check "loop.log keeps the lines written while the scenarios ran" \
  "$(has "$(cat "$REPO/logs/loop/loop.log" 2>/dev/null)" "holdout scenario 1 of 1: FAIL")"
check ".claude/ is left alone (a human may be editing there)" \
  "$([[ -e "$REPO/.claude/human-note.txt" ]] && echo yes || echo no)"
check "a --stop raised while the scenarios ran is honoured" \
  "$([[ $RC -eq 0 ]] && has "$OUT" "Stop sentinel detected")" "rc=$RC"
check "the write is reported, the loop's own files not counted" \
  "$(has "$OUT" "the scenarios wrote 3 change(s) into the checkout")" "$(grep -o 'the scenarios wrote [0-9]* change' <<< "$OUT" | head -2 | tr '\n' ' ')"
check "the holdout log names what was put back" \
  "$(has "$(hlog "$REPO" 1)" "created: heldout-report-w3k.txt")"
fi

# ─── index ───────────────────────────────────────────────────────────
if want index; then
section "index: a scenario that stages a file gets the index put back losslessly"
# A file a sparse checkout leaves out (skip-worktree, absent on disk), and an
# intent-to-add entry the worker leaves under .claude/ (which the commit sweep
# never touches, so it survives to the next prompt). read-tree would drop both:
# the first then reads as deleted and the sweep commits the deletion.
REPO=$(new_repo index)
(
  cd "$REPO" || exit 1
  printf 'sparse\n' > sparse-only.txt
  git add sparse-only.txt
  git commit -q -m "test: a file the sparse checkout leaves out"
  git update-index --skip-worktree sparse-only.txt
  rm sparse-only.txt
)
IDX_DIR="$TEST_ROOT/acceptance-index"
scenario "$IDX_DIR" "stages" "printf 's\n' > staged-q9z.txt && git add staged-q9z.txt
exit 1"
MOCK_ITA=.claude/ita-note.txt run_loop "$REPO" --max-iter 2 --holdout "$IDX_DIR"
check "no commit deletes the file the sparse checkout left out" \
  "$(git -C "$REPO" cat-file -e HEAD:sparse-only.txt 2>/dev/null && echo yes || echo no)" \
  "$(git -C "$REPO" log --name-status --format=%s | head -12 | tr '\n' ' ')"
check "it is still skip-worktree in the index" \
  "$([[ "$(git -C "$REPO" ls-files -v -- sparse-only.txt)" == "S sparse-only.txt" ]] && echo yes || echo no)" \
  "$(git -C "$REPO" ls-files -v -- sparse-only.txt)"
LAST=$(last_supervisor_prompt)
check "a second supervisor prompt was captured" "$(has "$LAST" "Held-out acceptance")"
check "the next prompt still sees the intent-to-add entry as one" "$(has "$LAST" " A .claude/ita-note.txt")"
check "no prompt carries the path a scenario staged" "$(lacks "$(prompts)" "staged-q9z")"
check "and the index does not keep it" "$(lacks "$(git -C "$REPO" status --porcelain)" "staged-q9z")"
check "the holdout log says the index was put back" "$(has "$(hlog "$REPO" 1)" "changed: (the git index)")"
check "no index backup is left in the git dir" \
  "$(compgen -G "$REPO/.git/clade-holdout-*" >/dev/null && echo no || echo yes)"
fi

# ─── leak ────────────────────────────────────────────────────────────
if want leak; then
section "leak: nothing in the checkout names a scenario or carries its output"
# Nothing ignored, so run-tasks.sh's `git add -A` puts logs/loop in the
# worker's commit, and every file the loop writes there is one a later prompt
# or commit can carry.
REPO=$(new_repo leak)
: > "$REPO/.gitignore"
git -C "$REPO" commit -q -am "test: ignore nothing"
LEAK_DIR="$TEST_ROOT/holdout-leak-v2m"
# The output markers are computed, so they appear only in what the scenario
# prints, never in its source.
scenario "$LEAK_DIR" "zz-leaky-scenario" 'echo "SCENARIO-OUT-$((6*7))-MARK"
echo "SCENARIO-ERR-$((6*7))-MARK" >&2
exit 3'
run_loop "$REPO" --max-iter 2 --holdout "$LEAK_DIR"
HL=$(hlog "$REPO" 1)
check "control: the holdout log outside the repository has the name and both output streams" \
  "$([[ "$HL" == *"zz-leaky-scenario: FAIL (exit 3)"* && "$HL" == *SCENARIO-OUT-42-MARK* && "$HL" == *SCENARIO-ERR-42-MARK* ]] && echo yes || echo no)"
check "control: the worker's commit did carry logs/loop" \
  "$(has "$(git -C "$REPO" log --name-only --format=)" "logs/loop/loop.log")"
LEAKED=$(grep -rlF -e zz-leaky-scenario -e holdout-leak-v2m -e SCENARIO-OUT-42 -e SCENARIO-ERR-42 \
  -e "$HOME/.claude/loop-holdout" "$REPO" 2>/dev/null)
check "no file in the checkout names the scenario, DIR, the holdout log or the output" \
  "$([[ -z "$LEAKED" ]] && echo yes || echo no)" "$(tr '\n' ' ' <<< "$LEAKED")"
HIST=$(git -C "$REPO" log --all -p)
check "and no commit does" \
  "$([[ "$HIST" != *zz-leaky-scenario* && "$HIST" != *holdout-leak-v2m* && "$HIST" != *SCENARIO-OUT-42* && "$HIST" != *SCENARIO-ERR-42* ]] && echo yes || echo no)"
check "loop.log still counts the failure" \
  "$(has "$(cat "$REPO/logs/loop/loop.log" 2>/dev/null)" "holdout: 1 of 1 scenario(s) FAILED")"
check "the terminal is told where the holdout log is" \
  "$(has "$OUT" "Holdout log:  $HOME/.claude/loop-holdout/leak-")"
fi

# ─── fixture ─────────────────────────────────────────────────────────
if want fixture; then
section "fixture: an edited fixture under DIR is a changed scenario set"
# The scenario passes once README.md holds the line its expected-output
# fixture names. A worker rewriting that fixture (nested, not executable) to
# what it wrote makes the check pass without touching the scenario itself.
REPO=$(new_repo fixture)
FIX_DIR="$TEST_ROOT/acceptance-fixture"
mkdir -p "$FIX_DIR/fixtures/expected"
printf 'never-in-readme-r5t\n' > "$FIX_DIR/fixtures/expected/line.txt"
scenario "$FIX_DIR" "check" "grep -qx \"\$(cat '$FIX_DIR/fixtures/expected/line.txt')\" README.md"
MOCK_FIXTURE="$FIX_DIR/fixtures/expected/line.txt" run_loop "$REPO" --max-iter 2 --holdout "$FIX_DIR"
LP=$(cat "$REPO/logs/loop/last-progress" 2>/dev/null)
check "the run converges at iteration 2, not 1" \
  "$([[ $RC -eq 0 ]] && has "$LP" "Iterations: 2")" "rc=$RC; $LP"
check "it reconciles once, on the next iteration's unchanged set" \
  "$([[ "$(grep -c "Coordinator reconciled" <<< "$OUT")" -eq 1 ]] && echo yes || echo no)" \
  "$(grep -c "Coordinator reconciled" <<< "$OUT") reconciliations"
check "the edit is reported" "$(has "$OUT" "HOLDOUT CHANGED mid-run")"
check "last-progress names the iteration it changed in" \
  "$(has "$LP" "scenario set CHANGED mid-run at iteration 1")"
fi

# ─── named ───────────────────────────────────────────────────────────
if want named; then
section "named: a goal or --context file naming the holdout is warned about"
# Both files are pasted into the supervisor prompt whole, so a holdout path in
# either undoes the counts-only context. --dry-run validates the holdout too.
REPO=$(new_repo named)
NAMED_DIR="$HOME/acceptance-named"
scenario "$NAMED_DIR" "check" 'exit 0'
GOAL="$REPO/.claude/goal.md"
NAMED_WARN="names the holdout directory"
printf '# Goal\n\n- [ ] exact item (acceptance lives in %s/)\n' "$NAMED_DIR" > "$GOAL"
run_loop "$REPO" --dry-run --holdout "$NAMED_DIR"
check "a goal naming DIR gets a warning" \
  "$(has "$OUT" "WARNING: --holdout: .claude/goal.md $NAMED_WARN")" "rc=$RC; $OUT"
check "and the run still proceeds: a warning, not a refusal" "$([[ $RC -eq 0 ]] && echo yes || echo no)" "rc=$RC"
printf '# Goal\n\n- [ ] exact item\n' > "$GOAL"
printf 'The scenarios are in ~/acceptance-named.\n' > "$TEST_ROOT/named-context.md"
run_loop "$REPO" --dry-run --holdout "$NAMED_DIR" --context "$TEST_ROOT/named-context.md"
check "a --context file naming DIR's ~/ form gets a warning" \
  "$(has "$OUT" "WARNING: --holdout: $TEST_ROOT/named-context.md $NAMED_WARN")" "$OUT"
ln -s "$NAMED_DIR" "$TEST_ROOT/named-link"
printf '# Goal\n\n- [ ] exact item (see %s)\n' "$NAMED_DIR" > "$GOAL"
run_loop "$REPO" --dry-run --holdout "$TEST_ROOT/named-link"
check "a goal naming the physical path behind a symlinked DIR gets a warning" \
  "$(has "$OUT" "$NAMED_WARN")" "$OUT"
# A DIR given as a bare name (a symlink in the checkout to a directory outside
# it) is not searched: "ac" is in "exact" and "each".
ln -s "$NAMED_DIR" "$REPO/ac"
printf '# Goal\n\n- [ ] exact item, for each acceptance-named check\n' > "$GOAL"
run_loop "$REPO" --dry-run --holdout ac
check "a goal sharing only a bare DIR name, DIR's basename and a scenario name gets no warning" \
  "$(lacks "$OUT" "$NAMED_WARN")" "rc=$RC; $OUT"
check "and that bare-name holdout is accepted" "$([[ $RC -eq 0 ]] && echo yes || echo no)" "rc=$RC; $OUT"
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

mutation green loop_holdout.sh \
  "positive negative refuse converge drift tamper resume gone timeout checkout index leak fixture named" \
  "no-op control (a comment reworded)" \
  "# Content digest of FILE" "# The content digest of FILE"
mutation red loop-runner.sh "negative" "the holdout term of the reconcile gate" \
  ' \
       && [ "$holdout_result" -eq 0 ]; then' '; then'
mutation red loop-runner.sh "named" "the named-holdout warning call" \
  '  holdout_warn_named "$HOLDOUT_DIR" "$GOAL_FILE" "$CONTEXT_FILE"
' ''
mutation red loop_holdout.sh "named" "the ~/ form of DIR in the named-holdout search" \
  '"$HOME"/*) forms="$forms~/${form#"$HOME"/}"$'"'"'\n'"'"' ;;' '"$HOME"/*) ;;'
mutation red loop_holdout.sh "named" "the physical path in the named-holdout search" \
  'for form in "$given" "$LOOP_HOLDOUT_DIR"; do' 'for form in "$given"; do'
mutation red loop_holdout.sh "named" "a bare name never searched for" \
  'case "$form" in */*) ;; *) continue ;; esac' ':'
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
mutation red loop_checkpoint.py "resume" "the --holdout term of the resume identity" \
  'if recorded_holdout != args.holdout:' 'if False:'
mutation red loop-runner.sh "resume" "the checkpoint recording the run's --holdout" \
  '--holdout="$(holdout_state_dir)" \
    --holdout-fingerprint=' '--holdout-fingerprint='
mutation red loop-runner.sh "resume" "the baseline fingerprint restored on resume" \
  '  holdout_state_restore \
' '  : \
'
mutation red loop_holdout.sh "gone" "an unrunnable scenario set counted as failed" \
  '    LOOP_HOLDOUT_LAST_FAILED=1
    return 1' '    LOOP_HOLDOUT_LAST_FAILED=0
    return 0'
mutation red loop_holdout.sh "gone" "no '1 of 0' when nothing could run" \
  '  if [ "$LOOP_HOLDOUT_LAST_TOTAL" -eq 0 ]; then
    what=' '  if false; then
    what='
mutation red loop_holdout.sh "timeout" "the per-scenario watchdog" \
  '_holdout_bounded "${HOLDOUT_TIMEOUT:-120}" "$f"' '"$f"'
mutation red loop_holdout.sh "timeout" "the watchdog taking the whole process group" \
  '            os.killpg(child.pid, sig)' '            os.kill(child.pid, sig)'
mutation red loop_holdout.sh "refuse" "no --holdout without python3 for the watchdog" \
  'if ! command -v python3 >/dev/null 2>&1; then' 'if false; then'
mutation red loop_holdout.sh "leak" "the holdout log kept outside the repository" \
  'local f="$LOOP_HOLDOUT_LOG_DIR/iter-${ITERATION:-0}-holdout.log"' \
  'local f="$LOG_DIR/iter-${ITERATION:-0}-holdout.log"'
mutation red loop_holdout.sh "leak" "no scenario name in loop.log" \
  'log_warn "  holdout scenario $total of $n: FAIL"' \
  'log_warn "  holdout scenario $total of $n: FAIL ($name)"'
mutation red loop_holdout.sh "leak" "the holdout log's location told to the terminal only" \
  "_holdout_tell() { echo \"[\$(date '+%H:%M:%S')] [INFO]  \$*\" >&2; }" \
  '_holdout_tell() { log_info "$*"; }'
mutation red loop-runner.sh "resume" "the recovery hint naming DIR kept out of loop.log" \
  '    log_error "[RECOVERY] ${recovered%%$'"'"'\n'"'"'*}"' '    log_error "[RECOVERY] $recovered"'
mutation red loop_holdout.sh "refuse" "the holdout log refused inside the checkout" \
  'if _holdout_lands_inside "the holdout log' 'if false && _holdout_lands_inside "the holdout log'
mutation red loop_holdout.sh "refuse" "the holdout log refused inside DIR" \
  'if _holdout_is_inside "$log_abs" "$abs"; then' 'if false; then'
mutation red loop_holdout.sh "refuse" "the resume checkpoint refused inside the checkout" \
  '     _holdout_lands_inside "the resume checkpoint' '     false && _holdout_lands_inside "the resume checkpoint'
mutation red loop_holdout.sh "fixture" "the fingerprint walking DIR recursively" \
  'find . -print0 2>/dev/null' 'find . -maxdepth 1 -print0 2>/dev/null'
mutation red loop_holdout.sh "fixture" "the fingerprint covering file content" \
  'printf '"'"'f %s %s %s\n'"'"' "$x" "$(_holdout_content_hash "$p")" "$p"' \
  'printf '"'"'f %s %s %s\n'"'"' "$x" - "$p"'
mutation red loop_holdout.sh "index" "the git index put back" \
  '    _holdout_index_put_back "$idx_before" || return 1' '    :'
mutation red loop_holdout.sh "index" "the index put back byte for byte, not with read-tree" \
  'elif cp "$backup" "$lock" 2>/dev/null && mv -f "$lock" "$index"; then' \
  'elif rm -f "$lock" && git read-tree HEAD; then'
mutation red loop_holdout.sh "refuse" "the scenario-timeout validation" \
  'if [ "$timeout_ok" != "true" ]; then' 'if false; then'
mutation red loop_holdout.sh "refuse" "the scenario-symlink-into-a-sibling-worktree refusal" \
  'if [ "$there" = "$common" ]; then' 'if false; then'
mutation red loop_holdout.sh "checkout" "putting back what the scenarios wrote" \
  'restored=$(cd "$LOOP_HOLDOUT_CHECKOUT" && _holdout_restore "$cap" 2>>"$detail") || restored=""' \
  'restored=0'
mutation red loop_holdout.sh "checkout" "LOG_DIR left out of the put-back" \
  '        case "$p" in "$log"|"$log"/*) continue ;; esac' '        :'
mutation red loop_holdout.sh "checkout" "STATE_FILE left out of the put-back" \
  'if [ -n "$state" ] && [ "$p" = "$state" ]; then continue; fi' ':'
mutation red loop_holdout.sh "checkout" ".claude/ left out of the put-back" \
  'case "$p" in .claude|.claude/*) continue ;; esac' ':'
mutation red loop_holdout.sh "tamper" "a pass on a changed set not counted by node_holdout" \
  '  if holdout_changed_this_check; then
    log_warn "holdout: all' '  if false; then
    log_warn "holdout: all'
mutation red loop_holdout.sh "tamper" "a changed set blocking convergence" \
  '  if holdout_changed_this_check; then
    log_warn "Goal checklist' '  if false; then
    log_warn "Goal checklist'
mutation red loop_holdout.sh "tamper" "the change reaching last-progress and the report" \
  '  if [ -n "$LOOP_HOLDOUT_CHANGED_AT" ]; then
    line=' '  if false; then
    line='
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
