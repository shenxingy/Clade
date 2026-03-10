#!/usr/bin/env bash
# statusline-toggle (slt) — control Claude Code status line display.
#
# MODES   (~/.claude/.statusline-mode):   symbol | percent | off
# THEMES  (~/.claude/.statusline-theme):  see: slt theme
#
# Usage:
#   slt                   cycle mode: symbol → percent → off → symbol
#   slt symbol/percent/off  set mode directly
#   slt theme             list all themes
#   slt theme <name>      set theme + show stage meanings

MODE_FILE="$HOME/.claude/.statusline-mode"
THEME_FILE="$HOME/.claude/.statusline-theme"

# ─── Theme registry ───
# Format: name  e0  e1  e2  e3  label0  label1  label2  label3
#   e0-e3 = emoji for each stage (far-behind / behind / on-track / ahead)

declare -A THEME_E0 THEME_E1 THEME_E2 THEME_E3
declare -A THEME_L0 THEME_L1 THEME_L2 THEME_L3
declare -A THEME_DESC

_def() {
  local n=$1
  THEME_E0[$n]=$2; THEME_E1[$n]=$3; THEME_E2[$n]=$4; THEME_E3[$n]=$5
  THEME_L0[$n]=$6; THEME_L1[$n]=$7; THEME_L2[$n]=$8; THEME_L3[$n]=$9
  THEME_DESC[$n]="${10}"
}

#        name      e0   e1   e2   e3    label0          label1         label2         label3          desc
_def circles  "○"  "◑"  "●"  "◉"  "far behind"    "a bit behind" "on track"     "crushing it"  "classic circles"
_def plain    "--" "-"  "+"  "++" "far behind"    "a bit behind" "on track"     "crushing it"  "ASCII compat (no emoji)"
_def bird     "🥚" "🐣" "🐥" "🦢" "egg"           "hatching"     "duckling"     "swan!"        "ugly duckling → swan"
_def moon     "🌑" "🌙" "🌛" "🌝" "new moon"      "crescent"     "half moon"    "full moon!"   "new → full moon"
_def weather  "🌩️" "🌧️" "🌤️" "🌈" "thunderstorm"  "rainy"        "clearing up"  "rainbow!"     "storm → rainbow"
_def mood     "🫠" "😐" "😊" "🤩" "melting"       "meh"          "feeling good" "on fire!"     "melting → ecstatic"
_def coffee   "😴" "☕" "💪" "⚡" "not awake yet" "caffeinated"  "energized"    "supercharged" "tired → wired"
_def rocket   "🌍" "🚀" "🛸" "⭐" "grounded"      "launched"     "in orbit"     "among stars"  "earth → star"
_def ocean    "🫧" "🐠" "🐬" "🐋" "just a ripple" "swimming"     "diving deep"  "whale mode"   "ripple → whale"
_def dragon   "🥚" "🦎" "🐉" "👑" "egg"           "lizard"       "dragon"       "dragon king!" "egg → dragon king"

VALID_THEMES=(circles plain bird moon weather mood coffee rocket ocean dragon)

_get_mode() {
  local m; m=$(cat "$MODE_FILE" 2>/dev/null)
  case "$m" in symbol|percent|number|off) echo "$m" ;; *) echo "symbol" ;; esac
}

_get_theme() {
  local t; t=$(cat "$THEME_FILE" 2>/dev/null)
  # validate against known themes
  for v in "${VALID_THEMES[@]}"; do [[ "$t" == "$v" ]] && echo "$t" && return; done
  echo "circles"
}

_show_theme_stages() {
  local n=$1
  local e0=${THEME_E0[$n]} e1=${THEME_E1[$n]} e2=${THEME_E2[$n]} e3=${THEME_E3[$n]}
  local l0=${THEME_L0[$n]} l1=${THEME_L1[$n]} l2=${THEME_L2[$n]} l3=${THEME_L3[$n]}
  echo "  $e0  $l0     (delta < -15%)"
  echo "  $e1  $l1     (-15% to -5%)"
  echo "  $e2  $l2     (-5% to +5%)"
  echo "  $e3  $l3     (delta > +5%)"
}

_show_all_themes() {
  local current; current=$(_get_theme)
  echo "Available themes:"
  echo ""
  for n in "${VALID_THEMES[@]}"; do
    local marker="  "; [[ "$n" == "$current" ]] && marker="→ "
    local e0=${THEME_E0[$n]} e1=${THEME_E1[$n]} e2=${THEME_E2[$n]} e3=${THEME_E3[$n]}
    printf "%s%-9s  %s%s%s%s   %s\n" "$marker" "$n" "$e0" "$e1" "$e2" "$e3" "${THEME_DESC[$n]}"
  done
  echo ""
  echo "Usage: slt theme <name>"
}

_mode_preview() {
  local mode=$1 theme; theme=$(_get_theme)
  local e2=${THEME_E2[$theme]}
  case "$mode" in
    symbol)  echo "  symbol  → $e2 (4d)          emoji only" ;;
    percent) echo "  percent → $e2 +4% (4d)      emoji + delta" ;;
    number)  echo "  number  → +4% (4d)           delta only, no emoji" ;;
    off)     echo "  off     → (nothing)          no indicator" ;;
  esac
}

# ─── Handle: slt theme [name] ───

if [[ "$1" == "theme" ]]; then
  if [[ -z "$2" || "$2" == "list" ]]; then
    _show_all_themes
    exit 0
  fi
  _valid=0
  for v in "${VALID_THEMES[@]}"; do [[ "$2" == "$v" ]] && _valid=1 && break; done
  if [[ $_valid -eq 0 ]]; then
    echo "Unknown theme: $2"
    echo "Run 'slt theme' to see all available themes."
    exit 1
  fi
  echo "$2" > "$THEME_FILE"
  _e0=${THEME_E0[$2]} _e1=${THEME_E1[$2]} _e2=${THEME_E2[$2]} _e3=${THEME_E3[$2]}
  echo "Theme: $2  $_e0$_e1$_e2$_e3  — ${THEME_DESC[$2]}"
  _show_theme_stages "$2"
  exit 0
fi

# ─── Handle: slt <mode> (direct set) ───

if [[ -n "$1" ]]; then
  case "$1" in
    symbol|percent|number|off)
      echo "$1" > "$MODE_FILE"
      echo "Mode set to: $1"
      _mode_preview "$1"
      ;;
    *)
      echo "Unknown: $1"
      echo ""
      echo "Modes:   slt [symbol|percent|off]"
      echo "Themes:  slt theme [name]   (run 'slt theme' to see all)"
      exit 1
      ;;
  esac
  exit 0
fi

# ─── Default: cycle mode ───

current=$(_get_mode)
case "$current" in
  symbol)  next="percent" ;;
  percent) next="number"  ;;
  number)  next="off"     ;;
  *)       next="symbol"  ;;
esac

echo "$next" > "$MODE_FILE"
theme=$(_get_theme)
e0=${THEME_E0[$theme]} e1=${THEME_E1[$theme]} e2=${THEME_E2[$theme]} e3=${THEME_E3[$theme]}
echo "Mode: $current → $next   [theme: $theme  $e0$e1$e2$e3]"
_mode_preview "$next"
