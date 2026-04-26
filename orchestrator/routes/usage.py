"""
Multi-machine Claude Code usage aggregation API.

- GET  /api/usage/summary         — aggregated view (by machine/day/model)
- GET  /api/usage/machines        — known machines + last seen
- POST /api/usage/poll            — manually trigger ccusage poll on this server
- POST /api/usage/ingest          — accept pushed payload from another machine
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

import usage_tracker
from config import GLOBAL_SETTINGS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("/summary")
async def get_summary(
    since: Optional[str] = Query(None, description="YYYY-MM-DD lower bound (inclusive)"),
    machine_id: Optional[str] = Query(None, description="filter to one machine"),
):
    return await usage_tracker.summary(since=since, machine_id=machine_id)


@router.get("/machines")
async def get_machines():
    return {"machines": await usage_tracker.list_machines()}


@router.post("/poll")
async def trigger_poll(machine_id: Optional[str] = None, since: Optional[str] = None):
    """Manually run ccusage on THIS server and store rows. Useful for one-shot."""
    return await usage_tracker.poll_local(machine_id=machine_id, since=since)


@router.post("/ingest")
async def ingest(payload: dict, authorization: Optional[str] = Header(None)):
    """Accept usage rows pushed from another machine.

    Auth: if usage_ingest_token is configured, requires `Authorization: Bearer <token>`.
    Empty token in settings = open (LAN/Tailscale-only deployments).
    """
    expected = (GLOBAL_SETTINGS.get("usage_ingest_token") or "").strip()
    if expected:
        provided = (authorization or "").removeprefix("Bearer ").strip()
        if provided != expected:
            raise HTTPException(status_code=401, detail="invalid ingest token")
    try:
        n = await usage_tracker.ingest_remote(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"rows": n, "machine_id": payload.get("machine_id")}
