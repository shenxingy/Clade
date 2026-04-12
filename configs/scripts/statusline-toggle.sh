#!/usr/bin/env bash
# statusline-toggle (slt) — control Claude Code status line display.
# Compatible with Bash 3.2+ (macOS default).
#
# MODES   (~/.claude/.statusline-mode):   symbol | percent | number | off
# THEMES  (~/.claude/.statusline-theme):  see: slt theme
#
# Usage:
#   slt                   cycle mode: symbol → percent → number → off → symbol
#   slt symbol/percent/number/off  set mode directly
#   slt theme             list all themes
#   slt theme <name>      set theme + show stage meanings

MODE_FILE="$HOME/.claude/.statusline-mode"
THEME_FILE="$HOME/.claude/.statusline-theme"

VALID_THEMES="circles plain bird moon weather mood coffee rocket ocean dragon"

# ─── Theme data lookup (Bash 3.2 compatible — no associative arrays) ───

_theme_data() {
  # Returns: e0 e1 e2 e3 "label0" "label1" "label2" "label3" "desc"
  case "$1" in
    circles) echo '○|◑|●|◉|far behind|a bit behind|on track|crushing it|classic circles' ;;
    plain)   echo '--|−|+|++|far behind|a bit behind|on track|crushing it|ASCII compat (no emoji)' ;;
    bird)    echo '🥚|🐣|🐥|🦢|egg|hatching|duckling|swan!|ugly duckling → swan' ;;
    moon)    echo '🌑|🌙|🌛|🌝|new moon|crescent|half moon|full moon!|new → full moon' ;;
    weather) echo '🌩️|🌧️|🌤️|🌈|thunderstorm|rainy|clearing up|rainbow!|storm → rainbow' ;;
    mood)    echo '🫠|😐|😊|🤩|melting|meh|feeling good|on fire!|melting → ecstatic' ;;
    coffee)  echo '😴|☕|💪|⚡|not awake yet|caffeinated|energized|supercharged|tired → wired' ;;
    rocket)  echo '🌍|🚀|🛸|⭐|grounded|launched|in orbit|among stars|earth → star' ;;
    ocean)   echo '🫧|🐠|🐬|🐋|just a ripple|swimming|diving deep|whale mode|ripple → whale' ;;
    dragon)  echo '🥚|🦎|🐉|👑|egg|lizard|dragon|dragon king!|egg → dragon king' ;;
  esac
}

# Parse pipe-delimited theme data into positional fields
_field() { echo "$1" | cut -d'|' -f"$2"; }

_get_mode() {
  local m; m=$(cat "$MODE_FILE" 2>/dev/null)
  case "$m" in symbol|percent|number|off) echo "$m" ;; *) echo "symbol" ;; esac
}

_get_theme() {
  local t; t=$(cat "$THEME_FILE" 2>/dev/null)
  for v in $VALID_THEMES; do [ "$t" = "$v" ] && echo "$t" && return; done
  echo "circles"
}

_show_theme_stages() {
  local data; data=$(_theme_data "$1")
  local e0; e0=$(_field "$data" 1)
  local e1; e1=$(_field "$data" 2)
  local e2; e2=$(_field "$data" 3)
  local e3; e3=$(_field "$data" 4)
  local l0; l0=$(_field "$data" 5)
  local l1; l1=$(_field "$data" 6)
  local l2; l2=$(_field "$data" 7)
  local l3; l3=$(_field "$data" 8)
  echo "  $e0  $l0     (delta < -15%)"
  echo "  $e1  $l1     (-15% to -5%)"
  echo "  $e2  $l2     (-5% to +5%)"
  echo "  $e3  $l3     (delta > +5%)"
}

_show_all_themes() {
  local current; current=$(_get_theme)
  echo "Available themes:"
  echo ""
  for n in $VALID_THEMES; do
    local marker="  "; [ "$n" = "$current" ] && marker="→ "
    local data; data=$(_theme_data "$n")
    local e0; e0=$(_field "$data" 1)
    local e1; e1=$(_field "$data" 2)
    local e2; e2=$(_field "$data" 3)
    local e3; e3=$(_field "$data" 4)
    local desc; desc=$(_field "$data" 9)
    printf "%s%-9s  %s%s%s%s   %s\n" "$marker" "$n" "$e0" "$e1" "$e2" "$e3" "$desc"
  done
  echo ""
  echo "Usage: slt theme <name>"
}

_mode_preview() {
  local mode=$1
  local theme; theme=$(_get_theme)
  local data; data=$(_theme_data "$theme")
  local e2; e2=$(_field "$data" 3)
  case "$mode" in
    symbol)  echo "  symbol  → $e2 (4d)                emoji only" ;;
    percent) echo "  percent → $e2 +4% (4d)            emoji + delta" ;;
    number)  echo "  number  → +4% (4d)                delta only, no emoji" ;;
    bar)     echo "  bar     → ▓▓▓▓░░░░░░ +4% (4d)    10-block usage bar" ;;
    off)     echo "  off     → (nothing)               no indicator" ;;
  esac
}

# ─── Handle: slt theme [name] ───

if [ "$1" = "theme" ]; then
  if [ -z "$2" ] || [ "$2" = "list" ]; then
    _show_all_themes
    exit 0
  fi
  _valid=0
  for v in $VALID_THEMES; do [ "$2" = "$v" ] && _valid=1 && break; done
  if [ $_valid -eq 0 ]; then
    echo "Unknown theme: $2"
    echo "Run 'slt theme' to see all available themes."
    exit 1
  fi
  echo "$2" > "$THEME_FILE"
  local_data=$(_theme_data "$2")
  _e0=$(_field "$local_data" 1)
  _e1=$(_field "$local_data" 2)
  _e2=$(_field "$local_data" 3)
  _e3=$(_field "$local_data" 4)
  _desc=$(_field "$local_data" 9)
  echo "Theme: $2  $_e0$_e1$_e2$_e3  — $_desc"
  _show_theme_stages "$2"
  exit 0
fi

# ─── Handle: slt <mode> (direct set) ───

if [ -n "$1" ]; then
  case "$1" in
    symbol|percent|number|bar|off)
      echo "$1" > "$MODE_FILE"
      echo "Mode set to: $1"
      _mode_preview "$1"
      ;;
    *)
      echo "Unknown: $1"
      echo ""
      echo "Modes:   slt [symbol|percent|number|bar|off]"
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
  number)  next="bar"     ;;
  bar)     next="off"     ;;
  *)       next="symbol"  ;;
esac

echo "$next" > "$MODE_FILE"
theme=$(_get_theme)
data=$(_theme_data "$theme")
e0=$(_field "$data" 1)
e1=$(_field "$data" 2)
e2=$(_field "$data" 3)
e3=$(_field "$data" 4)
echo "Mode: $current → $next   [theme: $theme  $e0$e1$e2$e3]"
_mode_preview "$next"
