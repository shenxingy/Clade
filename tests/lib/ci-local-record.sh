#!/usr/bin/env bash
# ci-local-record.sh — the --json output is a gate record: the cases of
# tests/test-ci-local.sh that pin what land-pr.py and /green read from it.
#
# Sourced by that suite, never run on its own: it uses the suite's helpers
# (pass, fail, assert_*, section), its $RUNNER, $SANDBOX and $FAKE, and — for
# ci_local_record_mutations, called from the suite's mutation table — its
# `mutation` function. Moved out of the suite, at its 1500-line cap, on
# 2026-11-26.

# ─── Head and dirty ──────────────────────────────────────────────────
# land-pr.py merges a PR whose head a green record names, so a record must say
# which commit it tested and whether the tree held more than that commit.
section "the JSON is a gate record: head and dirty"
REC="$SANDBOX/record-repo"; mkdir -p "$REC/.github/workflows"
printf 'name: CI\non: [push]\njobs:\n  ok:\n    name: Ok\n    runs-on: ubuntu-latest\n    steps:\n      - name: Pass\n        run: "true"\n' \
  > "$REC/.github/workflows/ci.yml"
git -C "$REC" init -q && git -C "$REC" add -A \
  && git -C "$REC" -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false commit -q -m base
REC_HEAD="$(git -C "$REC" rev-parse HEAD)"
rec_field() { python3 "$RUNNER" --repo "$REC" --json 2>/dev/null \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['head'], d['dirty'], d['exit'], bool(d['ended']))" 2>/dev/null; }
assert_eq "$(rec_field)" "$REC_HEAD False 0 True" "a clean checkout's record names HEAD, not dirty, exit 0, ended"
touch "$REC/untracked.txt"
assert_eq "$(rec_field)" "$REC_HEAD True 0 True" "an untracked file marks the record dirty"
HEADLESS=$(python3 "$RUNNER" --repo "$FAKE" --json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['head'])" 2>/dev/null)
assert_eq "$HEADLESS" "None" "outside git the record names no head"

# ─── Nothing but the record on stdout ────────────────────────────────
# --clean-home names its HOME on stderr. On stdout the banner came before the
# JSON, so a gate run with it wrote a record no caller could parse.
CH_OUT="$(python3 "$RUNNER" --repo "$FAKE" --clean-home --json 2>"$SANDBOX/clean-home.err")"
if python3 -c "import json,sys; json.load(sys.stdin)" <<< "$CH_OUT" 2>/dev/null; then
  pass "--clean-home --json prints only the JSON on stdout"
else
  fail "--clean-home --json prints only the JSON on stdout" "first line: $(head -1 <<< "$CH_OUT")"
fi
assert_contains "$(cat "$SANDBOX/clean-home.err")" "clean HOME: " "--clean-home names its HOME on stderr"

ci_local_record_mutations() {
  mutation red "the --clean-home banner kept off stdout" \
    '(no ~/.claude, no installed skills)", file=sys.stderr)' '(no ~/.claude, no installed skills)")'
  mutation red "the dirty flag on the record" \
    'return head.stdout.strip(), bool(status.stdout.strip())' 'return head.stdout.strip(), False'
}
