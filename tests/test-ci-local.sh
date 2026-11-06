#!/usr/bin/env bash
# test-ci-local.sh — the local CI runner must be able to go red.
#
# The failure mode this guards is specific and this repository has shipped it
# twice in other instruments: a checker that cannot fire reports a clean run
# exactly like a clean codebase. Here it would be worse than useless — a runner
# that silently executes nothing and exits 0 is a green light for a broken push.
#
# Every assertion runs against a SYNTHETIC workflow under /tmp, never the real
# one, so the test is fast and cannot be confused by the repository's own state.
#
# The second fixture is a multi-lane workflow: a services job, a step whose
# `if:` reads step outputs, an E2E step whose env needs runner context, a
# pull_request_target workflow, workflow-level defaults. Those lanes run on
# every hosted push and could not run here; the suite asserts they come back
# UNPROVEN (summary PARTIAL, JSON `unproven`, exit 2 under --strict) and never
# as passed. The last suite removes each guard from a copy of ci-local.py and
# requires this suite to go red; an anchor that no longer matches is a failure.
#
# Usage:
#   bash tests/test-ci-local.sh        # Run all tests
#   bash tests/test-ci-local.sh -v     # Verbose mode
# Internal (the mutation suite sets these for each mutant run):
#   CI_LOCAL_RUNNER=PATH   test this copy of ci-local.py instead of the repo's
#   CI_LOCAL_MUTANT=1      stop at the first failure; skip the mutation suite

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="${CI_LOCAL_RUNNER:-$REPO_ROOT/configs/scripts/ci-local.py}"
CI_LOCAL_MUTANT="${CI_LOCAL_MUTANT:-}"
VERBOSE="${1:-}"

TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'

pass() { TESTS_RUN=$((TESTS_RUN+1)); TESTS_PASSED=$((TESTS_PASSED+1)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() {
  TESTS_RUN=$((TESTS_RUN+1)); TESTS_FAILED=$((TESTS_FAILED+1))
  echo -e "  ${RED}✗${NC} $1"; [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
  # A mutant run only has to show that SOMETHING noticed.
  [[ -n "$CI_LOCAL_MUTANT" ]] && exit 1
  return 0
}
section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }
assert_eq() {
  local got="$1" want="$2" msg="$3"
  if [[ "$got" == "$want" ]]; then pass "$msg"; else fail "$msg" "expected '$want', got '$got'"; fi
}
assert_contains() {
  local hay="$1" needle="$2" msg="$3"
  if grep -qF -- "$needle" <<< "$hay"; then pass "$msg"
  else fail "$msg" "output lacks '$needle'"; [[ "$VERBOSE" == "-v" ]] && echo "$hay" | head -20; fi
}
assert_lacks() {
  local hay="$1" needle="$2" msg="$3"
  if grep -qF -- "$needle" <<< "$hay"; then fail "$msg" "output contains '$needle'"
  else pass "$msg"; fi
}

command -v python3 >/dev/null 2>&1 || { echo "python3 not found — skipping"; exit 0; }

SANDBOX="$(mktemp -d /tmp/clade-ci-local-XXXXXX)"
case "$SANDBOX" in /tmp/clade-ci-local-*) : ;; *) echo "FATAL: sandbox not under /tmp"; exit 1 ;; esac
trap 'rm -rf "$SANDBOX"' EXIT
# The venv that stands in for actions/setup-python is keyed by repository path,
# and every run's fixture is a fresh one: keep it in the sandbox, not ~/.cache.
export XDG_CACHE_HOME="$SANDBOX/cache"

FAKE="$SANDBOX/repo"
mkdir -p "$FAKE/.github/workflows"
cat > "$FAKE/.github/workflows/ci.yml" <<'YAML'
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  good:
    name: Good Job
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Say hello
        run: echo hello-from-good
      - name: Multi line block
        run: |
          echo first
          echo second

  bad:
    name: Bad Job
    runs-on: ubuntu-latest
    steps:
      - name: This one fails
        run: |
          echo about-to-fail
          exit 3
      - name: Never reached
        run: echo SHOULD-NOT-RUN

  gated:
    name: Gated Job
    if: github.event_name == 'schedule'
    runs-on: ubuntu-latest
    steps:
      - name: Only on a schedule
        run: echo gated-ran

  mac_only:
    name: Mac Only
    runs-on: macos-latest
    steps:
      - name: Mac step
        run: echo mac-ran

  secretive:
    name: Needs A Secret
    runs-on: ubuntu-latest
    steps:
      - name: Uses a secret
        env:
          TOKEN: ${{ secrets.SOME_TOKEN }}
        run: echo secret-step-ran

  matrixed:
    name: Matrix Job
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest]
    steps:
      - name: Matrix step
        run: echo matrix-ran

  conditional_step:
    name: Step Level If
    runs-on: ubuntu-latest
    steps:
      - name: Only sometimes
        if: github.ref == 'refs/heads/main'
        run: echo conditional-step-ran
YAML

run_it() { python3 "$RUNNER" --repo "$FAKE" "$@" 2>&1; }

# ─── 1. The plan ─────────────────────────────────────────────────────
section "the plan names what runs and what does not"
OUT="$(run_it --list)"
assert_contains "$OUT" "Good Job"  "a runnable job is listed"
assert_contains "$OUT" "Bad Job"   "a failing job is still listed (it runs)"
assert_contains "$OUT" "conditional" "a schedule-gated job is skipped as conditional"
assert_contains "$OUT" "needs Darwin" "a macOS job says which platform it needs"
# Count the listed jobs rather than grepping for the digit — the first version
# of this assertion looked for the string "5" anywhere in the output, which is
# a proxy, not a check, and it failed for the right reason.
LISTED=$(grep -cE '^  \[(run |skip)\] ' <<< "$OUT" || true)
assert_eq "$LISTED" "7" "exactly the 7 real jobs are listed, not the on: triggers"
PHANTOM=$(grep -cE '\] (push|pull_request|schedule|workflow_dispatch) ' <<< "$OUT" || true)
assert_eq "$PHANTOM" "0" "no trigger name is parsed as a job"

# ─── 2. It can go red ────────────────────────────────────────────────
section "it can go red, and says exactly where"
OUT="$(run_it)"; RC=$?
assert_eq "$RC" "1" "a failing step makes the whole run exit non-zero"
assert_contains "$OUT" "FAILED  Bad Job" "the failing job is named"
assert_contains "$OUT" "This one fails"  "the failing STEP is named"
assert_contains "$OUT" "exit 3"          "the real exit code is reported, not just failure"
assert_contains "$OUT" "about-to-fail"   "the step's own output is shown"

# GitHub stops a job at its first failed step; so must this.
if grep -q "SHOULD-NOT-RUN" <<< "$OUT"; then
  fail "a job stops at its first failed step" "the later step ran anyway"
else
  pass "a job stops at its first failed step"
fi

# ─── 3. It can go green ──────────────────────────────────────────────
section "it can go green on a job that passes"
OUT="$(run_it --job "Good Job")"; RC=$?
assert_eq "$RC" "0" "a passing job exits 0"
assert_contains "$OUT" "1/1 job(s) passed" "the count reflects what actually ran"

# ─── 4. Skips are reported, never silent ─────────────────────────────
section "nothing-ran must not look like everything-passed"
OUT="$(run_it --job "Mac Only")"; RC=$?
assert_eq "$RC" "0" "a job that cannot run here is not a failure"
assert_contains "$OUT" "skipped Mac Only" "the skip is reported in the summary"
assert_contains "$OUT" "0/0 job(s) passed" "zero jobs ran, and the summary says zero"

# A job whose every step is skipped executed NOTHING. Reporting it as passed is
# the exact lie this tool exists to prevent, and the first version did it.
OUT="$(run_it --job "Needs A Secret")"
assert_contains "$OUT" "0/0 job(s) passed" "a job with no runnable step is not counted as passed"
assert_contains "$OUT" "every step skipped" "and the reason names why it ran nothing"

# ─── 4b. Constructs the parser cannot model are LOUD skips ───────────
# A matrix job quietly collapsed to one leg, or a container job run on the
# host, is a green that covered less than it appears to — the same
# nothing-ran-looks-like-all-passed failure arriving from a new direction.
section "unmodelled workflow constructs are refused, not half-run"
OUT="$(run_it --list)"
assert_contains "$OUT" "does not model" "a matrix job is skipped with a reason naming why"
if grep -A1 'Matrix Job' <<< "$OUT" | grep -q 'strategy'; then
  pass "the matrix job names strategy: as the construct"
else
  fail "the matrix job names strategy: as the construct" "$(grep -A1 'Matrix Job' <<< "$OUT")"
fi
if grep -A1 'Step Level If' <<< "$OUT" | grep -q 'UNPROVEN.*step-level if'; then
  pass "a step-level if: it cannot evaluate leaves that lane UNPROVEN"
else
  fail "a step-level if: it cannot evaluate leaves that lane UNPROVEN" "$(grep -A1 'Step Level If' <<< "$OUT")"
fi
OUT="$(run_it --job "Matrix Job")"
assert_contains "$OUT" "0/0 job(s) passed" "a matrix job is never counted as passed"
assert_contains "$OUT" "unproven Matrix Job" "and it is named as an unproven lane"

# A failure outranks everything: --strict's exit 2 is for "nothing failed, but".
OUT="$(run_it --strict)"; RC=$?
assert_eq "$RC" "1" "a failed job exits 1 under --strict too, not 2"
assert_contains "$OUT" "lane(s) unproven" "and the unproven lanes are still listed beside the failure"

# ─── 5. JSON is usable by an automatic fixer ─────────────────────────
section "the JSON carries what a fixer needs"
JSON="$(run_it --json)"
for field in '"job": "Bad Job"' '"step": "This one fails"' '"exit_code": 3' '"command"' '"output_tail"' '"seconds"'; do
  assert_contains "$JSON" "$field" "json carries $field"
done
if python3 -c "import json,sys; json.load(sys.stdin)" <<< "$JSON" 2>/dev/null; then
  pass "the JSON parses"
else
  fail "the JSON parses" "invalid JSON on a failing run"
fi
SKIPPED=$(python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['skipped']))" <<< "$JSON" 2>/dev/null || echo -1)
if [[ "$SKIPPED" -ge 2 ]]; then pass "the JSON lists skipped jobs too ($SKIPPED)"
else fail "the JSON lists skipped jobs too" "got $SKIPPED"; fi

# ─── 6. A repository with no workflows is an error, not a pass ───────
section "no workflows is an error, not a silent success"
EMPTY="$SANDBOX/empty"; mkdir -p "$EMPTY"
python3 "$RUNNER" --repo "$EMPTY" >/dev/null 2>&1
assert_eq "$?" "1" "a repo with no .github/workflows exits non-zero"

# ─── 7. A multi-lane repository: unproven is not green ───────────────
# Shaped like a real application repo (unit, services-backed backend, E2E,
# a nightly tier, a pull_request_target triage bot, workflow-level defaults).
# Every step that must NOT run touches a marker; every step that must run
# touches one too, so the assertions read what happened, not what was printed.
LANES="$SANDBOX/lanes"
mkdir -p "$LANES/.github/workflows"
cat > "$LANES/.github/workflows/lanes.yml" <<'YAML'
name: Lanes
on:
  push:
    branches: [main]
  pull_request:

env:
  CI_LOCAL_T_WF: from-workflow
  CI_LOCAL_T_SHARED: workflow

jobs:
  unit:
    name: Unit Tests
    runs-on: ubuntu-latest
    env:
      CI_LOCAL_T_SHARED: job
      CI_LOCAL_T_QUOTED: 'it''s quoted'   # a trailing comment is not the value
      CI_LOCAL_T_OVERRIDE: job
    steps:
      - uses: actions/checkout@v4
      - name: Env reaches the step
        env:
          CI_LOCAL_T_DQ: "dq \"x\""
          CI_LOCAL_T_OVERRIDE: step
        run: |
          test "$CI_LOCAL_T_WF" = from-workflow
          test "$CI_LOCAL_T_SHARED" = job
          test "$CI_LOCAL_T_QUOTED" = "it's quoted"
          test "$CI_LOCAL_T_DQ" = 'dq "x"'
          test "$CI_LOCAL_T_OVERRIDE" = step
      - name: Upload coverage
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: coverage
      - name: Cleanup
        if: ${{ always() }}
        run: touch .cleanup-ran
      - name: Not cancelled
        if: "!cancelled()"   # quoted, as YAML requires for a leading !
        run: touch .not-cancelled-ran
      - name: Report on failure
        if: failure()
        run: |
          touch .failure-only-ran
          exit 7

  backend:
    name: Backend Tests
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: test
        ports:
          - 5432:5432
    env:
      DATABASE_URL: postgresql://test:test@localhost:5432/app_test
    steps:
      - uses: actions/checkout@v4
      - name: Run backend tests
        run: touch .backend-ran

  e2e:
    name: E2E
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build
        run: echo e2e-build
      - name: Run E2E
        env:
          E2E_DB: ${{ runner.temp }}/e2e.db
        run: touch .e2e-ran
      - name: Changed-only step
        if: steps.changes.outputs.web == 'true'
        run: touch .changed-ran
      - name: After the unproven steps
        run: touch .after-unproven-ran

  nightly_db:
    name: Nightly DB
    if: github.event_name == 'schedule'
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7
    steps:
      - name: Needs redis
        run: touch .nightly-ran

# A column-0 comment inside jobs: is a comment, not the end of the section.
  after_comment:
    name: After Comment
    runs-on: ubuntu-latest
    steps:
      - name: Still a job
        run: touch .after-comment-ran
YAML
cat > "$LANES/.github/workflows/triage.yml" <<'YAML'
name: Triage
on:
  pull_request_target:
    types: [opened]

jobs:
  triage:
    runs-on: ubuntu-latest
    steps:
      - name: Label
        id: label
        env:
          TITLE: ${{ github.event.pull_request.title }}
        run: echo labelled
      - name: Comment
        if: steps.label.outcome == 'success'
        continue-on-error: true
        run: touch .triage-ran
YAML
cat > "$LANES/.github/workflows/defaults.yml" <<'YAML'
name: Defaults
on: [push]

defaults:
  run:
    working-directory: app

jobs:
  build:
    name: Defaults Build
    runs-on: ubuntu-latest
    steps:
      - name: Build in app/
        run: touch .defaults-ran
YAML

lanes() { python3 "$RUNNER" --repo "$LANES" "$@" 2>&1; }
clear_markers() { rm -f "$LANES"/.*-ran; }
ran() { [[ -e "$LANES/.$1-ran" ]]; }
assert_ran() { if ran "$1"; then pass "$2"; else fail "$2" "the .$1-ran marker is missing"; fi; }
assert_not_ran() { if ran "$1"; then fail "$2" "the .$1-ran marker exists: it executed"; else pass "$2"; fi; }

section "the plan separates reasoned skips from unproven lanes"
OUT="$(lanes --list)"
after() { grep -A2 -F -- "$1" <<< "$OUT"; }
assert_contains "$(after 'Backend Tests')" "UNPROVEN — uses services" "a services job is planned as UNPROVEN"
assert_contains "$(after '[run ] E2E')" "UNPROVEN step Run E2E" \
  "an E2E step whose env needs runner context is UNPROVEN, not 'needs a repository secret'"
assert_contains "$(after '[run ] E2E')" "UNPROVEN step Changed-only step" \
  "a step-level if: on step outputs is UNPROVEN, and its job still runs"
assert_contains "$(after 'Unit Tests')" "3/4 runnable" "always()/!cancelled() steps run, failure() does not"
assert_contains "$(after 'Nightly DB')" "conditional" "a schedule tier is a reasoned skip, tested before services:"
assert_lacks "$(after 'Nightly DB')" "UNPROVEN" "so the nightly tier is not reported as an unproven lane"
assert_contains "$(after '] triage')" "runs on GitHub's side only" \
  "a pull_request_target workflow is GitHub-side, even when it also uses continue-on-error"
assert_contains "$(after 'Defaults Build')" "UNPROVEN — uses workflow-level defaults" \
  "workflow-level defaults: is not silently dropped"
assert_contains "$OUT" "After Comment" "a column-0 comment does not end the jobs: section"

section "a run with an unproven lane is PARTIAL, never green"
clear_markers
OUT="$(lanes)"; RC=$?
assert_eq "$RC" "0" "report-only rollout: without --strict the exit code is still 0"
assert_contains "$OUT" "ci-local: PARTIAL: 3/3 job(s) passed" "the summary line says PARTIAL"
assert_contains "$OUT" "4 lane(s) unproven: Defaults Build, Backend Tests, E2E › Run E2E, E2E › Changed-only step" \
  "and names every unproven lane on that line"
assert_contains "$OUT" "unproven Backend Tests: uses services" "each unproven lane carries its reason"
assert_contains "$OUT" "skipped triage: runs on GitHub's side only" "a reasoned skip is still listed as skipped"
assert_lacks "$OUT" "unproven Nightly DB" "a conditional tier is not an unproven lane"
assert_contains "$OUT" "PARTIAL is not green" "the output says what PARTIAL means"
assert_lacks "$OUT" "FAILED" "nothing failed: env reached the step and failure() stayed off the success path"
assert_ran cleanup "an if: \${{ always() }} step runs on the success path"
assert_ran not-cancelled "an if: !cancelled() step runs on the success path"
assert_not_ran failure-only "an if: failure() step does not run on the success path"
assert_ran after-unproven "a skipped unproven step does not end its job"
assert_ran after-comment "the job after a column-0 comment executed"
for m in backend e2e changed nightly triage defaults; do
  assert_not_ran "$m" "the .$m-ran lane was not executed here"
done

section "--strict exits 2 on an unproven lane"
OUT="$(lanes --strict)"; RC=$?
assert_eq "$RC" "2" "--strict exits 2 when nothing failed but a lane is unproven"
assert_contains "$OUT" "ci-local: PARTIAL:" "and it is the PARTIAL verdict that made it 2, not a usage error"
OUT="$(lanes --strict --job "Unit Tests")"; RC=$?
assert_eq "$RC" "0" "--strict exits 0 when every lane that was asked for is proven"
assert_contains "$OUT" "ci-local: 1/1 job(s) passed" "a fully proven run has no PARTIAL in its summary"
assert_lacks "$OUT" "PARTIAL" "not even in the explanation line"

# An explicitly named conditional job runs — but it is still planned in full,
# so its services: keep it from running on the host.
clear_markers
OUT="$(lanes --strict --job "Nightly DB")"; RC=$?
assert_not_ran nightly "--job on a conditional services job does not run it on the host"
assert_eq "$RC" "2" "and --strict reports it as unproven"
assert_contains "$OUT" "unproven Nightly DB: uses services" "naming services as the reason"
OUT="$(lanes --all --list)"
assert_contains "$(after 'Nightly DB')" "UNPROVEN — uses services" "with --all the nightly services job is an unproven lane"

section "the JSON names the unproven lanes for /green"
clear_markers
JSON="$(python3 "$RUNNER" --repo "$LANES" --json --strict 2>/dev/null)"; RC=$?
assert_eq "$RC" "2" "--json --strict exits 2 as well"
CHECK=$(python3 - "$JSON" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
problems = []
if d.get("verdict") != "partial":
    problems.append(f"verdict={d.get('verdict')!r}")
got = sorted(f"{u['job']}|{u['step']}" for u in d.get("unproven", []))
want = sorted(["Defaults Build|", "Backend Tests|", "E2E|Run E2E", "E2E|Changed-only step"])
if got != want:
    problems.append(f"unproven={got}")
if any(not u.get("reason") or not u.get("workflow") for u in d.get("unproven", [])):
    problems.append("an unproven lane lacks its reason or workflow")
if d.get("partial") != ["E2E"]:
    problems.append(f"partial={d.get('partial')}")
skipped = {s["job"]: s.get("unproven") for s in d.get("skipped", [])}
if skipped != {"Defaults Build": True, "Backend Tests": True, "Nightly DB": False, "triage": False}:
    problems.append(f"skipped={skipped}")
if sorted(d.get("passed", [])) != ["After Comment", "E2E", "Unit Tests"]:
    problems.append(f"passed={d.get('passed')}")
print("; ".join(problems) or "ok")
PY
)
assert_eq "$CHECK" "ok" "verdict, unproven, partial, skipped[].unproven and passed are exact"

# ─── 8. Mutations: removing each guard turns this suite red ──────────
# A clean run and a run with a guard missing print the same "ALL PASSED"
# unless something removes the guard and looks. Each entry edits ONE guard out
# of a copy of ci-local.py, runs this suite against the copy, and requires it
# to go red. The first is the negative control: a no-op edit must stay green,
# or a red result proves nothing. Mutant runs stop at their first failure.
if [[ -z "$CI_LOCAL_MUTANT" ]]; then
section "mutations: each guard is observed, not just claimed"
MUT_DIR="$SANDBOX/mutants"; mkdir -p "$MUT_DIR"
NMUT=0; MUT_NAMES=(); MUT_EXPECT=()

# mutation EXPECT NAME ANCHOR REPLACEMENT [ANCHOR REPLACEMENT ...] — literal
# text, no regex; each anchor must match the current copy exactly once. Builds
# the mutant only; they all run, bounded-parallel, after the list.
mutation() {
  local expect="$1" name="$2" out
  out="$MUT_DIR/m$NMUT.py"
  shift 2
  cp "$RUNNER" "$out"
  while [[ "$#" -ge 2 ]]; do
    if ! CL_A="$1" CL_R="$2" python3 - "$out" <<'PY'
import os, sys
path, a, r = sys.argv[1], os.environ["CL_A"], os.environ["CL_R"]
text = open(path, encoding="utf-8").read()
if text.count(a) != 1:
    sys.exit(3)
open(path, "w", encoding="utf-8").write(text.replace(a, r))
PY
    then
      fail "mutation '$name': its anchor no longer matches ci-local.py exactly once"
      return 0
    fi
    shift 2
  done
  MUT_NAMES[NMUT]="$name"; MUT_EXPECT[NMUT]="$expect"
  NMUT=$((NMUT + 1))
}

mutation green "no-op control (a comment reworded)" \
  '# Report-only for one week, then the default' '# Report-only for one week,  then the default'
mutation red "the reasoned-first order (unmodelled tested before pull_request_target)" \
  '    if "pull_request_target" in on_block and "pull_request:" not in on_block:' \
  '    if job.unmodelled:
        what = ", ".join(sorted(set(job.unmodelled)))
        return Skip(f"uses {what}, which this runner does not model — run it hosted, "
                    "or split the job", unproven=True)
    if "pull_request_target" in on_block and "pull_request:" not in on_block:'
mutation red "unproven on an unmodelled job (services:)" \
  '"or split the job", unproven=True)' '"or split the job")'
mutation red "an unevaluable step if: being unproven" \
  'return _SUCCESS_PATH_IF.get(re.sub(r"\s+", "", cond))' \
  'return _SUCCESS_PATH_IF.get(re.sub(r"\s+", "", cond), True)'
mutation red "failure() staying off the success path" '"failure()": False,' '"failure()": True,'
mutation red "always() running on the success path" \
  '"success()": True, "always()": True,' '"success()": True, "always()": False,'
mutation red "the --strict exit 2" \
  'exit_code = 1 if failed else (2 if lanes and args.strict else 0)' 'exit_code = 1 if failed else 0'
mutation red "telling a secret from other GitHub context" \
  '_SECRET_REF = re.compile(r"\bsecrets\.|\bgithub\.token\b")' '_SECRET_REF = re.compile(r".")'
mutation red "job-level env" \
  'st.env = {**workflow_env, **job.env, **st.env}' 'st.env = {**workflow_env, **st.env}'
mutation red "workflow-level env" \
  'st.env = {**workflow_env, **job.env, **st.env}' 'st.env = {**job.env, **st.env}'
mutation red "YAML unquoting of a step env value" \
  'step.env[env_match.group(1)] = _scalar(env_match.group(2))' \
  'step.env[env_match.group(1)] = env_match.group(2).strip()'
mutation red "YAML unquoting of a job env value" \
  'current.env[pair.group(1)] = _scalar(pair.group(2))' \
  'current.env[pair.group(1)] = pair.group(2).strip()'
mutation red "flagging workflow-level defaults" \
  'workflow_unmodelled.append("workflow-level defaults")' 'pass'
mutation red "skipping a column-0 comment" \
  '        if raw.lstrip().startswith("#"):
            continue
' ''
mutation red "planning a --job conditional in full" \
  'plan = collect_jobs(repo, include_conditional=args.all or bool(args.job))' \
  'plan = collect_jobs(repo, include_conditional=args.all)' \
  '        if not plan:
            print(f"ci-local: no job matching {args.job}")
            return 1
' '        if not plan:
            print(f"ci-local: no job matching {args.job}")
            return 1
        plan = [(j, None if r and r.reason.startswith("conditional") else r) for j, r in plan]
'
mutation red "unproven steps reaching the lane list" \
  'lanes.extend(Lane(r.job, s.name, s.reason) for s in r.unproven_steps)' 'pass'
mutation red "the PARTIAL prefix on the summary line" \
  "print(f\"ci-local: {'PARTIAL: ' if verdict == 'partial' else ''}{summary}\")" \
  'print(f"ci-local: {summary}")'

# A shared host and a 4-core hosted runner both run this: at most 4 at once.
CL_JOBS=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)
[[ "$CL_JOBS" =~ ^[0-9]+$ && "$CL_JOBS" -ge 1 ]] || CL_JOBS=2
[[ "$CL_JOBS" -gt 4 ]] && CL_JOBS=4
run_mutant() {
  if command -v timeout >/dev/null 2>&1; then
    CI_LOCAL_RUNNER="$MUT_DIR/m$1.py" CI_LOCAL_MUTANT=1 timeout 120 \
      bash "$REPO_ROOT/tests/test-ci-local.sh" > "$MUT_DIR/m$1.log" 2>&1
  else
    CI_LOCAL_RUNNER="$MUT_DIR/m$1.py" CI_LOCAL_MUTANT=1 \
      bash "$REPO_ROOT/tests/test-ci-local.sh" > "$MUT_DIR/m$1.log" 2>&1
  fi
}
MUT_PIDS=(); MUT_RCS=(); CL_NEXT=0; CL_I=0
while [[ "$CL_I" -lt "$NMUT" ]]; do
  if [[ $((CL_I - CL_NEXT)) -ge "$CL_JOBS" ]]; then
    wait "${MUT_PIDS[$CL_NEXT]}"; MUT_RCS[CL_NEXT]=$?
    CL_NEXT=$((CL_NEXT + 1))
  fi
  run_mutant "$CL_I" &
  MUT_PIDS[CL_I]=$!
  CL_I=$((CL_I + 1))
done
while [[ "$CL_NEXT" -lt "$NMUT" ]]; do
  wait "${MUT_PIDS[$CL_NEXT]}"; MUT_RCS[CL_NEXT]=$?
  CL_NEXT=$((CL_NEXT + 1))
done

CL_I=0
while [[ "$CL_I" -lt "$NMUT" ]]; do
  CL_RC="${MUT_RCS[$CL_I]}"
  CL_FIRST=$(grep -m1 '✗' "$MUT_DIR/m$CL_I.log" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g; s/^ *✗ *//')
  CL_NAME="${MUT_NAMES[$CL_I]}"
  if [[ "${MUT_EXPECT[$CL_I]}" == green ]]; then
    if [[ "$CL_RC" -eq 0 ]]; then pass "control: $CL_NAME leaves the suite green"
    else fail "control: $CL_NAME leaves the suite green" "rc=$CL_RC, first failure: $CL_FIRST"; fi
  elif [[ "$CL_RC" -ne 0 ]]; then
    pass "without $CL_NAME: red — ${CL_FIRST:-rc=$CL_RC}"
  else
    fail "without $CL_NAME: the suite stayed GREEN" "this guard is claimed and not checked"
  fi
  CL_I=$((CL_I + 1))
done
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL PASSED${NC} ($TESTS_PASSED/$TESTS_RUN)"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
exit "$TESTS_FAILED"
