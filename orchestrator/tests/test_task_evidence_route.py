"""Task detail evidence API tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routes.tasks import get_task_evidence


async def test_task_evidence_route_returns_empty_attempts(task_queue):
    task = await task_queue.add("Task without attempts")

    response = await get_task_evidence(
        task["id"], s=SimpleNamespace(task_queue=task_queue)
    )

    assert response == {"task_id": task["id"], "attempts": []}


async def test_task_evidence_route_returns_latest_ordered_attempts(task_queue):
    task = await task_queue.add("Task with retry evidence")
    first = await task_queue.create_evidence_attempt(
        task["id"], attempt_id="attempt-first"
    )
    await task_queue.append_evidence_bundle(
        first["attempt_id"], lifecycle_state="running"
    )
    second = await task_queue.create_evidence_attempt(
        task["id"], attempt_id="attempt-second"
    )

    response = await get_task_evidence(
        task["id"], s=SimpleNamespace(task_queue=task_queue)
    )

    assert [item["attempt_id"] for item in response["attempts"]] == [
        "attempt-first",
        "attempt-second",
    ]
    assert [item["revision"] for item in response["attempts"]] == [2, 1]


async def test_task_evidence_route_rejects_unknown_task(task_queue):
    with pytest.raises(HTTPException) as error:
        await get_task_evidence(
            "missing", s=SimpleNamespace(task_queue=task_queue)
        )

    assert error.value.status_code == 404
