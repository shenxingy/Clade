#!/usr/bin/env python3
"""
usage-agent — standalone Claude Code usage reporter.

For machines that DON'T run the orchestrator but DO use Claude Code on the
same account. Polls `ccusage --json` and pushes to a hub orchestrator.

Setup (per node):
  1. Install ccusage:  npm install -g ccusage
  2. Point it at the hub. Every flag below except --since-days falls back to an
     env var, and the flag wins when both are given:
       --hub URL        CLADE_USAGE_HUB_URL    required; exits 2 without it
       --token TOKEN    CLADE_USAGE_HUB_TOKEN  sent as `Authorization: Bearer`
       --machine-id ID  CLADE_MACHINE_ID       defaults to the hostname
       --interval SECS  CLADE_USAGE_INTERVAL   loop mode only; default 900,
                                               floored at 60
       --since-days N   (flag only)            default 7; 0 pushes all-time
  3. Run it one of two ways:
       cron:            python3 usage-agent.py --hub http://hub:8000 --once
       systemd / nohup: python3 usage-agent.py --hub http://hub:8000 --interval 900
     `--once` runs a single cycle and exits non-zero when the push failed,
     which is what makes it the cron form. Without it the process loops
     forever and a failed cycle is logged rather than fatal, so a cron entry
     that omits `--once` leaves another daemon behind on every tick.

Hub-side token: required, and no longer "empty means open". `/api/usage/ingest`
is exempt from the control-plane middleware only while `usage_ingest_token` is
set in ~/.claude/orchestrator-settings.json — set it, and --token must match it.
Leave it empty and the endpoint falls back to the control plane, so --token must
carry the hub's `api_token` instead (minted into that same settings file on
first start). Only `api_allow_unauthenticated` serves ingest with no credential.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


def _resolve_cmd() -> list[str]:
    override = os.environ.get("CLADE_CCUSAGE_CMD")
    if override:
        return override.split()
    try:
        r = subprocess.run(["which", "ccusage"], capture_output=True, text=True, timeout=2)
        if r.returncode == 0 and r.stdout.strip():
            return ["ccusage"]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ["npx", "-y", "ccusage@latest"]


def run_ccusage(since: str | None = None, timeout: int = 120) -> list[dict]:
    cmd = _resolve_cmd() + ["--json"]
    if since:
        cmd += ["--since", since]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"ccusage failed: {e}", file=sys.stderr)
        return []
    if r.returncode != 0:
        print(f"ccusage exit={r.returncode} stderr={r.stderr[:200]}", file=sys.stderr)
        return []
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        print(f"ccusage json parse failed: {e}", file=sys.stderr)
        return []
    return data.get("daily", []) if isinstance(data, dict) else []


def flatten(daily: list[dict]) -> list[dict]:
    out = []
    for day in daily:
        date = day.get("date") or ""
        for mb in (day.get("modelBreakdowns") or []):
            input_t = int(mb.get("inputTokens", 0))
            output_t = int(mb.get("outputTokens", 0))
            cc_t = int(mb.get("cacheCreationTokens", 0))
            cr_t = int(mb.get("cacheReadTokens", 0))
            out.append({
                "date": date,
                "model_name": mb.get("modelName") or "unknown",
                "input_tokens": input_t,
                "output_tokens": output_t,
                "cache_creation_tokens": cc_t,
                "cache_read_tokens": cr_t,
                "total_tokens": input_t + output_t + cc_t + cr_t,
                "cost_usd": float(mb.get("cost", 0.0)),
            })
    return out


def push(hub_url: str, token: str, payload: dict, timeout: float = 15.0) -> bool:
    url = hub_url.rstrip("/") + "/api/usage/ingest"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except urllib.error.HTTPError as e:
        print(f"push HTTP error {e.code}: {e.read()[:200].decode(errors='replace')}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"push error: {e}", file=sys.stderr)
        return False


def one_shot(hub_url: str, token: str, machine_id: str, since_days: int) -> bool:
    since = None
    if since_days > 0:
        from datetime import date, timedelta
        since = (date.today() - timedelta(days=since_days)).strftime("%Y%m%d")
    daily = run_ccusage(since=since)
    snapshots = flatten(daily)
    if not snapshots:
        print("no snapshots to push (ccusage returned empty)", file=sys.stderr)
        return False
    payload = {"machine_id": machine_id, "hostname": socket.gethostname(), "snapshots": snapshots}
    ok = push(hub_url, token, payload)
    print(f"pushed {len(snapshots)} rows to {hub_url} as machine_id={machine_id}: {'ok' if ok else 'FAIL'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default=os.environ.get("CLADE_USAGE_HUB_URL", ""),
                    help="Hub URL (or env CLADE_USAGE_HUB_URL)")
    ap.add_argument("--token", default=os.environ.get("CLADE_USAGE_HUB_TOKEN", ""),
                    help="Bearer token (or env CLADE_USAGE_HUB_TOKEN)")
    ap.add_argument("--machine-id", default=os.environ.get("CLADE_MACHINE_ID") or socket.gethostname(),
                    help="Stable machine id (default: hostname)")
    ap.add_argument("--interval", type=int, default=int(os.environ.get("CLADE_USAGE_INTERVAL", "900")),
                    help="Poll interval seconds (default 900). Use --once to skip loop.")
    ap.add_argument("--since-days", type=int, default=7,
                    help="Only push last N days each cycle (0 = all-time)")
    ap.add_argument("--once", action="store_true", help="Run one cycle and exit")
    args = ap.parse_args()

    if not args.hub:
        print("ERROR: --hub or CLADE_USAGE_HUB_URL required", file=sys.stderr)
        return 2

    if args.once:
        return 0 if one_shot(args.hub, args.token, args.machine_id, args.since_days) else 1

    interval = max(60, args.interval)
    print(f"usage-agent: machine={args.machine_id} hub={args.hub} interval={interval}s")
    while True:
        try:
            one_shot(args.hub, args.token, args.machine_id, args.since_days)
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            print(f"cycle error: {e}", file=sys.stderr)
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
