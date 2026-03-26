#!/bin/bash
# memory-watchdog.sh — Auto-kill claude workers under memory pressure to prevent OOM
#
# Usage:
#   Start:  nohup ~/.claude/scripts/memory-watchdog.sh &
#   Stop:   kill $(cat /tmp/memory-watchdog.pid)
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

set -uo pipefail

MEM_WARN_THRESHOLD="${MEM_WARN_THRESHOLD:-80}"
MEM_KILL_THRESHOLD="${MEM_KILL_THRESHOLD:-88}"
MEM_EMERGENCY="${MEM_EMERGENCY:-95}"
CHECK_INTERVAL="${CHECK_INTERVAL:-15}"
PID_FILE="/tmp/memory-watchdog.pid"
LOG_FILE="/tmp/memory-watchdog.log"

echo $$ > "$PID_FILE"

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE"
}

# ─── Cross-platform memory usage (%) ─────────────────────────────────────────

get_mem_usage() {
  if [[ "$(uname)" == "Darwin" ]]; then
    # macOS: use vm_stat + sysctl
    local page_size pages_free pages_inactive pages_speculative mem_total free_bytes
    page_size=$(sysctl -n hw.pagesize)
    pages_free=$(vm_stat | awk '/Pages free/ {gsub(/\./,"",$3); print $3}')
    pages_inactive=$(vm_stat | awk '/Pages inactive/ {gsub(/\./,"",$3); print $3}')
    pages_speculative=$(vm_stat | awk '/Pages speculative/ {gsub(/\./,"",$3); print $3}')
    mem_total=$(sysctl -n hw.memsize)
    free_bytes=$(( (pages_free + pages_inactive + pages_speculative) * page_size ))
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

# Get claude -p worker PIDs (oldest first)
# Match: "claude" followed by "-p" as a standalone flag (not --profile etc.)
get_worker_pids() {
  pgrep -f "claude\s+.*\s-p\s" 2>/dev/null | head -20 || true
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
