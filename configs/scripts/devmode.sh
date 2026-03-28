#!/usr/bin/env bash
# devmode — Toggle Claude Code dev mode
#
# Dev mode relaxes pre-tool-guardian.sh: DB migrations are allowed through.
# Catastrophic operations (rm -rf /, DROP DATABASE, force push to main)
# remain blocked regardless of mode.
#
# Usage:
#   devmode          — toggle current mode
#   devmode on       — enable dev mode
#   devmode off      — disable dev mode (normal mode)
#   devmode status   — show current mode without changing it

set -euo pipefail

FLAG="$HOME/.claude/.dev-mode"

_status() {
  if [[ -f "$FLAG" ]]; then
    echo "dev mode: ON  (DB migrations allowed)"
  else
    echo "dev mode: OFF (normal mode — migrations blocked)"
  fi
}

case "${1:-toggle}" in
  on)
    touch "$FLAG"
    echo "dev mode: ON  (DB migrations allowed)"
    ;;
  off)
    rm -f "$FLAG"
    echo "dev mode: OFF (normal mode — migrations blocked)"
    ;;
  status)
    _status
    ;;
  toggle)
    if [[ -f "$FLAG" ]]; then
      rm -f "$FLAG"
      echo "dev mode: OFF (normal mode — migrations blocked)"
    else
      touch "$FLAG"
      echo "dev mode: ON  (DB migrations allowed)"
    fi
    ;;
  *)
    echo "Usage: devmode [on|off|status]  (no arg = toggle)"
    exit 1
    ;;
esac
