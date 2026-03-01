#!/usr/bin/env python3
"""
claude-usage-watch — compact Claude Code quota pace for the status line.

Output: ⚡ +3% (4.4d)
  +3%  = usage% - elapsed%  (positive = ahead of pace, negative = under pace)
  4.4d = days until weekly reset

Color: green if delta ≤ 5, yellow if ≤ 20, red if > 20.
Cache: 2 minutes (avoids hammering the API on every status refresh).
"""
import json, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

USAGE_API  = "https://api.anthropic.com/api/oauth/usage"
CREDS_FILE = Path.home() / ".claude" / ".credentials.json"
CACHE_FILE = Path.home() / ".claude" / "usage-watch-cache.json"
CACHE_TTL  = 300  # seconds (5 min — 1% quota takes ~100 min to accumulate)


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
        if hours < 1:   return f"{int(hours*60)}m"
        if hours < 24:  return f"{hours:.0f}h"
        return f"{hours/24:.1f}d"
    except Exception:
        return "?"


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
    delta   = usage - elapsed

    sign = "+" if delta >= 0 else ""
    delta_str = f"{sign}{delta:.0f}%"

    if delta <= -20:
        colored = f"\033[1;31m{delta_str}\033[0m"   # red — significantly underpacing
    elif delta <= -10:
        colored = f"\033[1;33m{delta_str}\033[0m"   # yellow — slightly slow
    else:
        colored = delta_str                          # no color — normal

    print(f"{colored} ({left})", end="")


if __name__ == "__main__":
    run()
