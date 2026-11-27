#!/usr/bin/env bash
# Clade's merge check: the properties of the WHOLE tree that two PRs, each green
# on its own head, can break together. land-pr.py runs it on the merge result
# (a throwaway worktree of the tree merge-tree wrote) before it merges, and
# refuses with exit 22 when it fails.
#
# Why these and nothing else. On 2026-11-26 main was red for 2 h 44 min, eleven
# pushes in a row, and every red was one of these: two merges that each kept
# tests/test-hooks.sh under the 1500-line cap took it to 1,503 together; two
# took tests/test-kimi-hooks.sh to 1,577; and a byte ceiling on
# configs/CLAUDE.md, measured on one PR's base, was already 80 bytes short of
# what another PR had just merged. Each PR's gate tested its own head, so none
# could see it. The five drift gates are here for the same reason: two PRs that
# each regenerated a surface can merge into a tree neither regenerated.
#
# It must stay seconds (about 3 s on aries): it runs once per merge, and it is
# not a second gate — ci-local.py on the PR head is the gate.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

# The orchestrator venv lives in the main checkout, never in this throwaway
# worktree; LAND_PR_REPO is the checkout land-pr.py ran from (often a linked
# worktree, whose common dir is the main checkout's .git).
py=""
if [[ -n "${LAND_PR_REPO:-}" ]]; then
  common=$(git -C "$LAND_PR_REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
  [[ -n "$common" && -x "${common%/.git}/orchestrator/.venv/bin/python" ]] && py="${common%/.git}/orchestrator/.venv/bin/python"
fi
if [[ -z "$py" ]] && python3 -c 'import pytest' 2>/dev/null; then
  py=python3
fi
if [[ -z "$py" ]]; then
  echo "merge-check: no python with pytest (orchestrator/.venv in the main checkout, or python3 -m pytest)"
  exit 1
fi

rc=0
bash .claude/pre-commit.sh || rc=1
"$py" -m pytest -q -p no:cacheprovider \
  orchestrator/tests/test_conventions.py orchestrator/tests/test_codex_plugin.py || rc=1
exit "$rc"
