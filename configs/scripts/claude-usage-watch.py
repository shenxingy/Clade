#!/usr/bin/env python3
"""
claude-usage-watch — Claude Code quota pace for the status line.

Metric: delta = usage% - elapsed% × 0.95
  delta = 0  → exactly on pace for 95% weekly target
  delta > 0  → ahead of 95% target
  delta < 0  → behind 95% target
  Linear: moving 1pt always requires the same amount of work, any day of the week.

Modes  (~/.claude/.statusline-mode):   symbol | percent | off
Themes (~/.claude/.statusline-theme):  circles | bird | plant

slt            — cycle mode (symbol → percent → off → symbol)
slt theme bird — set theme
"""
import json, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

USAGE_API    = "https://api.anthropic.com/api/oauth/usage"
CREDS_FILE   = Path.home() / ".claude" / ".credentials.json"
CACHE_FILE   = Path.home() / ".claude" / "usage-watch-cache.json"
MODE_FILE    = Path.home() / ".claude" / ".statusline-mode"
THEME_FILE   = Path.home() / ".claude" / ".statusline-theme"
CACHE_TTL    = 300
TARGET_RATE  = 0.95   # 95% weekly utilization = "excellent"

# ─── Themes ───
# Four levels: [far behind, behind, on track, ahead]
# delta thresholds: < -15  /  -15 to -5  /  -5 to +5  /  > +5

THEMES = {
    "circles": ["○",  "◑",  "●",  "◉" ],
    "bird":    ["🥚", "🐣", "🐥", "🦅"],
    "plant":   ["🌱", "🌿", "🌸", "🌺"],
    "weather": ["🌧️", "🌤️", "☀️", "🌈"],
    "mood":    ["😴", "😐", "😊", "🤩"],
    "crystal": ["🪨", "💎", "💍", "👑"],
    "coffee":  ["😴", "☕", "🧠", "⚡"],
    "rocket":  ["🌍", "🚀", "🛸", "⭐"],
    "ocean":   ["🐚", "🐠", "🐬", "🐋"],
    "dragon":  ["🥚", "🦎", "🐉", "🔥"],
}

def _mode():
    try:
        m = MODE_FILE.read_text().strip()
        return m if m in ("symbol", "percent", "number", "off") else "symbol"
    except Exception:
        return "symbol"

def _theme():
    try:
        t = THEME_FILE.read_text().strip()
        return t if t in THEMES else "circles"
    except Exception:
        return "circles"

def _symbol(delta):
    levels = THEMES[_theme()]
    if delta < -15: return levels[0]
    if delta < -5:  return levels[1]
    if delta < 5:   return levels[2]
    return levels[3]

# ─── Continuous truecolor gradient ───
# Maps projected% to color: 0%=red  50%=yellow  95%=green  >100%=bold bright green

RESET = "\033[0m"

def _color(projected):
    # Muted palette — low saturation so the indicator doesn't steal attention.
    # 0% → soft red  →  50% → amber  →  95% → sage green  →  >100% → slightly brighter green
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

def _load_cache():
    try:
        d = json.loads(CACHE_FILE.read_text())
        if time.time() - d.get("_at", 0) < CACHE_TTL:
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

    data = _load_cache()
    if not data or "seven_day" not in data:
        token = _load_token()
        if not token:
            return
        data = _fetch(token)
        if not data or "seven_day" not in data:
            return
        _save_cache(data)

    w       = data["seven_day"]
    usage   = w.get("utilization") or 0.0
    resets  = w.get("resets_at", "")
    elapsed = _elapsed_pct(resets)
    left    = _remaining(resets)

    # Delta: how far ahead/behind the 95% weekly target pace
    # Linear: 1pt delta always = 1% of weekly quota, regardless of day
    delta     = usage - elapsed * TARGET_RATE
    projected = (usage / elapsed * 100) if elapsed > 0 else 0  # for color only

    sym = _symbol(delta)
    col = _color(projected)

    sign = "+" if delta >= 0 else ""
    pct  = f"{sign}{delta:.0f}%"

    if mode == "percent":
        print(f"{sym} {col}{pct}{RESET} ({left})", end="")
    elif mode == "number":
        print(f"{col}{pct}{RESET} ({left})", end="")
    else:  # symbol
        print(f"{sym} ({left})", end="")


if __name__ == "__main__":
    run()
