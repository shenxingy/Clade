"""
Usage tracker — multi-machine Claude Code usage aggregation.

Leaf module. No internal deps.

Each machine polls `ccusage --json` periodically, stores snapshots locally in
~/.claude/orchestrator/usage.db, and (optionally) pushes to a designated hub
orchestrator. The hub stores everyone's data in the same table keyed by
machine_id, so the dashboard shows per-machine breakdown of a shared account.

Architecture:
- Hub mode:   usage_hub_url empty → this orchestrator IS the hub
- Node mode:  usage_hub_url set    → poll local + push to hub
- Both:       always store locally first, then forward
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

import aiosqlite
import httpx

logger = logging.getLogger(__name__)

# ─── Paths ────────────────────────────────────────────────────────────────────

USAGE_DIR = Path.home() / ".claude" / "orchestrator"
USAGE_DB = USAGE_DIR / "usage.db"

# ─── Schema ───────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_snapshots (
    machine_id              TEXT NOT NULL,
    date                    TEXT NOT NULL,        -- YYYY-MM-DD
    model_name              TEXT NOT NULL,
    input_tokens            INTEGER NOT NULL DEFAULT 0,
    output_tokens           INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens   INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens       INTEGER NOT NULL DEFAULT 0,
    total_tokens            INTEGER NOT NULL DEFAULT 0,
    cost_usd                REAL    NOT NULL DEFAULT 0.0,
    last_seen_at            REAL    NOT NULL,
    PRIMARY KEY (machine_id, date, model_name)
);

CREATE TABLE IF NOT EXISTS usage_machines (
    machine_id      TEXT PRIMARY KEY,
    hostname        TEXT,
    first_seen_at   REAL NOT NULL,
    last_seen_at    REAL NOT NULL,
    total_polls     INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT
);

CREATE INDEX IF NOT EXISTS idx_snap_date ON usage_snapshots(date);
CREATE INDEX IF NOT EXISTS idx_snap_machine ON usage_snapshots(machine_id);
"""


# ─── DB ───────────────────────────────────────────────────────────────────────

_init_lock = asyncio.Lock()
_initialized = False


async def _ensure_db() -> None:
    global _initialized
    async with _init_lock:
        if _initialized:
            return
        USAGE_DIR.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(USAGE_DB)) as db:
            await db.executescript(_SCHEMA)
            await db.commit()
        _initialized = True


# ─── ccusage runner ───────────────────────────────────────────────────────────


def _ccusage_cmd() -> list[str]:
    """Resolve the ccusage invocation. Prefer global install; fallback to npx."""
    # Allow env override for non-standard installs
    override = os.environ.get("CLADE_CCUSAGE_CMD")
    if override:
        return override.split()
    # Try global binary first
    for binary in ("ccusage",):
        try:
            r = subprocess.run(["which", binary], capture_output=True, text=True, timeout=2)
            if r.returncode == 0 and r.stdout.strip():
                return [binary]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    # Fallback: npx (slow first run, cached after)
    return ["npx", "-y", "ccusage@latest"]


def run_ccusage(since: str | None = None, timeout: int = 90) -> list[dict]:
    """Run ccusage and return the daily breakdown list. Empty list on failure."""
    cmd = _ccusage_cmd() + ["--json"]
    if since:
        cmd += ["--since", since]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("ccusage timed out after %ss", timeout)
        return []
    except FileNotFoundError:
        logger.warning("ccusage command not found; install with `npm i -g ccusage`")
        return []
    if r.returncode != 0:
        logger.warning("ccusage exit=%s stderr=%s", r.returncode, r.stderr[:300])
        return []
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        logger.warning("ccusage json parse failed: %s", e)
        return []
    return data.get("daily", []) if isinstance(data, dict) else []


# ─── Ingestion ────────────────────────────────────────────────────────────────


def _machine_id() -> str:
    """Stable machine ID. Override with CLADE_MACHINE_ID env."""
    return os.environ.get("CLADE_MACHINE_ID") or socket.gethostname()


def _flatten_daily(daily: list[dict], machine_id: str, now: float) -> list[tuple]:
    """Flatten ccusage daily output into per-(machine, date, model) rows."""
    rows = []
    for day in daily:
        date = day.get("date") or ""
        breakdowns = day.get("modelBreakdowns") or []
        if not breakdowns:
            # ccusage always emits modelBreakdowns; if empty, skip
            continue
        for mb in breakdowns:
            rows.append((
                machine_id,
                date,
                mb.get("modelName") or "unknown",
                int(mb.get("inputTokens", 0)),
                int(mb.get("outputTokens", 0)),
                int(mb.get("cacheCreationTokens", 0)),
                int(mb.get("cacheReadTokens", 0)),
                int(mb.get("inputTokens", 0)) + int(mb.get("outputTokens", 0))
                + int(mb.get("cacheCreationTokens", 0)) + int(mb.get("cacheReadTokens", 0)),
                float(mb.get("cost", 0.0)),
                now,
            ))
    return rows


async def _upsert_machine(db, machine_id: str, hostname: str, now: float, error: str | None) -> None:
    cur = await db.execute("SELECT first_seen_at, total_polls FROM usage_machines WHERE machine_id = ?", (machine_id,))
    row = await cur.fetchone()
    if row:
        await db.execute(
            "UPDATE usage_machines SET last_seen_at = ?, total_polls = total_polls + 1, last_error = ?, hostname = ? WHERE machine_id = ?",
            (now, error, hostname, machine_id),
        )
    else:
        await db.execute(
            "INSERT INTO usage_machines (machine_id, hostname, first_seen_at, last_seen_at, total_polls, last_error) VALUES (?, ?, ?, ?, 1, ?)",
            (machine_id, hostname, now, now, error),
        )


async def store_rows(rows: list[tuple], machine_id: str, hostname: str, error: str | None = None) -> int:
    """UPSERT daily rows. Returns number of rows written."""
    await _ensure_db()
    now = time.time()
    async with aiosqlite.connect(str(USAGE_DB)) as db:
        await _upsert_machine(db, machine_id, hostname, now, error)
        if rows:
            await db.executemany(
                """
                INSERT INTO usage_snapshots
                    (machine_id, date, model_name, input_tokens, output_tokens,
                     cache_creation_tokens, cache_read_tokens, total_tokens, cost_usd, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(machine_id, date, model_name) DO UPDATE SET
                    input_tokens = excluded.input_tokens,
                    output_tokens = excluded.output_tokens,
                    cache_creation_tokens = excluded.cache_creation_tokens,
                    cache_read_tokens = excluded.cache_read_tokens,
                    total_tokens = excluded.total_tokens,
                    cost_usd = excluded.cost_usd,
                    last_seen_at = excluded.last_seen_at
                """,
                rows,
            )
        await db.commit()
    return len(rows)


async def poll_local(machine_id: str | None = None, since: str | None = None) -> dict:
    """Poll ccusage on this machine and store rows. Returns summary."""
    mid = machine_id or _machine_id()
    hostname = socket.gethostname()
    daily = await asyncio.to_thread(run_ccusage, since)
    if not daily:
        await store_rows([], mid, hostname, error="ccusage returned no data")
        return {"machine_id": mid, "rows": 0, "error": "ccusage returned no data"}
    rows = _flatten_daily(daily, mid, time.time())
    n = await store_rows(rows, mid, hostname)
    return {"machine_id": mid, "rows": n, "days": len(daily)}


# ─── Hub push (node mode) ─────────────────────────────────────────────────────


async def push_to_hub(hub_url: str, token: str, payload: dict, timeout: float = 10.0) -> bool:
    """Push usage rows to a remote hub. Returns True on 2xx."""
    url = hub_url.rstrip("/") + "/api/usage/ingest"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, json=payload, headers=headers)
            if 200 <= r.status_code < 300:
                return True
            logger.warning("hub push failed: %s %s", r.status_code, r.text[:200])
            return False
    except Exception as e:
        logger.warning("hub push error: %s", e)
        return False


def _rows_to_payload(rows: list[tuple], machine_id: str) -> dict:
    """Convert tuple rows back to JSON payload for hub ingest."""
    return {
        "machine_id": machine_id,
        "hostname": socket.gethostname(),
        "snapshots": [
            {
                "date": r[1],
                "model_name": r[2],
                "input_tokens": r[3],
                "output_tokens": r[4],
                "cache_creation_tokens": r[5],
                "cache_read_tokens": r[6],
                "total_tokens": r[7],
                "cost_usd": r[8],
            }
            for r in rows
        ],
    }


async def ingest_remote(payload: dict) -> int:
    """Hub-side: accept pushed payload, store as machine-tagged rows."""
    mid = (payload.get("machine_id") or "").strip()
    if not mid:
        raise ValueError("payload missing machine_id")
    hostname = (payload.get("hostname") or "").strip() or mid
    snapshots = payload.get("snapshots") or []
    now = time.time()
    rows = [
        (
            mid,
            s.get("date") or "",
            s.get("model_name") or "unknown",
            int(s.get("input_tokens", 0)),
            int(s.get("output_tokens", 0)),
            int(s.get("cache_creation_tokens", 0)),
            int(s.get("cache_read_tokens", 0)),
            int(s.get("total_tokens", 0)),
            float(s.get("cost_usd", 0.0)),
            now,
        )
        for s in snapshots
        if s.get("date")
    ]
    return await store_rows(rows, mid, hostname)


# ─── Read API ─────────────────────────────────────────────────────────────────


async def list_machines() -> list[dict]:
    await _ensure_db()
    async with aiosqlite.connect(str(USAGE_DB)) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT machine_id, hostname, first_seen_at, last_seen_at, total_polls, last_error FROM usage_machines ORDER BY last_seen_at DESC"
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def summary(since: str | None = None, machine_id: str | None = None) -> dict:
    """Return aggregated view: by_machine, by_day, by_model, totals."""
    await _ensure_db()
    where = []
    params: list[Any] = []
    if since:
        where.append("date >= ?")
        params.append(since)
    if machine_id:
        where.append("machine_id = ?")
        params.append(machine_id)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    async with aiosqlite.connect(str(USAGE_DB)) as db:
        db.row_factory = aiosqlite.Row

        cur = await db.execute(
            f"""SELECT machine_id, SUM(total_tokens) AS total_tokens, SUM(cost_usd) AS cost_usd
                FROM usage_snapshots {where_sql}
                GROUP BY machine_id ORDER BY cost_usd DESC""",
            params,
        )
        by_machine = [dict(r) for r in await cur.fetchall()]

        cur = await db.execute(
            f"""SELECT date, SUM(total_tokens) AS total_tokens, SUM(cost_usd) AS cost_usd
                FROM usage_snapshots {where_sql}
                GROUP BY date ORDER BY date DESC LIMIT 60""",
            params,
        )
        by_day = [dict(r) for r in await cur.fetchall()]

        cur = await db.execute(
            f"""SELECT model_name, SUM(total_tokens) AS total_tokens, SUM(cost_usd) AS cost_usd
                FROM usage_snapshots {where_sql}
                GROUP BY model_name ORDER BY cost_usd DESC""",
            params,
        )
        by_model = [dict(r) for r in await cur.fetchall()]

        cur = await db.execute(
            f"""SELECT machine_id, date, model_name, total_tokens, cost_usd
                FROM usage_snapshots {where_sql}
                ORDER BY date DESC, cost_usd DESC LIMIT 200""",
            params,
        )
        recent = [dict(r) for r in await cur.fetchall()]

        cur = await db.execute(
            f"""SELECT SUM(total_tokens) AS total_tokens, SUM(cost_usd) AS cost_usd, COUNT(DISTINCT machine_id) AS machines
                FROM usage_snapshots {where_sql}""",
            params,
        )
        totals_row = await cur.fetchone()
        totals = dict(totals_row) if totals_row else {}

    return {
        "totals": totals,
        "by_machine": by_machine,
        "by_day": by_day,
        "by_model": by_model,
        "recent": recent,
    }


# ─── Background poller ────────────────────────────────────────────────────────


_poller_task: asyncio.Task | None = None


async def _poller_loop(interval_sec: int, hub_url: str, hub_token: str, since_days: int) -> None:
    """Run forever: poll locally, push to hub if configured."""
    mid = _machine_id()
    # Stagger first poll a few seconds after startup
    await asyncio.sleep(5)
    while True:
        try:
            since = None
            if since_days > 0:
                from datetime import date, timedelta
                since = (date.today() - timedelta(days=since_days)).strftime("%Y%m%d")
            result = await poll_local(mid, since=since)
            logger.info("usage poll: %s", result)
            if hub_url and result.get("rows"):
                # Re-read just-stored rows to push (filter by machine + since)
                await _ensure_db()
                async with aiosqlite.connect(str(USAGE_DB)) as db:
                    cur = await db.execute(
                        """SELECT machine_id, date, model_name, input_tokens, output_tokens,
                                  cache_creation_tokens, cache_read_tokens, total_tokens, cost_usd, last_seen_at
                           FROM usage_snapshots WHERE machine_id = ?""" + (" AND date >= ?" if since else ""),
                        (mid, since[:4] + "-" + since[4:6] + "-" + since[6:8]) if since else (mid,),
                    )
                    rows = list(await cur.fetchall())
                payload = _rows_to_payload(rows, mid)
                ok = await push_to_hub(hub_url, hub_token, payload)
                logger.info("usage push to hub: %s (%d rows)", "ok" if ok else "FAIL", len(rows))
        except Exception as e:
            logger.exception("usage poller error: %s", e)
        await asyncio.sleep(max(60, interval_sec))


def start_poller(interval_sec: int, hub_url: str = "", hub_token: str = "", since_days: int = 7) -> None:
    """Idempotent — start the background poller if not already running."""
    global _poller_task
    if _poller_task and not _poller_task.done():
        return
    _poller_task = asyncio.create_task(_poller_loop(interval_sec, hub_url, hub_token, since_days))


async def stop_poller() -> None:
    global _poller_task
    if _poller_task and not _poller_task.done():
        _poller_task.cancel()
        with suppress(asyncio.CancelledError):
            await _poller_task
    _poller_task = None
