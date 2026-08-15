#!/usr/bin/env bash
# radar-cron.sh — run /radar unattended on a schedule.
#
# Why a local cron and not a cloud routine: radar's third lane mines
# ~/.claude/corrections/history.jsonl — this machine's record of where the
# stack actually failed its user. A cloud runner cannot see that file, and the
# lane that only reads the public web is the one that already existed.
#
# Why not CronCreate: those jobs are session-only and auto-expire after 7 days.
# "Keep up with the field" is not a one-week commitment.
#
# Install (weekly, Monday 08:07 local — off the :00 mark on purpose):
#   (crontab -l 2>/dev/null; echo "7 8 * * 1 $HOME/.claude/scripts/radar-cron.sh") | crontab -
# Remove:
#   crontab -l | grep -v radar-cron | crontab -
set -uo pipefail

CLAUDE_BIN="${CLADE_CLAUDE_BIN:-$HOME/.local/bin/claude}"
RESEARCH_DIR="$HOME/.claude/research"
LOG="$RESEARCH_DIR/radar-cron.log"
LOCK="/tmp/clade-radar.lock"
# A sweep that searches, reads, and triages is not a 60-second job; but an
# unattended run that hangs must not still be holding the lock next week.
TIMEOUT_SECS="${CLADE_RADAR_TIMEOUT:-2700}"

mkdir -p "$RESEARCH_DIR"

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }

if [[ ! -x "$CLAUDE_BIN" ]]; then
  log "SKIP: no claude binary at $CLAUDE_BIN (set CLADE_CLAUDE_BIN)"
  exit 0
fi

# flock -n: if last week's run is somehow still going, skip rather than stack.
exec 9>"$LOCK" || exit 0
if ! flock -n 9; then
  log "SKIP: a radar run is already in progress"
  exit 0
fi

_timeout() { if command -v timeout >/dev/null 2>&1; then timeout "$@"; else shift; "$@"; fi; }

log "START weekly radar sweep"
# --print: headless, one shot. Permission mode is explicit rather than inherited
# from the interactive shell alias, which cron does not load.
if _timeout "$TIMEOUT_SECS" "$CLAUDE_BIN" \
     --print \
     --permission-mode acceptEdits \
     "/radar

Run the full three-lane sweep unattended. Write the digest to \
$RESEARCH_DIR/radar-\$(date +%Y-%m-%d).md and append every concept examined to \
$RESEARCH_DIR/known-concepts.md.

You are running with no human present: do not ask questions, and do not leave a \
confirmed gap as a bare TODO if it is small enough to build and verify now." \
     >> "$LOG" 2>&1; then
  log "DONE"
else
  rc=$?
  [[ $rc -eq 124 ]] && log "TIMEOUT after ${TIMEOUT_SECS}s" || log "FAILED rc=$rc"
fi
