#!/usr/bin/env bash
# statusline-toggle — cycle through Claude Code status line display modes.
#
# Modes:  symbol (default) → percent → bar → symbol → ...
# Usage:  slt          (cycle to next mode)
#         slt symbol   (set specific mode)
#         slt percent
#         slt bar

MODE_FILE="$HOME/.claude/.statusline-mode"
MODES=("symbol" "percent" "bar")

_current() {
  cat "$MODE_FILE" 2>/dev/null || echo "symbol"
}

_set() {
  echo "$1" > "$MODE_FILE"
}

_preview() {
  local mode="$1"
  case "$mode" in
    symbol)  echo "  symbol  → ● (4d)      circle/dot showing pace" ;;
    percent) echo "  percent → 73% (4d)    projected utilization %" ;;
    bar)     echo "  bar     → ▓▓▓░░ (4d)  5-block progress bar" ;;
  esac
}

# ─── Set specific mode ───

if [[ -n "$1" ]]; then
  case "$1" in
    symbol|percent|bar)
      _set "$1"
      echo "Status line mode set to: $1"
      _preview "$1"
      ;;
    *)
      echo "Unknown mode: $1"
      echo "Valid modes: symbol  percent  bar"
      exit 1
      ;;
  esac
  exit 0
fi

# ─── Cycle to next mode ───

current=$(_current)
next=""
for i in "${!MODES[@]}"; do
  if [[ "${MODES[$i]}" == "$current" ]]; then
    next="${MODES[$(( (i + 1) % ${#MODES[@]} ))]}"
    break
  fi
done

[[ -z "$next" ]] && next="symbol"

_set "$next"
echo "Status line mode: $current → $next"
_preview "$next"
