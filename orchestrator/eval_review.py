"""Explicit human review and atomic corpus promotion for eval candidates."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from runtime_redaction import redact_runtime


EVALS_ROOT = Path(__file__).resolve().parent / "evals"
_CASE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_ORACLE_CATEGORIES = {
    "clear-approve",
    "style-nit-no-reject",
    "reject-spec-violation",
    "reject-missing-test-on-fix",
    "reject-quality",
    "infra-error",
}
_ORACLE_VERDICTS = {"approved", "rejected", "unreviewed"}
_ORACLE_SIMULATIONS = {"timeout", "garbage_output", "empty_output"}
_TARGETS = {
    "oracle": ("oracle_case", "oracle_cases"),
    "resolve": ("resolve_case", "resolve_cases"),
}


class EvalReviewError(ValueError):
    """Raised when a human review request is invalid."""


class EvalReviewConflict(EvalReviewError):
    """Raised when a candidate or corpus path was already decided."""


def _nonempty(case: dict, field: str) -> str:
    value = case.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EvalReviewError(f"{field} must be a non-empty string")
    return value.strip()


def _case_id(case: dict, field: str) -> str:
    value = _nonempty(case, field)
    if not _CASE_ID.fullmatch(value):
        raise EvalReviewError(
            f"{field} must use lowercase letters, numbers, dot, dash, or underscore"
        )
    return value


def _provenance(candidate: dict, reviewer: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": "clade.eval_promotion/v1",
        "candidate_id": candidate["candidate_id"],
        "source_task_id": candidate["source_task_id"],
        "source_attempt_id": candidate["source_attempt_id"],
        "source_attempt_revision": candidate["source_attempt_revision"],
        "source_evidence_digest": candidate["source_evidence_digest"],
        "trigger": candidate["trigger"],
        "diff_digest": candidate["diff_digest"],
        "reviewer": reviewer,
        "reason": reason,
        "redaction_metadata": candidate.get(
            "_promotion_redaction_metadata",
            {
                "schema_version": "clade.redaction/v1",
                "count": 0,
                "kinds": {},
                "fields": [],
            },
        ),
    }


def _oracle_case(
    candidate: dict, case: dict, reviewer: str, reason: str
) -> tuple[str, dict]:
    case_id = _case_id(case, "id")
    category = _nonempty(case, "category")
    verdict = _nonempty(case, "expected_verdict")
    if category not in _ORACLE_CATEGORIES:
        raise EvalReviewError("invalid oracle category")
    if verdict not in _ORACLE_VERDICTS:
        raise EvalReviewError("invalid oracle expected_verdict")
    diff = candidate.get("payload", {}).get("diff")
    if not isinstance(diff, str) or not diff.strip():
        raise EvalReviewError("oracle promotion requires a captured textual diff")
    promoted = {
        "id": case_id,
        "category": category,
        "source": f"eval:{candidate['candidate_id']}",
        "task": _nonempty(case, "task"),
        "diff": diff,
        "expected_verdict": verdict,
        "rationale": _nonempty(case, "rationale"),
        "promotion_provenance": _provenance(
            candidate, reviewer, reason
        ),
    }
    for field in ("acceptance_criteria", "test_evidence", "simulate"):
        if field in case:
            promoted[field] = case[field]
    simulation = promoted.get("simulate")
    if simulation is not None and simulation not in _ORACLE_SIMULATIONS:
        raise EvalReviewError("invalid oracle simulation")
    if bool(simulation) != (verdict == "unreviewed"):
        raise EvalReviewError(
            "unreviewed oracle cases require a simulation and other verdicts forbid it"
        )
    criteria = promoted.get("acceptance_criteria")
    if criteria is not None and (
        not isinstance(criteria, list)
        or not all(isinstance(item, str) and item.strip() for item in criteria)
    ):
        raise EvalReviewError(
            "acceptance_criteria must be a list of non-empty strings"
        )
    test_evidence = promoted.get("test_evidence")
    if test_evidence is not None and (
        not isinstance(test_evidence, dict)
        or not isinstance(test_evidence.get("tests_passed"), bool)
    ):
        raise EvalReviewError(
            "test_evidence must contain a boolean tests_passed"
        )
    if test_evidence is not None and any(
        not isinstance(test_evidence.get(field, ""), str)
        for field in ("test_output", "reg_warning")
    ):
        raise EvalReviewError(
            "test_evidence output fields must be strings"
        )
    return case_id, promoted


def _resolve_case(
    candidate: dict, case: dict, reviewer: str, reason: str
) -> tuple[str, dict]:
    case_id = _case_id(case, "instance_id")
    promoted = {
        field: case.get(field)
        for field in (
            "instance_id",
            "repo",
            "base_commit",
            "problem_statement",
            "FAIL_TO_PASS",
            "PASS_TO_PASS",
            "test_cmd",
            "synthetic",
        )
        if field in case
    }
    promoted["instance_id"] = case_id
    for field in (
        "repo",
        "base_commit",
        "problem_statement",
        "test_cmd",
    ):
        promoted[field] = _nonempty(case, field)
    for field in ("FAIL_TO_PASS", "PASS_TO_PASS"):
        value = case.get(field)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise EvalReviewError(
                f"{field} must be a list of non-empty strings"
            )
        promoted[field] = value
    if not promoted["FAIL_TO_PASS"]:
        raise EvalReviewError("FAIL_TO_PASS must not be empty")
    synthetic = promoted.get("synthetic")
    if synthetic is not None and (
        not isinstance(synthetic, dict)
        or not isinstance(synthetic.get("repo_files"), dict)
        or not synthetic["repo_files"]
        or not all(
            isinstance(path, str) and isinstance(content, str)
            for path, content in synthetic["repo_files"].items()
        )
        or not isinstance(synthetic.get("canned_patch"), str)
    ):
        raise EvalReviewError("synthetic resolve case has an invalid shape")
    promoted["observed_patch"] = candidate.get("payload", {}).get("diff")
    promoted["promotion_provenance"] = _provenance(
        candidate, reviewer, reason
    )
    return case_id, promoted


def _render_case(
    target: str,
    candidate: dict,
    case: dict,
    reviewer: str,
    reason: str,
) -> tuple[str, str, bytes]:
    if target not in _TARGETS:
        raise EvalReviewError("target must be oracle or resolve")
    if not isinstance(case, dict):
        raise EvalReviewError("case must be a JSON object")
    case_id, payload = (
        _oracle_case(candidate, case, reviewer, reason)
        if target == "oracle"
        else _resolve_case(candidate, case, reviewer, reason)
    )
    encoded = (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    return case_id, _TARGETS[target][1], encoded


def _publish_exclusive(path: Path, content: bytes) -> bool:
    """Atomically expose complete content without overwriting a corpus case."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == content:
            return False
        raise EvalReviewConflict(f"corpus case already exists: {path.name}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_path, path)
        except FileExistsError as exc:
            if path.read_bytes() == content:
                return False
            raise EvalReviewConflict(
                f"corpus case already exists: {path.name}"
            ) from exc
        return True
    finally:
        temp_path.unlink(missing_ok=True)


async def promote_candidate(
    task_queue,
    candidate_id: str,
    *,
    target: str,
    reviewer: str,
    reason: str,
    case: dict,
    evals_root: Path = EVALS_ROOT,
) -> dict:
    """Promote exactly one quarantined candidate after explicit human labeling."""

    candidate = await task_queue.get_eval_candidate(candidate_id)
    if candidate is None:
        raise EvalReviewError(f"unknown eval candidate: {candidate_id}")
    if candidate["status"] != "quarantined":
        raise EvalReviewConflict(
            f"eval candidate already decided: {candidate['status']}"
        )
    reviewer = str(reviewer or "").strip()
    reason = str(reason or "").strip()
    if not reviewer or not reason:
        raise EvalReviewError("reviewer and reason are required")
    reviewer_check = redact_runtime(
        reviewer, field_path="$.eval_promotion.reviewer"
    )
    if reviewer_check.metadata.redacted:
        raise EvalReviewError("reviewer must be a non-sensitive stable identifier")
    review = redact_runtime(
        {"reason": reason, "case": case},
        field_path="$.eval_promotion",
    )
    reason = review.value["reason"]
    case = review.value["case"]
    candidate = dict(candidate)
    candidate["_promotion_redaction_metadata"] = (
        review.metadata.to_dict()
    )
    case_id, directory, encoded = _render_case(
        target, candidate, case, reviewer, reason
    )
    destination = evals_root.resolve() / directory / f"{case_id}.json"
    created = _publish_exclusive(destination, encoded)
    relative_ref = f"evals/{directory}/{case_id}.json"
    decided_at = time.time()
    try:
        decided = await task_queue.decide_eval_candidate(
            candidate_id,
            status="promoted",
            reviewer=reviewer,
            reason=reason,
            promotion_kind=_TARGETS[target][0],
            promotion_ref=relative_ref,
            decided_at=decided_at,
        )
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return {"candidate": decided, "corpus_path": str(destination)}


async def reject_candidate(
    task_queue,
    candidate_id: str,
    *,
    reviewer: str,
    reason: str,
) -> dict:
    """Reject one quarantined candidate without writing a corpus case."""

    try:
        return await task_queue.decide_eval_candidate(
            candidate_id,
            status="rejected",
            reviewer=reviewer,
            reason=reason,
        )
    except ValueError as exc:
        if "already decided" in str(exc):
            raise EvalReviewConflict(str(exc)) from exc
        raise EvalReviewError(str(exc)) from exc
