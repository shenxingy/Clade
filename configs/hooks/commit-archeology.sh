#!/usr/bin/env bash
# commit-archeology.sh (hook) — Inject recurring commit-pattern lessons at SessionStart.
# exists-for: no incident recorded (added 2026-05-06 in c8dd7b6); need: surface recurring fix-commit patterns (wiring, deploy and compat gaps) at session start · retire-when: an ablation shows the injected lessons do not reduce the fix-commit patterns they report
#
# Reads cached patterns from ~/.claude/commit-lessons/<slug>.jsonl
# (refreshes in the background if stale; auto-creates on first run).
# Prints markdown to stdout — Claude Code injects it as additionalContext.
#
# Safe to run anywhere: silent no-op outside git repos or on small repos.

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0
git rev-parse --is-inside-work-tree &>/dev/null || exit 0

ARCH="${HOME}/.claude/scripts/commit-archeology.sh"
[[ -x "$ARCH" ]] || exit 0

"$ARCH" --inject 2>/dev/null
