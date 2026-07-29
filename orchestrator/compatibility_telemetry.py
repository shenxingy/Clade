"""Secret-free counters for compatibility-window decisions.

Only a fixed event identifier, a count, and timestamps are persisted.  Values
from settings, task payloads, database rows, endpoints, and credentials never
cross this boundary.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

SCHEMA_VERSION: Final = "clade.compatibility_telemetry/v1"
SETTINGS_WORKER_PROVIDER: Final = "settings.worker_provider"
TASKS_API_PROVIDER: Final = "tasks.api.provider"
TASKS_SQLITE_PROVIDER: Final = "tasks.sqlite.provider_backfill"

_ALLOWED_EVENTS: Final = frozenset(
    {
        SETTINGS_WORKER_PROVIDER,
        TASKS_API_PROVIDER,
        TASKS_SQLITE_PROVIDER,
    }
)
_telemetry_file = Path.home() / ".claude" / "compatibility-telemetry.json"
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty(observed_at: str | None = None) -> dict:
    timestamp = observed_at or _now()
    return {
        "schema_version": SCHEMA_VERSION,
        "window_started_at": timestamp,
        "observed_at": timestamp,
        "events": {},
    }


def read_compatibility_telemetry() -> dict:
    """Return a normalized snapshot; corrupt state starts a visible new window."""

    try:
        payload = json.loads(_telemetry_file.read_text())
    except FileNotFoundError:
        return _empty()
    except Exception as exc:
        logger.warning("compatibility telemetry is unreadable (%s); starting new window", exc)
        return _empty()
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        logger.warning("compatibility telemetry has an unsupported schema; starting new window")
        return _empty()
    events = payload.get("events")
    if not isinstance(events, dict):
        return _empty()
    sanitized = {
        key: value
        for key, value in events.items()
        if key in _ALLOWED_EVENTS and isinstance(value, dict)
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "window_started_at": payload.get("window_started_at") or _now(),
        "observed_at": payload.get("observed_at") or _now(),
        "events": sanitized,
    }


def record_compatibility_use(event: str, count: int = 1) -> None:
    """Atomically increment one allowlisted event without recording its value."""

    if event not in _ALLOWED_EVENTS:
        raise ValueError(f"Unknown compatibility event: {event}")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError("Compatibility event count must be a positive integer")
    try:
        with _lock:
            payload = read_compatibility_telemetry()
            timestamp = _now()
            current = payload["events"].get(event) or {}
            payload["events"][event] = {
                "count": int(current.get("count") or 0) + count,
                "first_seen_at": current.get("first_seen_at") or timestamp,
                "last_seen_at": timestamp,
            }
            payload["observed_at"] = timestamp
            _telemetry_file.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(_telemetry_file.parent, 0o700)
            temporary = _telemetry_file.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(payload, indent=2) + "\n")
            os.chmod(temporary, 0o600)
            temporary.replace(_telemetry_file)
    except Exception as exc:
        logger.warning("could not persist compatibility telemetry: %s", exc)
