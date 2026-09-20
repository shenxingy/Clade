#!/usr/bin/env python3
"""
claude-usage-watch — Claude Code quota pace for the status line.

Metric: delta = usage% - elapsed% × 0.95
  delta = 0  → exactly on pace for 95% weekly target
  delta > 0  → ahead of 95% target
  delta < 0  → behind 95% target
  Linear: moving 1pt always requires the same amount of work, any day of the week.

  A positive delta does NOT on its own mean the burn is healthy, because the
  +5 that earns the top badge means a different overshoot at every point in
  the window: 145% projected at 10% elapsed, 101% at 90% (95 + 500/elapsed%).
  Past OVERPACE_PROJECTED the run exhausts the window before 80% of it has
  passed, and the scale shows that as the bottom level, not the top one.

Modes  (~/.claude/.statusline-mode):   symbol | percent | off
Themes (~/.claude/.statusline-theme):  circles | bird | plant

slt            — cycle mode (symbol → percent → off → symbol)
slt theme bird — set theme
"""
import json, locale, os, subprocess, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

USAGE_API    = "https://api.anthropic.com/api/oauth/usage"
CREDS_FILE   = Path.home() / ".claude" / ".credentials.json"
CACHE_FILE   = Path.home() / ".claude" / "usage-watch-cache.json"
MODE_FILE    = Path.home() / ".claude" / ".statusline-mode"
THEME_FILE   = Path.home() / ".claude" / ".statusline-theme"
CACHE_TTL       = 300
CACHE_TTL_STALE = 3600 * 24 * 7  # use stale cache for up to 7d (full period) if API is unavailable
TARGET_RATE  = 0.95   # 95% weekly utilization = "excellent"
# Projected utilization past which "ahead of target" is a blowout, not a grade:
# 125% runs the quota out with a fifth of the window still to go. The badge and
# the colour share one predicate so they cannot disagree — they did, with the
# docs calling >100% "Overpacing" while the colour painted it the best green.
OVERPACE_PROJECTED = 125.0

# ─── Themes ───
# Four levels: [far behind or overpacing, behind, on track, ahead]
# delta thresholds: < -15  /  -15 to -5  /  -5 to +5  /  > +5
# The scale is two-sided: level 0 is "wrong amount of quota for the time left",
# which under-use and a projected blowout both are.

THEMES = {
    "circles": ["○",  "◑",  "●",  "◉" ],
    "plain":   ["--", "-",  "+",  "++"],
    "bird":    ["🥚", "🐣", "🐥", "🦢"],
    "moon":    ["🌑", "🌙", "🌛", "🌝"],
    "weather": ["🌩️", "🌧️", "🌤️", "🌈"],
    "mood":    ["🫠", "😐", "😊", "🤩"],
    "coffee":  ["😴", "☕", "💪", "⚡"],
    "rocket":  ["🌍", "🚀", "🛸", "⭐"],
    "ocean":   ["🫧", "🐠", "🐬", "🐋"],
    "dragon":  ["🥚", "🦎", "🐉", "👑"],
}

# Themes that use only ASCII — always safe to render
_ASCII_THEMES = {"plain"}
# Themes that use Unicode symbols (no emoji) — safe on UTF-8 locales
_UNICODE_THEMES = {"circles"} | _ASCII_THEMES


def _emoji_supported() -> bool:
    """Return False if the environment is unlikely to render emoji correctly."""
    # Explicit opt-out via env var (e.g. set in .zshrc for problem terminals)
    if os.environ.get("CLAUDE_SLT_ASCII") == "1":
        return False
    # Locale must be UTF-8 for any multi-byte character
    enc = locale.getpreferredencoding(False).upper().replace("-", "")
    if enc not in ("UTF8",):
        return False
    # $COLORTERM=truecolor / 24bit indicates a modern terminal with emoji support
    colorterm = os.environ.get("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit"):
        return True
    # $TERM_PROGRAM: known terminals with reliable emoji support
    term_prog = os.environ.get("TERM_PROGRAM", "")
    if term_prog in ("iTerm.app", "WezTerm", "Hyper", "vscode", "Tabby"):
        return True
    # $TERM: basic terminals typically lack emoji font fallback
    term = os.environ.get("TERM", "")
    if term in ("dumb", "vt100", "xterm"):
        return False
    # Default: assume capable (avoids false negatives on most modern setups)
    return True

def _mode():
    try:
        m = MODE_FILE.read_text().strip()
        return m if m in ("symbol", "percent", "number", "bar", "off") else "symbol"
    except Exception:
        return "symbol"

def _theme():
    try:
        t = THEME_FILE.read_text().strip()
        t = t if t in THEMES else "circles"
    except Exception:
        t = "circles"
    # If the chosen theme uses emoji but the terminal can't render it, fall back
    if t not in _UNICODE_THEMES and not _emoji_supported():
        return "plain"
    return t

def _overpacing(delta, projected):
    """Ahead of target AND burning fast enough to run dry before the reset."""
    return delta >= 5 and projected > OVERPACE_PROJECTED

def _symbol(delta, projected):
    levels = THEMES[_theme()]
    if _overpacing(delta, projected): return levels[0]
    if delta < -15: return levels[0]
    if delta < -5:  return levels[1]
    if delta < 5:   return levels[2]
    return levels[3]

# ─── Continuous truecolor gradient ───
# Maps projected% to color: 0%=red  50%=yellow  95%=green  >100%=bold bright green

RESET = "\033[0m"

def _color(projected, delta):
    # Muted palette — low saturation so the indicator doesn't steal attention.
    # 0% → soft red  →  50% → amber  →  95% → sage green  →  >100% → slightly brighter green
    # The one case that IS meant to steal attention: a projection that empties
    # the window early. Without it 101% and 205% were painted the same green.
    if _overpacing(delta, projected):
        return "\033[38;2;185;28;28m"   # overpacing — quota gone before reset
    if projected > 100:
        return "\033[38;2;85;160;85m"    # soft bright green, no bold
    p = max(0.0, min(projected, 95.0))
    if p <= 50:
        t = p / 50.0
        r = 160
        g = int(75 + 50 * t)             # 75 → 125
        b = int(75 - 20 * t)             # 75 → 55
    else:
        t = (p - 50.0) / 45.0
        r = int(160 - 90 * t)            # 160 → 70
        g = int(125 + 20 * t)            # 125 → 145
        b = int(55 + 15 * t)             # 55 → 70
    return f"\033[38;2;{r};{g};{b}m"

# ─── API / cache ───

def _load_token():
    # macOS: prefer Keychain (Claude Code refreshes tokens there, not in .credentials.json)
    if sys.platform == "darwin":
        try:
            raw = subprocess.check_output(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                text=True, stderr=subprocess.DEVNULL, timeout=5,
            ).strip()
            return json.loads(raw)["claudeAiOauth"]["accessToken"]
        except Exception:
            pass
    # Linux / fallback: read from .credentials.json
    try:
        return json.loads(CREDS_FILE.read_text())["claudeAiOauth"]["accessToken"]
    except Exception:
        return None

def _fetch(token):
    req = urllib.request.Request(USAGE_API, headers={
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
    })
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return None

def _load_cache(max_age=CACHE_TTL):
    try:
        d = json.loads(CACHE_FILE.read_text())
        if time.time() - d.get("_at", 0) < max_age:
            return d
    except Exception:
        pass
    return None

def _save_cache(d):
    try:
        d["_at"] = time.time()
        CACHE_FILE.write_text(json.dumps(d))
    except Exception:
        pass

def _load_statusline_input():
    """Adapt Claude Code's native rate-limit input to the legacy API shape."""
    try:
        data = json.load(sys.stdin)
        native = data["rate_limits"]["seven_day"]
        usage = native["used_percentage"]
        resets_at = native["resets_at"]
        if usage is None or resets_at is None:
            return None
        if isinstance(resets_at, (int, float)):
            resets_at = datetime.fromtimestamp(
                resets_at, timezone.utc
            ).isoformat()
        return {
            "seven_day": {
                "utilization": float(usage),
                "resets_at": resets_at,
            }
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

# ─── Calculations ───

def _elapsed_pct(resets_at_str, days=7):
    try:
        resets_at = datetime.fromisoformat(resets_at_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        period_s = days * 86400
        elapsed_s = period_s - (resets_at - now).total_seconds()
        return max(0.0, min(100.0, elapsed_s / period_s * 100))
    except Exception:
        return 0.0

def _remaining(resets_at_str):
    try:
        resets_at = datetime.fromisoformat(resets_at_str.replace("Z", "+00:00"))
        hours = (resets_at - datetime.now(timezone.utc)).total_seconds() / 3600
        if hours < 1:    return f"{int(hours*60)}m"
        if hours < 24:   return f"{hours:.0f}h"
        if hours < 48:   return f"{hours/24:.1f}d"
        return f"{hours/24:.0f}d"
    except Exception:
        return "?"

# ─── Main ───

def run():
    mode = _mode()
    if mode == "off":
        return

    data = (
        _load_statusline_input()
        if "--statusline-input" in sys.argv[1:]
        else None
    )
    if not data:
        data = _load_cache()
    if not data or "seven_day" not in data:
        token = _load_token()
        if token:
            fetched = _fetch(token)
            if fetched and "seven_day" in fetched:
                data = fetched
                _save_cache(data)
        # If fresh fetch failed, try stale cache as fallback
        if not data or "seven_day" not in data:
            data = _load_cache(max_age=CACHE_TTL_STALE)
        if not data or "seven_day" not in data:
            return

    w       = data["seven_day"]
    usage   = w.get("utilization") or 0.0
    resets  = w.get("resets_at", "")

    # If resets_at is in the past, the cached data is from a previous cycle — stale
    try:
        resets_dt = datetime.fromisoformat(resets.replace("Z", "+00:00"))
        if resets_dt < datetime.now(timezone.utc):
            # Previous cycle data — show a stale indicator
            sym = THEMES[_theme()][2]  # on-track symbol as neutral
            dim = "\033[2m"  # dim
            if mode == "off":
                return
            print(f"{dim}{sym} (?){RESET}", end="")
            return
    except Exception:
        pass

    elapsed = _elapsed_pct(resets)
    left    = _remaining(resets)

    # Delta: how far ahead/behind the 95% weekly target pace
    # Linear: 1pt delta always = 1% of weekly quota, regardless of day
    delta     = usage - elapsed * TARGET_RATE
    projected = (usage / elapsed * 100) if elapsed > 0 else 0  # colour AND the overpace guard

    sym = _symbol(delta, projected)
    col = _color(projected, delta)

    sign = "+" if delta >= 0 else ""
    pct  = f"{sign}{delta:.0f}%"

    if mode == "percent":
        print(f"{sym} {col}{pct}{RESET} ({left})", end="")
    elif mode == "number":
        print(f"{col}{pct}{RESET} ({left})", end="")
    elif mode == "bar":
        filled = min(10, round(usage / 10))
        bar = "▓" * filled + "░" * (10 - filled)
        print(f"{col}{bar}{RESET} {pct} ({left})", end="")
    else:  # symbol
        print(f"{sym} ({left})", end="")


if __name__ == "__main__":
    run()
