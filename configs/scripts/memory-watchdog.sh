#!/bin/bash
# memory-watchdog.sh — Auto-kill claude workers under memory pressure to prevent OOM
#
# Usage:
#   Start:  nohup ~/.claude/scripts/memory-watchdog.sh &
#   Stop:   ~/.claude/scripts/memory-watchdog.sh --stop
#
# The pid file lives in this user's private runtime dir (see
# configs/hooks/lib/runtime-dir.sh), NOT at a fixed /tmp path: on a shared host
# the first account to create /tmp/memory-watchdog.pid owns it and every other
# account's watchdog silently cannot record or find its own pid. Override with
# MW_PID_FILE; --stop resolves the same path the daemon wrote.
#
# How it works:
#   Checks memory usage every CHECK_INTERVAL seconds.
#   When usage exceeds thresholds:
#     1. SIGTERM oldest claude -p worker (graceful shutdown)
#     2. Wait, if still high, kill next
#     3. At emergency threshold (>95%), SIGKILL immediately
#
# Environment variables (override defaults):
#   MEM_WARN_THRESHOLD=80  — warning threshold (%)
#   MEM_KILL_THRESHOLD=88  — start killing workers (%)
#   MEM_EMERGENCY=95       — emergency SIGKILL threshold (%)
#   CHECK_INTERVAL=15      — check interval (seconds)
#   MW_PID_FILE=<path>     — override the pid file location
#   MW_LOG_FILE=<path>     — override the log file location

set -uo pipefail

MEM_WARN_THRESHOLD="${MEM_WARN_THRESHOLD:-80}"
MEM_KILL_THRESHOLD="${MEM_KILL_THRESHOLD:-88}"
MEM_EMERGENCY="${MEM_EMERGENCY:-95}"
CHECK_INTERVAL="${CHECK_INTERVAL:-15}"

# A long-lived log belongs in $HOME, not a runtime dir systemd reaps on last
# logout. Pure assignment: sourcing this file must create nothing (see the
# source guard below).
LOG_FILE="${MW_LOG_FILE:-$HOME/.claude/memory-watchdog.log}"

# _mw_pid_file — resolve the pid file path. Deferred (not evaluated at source
# time) because resolving the runtime root creates a directory.
_mw_pid_file() {
  if [[ -n "${MW_PID_FILE:-}" ]]; then printf '%s' "$MW_PID_FILE"; return; fi
  local lib rt
  lib="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/../hooks/lib/runtime-dir.sh"
  # shellcheck source=/dev/null
  [[ -f "$lib" ]] && . "$lib" 2>/dev/null
  if declare -f clade_runtime_dir >/dev/null 2>&1 && rt=$(clade_runtime_dir 2>/dev/null); then
    printf '%s/memory-watchdog.pid' "$rt"
  else
    printf '%s/.claude/memory-watchdog.pid' "$HOME"
  fi
}

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE"
}

# ─── Cross-platform memory usage (%) ─────────────────────────────────────────

get_mem_usage() {
  if [[ "$(uname)" == "Darwin" ]]; then
    # macOS: use vm_stat + sysctl
    # vm_stat pages_free already includes speculative on some kernels — use free+inactive only
    local page_size pages_free pages_inactive mem_total free_bytes
    page_size=$(sysctl -n hw.pagesize)
    pages_free=$(vm_stat | awk '/Pages free/ {gsub(/\./,"",$3); print $3}')
    pages_inactive=$(vm_stat | awk '/Pages inactive/ {gsub(/\./,"",$3); print $3}')
    mem_total=$(sysctl -n hw.memsize)
    free_bytes=$(( (pages_free + pages_inactive) * page_size ))
    echo $(( 100 - (free_bytes * 100 / mem_total) ))
  else
    # Linux: use /proc/meminfo (MemAvailable is the best indicator)
    local mem_total mem_available
    mem_total=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
    mem_available=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
    echo $(( 100 - (mem_available * 100 / mem_total) ))
  fi
}

# ─── Worker process management ────────────────────────────────────────────────

# Select worker PIDs, oldest first, from `ps -eo pid=,etimes=,comm=,args=`
# lines on stdin. Split out from the ps call so it can be tested against
# synthetic process tables.
#
# Two things this has to get right, both of which the previous
# `pgrep -f "claude[[:space:]].*[[:space:]]-p[[:space:]]"` got wrong:
#
#   1. That pattern requires a token BETWEEN "claude" and "-p". Every command
#      worker_provider.py builds puts -p immediately after claude
#      (`claude -p "$(cat task.md)" --model ...`), so it matched none of them.
#      Verified by spawning a worker-shaped process: pgrep returned nothing
#      while /bin/sh -c 'claude -p ...' was live. Under memory pressure the
#      watchdog logged "No claude worker processes to kill" and freed nothing.
#   2. A worker is spawned via create_subprocess_shell, so the `sh -c` wrapper
#      carries the same command line and gets the LOWER pid. Selecting on the
#      full command line and taking `head -1` therefore signals the wrapper,
#      orphaning the claude process it was supposed to stop. Matching on comm
#      keeps only the real executable.
#
# "Oldest" is elapsed time, not pid order — pid order is not age order once
# pids wrap, and it was never age order across a parent/child pair.
select_worker_pids() {
  awk '
    {
      pid = $1; etimes = $2; comm = $3
      args = ""
      for (i = 4; i <= NF; i++) args = args " " $i
      if (comm != "claude") next          # skip the sh -c wrapper and everything else
      if (args !~ / -p( |$)/) next        # print mode only; leave interactive sessions alone
      print etimes, pid
    }
  ' | sort -rn | awk '{ print $2 }' | head -20
}

# Get claude -p worker PIDs (oldest first)
get_worker_pids() {
  ps -eo pid=,etimes=,comm=,args= 2>/dev/null | select_worker_pids || true
}

# Kill the oldest worker with given signal
kill_oldest_worker() {
  local sig="${1:-TERM}"
  local pids
  pids=$(get_worker_pids)

  if [[ -z "$pids" ]]; then
    log "  No claude worker processes to kill"
    return 1
  fi

  local oldest_pid
  oldest_pid=$(echo "$pids" | head -1)
  log "  Sending SIG${sig} to PID $oldest_pid"
  kill -"$sig" "$oldest_pid" 2>/dev/null || true
  return 0
}

# ─── Main loop ────────────────────────────────────────────────────────────────

# Sourcing this file must define the helpers WITHOUT starting the daemon, so
# the selection logic above can be exercised against synthetic process tables.
# It had no tests at all, which is how a pattern that matched none of the four
# command shapes worker_provider.py builds survived in a watchdog whose whole
# job is to act under memory pressure.
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
  return 0
fi

# Everything below runs ONLY as a daemon. The pid write and its EXIT trap used
# to sit at the top of the file, above this guard — so tests/test-memory-watchdog.sh,
# which sources the script, wrote and then deleted the pid file of whatever
# watchdog was actually live on the machine.
PID_FILE="$(_mw_pid_file)"

if [[ "${1:-}" == "--stop" ]]; then
  if [[ -f "$PID_FILE" ]] && kill "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; then
    echo "Stopped memory watchdog (pid file: $PID_FILE)"
  else
    echo "No running memory watchdog found (pid file: $PID_FILE)" >&2
    exit 1
  fi
  exit 0
fi

mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null
echo $$ > "$PID_FILE"
trap 'rm -f "$PID_FILE"' EXIT INT TERM

log "=== Memory watchdog started ==="
log "  Thresholds — warn: ${MEM_WARN_THRESHOLD}%  kill: ${MEM_KILL_THRESHOLD}%  emergency: ${MEM_EMERGENCY}%"
log "  Interval: ${CHECK_INTERVAL}s  PID: $$"

while true; do
  usage=$(get_mem_usage 2>/dev/null || echo "0")

  if (( usage >= MEM_EMERGENCY )); then
    log "[EMERGENCY] Memory ${usage}% >= ${MEM_EMERGENCY}%, force-killing worker"
    kill_oldest_worker KILL
    sleep 5
    usage=$(get_mem_usage 2>/dev/null || echo "0")
    if (( usage >= MEM_EMERGENCY )); then
      log "[EMERGENCY] Still ${usage}%, killing next worker"
      kill_oldest_worker KILL
    fi

  elif (( usage >= MEM_KILL_THRESHOLD )); then
    log "[KILL] Memory ${usage}% >= ${MEM_KILL_THRESHOLD}%, gracefully terminating worker"
    kill_oldest_worker TERM
    sleep 10

  elif (( usage >= MEM_WARN_THRESHOLD )); then
    log "[WARN] Memory ${usage}% >= ${MEM_WARN_THRESHOLD}%, no action yet"
  fi

  sleep "$CHECK_INTERVAL"
done
