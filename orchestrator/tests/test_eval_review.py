"""Human-only eval review writes validated corpora with full provenance."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from eval_review import (
    EvalReviewConflict,
    EvalReviewError,
    promote_candidate,
    reject_candidate,
)
from routes.evals import get_candidate, promote, reject


GITHUB_TOKEN = "ghp_" + "A" * 40


def _load_eval_module(name: str):
    path = Path(__file__).parent.parent / "evals" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_review_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


ORACLE_EVAL = _load_eval_module("run_oracle_eval")
RESOLVE_EVAL = _load_eval_module("run_resolve_eval")


async def _candidate(
    task_queue,
    *,
    attempt_id: str = "attempt-review",
    trigger: str = "oracle_rejected",
    diff: str = "diff --git a/a.py b/a.py\n+fixed\n",
):
    task = await task_queue.add("Review a production failure")
    source = await task_queue.create_evidence_attempt(
        task["id"],
        attempt_id=attempt_id,
        bundle_id=f"bundle-{attempt_id}",
    )
    candidate, _ = await task_queue.create_eval_candidate(
        source["attempt_id"],
        trigger=trigger,
        diff=diff,
        payload={"observed": "rejected"},
    )
    return candidate


def _oracle_case(case_id: str = "production-parser-regression"):
    return {
        "id": case_id,
        "category": "reject-quality",
        "task": "Fix the parser without deleting comments",
        "expected_verdict": "rejected",
        "rationale": "Human reproduced the destructive edit.",
        "test_evidence": {
            "tests_passed": False,
            "test_output": "1 failed",
            "reg_warning": "",
        },
    }


async def test_oracle_promotion_is_explicit_atomic_and_provenanced(
    task_queue, tmp_path
):
    candidate = await _candidate(task_queue)
    case = _oracle_case()
    case["task"] += f" token={GITHUB_TOKEN} /home/alex/private"
    result = await promote_candidate(
        task_queue,
        candidate["candidate_id"],
        target="oracle",
        reviewer="alex",
        reason=f"Reproduced locally with {GITHUB_TOKEN}",
        case=case,
        evals_root=tmp_path,
    )

    decided = result["candidate"]
    assert decided["status"] == "promoted"
    assert decided["decided_by"] == "alex"
    assert decided["promotion_kind"] == "oracle_case"
    assert decided["promotion_ref"] == (
        "evals/oracle_cases/production-parser-regression.json"
    )
    fixture_path = tmp_path / "oracle_cases" / "production-parser-regression.json"
    fixture = json.loads(fixture_path.read_text())
    assert ORACLE_EVAL.validate_case(fixture, fixture_path.name) == []
    assert fixture["diff"] == candidate["payload"]["diff"]
    provenance = fixture["promotion_provenance"]
    assert provenance["candidate_id"] == candidate["candidate_id"]
    assert provenance["source_attempt_revision"] == (
        candidate["source_attempt_revision"]
    )
    assert provenance["source_evidence_digest"] == (
        candidate["source_evidence_digest"]
    )
    assert provenance["redaction_metadata"]["count"] == 3
    assert GITHUB_TOKEN not in fixture_path.read_text()
    assert "/home/alex" not in fixture_path.read_text()

    with pytest.raises(EvalReviewConflict, match="already decided"):
        await promote_candidate(
            task_queue,
            candidate["candidate_id"],
            target="oracle",
            reviewer="alex",
            reason="repeat",
            case=case,
            evals_root=tmp_path,
        )


async def test_reject_never_writes_corpus_and_cannot_be_redecided(
    task_queue, tmp_path
):
    candidate = await _candidate(task_queue)
    rejected = await reject_candidate(
        task_queue,
        candidate["candidate_id"],
        reviewer="alex",
        reason="Not reproducible after environment repair",
    )

    assert rejected["status"] == "rejected"
    assert rejected["promotion_kind"] is None
    assert rejected["promotion_ref"] is None
    assert not list(tmp_path.rglob("*.json"))
    with pytest.raises(EvalReviewConflict, match="already decided"):
        await reject_candidate(
            task_queue,
            candidate["candidate_id"],
            reviewer="alex",
            reason="second verdict",
        )


async def test_conflicting_case_does_not_decide_second_candidate(
    task_queue, tmp_path
):
    first = await _candidate(task_queue, attempt_id="attempt-first")
    second = await _candidate(
        task_queue,
        attempt_id="attempt-second",
        diff="diff --git a/b.py b/b.py\n+different\n",
    )
    await promote_candidate(
        task_queue,
        first["candidate_id"],
        target="oracle",
        reviewer="alex",
        reason="first label",
        case=_oracle_case("shared-id"),
        evals_root=tmp_path,
    )

    with pytest.raises(EvalReviewConflict, match="already exists"):
        await promote_candidate(
            task_queue,
            second["candidate_id"],
            target="oracle",
            reviewer="alex",
            reason="second label",
            case={**_oracle_case("shared-id"), "rationale": "different"},
            evals_root=tmp_path,
        )
    assert (await task_queue.get_eval_candidate(
        second["candidate_id"]
    ))["status"] == "quarantined"


async def test_database_failure_removes_new_corpus_file(task_queue, tmp_path):
    candidate = await _candidate(task_queue)
    queue = SimpleNamespace(
        get_eval_candidate=AsyncMock(return_value=candidate),
        decide_eval_candidate=AsyncMock(side_effect=RuntimeError("db unavailable")),
    )

    with pytest.raises(RuntimeError, match="db unavailable"):
        await promote_candidate(
            queue,
            candidate["candidate_id"],
            target="oracle",
            reviewer="alex",
            reason="confirmed",
            case=_oracle_case("rollback-case"),
            evals_root=tmp_path,
        )
    assert not (tmp_path / "oracle_cases" / "rollback-case.json").exists()


async def test_resolve_promotion_requires_human_test_contract(
    task_queue, tmp_path
):
    candidate = await _candidate(task_queue, trigger="incident_failure")
    case = {
        "instance_id": "real-resolve-case",
        "repo": "owner/repo",
        "base_commit": "abc123",
        "problem_statement": "Parser deletes comments.",
        "FAIL_TO_PASS": ["tests/test_parser.py::test_comments"],
        "PASS_TO_PASS": ["tests/test_parser.py::test_basic"],
        "test_cmd": "python -m pytest -q",
    }
    result = await promote_candidate(
        task_queue,
        candidate["candidate_id"],
        target="resolve",
        reviewer="alex",
        reason="Reproduced with a deterministic test",
        case=case,
        evals_root=tmp_path,
    )

    fixture = json.loads(
        (tmp_path / "resolve_cases" / "real-resolve-case.json").read_text()
    )
    assert RESOLVE_EVAL.validate_instance(fixture, "real-resolve-case.json") == []
    assert result["candidate"]["promotion_kind"] == "resolve_case"
    assert fixture["observed_patch"] == candidate["payload"]["diff"]
    assert fixture["promotion_provenance"]["candidate_id"] == (
        candidate["candidate_id"]
    )


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"target": "automatic"}, "target"),
        ({"reviewer": ""}, "reviewer and reason"),
        ({"reviewer": GITHUB_TOKEN}, "non-sensitive stable identifier"),
        ({"reason": ""}, "reviewer and reason"),
        ({"case": {"id": "../escape"}}, "lowercase letters"),
    ],
)
async def test_promotion_validation_fails_closed(
    task_queue, tmp_path, kwargs, message
):
    candidate = await _candidate(task_queue)
    request = {
        "target": "oracle",
        "reviewer": "alex",
        "reason": "confirmed",
        "case": _oracle_case(),
        **kwargs,
    }
    with pytest.raises(EvalReviewError, match=message):
        await promote_candidate(
            task_queue,
            candidate["candidate_id"],
            evals_root=tmp_path,
            **request,
        )
    assert (await task_queue.get_eval_candidate(
        candidate["candidate_id"]
    ))["status"] == "quarantined"


async def test_review_routes_surface_not_found_validation_and_conflict(
    task_queue, monkeypatch
):
    session = SimpleNamespace(task_queue=task_queue)
    with pytest.raises(HTTPException) as missing:
        await get_candidate("eval-missing", s=session)
    assert missing.value.status_code == 404

    candidate = await _candidate(task_queue)
    monkeypatch.setattr(
        "routes.evals.promote_candidate",
        AsyncMock(side_effect=EvalReviewError("human label required")),
    )
    with pytest.raises(HTTPException) as invalid:
        await promote(candidate["candidate_id"], {}, s=session)
    assert invalid.value.status_code == 400

    await reject(
        candidate["candidate_id"],
        {"reviewer": "alex", "reason": "duplicate"},
        s=session,
    )
    with pytest.raises(HTTPException) as conflict:
        await reject(
            candidate["candidate_id"],
            {"reviewer": "alex", "reason": "again"},
            s=session,
        )
    assert conflict.value.status_code == 409


async def test_cli_lists_quarantined_candidates(task_queue):
    candidate = await _candidate(task_queue)
    command = [
        sys.executable,
        str(Path(__file__).parent.parent / "eval_review_cli.py"),
        "--claude-dir",
        str(task_queue._db_path.parent),
        "list",
    ]
    completed = subprocess.run(
        command, text=True, capture_output=True, check=True
    )
    listed = json.loads(completed.stdout)
    assert [item["candidate_id"] for item in listed] == [
        candidate["candidate_id"]
    ]
