#!/usr/bin/env bash
# statusline-toggle — cycle between Claude Code status line display modes.
#
# Modes:  symbol (default) ↔ percent
# Usage:  slt            (toggle)
#         slt symbol     (set specific mode)
#         slt percent

MODE_FILE="$HOME/.claude/.statusline-mode"
MODES=("symbol" "percent")

_current() {
  local m
  m=$(cat "$MODE_FILE" 2>/dev/null)
  # treat unknown/old values (e.g. "bar") as symbol
  case "$m" in
    symbol|percent) echo "$m" ;;
    *)              echo "symbol" ;;
  esac
}

_set() {
  echo "$1" > "$MODE_FILE"
}

_preview() {
  case "$1" in
    symbol)  echo "  symbol  → ● (4d)    colored circle (◉●◑○ = >100/75/50/0%)" ;;
    percent) echo "  percent → 73% (4d)  colored projected utilization %" ;;
  esac
}

# ─── Set specific mode ───

if [[ -n "$1" ]]; then
  case "$1" in
    symbol|percent)
      _set "$1"
      echo "Status line mode set to: $1"
      _preview "$1"
      ;;
    *)
      echo "Unknown mode: $1"
      echo "Valid modes: symbol  percent"
      exit 1
      ;;
  esac
  exit 0
fi

# ─── Toggle ───

current=$(_current)
if [[ "$current" == "symbol" ]]; then next="percent"; else next="symbol"; fi

_set "$next"
echo "Status line mode: $current → $next"
_preview "$next"
