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

# The default used to be the lowercase `clade` only. On a case-sensitive
# filesystem that is a different path from `Clade`, which is what the checkout
# is actually called on the author's own box — so the documented control missed
# its own repository by one capital letter and reported "not found". Try the
# spellings rather than pick one, and keep CLADE_REPO as the override.
if [[ -z "${CLADE_REPO:-}" ]]; then
  for _c in "$HOME/projects/Clade" "$HOME/projects/clade" "$HOME/clade" "$HOME/Clade"; do
    [[ -f "$_c/orchestrator/oracle_cli.py" ]] && { CLADE_REPO="$_c"; break; }
  done
  CLADE_REPO="${CLADE_REPO:-$HOME/projects/Clade}"
fi
CLI="$CLADE_REPO/orchestrator/oracle_cli.py"

if [[ ! -f "$CLI" ]]; then
  # Exit 2, never 0. This gate lives in the CLI layer but its implementation is
  # in orchestrator/, which docs/layers.json marks DORMANT — so anyone who
  # installed the toolkit without a Clade checkout cannot run it at any path.
  # That is a real limitation of the design, not a misconfiguration, and the
  # right behaviour is to say so loudly rather than approve by default.
  echo "oracle-review: needs a Clade checkout (looked for $CLI)." >&2
  echo "  Set CLADE_REPO=/path/to/Clade, or treat this gate as unavailable." >&2
  exit 2
fi

# Prefer the repo venv (has the pinned deps); plain python3 works too —
# oracle_cli + worker_review are stdlib-only by design.
PY="$CLADE_REPO/orchestrator/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

exec "$PY" "$CLI" "$@"
