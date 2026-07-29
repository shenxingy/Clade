"""Explicit human review routes for quarantined eval candidates."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from eval_review import (
    EvalReviewConflict,
    EvalReviewError,
    promote_candidate,
    reject_candidate,
)
from session import ProjectSession, _resolve_session


router = APIRouter(prefix="/api/eval-candidates", tags=["evals"])


@router.get("")
async def list_candidates(
    status: str = Query(default="quarantined"),
    limit: int = Query(default=100, ge=1, le=1000),
    s: ProjectSession = Depends(_resolve_session),
):
    try:
        return await s.task_queue.list_eval_candidates(
            status=status, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{candidate_id}")
async def get_candidate(
    candidate_id: str,
    s: ProjectSession = Depends(_resolve_session),
):
    try:
        candidate = await s.task_queue.get_eval_candidate(candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if candidate is None:
        raise HTTPException(status_code=404, detail="Eval candidate not found")
    return candidate


@router.post("/{candidate_id}/promote")
async def promote(
    candidate_id: str,
    body: dict,
    s: ProjectSession = Depends(_resolve_session),
):
    try:
        return await promote_candidate(
            s.task_queue,
            candidate_id,
            target=body.get("target", ""),
            reviewer=body.get("reviewer", ""),
            reason=body.get("reason", ""),
            case=body.get("case"),
        )
    except EvalReviewConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (EvalReviewError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{candidate_id}/reject")
async def reject(
    candidate_id: str,
    body: dict,
    s: ProjectSession = Depends(_resolve_session),
):
    try:
        return await reject_candidate(
            s.task_queue,
            candidate_id,
            reviewer=body.get("reviewer", ""),
            reason=body.get("reason", ""),
        )
    except EvalReviewConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (EvalReviewError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
