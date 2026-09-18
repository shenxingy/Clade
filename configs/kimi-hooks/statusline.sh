#!/usr/bin/env bash
# statusline.sh — Kimi Code footer line 1, Clade's quota pace indicator.
#
# Wired by install.sh as `[status_line] command` in ~/.kimi-code/tui.toml
# (Kimi's own docs suggest exactly this file name). Kimi runs the command
# under `sh -c` with a 300 ms deadline, at most once a second, feeds a JSON
# snapshot (model, cwd, gitBranch, permissionMode, planMode, contextTokens,
# sessionId, ...) on stdin, and takes only the FIRST stdout line; a non-zero
# exit or an empty line falls back to the built-in footer. So this file is a
# launcher and nothing else: the render lives in the kimi-usage skill's
# helper, which reads a cache and never touches the network on this path —
# a refresh it decides is due runs detached, in its own session, so the
# 300 ms reaper (a process-group kill) cannot take the fetch down with it.
#
# Exit 0 with no output on any missing prerequisite: that is the documented
# "use the built-in footer" signal, and a footer must never break a session.
#
# Bash 3.2 / BSD userland clean: no arrays, no GNU-only flags.

helper="${CLADE_KIMI_USAGE_HELPER:-$HOME/.claude/skills/kimi-usage/scripts/kimi_usage.py}"
[ -f "$helper" ] || exit 0

if command -v python3 >/dev/null 2>&1; then
  py=python3
elif command -v python >/dev/null 2>&1; then
  py=python
else
  exit 0
fi

exec "$py" "$helper" statusline
