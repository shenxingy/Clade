"""GitHub webhook handler for Claude Code Orchestrator."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from config import GLOBAL_SETTINGS
from session import registry

logger = logging.getLogger(__name__)

router = APIRouter()

# ─── Signature verification ────────────────────────────────────────────────────


def _verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 GitHub webhook signature."""
    if not secret:
        return True  # no secret configured → open endpoint
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ─── Webhook endpoint ──────────────────────────────────────────────────────────


@router.post("/api/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
):
    """Receive and process GitHub webhook events."""
    body = await request.body()
    secret = GLOBAL_SETTINGS.get("webhook_secret", "")

    if secret and not _verify_signature(body, x_hub_signature_256, secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    session = registry.default()
    if session is None:
        raise HTTPException(status_code=503, detail="No active session")

    task_queue = session.task_queue
    description: str | None = None
    source_ref: str | None = None

    # ─── issues event ─────────────────────────────────────────────────────────
    if x_github_event == "issues":
        action = payload.get("action", "")
        issue = payload.get("issue", {})
        issue_number = issue.get("number")
        issue_title = issue.get("title", "")
        issue_body = issue.get("body", "") or ""
        label_names = [lbl.get("name", "") for lbl in issue.get("labels", [])]

        if action in ("labeled", "opened") and "claude-do-it" in label_names:
            source_ref = f"github/issue/{issue_number}"
            description = (
                f"GitHub Issue #{issue_number}: {issue_title}\n\n{issue_body}"
            ).strip()

    # ─── issue_comment event ───────────────────────────────────────────────────
    elif x_github_event == "issue_comment":
        action = payload.get("action", "")
        comment = payload.get("comment", {})
        comment_body = (comment.get("body", "") or "").strip()
        issue = payload.get("issue", {})
        issue_number = issue.get("number")
        comment_id = comment.get("id")

        if action == "created" and comment_body.startswith("/claude "):
            instruction = comment_body[len("/claude "):].strip()
            source_ref = f"github/comment/{comment_id}"
            issue_title = issue.get("title", "")
            description = (
                f"GitHub Issue #{issue_number} ({issue_title}) — /claude instruction:\n\n"
                f"{instruction}"
            )

    if description is None or source_ref is None:
        return {"status": "ignored"}

    # ─── Deduplication: skip if a pending/running task with same source_ref exists
    existing_tasks = await task_queue.list()
    for t in existing_tasks:
        if t.get("source_ref") == source_ref and t.get("status") not in (
            "completed", "failed", "cancelled"
        ):
            logger.info("Skipping duplicate webhook event source_ref=%s", source_ref)
            return {"status": "duplicate", "source_ref": source_ref}

    task = await task_queue.add(description=description)
    logger.info(
        "Queued task %s from GitHub webhook event=%s source_ref=%s",
        task["id"], x_github_event, source_ref,
    )
    return {"status": "queued", "task_id": task["id"], "source_ref": source_ref}
