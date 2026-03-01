#!/usr/bin/env bash
# statusline-toggle (slt) — control Claude Code status line display.
#
# MODES   (~/.claude/.statusline-mode):   symbol | percent | off
# THEMES  (~/.claude/.statusline-theme):  circles | bird | plant
#
# Usage:
#   slt                 cycle mode: symbol → percent → off → symbol
#   slt symbol          set mode directly
#   slt percent
#   slt off
#   slt theme bird      set theme (circles | bird | plant)
#   slt theme plant
#   slt theme circles

MODE_FILE="$HOME/.claude/.statusline-mode"
THEME_FILE="$HOME/.claude/.statusline-theme"

_get_mode() {
  local m; m=$(cat "$MODE_FILE" 2>/dev/null)
  case "$m" in symbol|percent|off) echo "$m" ;; *) echo "symbol" ;; esac
}

_get_theme() {
  local t; t=$(cat "$THEME_FILE" 2>/dev/null)
  case "$t" in circles|bird|plant) echo "$t" ;; *) echo "circles" ;; esac
}

_mode_preview() {
  local theme; theme=$(_get_theme)
  case "$theme" in
    bird)    s1="🥚" s2="🐥" s3="🦅" ;;
    plant)   s1="🌱" s2="🌸" s3="🌺" ;;
    *)       s1="○"  s2="●"  s3="◉"  ;;
  esac
  case "$1" in
    symbol)  echo "  symbol  → $s2 (4d)        emoji/symbol only" ;;
    percent) echo "  percent → $s2 +4% (4d)    + delta vs 95% target" ;;
    off)     echo "  off     → (nothing)        clean prompt, no indicator" ;;
  esac
}

_theme_preview() {
  case "$1" in
    circles) echo "  circles → ○ ◑ ● ◉   (very behind → on track → ahead)" ;;
    bird)    echo "  bird    → 🥚 🐣 🐥 🦅  (egg → hatching → chick → eagle)" ;;
    plant)   echo "  plant   → 🌱 🌿 🌸 🌺  (seed → sprout → bloom → flower)" ;;
  esac
}

# ─── Handle: slt theme <name> ───

if [[ "$1" == "theme" ]]; then
  if [[ -z "$2" ]]; then
    echo "Current theme: $(_get_theme)"
    echo "Available: circles  bird  plant"
    echo "Usage: slt theme bird"
    exit 0
  fi
  case "$2" in
    circles|bird|plant)
      echo "$2" > "$THEME_FILE"
      echo "Theme set to: $2"
      _theme_preview "$2"
      ;;
    *)
      echo "Unknown theme: $2"
      echo "Available: circles  bird  plant"
      exit 1
      ;;
  esac
  exit 0
fi

# ─── Handle: slt <mode> (direct set) ───

if [[ -n "$1" ]]; then
  case "$1" in
    symbol|percent|off)
      echo "$1" > "$MODE_FILE"
      echo "Mode set to: $1"
      _mode_preview "$1"
      ;;
    *)
      echo "Unknown mode: $1"
      echo "Modes:  symbol  percent  off"
      echo "Themes: slt theme <circles|bird|plant>"
      exit 1
      ;;
  esac
  exit 0
fi

# ─── Default: cycle mode ───

current=$(_get_mode)
case "$current" in
  symbol)  next="percent" ;;
  percent) next="off"     ;;
  *)       next="symbol"  ;;
esac

echo "$next" > "$MODE_FILE"
echo "Mode: $current → $next"
_mode_preview "$next"
