#!/usr/bin/env bash
# pipeline-watch.sh — Continuous pipeline health monitor with alerting
#
# Usage: pipeline-watch.sh [--interval 300] [project-filter]
#
# Runs pipeline-check.sh on each interval, compares against stored state,
# and sends Telegram alerts (or stderr) on status changes.
# State persisted in ~/.claude/pipeline-watch-state.json

set -euo pipefail

# ─── Defaults ─────────────────────────────────────────────────────────────────

INTERVAL=300
FILTER=""
STATE_FILE="$HOME/.claude/pipeline-watch-state.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK_SCRIPT="$SCRIPT_DIR/pipeline-check.sh"

# ─── Argument Parsing ─────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interval)
      INTERVAL="${2:?--interval requires a value}"
      shift 2
      ;;
    --interval=*)
      INTERVAL="${1#--interval=}"
      shift
      ;;
    -*)
      echo "Unknown option: $1" >&2
      echo "Usage: pipeline-watch.sh [--interval SECONDS] [project-filter]" >&2
      exit 1
      ;;
    *)
      FILTER="$1"
      shift
      ;;
  esac
done

# ─── Validate ─────────────────────────────────────────────────────────────────

if [[ ! -x "$CHECK_SCRIPT" ]]; then
  echo "Error: pipeline-check.sh not found or not executable at $CHECK_SCRIPT" >&2
  exit 1
fi

# ─── Signal Handling ──────────────────────────────────────────────────────────

RUNNING=true
_cleanup() {
  RUNNING=false
  echo "" >&2
  echo "[pipeline-watch] Stopped ($(date '+%Y-%m-%d %H:%M:%S'))" >&2
}
trap _cleanup SIGINT SIGTERM

# ─── State Management ─────────────────────────────────────────────────────────

# Read current status for a key "project|pipeline" from state JSON
# Returns the stored status string, or empty if not found
_state_get() {
  local key="$1"
  if [[ ! -f "$STATE_FILE" ]]; then
    echo ""
    return
  fi
  python3 -c "
import json, sys
try:
    data = json.load(open('$STATE_FILE'))
    print(data.get('${key}', {}).get('status', ''))
except Exception:
    print('')
" 2>/dev/null || echo ""
}

# Write/update a status entry in state JSON
# Usage: _state_set "project|pipeline" STATUS
_state_set() {
  local key="$1" status="$2"
  python3 - "$STATE_FILE" "$key" "$status" <<'PYEOF' 2>/dev/null || true
import json, sys, os
from datetime import datetime

state_file, key, status = sys.argv[1], sys.argv[2], sys.argv[3]
data = {}
if os.path.exists(state_file):
    try:
        data = json.load(open(state_file))
    except Exception:
        data = {}
data[key] = {"status": status, "updated": datetime.now().isoformat()}
with open(state_file, 'w') as f:
    json.dump(data, f, indent=2)
PYEOF
}

# ─── Telegram Alert ───────────────────────────────────────────────────────────

_send_telegram() {
  local text="$1"
  if [[ -z "${TG_BOT_TOKEN:-}" || -z "${TG_CHAT_ID:-}" ]]; then
    return 1
  fi
  curl -s -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TG_CHAT_ID}" \
    --data-urlencode "text=${text}" \
    -d "parse_mode=HTML" > /dev/null 2>&1
}

_alert() {
  local status="$1" project="$2" pipeline="$3" detail="$4"
  local icon timestamp text

  timestamp=$(date '+%Y-%m-%d %H:%M:%S')
  case "$status" in
    DEAD)     icon="🔴" ;;
    DEGRADED) icon="🟡" ;;
    HEALTHY)  icon="✅" ;;
    *)        icon="⚪" ;;
  esac

  text="${icon} <b>Pipeline ${status}</b>
Project: ${project}
Pipeline: ${pipeline}
Detail: ${detail}
Time: ${timestamp}"

  # Try Telegram first, fall back to stderr
  if ! _send_telegram "$text"; then
    echo "[pipeline-watch] ALERT: ${status} | ${project} | ${pipeline} | ${detail} | ${timestamp}" >&2
  fi
}

# ─── One Check Cycle ─────────────────────────────────────────────────────────

_run_cycle() {
  local check_output prev_status new_status project pipeline detail key

  check_output=$(bash "$CHECK_SCRIPT" "$FILTER" 2>/dev/null) || true

  if [[ -z "$check_output" ]]; then
    return
  fi

  while IFS='|' read -r new_status project pipeline detail; do
    [[ -z "$new_status" ]] && continue
    key="${project}|${pipeline}"
    prev_status=$(_state_get "$key")

    # Alert on transitions
    if [[ "$prev_status" != "$new_status" ]]; then
      if [[ "$new_status" == "DEAD" || "$new_status" == "DEGRADED" ]]; then
        _alert "$new_status" "$project" "$pipeline" "$detail"
      elif [[ "$new_status" == "HEALTHY" && ( "$prev_status" == "DEAD" || "$prev_status" == "DEGRADED" ) ]]; then
        _alert "HEALTHY" "$project" "$pipeline" "recovered — $detail"
      fi
      _state_set "$key" "$new_status"
    fi
  done <<< "$check_output"
}

# ─── Main Loop ────────────────────────────────────────────────────────────────

echo "[pipeline-watch] Starting (interval=${INTERVAL}s, filter='${FILTER:-all}')" >&2
echo "[pipeline-watch] State: $STATE_FILE" >&2
echo "[pipeline-watch] Press Ctrl+C to stop" >&2
echo "" >&2

# Run immediately on startup
_run_cycle
echo "[pipeline-watch] Initial check complete ($(date '+%H:%M:%S'))" >&2

while [[ "$RUNNING" == true ]]; do
  # Sleep in small increments to respond quickly to signals
  local_count=0
  while [[ "$RUNNING" == true && "$local_count" -lt "$INTERVAL" ]]; do
    sleep 1
    local_count=$(( local_count + 1 ))
  done

  [[ "$RUNNING" == false ]] && break

  _run_cycle
  echo "[pipeline-watch] Cycle complete ($(date '+%H:%M:%S'))" >&2
done
