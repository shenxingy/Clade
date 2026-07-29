"""Evidence/eval metrics keep explicit, auditable denominators."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from eval_metrics import compute_eval_metrics
from eval_review import promote_candidate
from routes.evals import metrics as metrics_route


async def _approved_attempt(task_queue):
    task = await task_queue.add("Ship then discover a regression")
    attempt = await task_queue.create_evidence_attempt(
        task["id"], attempt_id="attempt-approved"
    )
    await task_queue.append_evidence_bundle(
        attempt["attempt_id"], lifecycle_state="running"
    )
    await task_queue.append_evidence_bundle(
        attempt["attempt_id"], lifecycle_state="verifying"
    )
    terminal = await task_queue.append_evidence_bundle(
        attempt["attempt_id"],
        lifecycle_state="delivered",
        evidence={
            "worker_envelope": {"status": "done"},
            "timing": {"finished_at": 10.0},
            "git": {"base_sha": "a", "head_sha": "b"},
            "verification": {"oracle_verdict": "approved"},
            "usage": {"input_tokens": 1},
            "artifacts": {"changed_files": ["a.py"]},
            "delivery_candidate": {"eligible": True},
        },
    )
    return terminal


async def test_metrics_link_false_approve_override_coverage_and_evidence(
    task_queue, tmp_path
):
    source = await _approved_attempt(task_queue)
    candidate, _ = await task_queue.create_eval_candidate(
        source["attempt_id"],
        trigger="managed_revert",
        diff="diff --git a/a.py b/a.py\n+regression\n",
        source_attempt_revision=source["revision"],
        source_evidence_digest=source["digest"],
    )
    await promote_candidate(
        task_queue,
        candidate["candidate_id"],
        target="oracle",
        reviewer="alex",
        reason="Reproduced after delivery",
        case={
            "id": "confirmed-false-approve",
            "category": "reject-quality",
            "task": "Avoid the regression",
            "expected_verdict": "rejected",
            "rationale": "Human confirmed the approved patch was defective.",
        },
        evals_root=tmp_path,
    )

    report = await compute_eval_metrics(task_queue._db_path, tmp_path)

    assert report["schema_version"] == "clade.eval_metrics/v1"
    assert report["candidates"] == {
        "total": 1,
        "quarantined": 0,
        "promoted": 1,
        "rejected": 0,
        "expired": 0,
    }
    assert report["north_star"] == {
        "metric": "verified_delivery_rate",
        "verified_deliveries": 1,
        "terminal_attempts": 1,
        "rate": 1.0,
    }
    assert report["evidence_completeness"] == {
        "complete": 1,
        "terminal_attempts": 1,
        "rate": 1.0,
    }
    assert report["source_integrity"]["rate"] == 1.0
    assert report["false_approvals"] == {
        "confirmed": 1,
        "oracle_approved_attempts": 1,
        "rate": 1.0,
    }
    assert report["human_overrides"] == {
        "count": 1,
        "comparable_promotions": 1,
        "rate": 1.0,
    }
    assert report["accepted_regression_coverage"] == {
        "covered": 1,
        "promoted": 1,
        "rate": 1.0,
    }


async def test_metrics_use_null_not_zero_without_a_denominator(
    task_queue, tmp_path
):
    report = await compute_eval_metrics(task_queue._db_path, tmp_path)

    assert report["north_star"]["rate"] is None
    assert report["evidence_completeness"]["rate"] is None
    assert report["source_integrity"]["rate"] is None
    assert report["false_approvals"]["rate"] is None
    assert report["human_overrides"]["rate"] is None
    assert report["accepted_regression_coverage"]["rate"] is None


async def test_north_star_counts_strict_deliveries_over_all_terminal_attempts(
    task_queue, tmp_path
):
    await _approved_attempt(task_queue)
    failed_task = await task_queue.add("Fail one bounded delivery")
    failed = await task_queue.create_evidence_attempt(
        failed_task["id"], attempt_id="attempt-failed"
    )
    await task_queue.append_evidence_bundle(
        failed["attempt_id"], lifecycle_state="running"
    )
    await task_queue.append_evidence_bundle(
        failed["attempt_id"],
        lifecycle_state="failed",
        evidence={
            "worker_envelope": {"status": "failed"},
            "timing": {"finished_at": 12.0},
            "git": {"base_sha": "a", "head_sha": "a"},
            "verification": {"oracle_verdict": "rejected"},
            "usage": {"input_tokens": 1},
            "artifacts": {"changed_files": []},
            "delivery_candidate": {"eligible": False},
        },
    )

    report = await compute_eval_metrics(task_queue._db_path, tmp_path)

    assert report["north_star"] == {
        "metric": "verified_delivery_rate",
        "verified_deliveries": 1,
        "terminal_attempts": 2,
        "rate": 0.5,
    }


async def test_missing_corpus_file_is_visible_as_uncovered(
    task_queue, tmp_path
):
    source = await _approved_attempt(task_queue)
    candidate, _ = await task_queue.create_eval_candidate(
        source["attempt_id"],
        trigger="managed_revert",
        diff="diff --git a/a.py b/a.py\n+regression\n",
    )
    promoted = await promote_candidate(
        task_queue,
        candidate["candidate_id"],
        target="oracle",
        reviewer="alex",
        reason="confirmed",
        case={
            "id": "missing-after-promotion",
            "category": "reject-quality",
            "task": "Avoid regression",
            "expected_verdict": "rejected",
            "rationale": "Confirmed.",
        },
        evals_root=tmp_path,
    )
    Path(promoted["corpus_path"]).unlink()

    report = await compute_eval_metrics(task_queue._db_path, tmp_path)

    assert report["accepted_regression_coverage"] == {
        "covered": 0,
        "promoted": 1,
        "rate": 0.0,
    }
    assert report["false_approvals"]["confirmed"] == 0


async def test_metrics_route_uses_session_database(
    task_queue, tmp_path, monkeypatch
):
    monkeypatch.setattr("routes.evals.EVALS_ROOT", tmp_path)
    response = await metrics_route(
        s=SimpleNamespace(task_queue=task_queue)
    )
    assert response["schema_version"] == "clade.eval_metrics/v1"
