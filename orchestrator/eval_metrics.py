"""Read-only, denominator-explicit evidence and eval quality metrics."""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite


SCHEMA_VERSION = "clade.eval_metrics/v1"
_TERMINAL = {"delivery_pending", "delivered", "failed", "cancelled", "reverted"}
_WORKER_TERMINAL_FIELDS = {
    "worker_envelope",
    "timing",
    "git",
    "verification",
    "usage",
    "artifacts",
    "delivery_candidate",
}


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _load_json(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _terminal_complete(evidence: dict) -> bool:
    failure = evidence.get("failure")
    if isinstance(failure, dict) and failure.get("stage") in {"preflight", "spawn"}:
        return bool(evidence.get("timing", {}).get("finished_at"))
    return _WORKER_TERMINAL_FIELDS <= set(evidence)


def _corpus_fixture(candidate: dict, evals_root: Path) -> dict | None:
    ref = candidate.get("promotion_ref")
    if not isinstance(ref, str) or not ref.startswith("evals/"):
        return None
    path = evals_root / ref.removeprefix("evals/")
    try:
        fixture = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    provenance = fixture.get("promotion_provenance", {})
    if (
        provenance.get("candidate_id") != candidate["candidate_id"]
        or provenance.get("source_evidence_digest")
        != candidate["source_evidence_digest"]
    ):
        return None
    return fixture


async def compute_eval_metrics(db_path: Path, evals_root: Path) -> dict:
    """Compute auditable ratios from persisted evidence and promoted corpora."""

    async with aiosqlite.connect(str(db_path)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT current.*
               FROM evidence_bundles AS current
               JOIN (
                   SELECT attempt_id, MAX(revision) AS revision
                   FROM evidence_bundles GROUP BY attempt_id
               ) AS latest
               ON current.attempt_id = latest.attempt_id
               AND current.revision = latest.revision"""
        ) as cursor:
            latest_rows = [dict(row) for row in await cursor.fetchall()]
        async with db.execute("SELECT * FROM eval_candidates") as cursor:
            candidates = [dict(row) for row in await cursor.fetchall()]
        async with db.execute(
            """SELECT attempt_id, revision, payload_digest, evidence_json
               FROM evidence_bundles"""
        ) as cursor:
            evidence_rows = [dict(row) for row in await cursor.fetchall()]

    exact_evidence = {
        (row["attempt_id"], row["revision"], row["payload_digest"]): _load_json(
            row["evidence_json"]
        )
        for row in evidence_rows
    }
    terminal = [
        row for row in latest_rows if row["lifecycle_state"] in _TERMINAL
    ]
    complete = sum(
        _terminal_complete(_load_json(row["evidence_json"])) for row in terminal
    )
    verified_deliveries = sum(
        row["lifecycle_state"] == "delivered"
        and _terminal_complete(evidence)
        and evidence.get("verification", {}).get("oracle_verdict") == "approved"
        and evidence.get("delivery_candidate", {}).get("eligible") is True
        for row in terminal
        for evidence in [_load_json(row["evidence_json"])]
    )
    approved_attempts = sum(
        _load_json(row["evidence_json"])
        .get("verification", {})
        .get("oracle_verdict")
        == "approved"
        for row in latest_rows
    )

    status_counts = {
        status: sum(row["status"] == status for row in candidates)
        for status in ("quarantined", "promoted", "rejected", "expired")
    }
    source_valid = 0
    false_approved_attempts: set[str] = set()
    covered_promotions = 0
    comparable_promotions = 0
    human_overrides = 0
    for candidate in candidates:
        key = (
            candidate["source_attempt_id"],
            candidate["source_attempt_revision"],
            candidate["source_evidence_digest"],
        )
        source = exact_evidence.get(key)
        if source is not None:
            source_valid += 1
        fixture = (
            _corpus_fixture(candidate, evals_root)
            if candidate["status"] == "promoted"
            else None
        )
        if fixture is not None:
            covered_promotions += 1
        observed = (
            source.get("verification", {}).get("oracle_verdict")
            if source is not None
            else None
        )
        expected = fixture.get("expected_verdict") if fixture else None
        if (
            candidate["status"] == "promoted"
            and observed == "approved"
            and fixture is not None
            and (
                expected == "rejected"
                or candidate.get("promotion_kind") == "resolve_case"
            )
        ):
            false_approved_attempts.add(candidate["source_attempt_id"])
        if observed in {"approved", "rejected"} and expected in {
            "approved",
            "rejected",
        }:
            comparable_promotions += 1
            human_overrides += observed != expected

    promoted = status_counts["promoted"]
    total_candidates = len(candidates)
    return {
        "schema_version": SCHEMA_VERSION,
        "candidates": {"total": total_candidates, **status_counts},
        "north_star": {
            "metric": "verified_delivery_rate",
            "verified_deliveries": verified_deliveries,
            "terminal_attempts": len(terminal),
            "rate": _ratio(verified_deliveries, len(terminal)),
        },
        "evidence_completeness": {
            "complete": complete,
            "terminal_attempts": len(terminal),
            "rate": _ratio(complete, len(terminal)),
        },
        "source_integrity": {
            "valid": source_valid,
            "candidates": total_candidates,
            "rate": _ratio(source_valid, total_candidates),
        },
        "false_approvals": {
            "confirmed": len(false_approved_attempts),
            "oracle_approved_attempts": approved_attempts,
            "rate": _ratio(len(false_approved_attempts), approved_attempts),
        },
        "human_overrides": {
            "count": human_overrides,
            "comparable_promotions": comparable_promotions,
            "rate": _ratio(human_overrides, comparable_promotions),
        },
        "accepted_regression_coverage": {
            "covered": covered_promotions,
            "promoted": promoted,
            "rate": _ratio(covered_promotions, promoted),
        },
    }
