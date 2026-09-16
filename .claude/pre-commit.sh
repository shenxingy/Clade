#!/usr/bin/env bash
# Clade's own pre-commit gate: the four drift checks, and nothing else.
#
# They are here rather than in committer.sh or checks.sh because both of those
# ship globally — committer.sh runs in 40+ repositories on this account — and a
# Clade-specific regeneration check has no business firing in an unrelated repo.
# checks.sh calls this file only when the repository being committed to has it.
#
# Scope is deliberate and narrow. These four are the gates that fail because a
# GENERATED artefact was not regenerated, which is a mechanical omission a human
# cannot usefully catch and a one-second command always can. Measured on this
# repo's CI history: 7 of the last 27 failed runs (26%) failed on one of these
# and nothing else. The full suite is NOT run here — `ci-local.py` is the gate
# before a push, this is only the gate before a commit, and a pre-commit hook
# slow enough to be worth skipping is a pre-commit hook that gets skipped.
#
# Total: about one second. Nothing here writes; each check only reports.
#
# It fires through `committer` (checks.sh staged -> run_repo_pre_commit), which
# is the only sanctioned way to commit here — CLAUDE.md's first rule is to use
# committer and NEVER `git add .`. A bare `git commit` bypasses it, and that is
# accepted rather than patched with a .git/hooks writer: .git/hooks is not
# versioned, so such a hook would exist only on whichever machine ran the
# installer — precisely the drift this gate exists to catch.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 0

FAILED=0
run() {
  local label="$1"; shift
  if ! out=$("$@" 2>&1); then
    echo "  ✗ $label"
    printf '%s\n' "$out" | tail -4 | sed 's/^/      /'
    FAILED=1
  fi
}

run "doc facts drift — run: python3 configs/scripts/doc-align.py sync" \
    python3 configs/scripts/doc-align.py verify
run "Codex plugin drift — run: python3 configs/scripts/regen-codex-plugin.py" \
    python3 configs/scripts/regen-codex-plugin.py --check
run "Claude Code plugin manifest drift — run: python3 configs/scripts/regen-cc-plugin.py" \
    python3 configs/scripts/regen-cc-plugin.py --check
run "settings reference drift — run: python3 configs/scripts/regen-settings-example.py" \
    python3 configs/scripts/regen-settings-example.py --check

if [[ $FAILED -ne 0 ]]; then
  echo ""
  echo "  A generated surface is stale. Regenerate it and stage the result —"
  echo "  this is the class of failure that costs a red CI run and a round trip"
  echo "  for a check that takes one second here."
  exit 1
fi
exit 0
