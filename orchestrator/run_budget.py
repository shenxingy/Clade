"""Pure run-budget policy and trace-attribution helpers.

Leaf module: stdlib only, with no orchestrator imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RunBudget:
    """Optional ceilings for one autonomous run; ``None`` means unlimited."""

    max_usd: float | None = None
    max_tokens: int | None = None


def budget_from_settings(settings: Mapping[str, Any]) -> RunBudget:
    """Build a budget from settings, treating missing/non-positive caps as unlimited."""
    raw_usd = settings.get("run_budget_usd")
    raw_tokens = settings.get("run_budget_tokens")
    try:
        usd = float(raw_usd) if raw_usd is not None else 0.0
    except (TypeError, ValueError):
        usd = 0.0
    try:
        tokens = int(raw_tokens) if raw_tokens is not None else 0
    except (TypeError, ValueError):
        tokens = 0
    return RunBudget(
        max_usd=usd if usd > 0 else None,
        max_tokens=tokens if tokens > 0 else None,
    )


def check_budget(
    spent_usd: float,
    spent_tokens: int,
    budget: RunBudget,
) -> tuple[bool, str | None]:
    """Return whether a configured ceiling has been reached and its stop reason."""
    if budget.max_usd is not None and spent_usd >= budget.max_usd:
        return True, "run_budget_usd_exceeded"
    if budget.max_tokens is not None and spent_tokens >= budget.max_tokens:
        return True, "run_budget_tokens_exceeded"
    return False, None


def attribution(repo: str, harness: str, model: str) -> dict[str, str]:
    """Return stable provenance tags for an autonomous-run trace span."""
    return {"repo": repo, "harness": harness, "model": model}
