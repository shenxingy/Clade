#!/usr/bin/env bash
# ci-local-flaky.sh — the rerun and FLAKY cases of tests/test-ci-local.sh.
#
# Sourced by that suite, never run on its own: it uses the suite's helpers
# (pass, fail, assert_*, section), its $RUNNER and $SANDBOX, and — for
# ci_local_flaky_mutations, called from the suite's mutation table — its
# `mutation` function. Split out because test-ci-local.sh sits at the edge of
# the 1500-line cap; the fixtures and the mutations that prove they can fire
# stay side by side here.
#
# What it pins, in ci-local.py's run_job and main:
#   - a step that exits non-zero runs once more, same command, env and cwd;
#     green the second time is FLAKY: its job is not failed, the run is not
#     green, and the steps after it still run;
#   - red again is a failure, reported with the RERUN's exit code and output
#     and the first attempt's exit code;
#   - a step that hit the step timeout is not rerun;
#   - --no-rerun makes the flake a plain failure; --strict exits 2 on FLAKY;
#   - verdict order fail > none > partial > flaky > pass, with the flaky steps
#     still listed when the run reads PARTIAL or fails.
# Each fixture step counts its own attempts in a file, so the assertions read
# how many times a step ran, not only what was printed about it.

FLAKY="$SANDBOX/flaky"; mkdir -p "$FLAKY/.github/workflows"
cat > "$FLAKY/.github/workflows/flaky.yml" <<'YAML'
name: Flaky
on: [push, pull_request]
jobs:
  flaky:
    name: Flaky Job
    runs-on: ubuntu-latest
    steps:
      - name: Passes on rerun
        run: |
          n=$(( $(cat .flaky-count 2>/dev/null || echo 0) + 1 )); echo "$n" > .flaky-count
          echo "flaky attempt $n"
          test "$n" -ge 2 || exit 4
      - name: After the flake
        run: touch .after-flake-ran
  twice:
    name: Fails Twice
    runs-on: ubuntu-latest
    steps:
      - name: Fails both times
        run: |
          n=$(( $(cat .twice-count 2>/dev/null || echo 0) + 1 )); echo "$n" > .twice-count
          echo "twice attempt $n"
          exit $((4 + n))
      - name: Never reached
        run: touch .after-twice-ran
  lane:
    name: Unproven Lane
    runs-on: ubuntu-latest
    steps:
      - name: Print SHA
        run: echo ${{ github.sha }}
      - name: Runs
        run: touch .lane-ran
YAML
# Its own repository: every other run here would wait out its sleep.
HANG="$SANDBOX/hang"; mkdir -p "$HANG/.github/workflows"
cat > "$HANG/.github/workflows/hang.yml" <<'YAML'
name: Hang
on: [push]
jobs:
  hangs:
    name: Hangs
    runs-on: ubuntu-latest
    steps:
      - name: Never returns
        run: |
          n=$(( $(cat .hang-count 2>/dev/null || echo 0) + 1 )); echo "$n" > .hang-count
          echo "hang attempt $n"
          exec sleep 30
YAML

# Every run starts from zero attempts and no markers.
flaky_reset() { rm -f "$FLAKY"/.*-count "$FLAKY"/.*-ran "$HANG"/.*-count; }
flaky_ci() { flaky_reset; python3 "$RUNNER" --repo "$FLAKY" "$@" 2>&1; }
flaky_json() { flaky_reset; python3 "$RUNNER" --repo "$FLAKY" --json "$@" 2>/dev/null; }
attempts() { cat "$1/.$2-count" 2>/dev/null || echo 0; }
# check_json JSON PYTHON — run PYTHON with `d` bound to the parsed JSON; it
# appends to `problems`. Prints "ok" or the problems.
check_json() {
  python3 - "$1" "$2" <<'PY'
import json, sys
problems = []
try:
    d = json.loads(sys.argv[1])
except ValueError as exc:
    print(f"invalid JSON: {exc}")
    sys.exit(0)
exec(sys.argv[2])
print("; ".join(problems) or "ok")
PY
}

section "a step that passes only on its rerun is FLAKY, not green"
OUT="$(flaky_ci --job "Flaky Job")"; RC=$?
assert_eq "$RC" "0" "report-only rollout: a FLAKY run exits 0 without --strict"
assert_eq "$(attempts "$FLAKY" flaky)" "2" "the failed step ran exactly twice"
assert_contains "$OUT" "ci-local: FLAKY: 1/1 job(s) passed" \
  "the summary line says FLAKY, and the job is not counted as failed"
assert_contains "$OUT" "  flaky: Flaky Job › Passes on rerun (first exit 4)" \
  "a line names the flaky step with its first exit code"
assert_contains "$OUT" "| flaky attempt 1" "the first attempt's output is shown: it is the flake's only evidence"
assert_contains "$OUT" "FLAKY is not green" "the output says what FLAKY means"
assert_lacks "$OUT" "FAILED  " "no job is reported failed"
if [[ -e "$FLAKY/.after-flake-ran" ]]; then pass "the step after a flaky step still runs"
else fail "the step after a flaky step still runs" "the .after-flake-ran marker is missing"; fi
OUT="$(flaky_ci --job "Flaky Job" --strict)"; RC=$?
assert_eq "$RC" "2" "--strict exits 2 on FLAKY"
assert_contains "$OUT" "ci-local: FLAKY:" "and it is the FLAKY verdict that made it 2"
CHECK=$(check_json "$(flaky_json --job "Flaky Job")" '
if d.get("verdict") != "flaky":
    problems.append("verdict=%r" % d.get("verdict"))
got = [(f["job"], f["step"], f["first_exit"]) for f in d.get("flaky", [])]
if got != [("Flaky Job", "Passes on rerun", 4)]:
    problems.append("flaky=%r" % got)
if "flaky attempt 1" not in "".join(f.get("first_output_tail", "") for f in d.get("flaky", [])):
    problems.append("flaky[].first_output_tail lacks the first attempt")
if d.get("failed") != [] or d.get("passed") != ["Flaky Job"] or d.get("unproven") != []:
    problems.append("failed=%r passed=%r unproven=%r" % (d.get("failed"), d.get("passed"), d.get("unproven")))
')
assert_eq "$CHECK" "ok" "JSON: verdict flaky, flaky[{job, step, first_exit}], nothing failed"

section "--no-rerun: a failed step is a failure at once"
OUT="$(flaky_ci --job "Flaky Job" --no-rerun)"; RC=$?
assert_eq "$RC" "1" "--no-rerun turns the flaky step into a failure"
assert_eq "$(attempts "$FLAKY" flaky)" "1" "and the step ran once"
assert_contains "$OUT" "FAILED  Flaky Job" "the job is reported failed"
assert_lacks "$OUT" "FLAKY" "and nothing is reported flaky"
if [[ -e "$FLAKY/.after-flake-ran" ]]; then fail "the job stops at the failed step" "the next step ran"
else pass "the job stops at the failed step"; fi

section "a step that fails twice failed, reported from its rerun"
OUT="$(flaky_ci --job "Fails Twice")"; RC=$?
assert_eq "$RC" "1" "a step red on both attempts fails the run"
assert_eq "$(attempts "$FLAKY" twice)" "2" "it was rerun once, no more"
assert_contains "$OUT" "exit 6 on rerun (first attempt exit 5)" "the rerun's exit code is reported, and the first one named"
assert_contains "$OUT" "| twice attempt 2" "the output shown is the rerun's"
assert_lacks "$OUT" "twice attempt 1" "not the first attempt's"
assert_lacks "$OUT" "FLAKY" "a step red twice is not flaky"
if [[ -e "$FLAKY/.after-twice-ran" ]]; then fail "the job stops at the step that failed twice" "the next step ran"
else pass "the job stops at the step that failed twice"; fi
CHECK=$(check_json "$(flaky_json --job "Fails Twice")" '
f = (d.get("failed") or [{}])[0]
if d.get("verdict") != "fail" or d.get("flaky") != []:
    problems.append("verdict=%r flaky=%r" % (d.get("verdict"), d.get("flaky")))
if (f.get("exit_code"), f.get("first_exit"), f.get("output_tail")) != (6, 5, "twice attempt 2"):
    problems.append("failed[0]=%r" % f)
')
assert_eq "$CHECK" "ok" "JSON: failed[].exit_code is the rerun's, first_exit the first attempt's"

section "a step that hit the step timeout is not rerun"
flaky_reset
OUT="$(python3 "$RUNNER" --repo "$HANG" --timeout 3 2>&1)"; RC=$?
assert_eq "$RC" "1" "a hung step fails the run"
assert_eq "$(attempts "$HANG" hang)" "1" "and ran once: a hang is not a flake signal"
assert_contains "$OUT" "exceeded the 3s step timeout" "the failure names the timeout"
assert_lacks "$OUT" "rerun" "and no rerun is mentioned"

section "the verdict order: fail > partial > flaky, the flaky steps always listed"
OUT="$(flaky_ci --job "Flaky Job" --job "Unproven Lane")"; RC=$?
assert_eq "$RC" "0" "PARTIAL with a flaky step exits 0 without --strict"
assert_contains "$OUT" "ci-local: PARTIAL: 2/2 job(s) passed" "an unproven lane outranks a flaky step: PARTIAL"
assert_contains "$OUT" "1 step(s) flaky" "the summary line still counts the flaky step"
assert_contains "$OUT" "  flaky: Flaky Job › Passes on rerun (first exit 4)" "and the flaky line still names it"
flaky_ci --job "Flaky Job" --job "Unproven Lane" --strict >/dev/null; RC=$?
assert_eq "$RC" "2" "--strict exits 2 on PARTIAL with a flaky step"
CHECK=$(check_json "$(flaky_json --job "Flaky Job" --job "Unproven Lane")" '
if d.get("verdict") != "partial":
    problems.append("verdict=%r" % d.get("verdict"))
if [(f["job"], f["first_exit"]) for f in d.get("flaky", [])] != [("Flaky Job", 4)]:
    problems.append("flaky=%r" % d.get("flaky"))
if [(u["job"], u["step"]) for u in d.get("unproven", [])] != [("Unproven Lane", "Print SHA")]:
    problems.append("unproven=%r" % d.get("unproven"))
')
assert_eq "$CHECK" "ok" "JSON: verdict partial, and flaky still lists the flaky step"
OUT="$(flaky_ci)"; RC=$?
assert_eq "$RC" "1" "a failure outranks both"
assert_contains "$OUT" "  flaky: Flaky Job › Passes on rerun (first exit 4)" "a failed run still names its flaky step"
CHECK=$(check_json "$(flaky_json)" '
if d.get("verdict") != "fail":
    problems.append("verdict=%r" % d.get("verdict"))
if [f["job"] for f in d.get("failed", [])] != ["Fails Twice"]:
    problems.append("failed=%r" % d.get("failed"))
if [f["job"] for f in d.get("flaky", [])] != ["Flaky Job"]:
    problems.append("flaky=%r" % d.get("flaky"))
')
assert_eq "$CHECK" "ok" "JSON: verdict fail, with the failure and the flaky step each listed"

# Called from the suite's mutation table, where `mutation` is defined.
ci_local_flaky_mutations() {
  mutation red "rerunning a failed step once" \
    'if rc != 0 and not timed_out and rerun:' 'if False:'
  mutation red "a timed-out step not being rerun" \
    'if rc != 0 and not timed_out and rerun:' 'if rc != 0 and rerun:'
  mutation red "a flaky step not counting as a pass" \
    '    elif flaky:
        verdict = "flaky"
' ''
  mutation red "a flaky step not counting as a failure" \
    'failed = [r for r in ran if r.status == "fail"]' \
    'failed = [r for r in ran if r.status == "fail" or r.flaky_steps]'
  mutation red "--no-rerun being honoured" 'rerun=not args.no_rerun))' 'rerun=True))'
  mutation red "--strict exiting 2 on FLAKY" \
    'exit_code = 1 if failed else (2 if verdict != "pass" and args.strict else 0)' \
    'exit_code = 1 if failed else (2 if verdict not in ("pass", "flaky") and args.strict else 0)'
  mutation red "the steps after a flaky step running" \
    '            # A flaky step does not end its job: the steps after it run, as after a pass.
            continue' '            if flaky:
                break
            continue'
  mutation red "a failure after a rerun reporting the rerun's output" \
    'rc, again, tail, timed_out = _attempt(' 'rc, again, _, timed_out = _attempt('
  mutation red "a failure after a rerun naming the first exit code" \
    'again = (f" on rerun (first attempt exit {step.first_exit})"' 'again = (""'
  mutation red "a flaky step keeping its first attempt's output" \
    'first_exit, first_tail = rc, tail' 'first_exit, first_tail = rc, ""'
  mutation red "the FLAKY prefix on the summary line" '"flaky": "FLAKY: ", ' ''
  mutation red "the line naming every flaky step" \
    '    if flaky:
        print("  flaky: "' '    if False:
        print("  flaky: "'
}
