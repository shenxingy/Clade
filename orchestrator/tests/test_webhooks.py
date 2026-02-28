"""Tests for GitHub webhook endpoint (routes/webhooks.py)."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from task_queue import TaskQueue

TEST_SECRET = "test-webhook-secret-xyz"


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_sig(body: bytes, secret: str = TEST_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _issues_payload(issue_number: int = 1, action: str = "labeled",
                    labels: list[str] | None = None) -> bytes:
    return json.dumps({
        "action": action,
        "issue": {
            "number": issue_number,
            "title": "Fix the bug",
            "body": "It is broken",
            "labels": [{"name": lbl} for lbl in (labels or [])],
        },
    }).encode()


def _comment_payload(issue_number: int = 2, comment_id: int = 99,
                     body: str = "/claude fix the memory leak") -> bytes:
    return json.dumps({
        "action": "created",
        "issue": {"number": issue_number, "title": "Memory leak"},
        "comment": {"id": comment_id, "body": body},
    }).encode()


# ─── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture
def webhook_app(task_queue: TaskQueue):
    """Minimal FastAPI app with the webhook router + mocked deps."""
    from routes.webhooks import router

    app = FastAPI()
    app.include_router(router)

    mock_session = MagicMock()
    mock_session.task_queue = task_queue

    # These patches are applied for the lifetime of the test via the fixture context.
    # Using monkeypatch here would require a sync fixture; we use unittest.mock instead.
    _patches = [
        patch("routes.webhooks.GLOBAL_SETTINGS", {"webhook_secret": TEST_SECRET}),
        patch("routes.webhooks.registry") ,
    ]
    started = [p.start() for p in _patches]
    mock_registry = started[1]
    mock_registry.default.return_value = mock_session

    yield app

    for p in _patches:
        p.stop()


# ─── Signature validation ─────────────────────────────────────────────────────


async def test_missing_signature_rejected(webhook_app: FastAPI):
    """No X-Hub-Signature-256 header → 403 when secret is configured."""
    async with AsyncClient(
        transport=ASGITransport(app=webhook_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/webhooks/github",
            content=b"{}",
            headers={"X-GitHub-Event": "ping"},
        )
    assert resp.status_code == 403


async def test_wrong_signature_rejected(webhook_app: FastAPI):
    """Wrong HMAC signature → 403."""
    body = _issues_payload(labels=["claude-do-it"])
    async with AsyncClient(
        transport=ASGITransport(app=webhook_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": "sha256=deadbeef",
            },
        )
    assert resp.status_code == 403


# ─── Task creation ────────────────────────────────────────────────────────────


async def test_issue_labeled_creates_task(webhook_app: FastAPI, task_queue: TaskQueue):
    """issues event with 'claude-do-it' label → 200 + task added to queue."""
    body = _issues_payload(issue_number=5, action="labeled", labels=["claude-do-it"])
    sig = _make_sig(body)
    async with AsyncClient(
        transport=ASGITransport(app=webhook_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/webhooks/github",
            content=body,
            headers={"X-GitHub-Event": "issues", "X-Hub-Signature-256": sig},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert data["source_ref"] == "github/issue/5"

    tasks = await task_queue.list()
    assert any(t["source_ref"] == "github/issue/5" for t in tasks)


async def test_duplicate_source_ref_skipped(webhook_app: FastAPI, task_queue: TaskQueue):
    """Same source_ref sent twice → second returns 200 but no new task created."""
    body = _issues_payload(issue_number=7, action="labeled", labels=["claude-do-it"])
    sig = _make_sig(body)
    headers = {"X-GitHub-Event": "issues", "X-Hub-Signature-256": sig}

    async with AsyncClient(
        transport=ASGITransport(app=webhook_app), base_url="http://test"
    ) as client:
        resp1 = await client.post("/api/webhooks/github", content=body, headers=headers)
        resp2 = await client.post("/api/webhooks/github", content=body, headers=headers)

    assert resp1.status_code == 200
    assert resp1.json()["status"] == "queued"
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "duplicate"

    tasks = await task_queue.list()
    matching = [t for t in tasks if t.get("source_ref") == "github/issue/7"]
    assert len(matching) == 1


async def test_issue_comment_creates_task(webhook_app: FastAPI, task_queue: TaskQueue):
    """issue_comment event with /claude prefix → task created."""
    body = _comment_payload(issue_number=3, comment_id=55, body="/claude fix memory leak")
    sig = _make_sig(body)
    async with AsyncClient(
        transport=ASGITransport(app=webhook_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/webhooks/github",
            content=body,
            headers={"X-GitHub-Event": "issue_comment", "X-Hub-Signature-256": sig},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert data["source_ref"] == "github/comment/55"

    tasks = await task_queue.list()
    assert any(t["source_ref"] == "github/comment/55" for t in tasks)
