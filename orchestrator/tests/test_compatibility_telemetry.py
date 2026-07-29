"""Compatibility retirement stays observable, secret-free, and idempotent."""

from __future__ import annotations

import json

import aiosqlite
import pytest

import compatibility_telemetry as telemetry
from task_queue import TaskQueue


def test_counter_records_only_allowlisted_identifier_count_and_time(
    tmp_path, monkeypatch
):
    path = tmp_path / "compatibility-telemetry.json"
    monkeypatch.setattr(telemetry, "_telemetry_file", path)

    telemetry.record_compatibility_use(telemetry.TASKS_API_PROVIDER)
    telemetry.record_compatibility_use(telemetry.TASKS_API_PROVIDER, count=2)
    snapshot = json.loads(path.read_text())

    assert snapshot["schema_version"] == telemetry.SCHEMA_VERSION
    assert snapshot["events"][telemetry.TASKS_API_PROVIDER]["count"] == 3
    serialized = path.read_text()
    assert "credential" not in serialized
    assert "endpoint" not in serialized
    assert path.stat().st_mode & 0o777 == 0o600


def test_counter_rejects_dynamic_event_names(tmp_path, monkeypatch):
    monkeypatch.setattr(
        telemetry, "_telemetry_file", tmp_path / "compatibility-telemetry.json"
    )

    with pytest.raises(ValueError, match="Unknown compatibility event"):
        telemetry.record_compatibility_use("settings.secret-value")


async def test_sqlite_provider_backfill_is_idempotent_and_api_is_canonical(
    tmp_claude_dir, tmp_path, monkeypatch
):
    telemetry_path = tmp_path / "compatibility-telemetry.json"
    monkeypatch.setattr(telemetry, "_telemetry_file", telemetry_path)
    initial = TaskQueue(tmp_claude_dir)
    task = await initial.add("Migrate one historical provider row")
    async with aiosqlite.connect(str(initial._db_path)) as db:
        await db.execute(
            "UPDATE tasks SET agent_runtime = NULL, provider = 'codex' WHERE id = ?",
            (task["id"],),
        )
        await db.commit()

    migrated = TaskQueue(tmp_claude_dir)
    fetched = await migrated.get(task["id"])
    assert fetched["agent_runtime"] == "codex"
    assert "provider" not in fetched
    assert (
        telemetry.read_compatibility_telemetry()["events"]
        [telemetry.TASKS_SQLITE_PROVIDER]["count"]
        == 1
    )

    repeated = TaskQueue(tmp_claude_dir)
    await repeated._ensure_db()
    assert (
        telemetry.read_compatibility_telemetry()["events"]
        [telemetry.TASKS_SQLITE_PROVIDER]["count"]
        == 1
    )
