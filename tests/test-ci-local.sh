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
# pull_request_target workflow, workflow-level defaults; later fixtures add
# secrets, unusual job ids, compound job-level if:, mixed triggers and gates
# that are actions. Those lanes run on every hosted push and could not run
# here; the suite asserts they come back UNPROVEN (summary PARTIAL, JSON
# `unproven`, exit 2 under --strict) and never as passed. The last suite
# removes each guard from a copy of ci-local.py and requires this suite to go
# red; an anchor that no longer matches is a failure.
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
# And zero jobs is not a pass. The verdict read "pass" here when it was first
# added, and /green reads "pass" as green.
assert_contains "$OUT" "ci-local: NOTHING RAN: 0/0" "the summary line says NOTHING RAN"
VERDICT=$(python3 "$RUNNER" --repo "$FAKE" --job "Mac Only" --json 2>/dev/null \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['verdict'])" 2>/dev/null)
assert_eq "$VERDICT" "none" "the JSON verdict is none, not pass, when no job ran"
run_it --job "Mac Only" --strict >/dev/null; RC=$?
assert_eq "$RC" "2" "--strict exits 2 when nothing ran"

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

# ─── 8. Lanes that read as reasoned, or as nothing ───────────────────
# Each job here was reported as a REASONED skip, or not reported at all, by an
# earlier version of this runner, while the hosted push/PR run executes it:
#   - a secret or GitHub context inherited from workflow or job env made every
#     step a "needs a repository secret" skip, and the run read pass; the next
#     version ran such a step with the secret unset, which lets aws, gh, npm
#     or docker fall back to this machine's own credentials. A secret, own or
#     inherited, now keeps its step from running, and the lane is unproven;
#   - a job-level if: on a push/PR condition read as a schedule tier;
#   - GitHub's own starter template puts step dashes level with `steps:`, so no
#     step parsed and the job read as setup-only;
#   - a reusable workflow and a flow-style steps: list read as setup-only;
#   - an env block scalar reached the step as the indicator `>-`.
# Plus the shapes that must keep running: an if: always() job, `env: # note`,
# a github-script `with: script: |`, and `defaults: run: shell: bash`.
EDGES="$SANDBOX/edges"
mkdir -p "$EDGES/.github/workflows"
cat > "$EDGES/.github/workflows/edges.yml" <<'YAML'
name: Edges
on:
  push:
  pull_request:

jobs:
  job_secret:
    name: Job Secret
    runs-on: ubuntu-latest
    env:
      CI_LOCAL_T_COV: ${{ secrets.CODECOV_TOKEN }}
    steps:
      - name: Upload coverage
        run: touch .job-secret-ran
      - name: Overrides it with a literal
        env:
          CI_LOCAL_T_COV: local
        run: |
          test "$CI_LOCAL_T_COV" = local
          touch .job-secret-override-ran

  step_secret:
    name: Step Secret
    runs-on: ubuntu-latest
    steps:
      - name: Own secret
        env:
          CI_LOCAL_T_KEY: ${{ secrets.DEPLOY_KEY }}
        run: touch .own-secret-ran
      - name: Secret in run
        run: touch .run-secret-ran  # ${{ secrets.DEPLOY_KEY }}
      - name: Indexed secret
        env:
          CI_LOCAL_T_IDX: ${{ secrets['NPM_TOKEN'] }}
        run: touch .idx-secret-ran
      - name: All secrets
        env:
          CI_LOCAL_T_ALL: ${{ toJSON(secrets) }}
        run: touch .all-secrets-ran
      - name: Indexed token
        env:
          CI_LOCAL_T_GHI: ${{ github['token'] }}
        run: touch .idx-token-ran
      - name: After the secrets
        run: touch .after-secret-ran

  run_expr:
    name: Run Expression
    runs-on: ubuntu-latest
    steps:
      - name: Print SHA
        run: echo ${{ github.sha }} && touch .sha-ran
      - name: After SHA
        run: touch .after-sha-ran

  runner_var:
    name: Runner Variable
    runs-on: ${{ vars.CI_RUNNER || 'windows-latest' }}
    steps:
      - name: On whatever runner
        run: touch .runner-var-ran

  pr_services:
    name: PR Services
    if: github.event.pull_request.draft == false
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
    steps:
      - name: Needs postgres
        run: touch .pr-services-ran

  pr_only:
    name: PR Only
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - name: Only on a PR
        run: touch .pr-only-ran

  always_job:
    name: Always Job
    if: always()
    runs-on: ubuntu-latest
    steps:
      - name: Runs whatever happened
        run: touch .always-job-ran

  on_failure:
    name: On Failure
    if: ${{ failure() }}
    runs-on: ubuntu-latest
    steps:
      - name: Only after a failure
        run: touch .on-failure-ran

  block_env:
    name: Block Scalar Env
    runs-on: ubuntu-latest
    env:
      CI_LOCAL_T_OPTS: >-
        --flag-a
        --flag-b
    steps:
      - name: Reads the folded value
        run: touch .block-env-ran

  env_comment:
    name: Env Comment
    runs-on: ubuntu-latest
    env: # shared settings
      CI_LOCAL_T_C: c
    steps:
      - name: Env under a commented key
        run: |
          test "$CI_LOCAL_T_C" = c
          touch .env-comment-ran

  script_action:
    name: Script Action
    runs-on: ubuntu-latest
    steps:
      - uses: actions/github-script@v7
        with:
          script: |
            core.info('not an env value')
      - name: After the script
        run: touch .script-action-ran

  reusable:
    name: Reusable
    uses: ./.github/workflows/called.yml

  flow_steps:
    name: Flow Steps
    runs-on: ubuntu-latest
    steps: [{name: Flow, run: touch .flow-ran}]

  job_defaults:
    name: Job Defaults
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: app
    steps:
      - name: In app/
        run: touch .job-defaults-ran
YAML
cat > "$EDGES/.github/workflows/inherit.yml" <<'YAML'
name: Inherit
on:
  push:
  pull_request:

env:
  CI_LOCAL_T_REPO: ${{ github.repository }}

jobs:
  wf_expr:
    name: Workflow Expression
    runs-on: ubuntu-latest
    steps:
      - name: Runs without it
        run: |
          test -z "${CI_LOCAL_T_REPO+set}"
          touch .wf-expr-ran

  job_expr:
    name: Job Expression
    runs-on: ubuntu-latest
    env:
      CI_LOCAL_T_JOBX: ${{ vars.SOMETHING }}
    steps:
      - name: Runs without the job value
        run: |
          test -z "${CI_LOCAL_T_JOBX+set}"
          touch .job-expr-ran
YAML
# A workflow-level token: run with it unset, `gh` would use this machine's
# own `gh auth` login. The step must not run at all.
cat > "$EDGES/.github/workflows/token.yml" <<'YAML'
name: Token
on: [push, pull_request]

env:
  CI_LOCAL_T_GH: ${{ github.token }}

jobs:
  wf_token:
    name: Workflow Token
    runs-on: ubuntu-latest
    steps:
      - name: Would fall back to gh auth
        run: touch .wf-token-ran
YAML
cat > "$EDGES/.github/workflows/shell.yml" <<'YAML'
name: Shell
on: [push]

defaults:
  run:
    shell: bash   # what this runner does anyway

jobs:
  bash_defaults:
    name: Bash Defaults
    runs-on: ubuntu-latest
    steps:
      - name: Plain bash
        run: touch .bash-defaults-ran
YAML
# GitHub's own starter template (python-app.yml): step dashes level with steps:.
cat > "$EDGES/.github/workflows/starter.yml" <<'YAML'
name: Python application

on:
  push:
    branches: [ "main" ]
  pull_request:
    branches: [ "main" ]

permissions:
  contents: read

jobs:
  build:

    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v4
    - name: Test with pytest
      env:
        CI_LOCAL_T_STARTER: s
      run: |
        test "$CI_LOCAL_T_STARTER" = s
        touch .starter-ran
YAML

edges() { python3 "$RUNNER" --repo "$EDGES" "$@" 2>&1; }
edge_ran() { [[ -e "$EDGES/.$1-ran" ]]; }

section "a secret never runs here, an inherited expression runs unset, a push/PR if: is unproven"
OUT="$(edges --list)"
eafter() { grep -A2 -F -- "$1" <<< "$OUT"; }
assert_contains "$(eafter '] Job Secret')" "UNPROVEN step Upload coverage: needs a repository secret (CI_LOCAL_T_COV)" \
  "a job-level secret keeps its step from running, and that lane is UNPROVEN"
assert_contains "$(eafter '] Job Secret')" "1/2 runnable" "a step overriding the inherited secret with a literal still runs"
assert_contains "$(eafter '] Step Secret')" "UNPROVEN step Own secret: needs a repository secret (CI_LOCAL_T_KEY)" \
  "a step-level secret is UNPROVEN, not a reasoned skip"
assert_contains "$(eafter '] Step Secret')" "UNPROVEN step Secret in run: needs a repository secret (in run:)" \
  "a secret used in run: is UNPROVEN too"
assert_contains "$(grep -A5 -F -- '] Step Secret' <<< "$OUT")" "UNPROVEN step Indexed secret: needs a repository secret (CI_LOCAL_T_IDX)" \
  "the index form secrets['X'] is a secret too, not GitHub context run unset"
assert_contains "$(grep -A5 -F -- '] Step Secret' <<< "$OUT")" "UNPROVEN step All secrets: needs a repository secret (CI_LOCAL_T_ALL)" \
  "toJSON(secrets) is a secret too"
assert_contains "$(grep -A5 -F -- '] Step Secret' <<< "$OUT")" "UNPROVEN step Indexed token: needs a repository secret (CI_LOCAL_T_GHI)" \
  "github['token'] is the token, like github.token"
assert_contains "$(eafter '] Workflow Token')" "UNPROVEN — every step skipped — needs a repository secret (CI_LOCAL_T_GH)" \
  "a workflow-level github.token keeps every step from running: that job is UNPROVEN"
assert_contains "$(eafter '] Workflow Expression')" "UNPROVEN step Runs without it: runs without CI_LOCAL_T_REPO" \
  "a workflow-level non-secret expression runs unset, unproven"
assert_contains "$(eafter '] Job Expression')" "runs without CI_LOCAL_T_JOBX, CI_LOCAL_T_REPO" \
  "a job-level non-secret expression runs unset, unproven"
assert_contains "$(eafter '] Run Expression')" "UNPROVEN step Print SHA: uses a GitHub expression" \
  "a \${{ }} in run: is UNPROVEN, not run and not reasoned"
assert_contains "$(eafter '] Runner Variable')" "UNPROVEN — runs-on is an expression" \
  "an expression runs-on with no strategy: is UNPROVEN, not a platform skip"
assert_contains "$(eafter '] PR Services')" "UNPROVEN — uses services" \
  "a services job with a PR condition is UNPROVEN, not a conditional tier"
assert_contains "$(eafter '] PR Only')" "UNPROVEN — job-level if:" \
  "a job gated on pull_request is UNPROVEN, not a conditional tier"
assert_contains "$(eafter '] On Failure')" "is false on a passing run" "a job-level failure() is a reasoned skip"
assert_lacks "$(eafter '] On Failure')" "UNPROVEN" "and not an unproven lane"
assert_contains "$OUT" "[run ] Always Job" "a job-level if: always() runs"
assert_contains "$(eafter '] Block Scalar Env')" "UNPROVEN — uses a job-level env block scalar" \
  "an env block scalar is UNPROVEN, not the literal indicator"
assert_contains "$OUT" "[run ] Env Comment" "env: # comment is still a plain mapping"
assert_contains "$OUT" "[run ] Script Action" "a github-script with: script: | is not an env block scalar"
assert_contains "$(eafter '] Reusable')" "UNPROVEN — uses a reusable workflow" \
  "a reusable workflow is UNPROVEN, not a setup-only job"
assert_contains "$(eafter '] Flow Steps')" "UNPROVEN — uses a steps: block it could not parse" \
  "a steps: block that parses to nothing is UNPROVEN, not a setup-only job"
assert_contains "$(eafter '] Job Defaults')" "UNPROVEN — uses defaults" "a job-level working-directory default is UNPROVEN"
assert_contains "$OUT" "[run ] Bash Defaults" "defaults: run: shell: bash alone is modelled, not unproven"
assert_contains "$(eafter '] build')" "1/1 runnable" "the GitHub starter template's step parses"

section "the edges run: PARTIAL with each lane named, the right steps executed"
rm -f "$EDGES"/.*-ran
# A value the developer's shell exports must not stand in for one the hosted run sets.
OUT="$(CI_LOCAL_T_REPO=from-the-shell CI_LOCAL_T_JOBX=from-the-shell edges)"; RC=$?
assert_eq "$RC" "0" "nothing failed: an inherited expression was unset, not left as its literal"
assert_contains "$OUT" "ci-local: PARTIAL: 10/10 job(s) passed" "the summary is PARTIAL over the 10 jobs that ran"
assert_contains "$OUT" "18 lane(s) unproven: Job Secret › Upload coverage, Step Secret › Own secret, Step Secret › Secret in run, Step Secret › Indexed secret, Step Secret › All secrets, Step Secret › Indexed token, Run Expression › Print SHA, Runner Variable, PR Services, PR Only, Block Scalar Env, Script Action › actions/github-script@v7, Reusable, Flow Steps, Job Defaults, Workflow Expression › Runs without it, Job Expression › Runs without the job value, Workflow Token" \
  "and names all eighteen unproven lanes on that line"
for m in wf-expr job-expr job-secret-override after-secret after-sha always-job env-comment script-action \
         bash-defaults starter; do
  if edge_ran "$m"; then pass "the .$m-ran step executed"; else fail "the .$m-ran step executed" "marker missing"; fi
done
# The secret steps above all: run with the variable unset, each would have
# reached this machine's own credentials.
for m in job-secret own-secret run-secret idx-secret all-secrets idx-token wf-token sha runner-var pr-services pr-only on-failure block-env \
         flow job-defaults; do
  if edge_ran "$m"; then fail "the .$m-ran lane was not executed here" "it executed"; else pass "the .$m-ran lane was not executed here"; fi
done
JSON="$(CI_LOCAL_T_REPO=from-the-shell python3 "$RUNNER" --repo "$EDGES" --json --strict 2>/dev/null)"; RC=$?
assert_eq "$RC" "2" "--strict exits 2 on the edges run"
CHECK=$(python3 - "$JSON" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
problems = []
if d.get("verdict") != "partial":
    problems.append(f"verdict={d.get('verdict')!r}")
got = sorted(f"{u['job']}|{u['step']}" for u in d.get("unproven", []))
want = sorted(["Job Secret|Upload coverage", "Step Secret|Own secret", "Step Secret|Secret in run",
               "Step Secret|Indexed secret", "Step Secret|All secrets", "Step Secret|Indexed token",
               "Run Expression|Print SHA", "Runner Variable|", "PR Services|", "PR Only|",
               "Block Scalar Env|", "Script Action|actions/github-script@v7", "Reusable|",
               "Flow Steps|", "Job Defaults|", "Workflow Expression|Runs without it",
               "Job Expression|Runs without the job value", "Workflow Token|"])
if got != want:
    problems.append(f"unproven={got}")
if sorted(d.get("partial", [])) != ["Job Expression", "Job Secret", "Run Expression", "Script Action",
                                    "Step Secret", "Workflow Expression"]:
    problems.append(f"partial={d.get('partial')}")
want_passed = ["Always Job", "Bash Defaults", "Env Comment", "Job Expression", "Job Secret",
               "Run Expression", "Script Action", "Step Secret", "Workflow Expression", "build"]
if sorted(d.get("passed", [])) != want_passed:
    problems.append(f"passed={d.get('passed')}")
skipped = {s["job"]: s.get("unproven") for s in d.get("skipped", [])}
if skipped != {"Runner Variable": True, "PR Services": True, "PR Only": True, "On Failure": False,
               "Block Scalar Env": True, "Reusable": True, "Flow Steps": True, "Job Defaults": True,
               "Workflow Token": True}:
    problems.append(f"skipped={skipped}")
print("; ".join(problems) or "ok")
PY
)
assert_eq "$CHECK" "ok" "verdict, unproven, partial, passed and skipped are exact"
OUT="$(edges --all --job "Always Job")"
assert_lacks "$OUT" "normally-skipped" "--all does not announce an if: always() job as normally skipped"

# A step that fails because it ran without inherited env says so: that may be
# the whole cause, and a fixer must not chase it in the code.
NOTE="$SANDBOX/note"; mkdir -p "$NOTE/.github/workflows"
cat > "$NOTE/.github/workflows/note.yml" <<'YAML'
name: Note
on: [push]
env:
  CI_LOCAL_T_NEEDED: ${{ vars.NEEDED }}
jobs:
  needs_it:
    name: Needs It
    runs-on: ubuntu-latest
    steps:
      - name: Reads the inherited variable
        run: test -n "${CI_LOCAL_T_NEEDED:-}"
YAML
OUT="$(python3 "$RUNNER" --repo "$NOTE" 2>&1)"; RC=$?
assert_eq "$RC" "1" "a step that needs the env it ran without fails, as before"
assert_contains "$OUT" "note: runs without CI_LOCAL_T_NEEDED" "the failure names the env it ran without"
REASON=$(python3 "$RUNNER" --repo "$NOTE" --json 2>/dev/null \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['failed'][0].get('reason', ''))" 2>/dev/null)
assert_contains "$REASON" "runs without CI_LOCAL_T_NEEDED" "and so does the JSON failed[].reason"

# ─── 8b. Job discovery: a lane never vanishes or merges ─────────────
# Every line at the jobs: indent is a job. A lowercase-only header regex read
# `Upper_Case:`, `_private:` and `commented:  # note` as nothing, and their
# keys landed on the job above: its name overwritten, its steps merged.
JOBS="$SANDBOX/jobs"; mkdir -p "$JOBS/.github/workflows"
cat > "$JOBS/.github/workflows/jobs.yml" <<'YAML'
name: Jobs
on: [push, pull_request]

jobs:
  first:
    name: First
    runs-on: ubuntu-latest
    steps:
      - run: touch .first-ran
  commented:  # a trailing comment after the id is legal YAML
    name: Commented
    runs-on: ubuntu-latest
    steps:
      - run: touch .commented-ran
  Upper_Case:
    name: Upper Case
    runs-on: ubuntu-latest
    steps:
      - run: touch .upper-ran
  _private:
    runs-on: ubuntu-latest
    steps:
      - run: touch .private-ran
  "quoted-id":
    runs-on: ubuntu-latest
    steps:
      - run: touch .quoted-ran
  deep_keys:
      name: Deep Keys
      runs-on: ubuntu-latest
      steps:
        - run: touch .deep-ran
  flow_job: {runs-on: ubuntu-latest, steps: [{run: touch .flow-job-ran}]}
YAML
cat > "$JOBS/.github/workflows/wide.yml" <<'YAML'
name: Wide
on: [push]
jobs:
    wide:
        name: Wide Indent
        runs-on: ubuntu-latest
        steps:
            - run: touch .wide-ran
YAML
jobs_ci() { python3 "$RUNNER" --repo "$JOBS" "$@" 2>&1; }
job_ran() { [[ -e "$JOBS/.$1-ran" ]]; }

section "every job is discovered: legal ids run, unreadable ones are UNPROVEN"
OUT="$(jobs_ci --list)"
jafter() { grep -A1 -F -- "$1" <<< "$OUT"; }
LISTED=$(grep -cE '^  \[(run |skip)\] ' <<< "$OUT" || true)
assert_eq "$LISTED" "8" "all 8 jobs are listed, none merged into its neighbour"
assert_contains "$OUT" "[run ] First " "the job above an unusual id keeps its own name"
assert_contains "$(jafter '] First ')" "1/1 runnable" "and only its own step"
assert_contains "$OUT" "[run ] Commented " "a job id with a trailing comment is a job"
assert_contains "$OUT" "[run ] Upper Case " "a job id starting with an uppercase letter is a job"
assert_contains "$OUT" "[run ] _private " "a job id starting with _ is a job"
assert_contains "$OUT" "[run ] quoted-id " "a quoted job id is a job"
assert_contains "$(jafter '] deep_keys')" "UNPROVEN — uses a job body it could not read" \
  "a job whose keys sit at another indent is UNPROVEN, not setup-only"
assert_contains "$(jafter '] flow_job')" "a job written on its key line" \
  "a flow-style job is UNPROVEN, naming why"
assert_contains "$(jafter '] wide')" "a jobs: block indented 4 spaces" \
  "jobs indented four spaces are listed, UNPROVEN, not dropped"
rm -f "$JOBS"/.*-ran
OUT="$(jobs_ci)"
assert_contains "$OUT" "ci-local: PARTIAL: 5/5 job(s) passed" "the five readable jobs ran"
assert_contains "$OUT" "3 lane(s) unproven: deep_keys, flow_job, wide" "and the three unreadable ones are named"
for m in first commented upper private quoted; do
  if job_ran "$m"; then pass "the .$m-ran job executed"; else fail "the .$m-ran job executed" "marker missing"; fi
done
for m in deep flow-job wide; do
  if job_ran "$m"; then fail "the .$m-ran job was not executed here" "it executed"; else pass "the .$m-ran job was not executed here"; fi
done

# ─── 8c. Compound job-level if: ─────────────────────────────────────
# Reasoned only when false on every push AND pull_request. A combinator that
# breaks turns a lane the PR run executes into a "conditional" skip.
CONDS="$SANDBOX/conds"; mkdir -p "$CONDS/.github/workflows"
{
  echo "name: Conditions"
  echo "on: [push, pull_request]"
  echo "jobs:"
  n=0
  while IFS='|' read -r cname cif; do
    n=$((n + 1))
    printf '  c%s:\n    name: %s\n    if: %s\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo c%s\n' \
      "$n" "$cname" "$cif" "$n"
  done <<'CONDS'
Schedule Or PR|github.event_name == 'schedule' || github.event_name == 'pull_request'
Schedule Or Dispatch|github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
Schedule And Main|github.event_name == 'schedule' && github.ref == 'refs/heads/main'
PR And Main|github.event_name == 'pull_request' && github.ref == 'refs/heads/main'
Grouped Off|${{ (github.event_name == 'schedule' || github.event_name == 'workflow_dispatch') && github.repository == 'o/r' }}
Precedence|github.event_name == 'schedule' && github.ref == 'refs/heads/main' || github.event_name == 'pull_request'
Quoted Operator|github.event_name == 'schedule' && github.head_ref != 'a || b'
Negated Schedule|${{ !(github.event_name == 'schedule') }}
CONDS
} > "$CONDS/.github/workflows/conds.yml"

section "compound job-level if: — || and && over event_name, grouped, quoted, negated"
OUT="$(python3 "$RUNNER" --repo "$CONDS" --list 2>&1)"
cafter() { grep -A1 -F -- "] $1 " <<< "$OUT"; }
assert_contains "$(cafter 'Schedule Or PR')" "UNPROVEN — job-level if:" \
  "schedule || pull_request runs on PRs: UNPROVEN, not a conditional tier"
assert_contains "$(cafter 'Schedule Or Dispatch')" "conditional" "schedule || workflow_dispatch is a reasoned tier"
assert_contains "$(cafter 'Schedule And Main')" "conditional" "schedule && anything is a reasoned tier"
assert_contains "$(cafter 'PR And Main')" "UNPROVEN — job-level if:" "pull_request && an unknown is UNPROVEN"
assert_contains "$(cafter 'Grouped Off')" "conditional" "(schedule || dispatch) && anything is a reasoned tier"
assert_contains "$(cafter 'Precedence')" "UNPROVEN — job-level if:" \
  "&& binds tighter than ||: schedule && x || pull_request runs on PRs"
assert_contains "$(cafter 'Quoted Operator')" "conditional" "a || inside a quoted string is not an operator"
assert_contains "$(cafter 'Negated Schedule')" "UNPROVEN — job-level if:" "!(schedule) runs on push: UNPROVEN"

# ─── 8d. pull_request_target is GitHub-side only without push/PR ────
# A substring test over the raw on: block, comments included, ran a
# pull_request_target job here when a comment said `pull_request:`, and
# skipped a workflow that ALSO runs on push.
TRIG="$SANDBOX/trig"; mkdir -p "$TRIG/.github/workflows"
cat > "$TRIG/.github/workflows/both.yml" <<'YAML'
name: Both
on:
  push:
  pull_request_target:   # labels fork PRs as well
jobs:
  both:
    name: Push And Target
    runs-on: ubuntu-latest
    steps:
      - run: touch .both-ran
YAML
cat > "$TRIG/.github/workflows/target.yml" <<'YAML'
name: Target
on:
# pull_request: retired when fork PRs needed write scopes
  pull_request_target:   # was pull_request: before
    types: [opened]
jobs:
  target:
    name: Target Only
    runs-on: ubuntu-latest
    steps:
      - run: touch .target-ran
YAML
cat > "$TRIG/.github/workflows/flow.yml" <<'YAML'
name: Flow
on: [pull_request_target, issues]
jobs:
  flow:
    name: Flow Target
    runs-on: ubuntu-latest
    steps:
      - run: touch .flow-target-ran
YAML
cat > "$TRIG/.github/workflows/quoted.yml" <<'YAML'
name: Quoted
"on": pull_request_target
"jobs":
  quoted:
    name: Quoted Target
    runs-on: ubuntu-latest
    steps:
      - run: touch .quoted-target-ran
YAML
section "pull_request_target: GitHub-side only when no push/pull_request triggers it"
rm -f "$TRIG"/.*-ran
OUT="$(python3 "$RUNNER" --repo "$TRIG" 2>&1)"
assert_contains "$OUT" "ci-local: 1/1 job(s) passed" "only the workflow that also runs on push ran"
for j in "Target Only" "Flow Target" "Quoted Target"; do
  assert_contains "$OUT" "skipped $j: runs on GitHub's side only" "$j is GitHub-side only"
done
if [[ -e "$TRIG/.both-ran" ]]; then pass "push + pull_request_target runs here: the push run executes it"
else fail "push + pull_request_target runs here: the push run executes it" "marker missing"; fi
for m in target flow-target quoted-target; do
  if [[ -e "$TRIG/.$m-ran" ]]; then fail "the .$m-ran job did not run here" "it executed"
  else pass "the .$m-ran job did not run here"; fi
done

# ─── 8e. Gates that are actions are UNPROVEN ────────────────────────
# A job whose only gate is an action — a lint action, a local composite —
# read as a setup-only skip, so a run of it plus one other job read pass.
ACTS="$SANDBOX/acts"; mkdir -p "$ACTS/.github/workflows"
cat > "$ACTS/.github/workflows/acts.yml" <<'YAML'
name: Actions
on: [push, pull_request]
jobs:
  lint:
    name: Lint Action
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: golangci/golangci-lint-action@v6   # pinned upstream
        with:
          version: latest
  composite:
    name: Local Composite
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run the suite
        uses: ./.github/actions/test
  mixed:
    name: Setup Then Action
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4   # v4.3.1
      - uses: actions/setup-node@v4
      - uses: pnpm/action-setup@v4
      - run: touch .mixed-install-ran
      - name: Lint
        uses: super-linter/super-linter@v7
  setup_only:
    name: Setup Only
    runs-on: ubuntu-latest
    steps:
      - uses: 'actions/checkout@v4'
      - uses: actions/cache@v4
        with:
          path: x
  notify:
    name: Failure Notice
    runs-on: ubuntu-latest
    steps:
      - run: touch .notify-job-ran
      - name: Notify
        if: failure()
        uses: some/notify-action@v1
YAML
section "a gate that is an action is UNPROVEN; setup actions are not gates"
OUT="$(python3 "$RUNNER" --repo "$ACTS" --list 2>&1)"
aafter() { grep -A1 -F -- "] $1 " <<< "$OUT"; }
assert_contains "$(aafter 'Lint Action')" \
  "UNPROVEN — its gates are actions, which this runner does not execute: golangci/golangci-lint-action@v6" \
  "a job whose only gate is a lint action is UNPROVEN, not setup-only"
assert_contains "$(aafter 'Local Composite')" "UNPROVEN — its gates are actions" \
  "a local composite action is a gate, not setup"
assert_contains "$(aafter 'Setup Then Action')" "UNPROVEN step Lint: action super-linter/super-linter@v7" \
  "an action gate in a job that also runs is an UNPROVEN step"
assert_contains "$(aafter 'Setup Only')" "no run: steps (setup-only job)" \
  "checkout and cache alone are setup, a reasoned skip"
assert_lacks "$(aafter 'Setup Only')" "UNPROVEN" "and not an unproven lane"
assert_lacks "$(aafter 'Failure Notice')" "UNPROVEN" "an action under if: failure() is off the success path"
rm -f "$ACTS"/.*-ran
JSON="$(python3 "$RUNNER" --repo "$ACTS" --json 2>/dev/null)"
CHECK=$(python3 - "$JSON" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
problems = []
if d.get("verdict") != "partial":
    problems.append(f"verdict={d.get('verdict')!r}")
got = sorted(f"{u['job']}|{u['step']}" for u in d.get("unproven", []))
if got != ["Lint Action|", "Local Composite|", "Setup Then Action|Lint"]:
    problems.append(f"unproven={got}")
if sorted(d.get("passed", [])) != ["Failure Notice", "Setup Then Action"]:
    problems.append(f"passed={d.get('passed')}")
skipped = {s["job"]: s.get("unproven") for s in d.get("skipped", [])}
if skipped != {"Lint Action": True, "Local Composite": True, "Setup Only": False}:
    problems.append(f"skipped={skipped}")
print("; ".join(problems) or "ok")
PY
)
assert_eq "$CHECK" "ok" "verdict, unproven, passed and skipped are exact for action gates"
python3 "$RUNNER" --repo "$ACTS" --job "Lint Action" --strict >/dev/null 2>&1; RC=$?
assert_eq "$RC" "2" "a run of only an action-gated job is not green under --strict"

# ─── 9. Mutations: removing each guard turns this suite red ──────────
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
  '    triggers = workflow_triggers(on_block)
' '    if job.unmodelled:
        what = ", ".join(sorted(set(job.unmodelled)))
        return Skip(f"uses {what}, which this runner does not model — run it hosted, "
                    "or split the job", unproven=True)
    triggers = workflow_triggers(on_block)
'
mutation red "unproven on an unmodelled job (services:)" \
  '"or split the job", unproven=True)' '"or split the job")'
mutation red "an unevaluable step if: being unproven" \
  'return _SUCCESS_PATH_IF.get(re.sub(r"\s+", "", _unwrap(condition)))' \
  'return _SUCCESS_PATH_IF.get(re.sub(r"\s+", "", _unwrap(condition)), True)'
mutation red "failure() staying off the success path" '"failure()": False,' '"failure()": True,'
mutation red "always() running on the success path" \
  '"success()": True, "always()": True,' '"success()": True, "always()": False,'
mutation red "the --strict exit 2" \
  'exit_code = 1 if failed else (2 if verdict != "pass" and args.strict else 0)' 'exit_code = 1 if failed else 0'
mutation red "telling a secret from other GitHub context" \
  '_SECRET_REF = re.compile(r"""\bsecrets\b|' '_SECRET_REF = re.compile(r""".|'
mutation red "the index and toJSON forms of secrets being secrets" \
  '_SECRET_REF = re.compile(r"""\bsecrets\b|' '_SECRET_REF = re.compile(r"""\bsecrets\.|'
mutation red "the index form of github.token being the token" \
  "|\\[\\s*['\"]token['\"]\\s*\\])" ")"
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
  'prefix = {"partial": "PARTIAL: ", "none": "NOTHING RAN: "}' 'prefix = {"none": "NOTHING RAN: "}'
mutation red "the none verdict when no job ran" \
  '    elif not ran:
        verdict = "none"
' ''
mutation red "a workflow-level expression being inherited (run unset), not the step's own" \
  '(workflow_env.keys() | job.env.keys())' 'job.env.keys()'
mutation red "a job-level expression being inherited (run unset), not the step's own" \
  '(workflow_env.keys() | job.env.keys())' 'workflow_env.keys()'
mutation red "an inherited expression being unset, not the shell's value" \
  'env.pop(key, None)' 'pass'
mutation red "a step run without inherited env reaching the lane list" \
  'if s.unproven and s.status != "fail"]' 'if s.unproven and s.status == "skip"]'
mutation red "the failure naming the env its step ran without" \
  '                reason=plan.reason,
                command=step.run,' '                command=step.run,'
mutation red "a \${{ }} in run: being unproven" \
  'return StepPlan(False, "uses a GitHub expression that cannot be evaluated locally",
                        unproven=True)' \
  'return StepPlan(False, "uses a GitHub expression that cannot be evaluated locally")'
mutation red "an expression runs-on being unproven" \
  '"runs-on is an expression (matrix leg) — run each leg on its own machine",
                    unproven=True)' \
  '"runs-on is an expression (matrix leg) — run each leg on its own machine")'
mutation red "no platform guess from an expression runs-on" \
  'if "${{" not in job.runs_on:' 'if True:'
mutation red "a push/PR job-level if: not being a conditional tier" \
  'return "off" if _off_push_pr(_unwrap(condition)) else "unknown"' 'return "off"'
mutation red "an unevaluable job-level if: being unproven" \
  '"locally (--all runs it anyway)", unproven=True)' '"locally (--all runs it anyway)")'
mutation red "a schedule tier being off the push/PR path" \
  'not in _PUSH_PR_EVENTS' 'in _PUSH_PR_EVENTS'
mutation red "a job-level always() running" \
  'return "run" if fixed else "off"' 'return "off"'
mutation red "a job-level failure() staying off a passing run" \
  'return "run" if fixed else "off"' 'return "run"'
mutation red "--all not announcing an always() job" \
  'if j.condition and r is None and job_condition(j.condition) != "run"]' \
  'if j.condition and r is None]'
mutation red "steps whose dash sits level with steps:" \
  '_STEP_DASH = re.compile(r"^( {4,})- \S")' '_STEP_DASH = re.compile(r"^( {6,})- \S")'
mutation red "a steps: block that parsed to nothing being unproven" \
  'if job.declares_steps and not job.steps:' 'if False:'
mutation red "a reusable workflow being unproven" \
  'current.unmodelled.append(f"a reusable workflow ({_scalar(value)[:60]})")' 'pass'
mutation red "an env block scalar being unproven" \
  'return bool(_BLOCK_SCALAR.fullmatch(_scalar(value)))' 'return False'
mutation red "only a step's env: children being env" \
  'if step_block == "env":' 'if True:'
mutation red "env: # comment being a plain mapping" \
  'bare = not _scalar(value)' 'bare = not value'
mutation red "defaults: run: shell: bash alone being modelled" \
  '    pairs = []
    for ln in lines:' '    return False
    pairs = []
    for ln in lines:'
mutation red "job-level defaults being unproven" \
  'job.unmodelled.append("defaults")' 'pass'

# A secret, own or inherited, never runs: run unset, a tool falls back to
# this machine's own credentials.
mutation red "an inherited secret keeping its step from running" \
  'secrets = sorted(k for k, v in step.env.items() if _expression_kind(v) == "secret")' \
  'secrets = sorted(k for k, v in step.env.items() if k not in step.inherited and _expression_kind(v) == "secret")'
mutation red "a step's own secret being the secret class" \
  'secrets = sorted(k for k, v in step.env.items() if _expression_kind(v) == "secret")' \
  'secrets = sorted(k for k, v in step.env.items() if k in step.inherited and _expression_kind(v) == "secret")'
mutation red "a secret in run: being the secret class" \
  'secrets.append("in run:")' 'pass'
mutation red "a secret skip being unproven" \
  '"it, a tool falls back to this machine'"'"'s own credentials",
                        unproven=True)' \
  '"it, a tool falls back to this machine'"'"'s own credentials")'
# Job discovery.
mutation red "a job id starting with an uppercase letter or _" \
  '[^\s"'"'"'#][^:]*?)\s*:' '[a-z][\w-]*)\s*:'
mutation red "a trailing comment after a job id" \
  '\s*:(?:\s(.*))?""")' '\s*:()""")'
mutation red "a quoted job id" \
  '_JOB_HEADER = re.compile(r"""("[^"]*"|'"'"'[^'"'"']*'"'"'|' '_JOB_HEADER = re.compile(r"""('
mutation red "a job written on its key line being flagged" \
  '            if rest:
                # `build:' '            if False:
                # `build:'
mutation red "jobs at another indent being flagged" \
  'current.unmodelled.append(f"a jobs: block indented {job_indent} spaces")' 'pass'
mutation red "a job body with no runs-on: being unproven" \
  'if not job.keys & {"runs-on", "uses"}:' 'if False:'
mutation red "a quoted top-level key (\"jobs\":)" \
  'section = raw.split(":", 1)[0].strip().strip("'"'"'\"")' 'section = raw.split(":", 1)[0].strip()'
# Compound job-level if:.
mutation red "|| being false only when every side is" \
  'return all(_off_push_pr(d) for d in disjuncts)' 'return any(_off_push_pr(d) for d in disjuncts)'
mutation red "&& being false when any side is" \
  'return any(_off_push_pr(c) for c in conjuncts)' 'return all(_off_push_pr(c) for c in conjuncts)'
mutation red "&& binding tighter than ||" \
  '    disjuncts = _split_top(e, "||")
    if len(disjuncts) > 1:
        return all(_off_push_pr(d) for d in disjuncts)
    conjuncts = _split_top(e, "&&")
    if len(conjuncts) > 1:
        return any(_off_push_pr(c) for c in conjuncts)' \
  '    conjuncts = _split_top(e, "&&")
    if len(conjuncts) > 1:
        return any(_off_push_pr(c) for c in conjuncts)
    disjuncts = _split_top(e, "||")
    if len(disjuncts) > 1:
        return all(_off_push_pr(d) for d in disjuncts)'
mutation red "an operator inside a quoted string not being one" \
  'quoted = not quoted          # '"''"' inside a string toggles twice' 'pass'
mutation red "grouping parentheses being stripped" \
  'while e.startswith("(") and e.endswith(")"):' 'while False:'
mutation red "a negated event test not reading as one" \
  'm = _EVENT_EQ.fullmatch(e)' 'm = _EVENT_EQ.search(e)'
# pull_request_target triggers.
mutation red "a push trigger beside pull_request_target keeping the workflow local" \
  'if "pull_request_target" in triggers and not triggers & _PUSH_PR_EVENTS:' \
  'if "pull_request_target" in triggers:'
mutation red "comments stripped from the on: block" \
  'lines = [re.sub(r"(^|\s)#.*$", "", ln).rstrip() for ln in on_block.splitlines()]' \
  'lines = [ln.rstrip() for ln in on_block.splitlines()]'
mutation red "a column-0 comment not ending the on: block" \
  'if lines[i] and not lines[i][0].isspace() and not lines[i].startswith("#")),' \
  'if lines[i] and not lines[i][0].isspace()),'
mutation red "flow-style triggers" \
  'return set(_flow_names(head))' 'return {head}'
mutation red "a quoted on: key" \
  '_ON_KEY = re.compile(r"""^(on|"on"|'"'"'on'"'"')\s*:""")' '_ON_KEY = re.compile(r"^on\s*:")'
# Gates that are actions.
mutation red "a gate action being unproven" \
  ': this runner executes only run: steps",
                        unproven=True)' ': this runner executes only run: steps")'
mutation red "a job whose gates are actions being unproven" \
  '+ ", ".join(actions)[:120], unproven=True)' '+ ", ".join(actions)[:120])'
mutation red "only setup actions being setup" \
  'return any(p.startswith("setup-") or p == "action-setup" for p in parts[1:])' 'return True'
mutation red "checkout, cache and artifacts being setup" \
  '_SETUP_ACTIONS = frozenset({"checkout", "cache", "upload-artifact", "download-artifact"})' \
  '_SETUP_ACTIONS: frozenset[str] = frozenset()'
mutation red "a local composite never being a setup action" \
  'return False      # ./local composite' 'return True      # ./local composite'
mutation red "an action off the success path being reasoned" \
  'if step.condition and success_path_if(step.condition) is False:
            return StepPlan(False, f"if: {_scalar(step.condition)[:60]} is false on the success path")' \
  'if False:
            pass'
mutation red "uses: read as a YAML scalar" \
  'step.uses = _scalar(value)' 'step.uses = value'

# A shared host and a 4-core hosted runner both run this: at most 4 at once.
CL_JOBS=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)
[[ "$CL_JOBS" =~ ^[0-9]+$ && "$CL_JOBS" -ge 1 ]] || CL_JOBS=2
[[ "$CL_JOBS" -gt 4 ]] && CL_JOBS=4
# A mutant that hangs or is starved on a loaded host must not pass for red:
# only a run that printed a ✗ counts. 300 s is far past a red mutant's ~10 s.
run_mutant() {
  if command -v timeout >/dev/null 2>&1; then
    CI_LOCAL_RUNNER="$MUT_DIR/m$1.py" CI_LOCAL_MUTANT=1 timeout 300 \
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
  # The escape byte via printf: BSD sed reads `\x1b` as a literal x1b.
  CL_FIRST=$(grep -m1 '✗' "$MUT_DIR/m$CL_I.log" 2>/dev/null \
    | sed "s/$(printf '\033')\[[0-9;]*m//g; s/^ *✗ *//")
  CL_NAME="${MUT_NAMES[$CL_I]}"
  if [[ "${MUT_EXPECT[$CL_I]}" == green ]]; then
    if [[ "$CL_RC" -eq 0 ]]; then pass "control: $CL_NAME leaves the suite green"
    else fail "control: $CL_NAME leaves the suite green" "rc=$CL_RC, first failure: $CL_FIRST"; fi
  elif [[ "$CL_RC" -eq 124 || -z "$CL_FIRST" ]] && [[ "$CL_RC" -ne 0 ]]; then
    fail "without $CL_NAME: inconclusive" "rc=$CL_RC with no failed assertion (timed out or crashed)"
  elif [[ "$CL_RC" -ne 0 ]]; then
    pass "without $CL_NAME: red — $CL_FIRST"
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
