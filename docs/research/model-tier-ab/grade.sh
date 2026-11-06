#!/usr/bin/env bash
# grade.sh AB [TASK...] — one TSV row per cell, of the named tasks only if any are given:
# task arm rep verdict verifier_rc edited_verifier out_of_scope.
# The verifier never runs in the agent's cell. It runs in a fresh copy of the task's
# pristine base with only the agent's OWNED files copied in, under an empty HOME, so
# nothing else the agent changed (a test, a conftest.py, a sourced helper, the pytest
# config) can reach it. The cell itself is left as the agent left it, so a regrade sees
# the same evidence. No model call. Needs the same PY as prep.sh, and Linux / GNU
# coreutils (`timeout`).
# A verifier killed by the timeout is `timeout`, not `fail`: under a load average of
# ~220 on 32 cores one known-good cell needed more than 150 s. Regrade those cells.
# Protocol: ../2026-10-23-workflow-effort-and-reader-ab.md#queued-model-tier-for-implement-stages
set -u
[ $# -ge 1 ] || { echo "usage: grade.sh AB [TASK...]" >&2; exit 2; }
ab=$1; shift
only=" $* "
: "${PY:?set PY to the python prep.sh used}"
export PY
command -v timeout >/dev/null 2>&1 || { echo "grade.sh needs GNU timeout (coreutils)" >&2; exit 2; }
limit=${AB_TIMEOUT:-600}
work=$(mktemp -d "${TMPDIR:-/tmp}/ab-grade.XXXXXX")
trap 'rm -rf "$work"' EXIT
# A changed path outside the owned files that the verifier could load: any test
# directory, a conftest.py, or a pytest/tox/setuptools config file.
TESTISH='(^|/)tests?/|(^|/)conftest\.py$|(^|/)(pytest\.ini|tox\.ini|setup\.cfg|pyproject\.toml)$'
CACHES='(^|/)(__pycache__|\.pytest_cache|\.ab-home)/|\.pyc$'

printf 'task\tarm\trep\tverdict\tverifier_rc\tedited_verifier\tout_of_scope\n'
for cell in "$ab"/*/[ABC]-[0-9]*; do
  [ -d "$cell/.git" ] || continue
  t=$(dirname "$cell"); id=$(basename "$t"); name=$(basename "$cell")
  [ "$only" = "  " ] || case $only in *" $id "*) ;; *) continue ;; esac
  # ─── The base must still be the committed tree prep.sh built ───
  base=$(git -C "$t/base" rev-parse HEAD)
  if [ -n "$(git -C "$t/base" status --porcelain --ignored --untracked-files=all)" ]; then
    echo "$t/base differs from its commit; rebuild with prep.sh before grading" >&2; exit 2
  fi
  # ─── What the agent changed, read from the cell without touching it ───
  # A throwaway index holding the base tree: git diff refreshes whatever index it
  # reads, and against base, a file the agent added (staged or not) is untracked.
  idx=$work/index; rm -f "$idx"
  GIT_INDEX_FILE=$idx git -C "$cell" read-tree "$base"
  changed=$( { GIT_INDEX_FILE=$idx git -C "$cell" diff --name-only "$base" --
    GIT_INDEX_FILE=$idx git -C "$cell" ls-files --others --exclude-standard; } \
    | grep -v -E "$CACHES" | LC_ALL=C sort -u)
  outside=$(printf '%s\n' "$changed" | sed '/^$/d' | grep -v -x -F -f "$t/owned.txt")
  edited=0
  if printf '%s\n' "$outside" | sed '/^$/d' | grep -q -x -F -f "$t/protected.txt" \
    || printf '%s\n' "$outside" | grep -q -E "$TESTISH"; then edited=1; fi
  scope=$(printf '%s\n' "$outside" | sed '/^$/d' | tr '\n' ' ')
  # ─── The graded tree: pristine base plus the owned files exactly as the cell has them ───
  g=$work/$id-$name h=$work/$id-$name.home
  rm -rf "$g" "$h"; cp -a "$t/base" "$g"; mkdir "$h"
  while read -r p; do
    [ -n "$p" ] || continue
    if [ -e "$cell/$p" ] || [ -L "$cell/$p" ]; then
      mkdir -p "$g/$(dirname "$p")"; rm -f "$g/$p"; cp -a "$cell/$p" "$g/$p"
    else rm -f "$g/$p"; fi
  done < "$t/owned.txt"
  rc=$(cd "$g" && HOME="$h" timeout "$limit" bash -c "$(cat "$t/verifier.txt")" </dev/null >/dev/null 2>&1; echo $?)
  rm -rf "$g" "$h"
  if [ "$rc" = 124 ]; then verdict=timeout
  elif [ "$rc" = 0 ] && [ "$edited" = 0 ]; then verdict=pass
  elif [ "$rc" = 0 ]; then verdict=pass-but-edited-verifier
  else verdict=fail; fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$id" "${name%-*}" "${name#*-}" "$verdict" "$rc" "$edited" "${scope% }"
done
