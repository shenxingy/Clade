#!/usr/bin/env bash
# ci-local-strict.sh — exit 2 is the default: the cases of tests/test-ci-local.sh
# that pin what a caller keying on the exit code sees, now that the report-only
# week (2026-11-06 to 11-13) is over.
#
# Sourced by that suite, never run on its own: it uses the suite's helpers
# (pass, fail, assert_*, section), its $RUNNER, the $LANES fixture and its
# `lanes` and `clear_markers`, and — for ci_local_strict_mutations, called from
# the suite's mutation table — its `mutation` function. The suite sits at its
# 1500-line cap, so these live here (2026-11-26).

section "exit 2 is the default; --no-strict is the report-only week's exit 0"
clear_markers
# The record says what the process said: a caller reading `exit` from the JSON
# (land-pr.py's tiny format, a log) must not see 0 beside a shell that saw 2.
strict_exit() { python3 -c "import json,sys; d=json.load(sys.stdin); print(d['verdict'], d['exit'])" 2>/dev/null; }
assert_eq "$(python3 "$RUNNER" --repo "$LANES" --json 2>/dev/null | strict_exit)" "partial 2" \
  "a PARTIAL record carries exit 2 by default"
assert_eq "$(python3 "$RUNNER" --repo "$LANES" --json --no-strict 2>/dev/null | strict_exit)" "partial 0" \
  "and exit 0 under --no-strict, with the same verdict"
# A caller that already passed --strict keeps working: the flag is still accepted.
lanes --strict >/dev/null; RC=$?
assert_eq "$RC" "2" "an explicit --strict is still accepted and still exits 2"
# The explanation line tells the reader what the exit code was and how to get the old one.
OUT="$(lanes)"
assert_contains "$OUT" "did not prove them. Prove them hosted (or where their services exist) — exit 2 (--no-strict: 0)." \
  "the PARTIAL line names the exit 2 and the flag that turns it off"
OUT="$(lanes --no-strict)"
assert_contains "$OUT" "where their services exist) — exit 0 under --no-strict." \
  "under --no-strict it says the exit was 0 because of the flag"
assert_lacks "$OUT" "exit 2" "and does not claim an exit 2 it did not make"

ci_local_strict_mutations() {
  mutation red "strict being the default" \
    'ap.add_argument("--strict", action=argparse.BooleanOptionalAction, default=True,' \
    'ap.add_argument("--strict", action=argparse.BooleanOptionalAction, default=False,'
  mutation red "--no-strict being honoured" \
    'exit_code = 1 if failed else (2 if verdict != "pass" and args.strict else 0)' \
    'exit_code = 1 if failed else (2 if verdict != "pass" else 0)'
  mutation red "the exit the explanation line names" \
    'strict_note = " — exit 2 (--no-strict: 0)." if args.strict else " — exit 0 under --no-strict."' \
    'strict_note = "."'
}
