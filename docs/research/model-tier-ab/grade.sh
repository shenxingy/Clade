#!/usr/bin/env bash
# grade.sh AB [TASK...] — one TSV row per cell, of the named tasks only if any are given:
# task arm rep verdict verifier_rc edited_verifier out_of_scope.
# Restores the read-only files from the base commit BEFORE running the verifier, so an
# edited test earns nothing. No model call. Needs the same PY as prep.sh.
# A verifier killed by the timeout is `timeout`, not `fail`: under a load average of
# ~220 on 32 cores one known-good cell needed more than 150 s. Regrade those cells.
# Protocol: ../2026-10-23-workflow-effort-and-reader-ab.md#queued-model-tier-for-implement-stages
set -u
ab=$1; shift
only=" $* "
: "${PY:?set PY to the python prep.sh used}"
export PY
limit=${AB_TIMEOUT:-600}
printf 'task\tarm\trep\tverdict\tverifier_rc\tedited_verifier\tout_of_scope\n'
for cell in "$ab"/*/[ABC]-[0-9]*; do
  [ -d "$cell/.git" ] || continue
  t=$(dirname "$cell"); id=$(basename "$t"); name=$(basename "$cell")
  [ "$only" = "  " ] || case $only in *" $id "*) ;; *) continue ;; esac
  base=$(git -C "$cell" rev-list --max-parents=0 HEAD)
  edited=0
  while read -r p; do
    [ -n "$p" ] || continue
    git -C "$cell" diff --quiet "$base" -- "$p" 2>/dev/null || edited=1
  done < "$t/protected.txt"
  # shellcheck disable=SC2046  # one path per line, no spaces in this repository's test paths
  git -C "$cell" checkout -q "$base" -- $(cat "$t/protected.txt")
  rc=$(cd "$cell" && HOME="$t/home" timeout "$limit" bash -c "$(cat "$t/verifier.txt")" </dev/null >/dev/null 2>&1; echo $?)
  scope=$(git -C "$cell" status --porcelain --untracked-files=all | cut -c4- \
    | grep -v -E '(__pycache__/|\.pyc$|\.pytest_cache/)' \
    | grep -v -x -F -f "$t/owned.txt" | tr '\n' ' ')
  if [ "$rc" = 124 ]; then verdict=timeout
  elif [ "$rc" = 0 ] && [ "$edited" = 0 ]; then verdict=pass
  elif [ "$rc" = 0 ]; then verdict=pass-but-edited-verifier
  else verdict=fail; fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$id" "${name%-*}" "${name#*-}" "$verdict" "$rc" "$edited" "$scope"
done
