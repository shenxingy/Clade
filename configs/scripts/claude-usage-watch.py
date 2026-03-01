#!/usr/bin/env python3
"""
claude-usage-watch — compact Claude Code quota pace for the status line.

Modes (set via ~/.claude/.statusline-mode):
  symbol  (default)  ● (4d)    — colored circle showing pace
  percent            73% (4d)  — colored projected utilization %

Color gradient 0→100%: red → yellow → green → bright green (>100%)
Toggle with: slt  (statusline-toggle — cycles symbol ↔ percent)

Cache: 5 minutes.
"""
import json, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

USAGE_API  = "https://api.anthropic.com/api/oauth/usage"
CREDS_FILE = Path.home() / ".claude" / ".credentials.json"
CACHE_FILE = Path.home() / ".claude" / "usage-watch-cache.json"
MODE_FILE  = Path.home() / ".claude" / ".statusline-mode"
CACHE_TTL  = 300

# ─── Mode ───

def _mode():
    try:
        m = MODE_FILE.read_text().strip()
        return m if m in ("symbol", "percent") else "symbol"
    except Exception:
        return "symbol"

# ─── Color gradient ───

RED          = "\033[31m"
YELLOW       = "\033[33m"
GREEN        = "\033[32m"
BRIGHT_GREEN = "\033[1;32m"
RESET        = "\033[0m"

def _color(projected):
    if projected > 100: return BRIGHT_GREEN
    if projected >= 75: return GREEN
    if projected >= 50: return YELLOW
    return RED

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

# ─── Renderers ───

def _render_symbol(projected, left):
    if projected > 100:  symbol = "◉"
    elif projected >= 75: symbol = "●"
    elif projected >= 50: symbol = "◑"
    else:                 symbol = "○"
    col = _color(projected)
    return f"{col}{symbol}{RESET} ({left})"


def _render_percent(projected, left):
    col = _color(projected)
    pct = min(int(projected), 999)
    return f"{col}{pct}%{RESET} ({left})"

# ─── Main ───

def run():
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

    projected = (usage / elapsed * 100) if elapsed > 0 else 0

    if _mode() == "percent":
        print(_render_percent(projected, left), end="")
    else:
        print(_render_symbol(projected, left), end="")


if __name__ == "__main__":
    run()
