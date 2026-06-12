#!/usr/bin/env bash
# oracle-review.sh — standalone oracle gate (CLI layer, no orchestrator needed).
#
# Thin shim over orchestrator/oracle_cli.py: cross-checks a diff with a second
# model using the SAME judge code the orchestrator runs (single source).
# Deployed to ~/.claude/scripts/ by install.sh; works in any project.
#
# Usage:
#   oracle-review.sh --task "fix: handle empty input" --staged
#   oracle-review.sh --task-file task.md --range origin/main...HEAD
#   git diff | oracle-review.sh --task "..." --diff-file -
#
# Exit codes: 0 approved/empty, 1 rejected, 2 unreviewed (infra error or
# missing clade repo — never silently approve).
set -euo pipefail

CLADE_REPO="${CLADE_REPO:-$HOME/projects/clade}"
CLI="$CLADE_REPO/orchestrator/oracle_cli.py"

if [[ ! -f "$CLI" ]]; then
  echo "oracle-review: clade repo not found at $CLADE_REPO (set CLADE_REPO)" >&2
  exit 2
fi

# Prefer the repo venv (has the pinned deps); plain python3 works too —
# oracle_cli + worker_review are stdlib-only by design.
PY="$CLADE_REPO/orchestrator/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

exec "$PY" "$CLI" "$@"
