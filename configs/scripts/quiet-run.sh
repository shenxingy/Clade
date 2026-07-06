#!/usr/bin/env bash
# quiet-run — Run a noisy command, keep its output out of the agent transcript.
#
# Usage: quiet-run <command> [args...]
#   quiet-run .venv/bin/python -m pytest tests/ -q
#   quiet-run bash -c 'cd orchestrator && npm run build'
#
# Full stdout+stderr goes to .claude/logs/quiet-<timestamp>-<pid>.log, one
# line per line of output, each prefixed with a wall-clock [HH:MM:SS] stamp
# (Thorsten Ball: a merged, time-correlatable log — /verify's UI-interaction
# strategy appends browser_console_messages to this SAME file tagged
# [browser], so a test failure and a JS console error can be read in one
# chronological artifact instead of two disconnected ones).
# stdout gets a one-line verdict; on failure it adds failed-test names
# (pytest-style summary lines) plus the last QUIET_RUN_TAIL lines (default 80).
# The underlying exit code is ALWAYS mirrored — quiet-run never converts a
# failure into a success.
#
# Why: every in-session verify/build streams thousands of raw output lines
# into the transcript against the per-task token budget. The verdict + failure
# tail is what the agent acts on; the full log stays on disk for deep dives.
#
# Env:
#   QUIET_RUN_TAIL     lines to print on failure (default 80)
#   QUIET_RUN_LOG_DIR  log directory (default .claude/logs)

set -uo pipefail

if [[ $# -eq 0 ]]; then
  echo "Usage: quiet-run <command> [args...]" >&2
  exit 2
fi

TAIL_LINES="${QUIET_RUN_TAIL:-80}"
LOG_DIR="${QUIET_RUN_LOG_DIR:-.claude/logs}"

# Missing/uncreatable log dir must not block the run — fall back to a temp dir
if ! mkdir -p "$LOG_DIR" 2>/dev/null; then
  LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/quiet-run.XXXXXX")"
fi

# PID suffix avoids collisions between parallel workers in the same second
LOG_FILE="$LOG_DIR/quiet-$(date +%Y%m%d-%H%M%S)-$$.log"

# Per-line timestamp via a read loop (portable — no GNU-only `ts`/`date +%N`
# dependency). pipefail (set above) makes $PIPESTATUS[0] and a bare $? after
# the pipe agree on the ORIGINAL command's exit code, not the read loop's;
# PIPESTATUS[0] is used explicitly below to remove any doubt.
"$@" 2>&1 | while IFS= read -r _line || [[ -n "$_line" ]]; do
  printf '[%s] %s\n' "$(date +%H:%M:%S)" "$_line"
done >"$LOG_FILE"
rc=${PIPESTATUS[0]}

total_lines=$(wc -l < "$LOG_FILE" | tr -d ' ')

if [[ "$rc" -eq 0 ]]; then
  echo "quiet-run: OK (exit 0, ${total_lines} lines) — $*"
  echo "  full log: $LOG_FILE"
else
  echo "quiet-run: FAILED (exit ${rc}, ${total_lines} lines) — $*"
  echo "  full log: $LOG_FILE"
  # Failed-test names (pytest/unittest summary lines), capped at 20.
  # Lines now carry a leading [HH:MM:SS] stamp, so match just past it.
  failed_names=$(grep -E '^\[[0-9:]+\] (FAILED|ERROR)[ :]' "$LOG_FILE" 2>/dev/null | head -20 || true)
  if [[ -n "$failed_names" ]]; then
    echo "  failed:"
    sed 's/^/    /' <<< "$failed_names"
  fi
  echo "  ── last ${TAIL_LINES} lines ──"
  tail -n "$TAIL_LINES" "$LOG_FILE" | sed 's/^/  /'
fi

exit "$rc"
