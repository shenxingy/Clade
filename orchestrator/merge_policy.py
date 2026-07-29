"""Truthful pull-request history selection.

Merge strategy is a semantic decision, not a formatting preference.  This
module is pure so the Orchestrator and its tests can make the same decision
without contacting a forge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Mapping

MERGE_STRATEGIES: Final = frozenset({"auto", "squash", "rebase", "merge"})
_REPO_FLAGS: Final = {
    "squash": "squashMergeAllowed",
    "rebase": "rebaseMergeAllowed",
    "merge": "mergeCommitAllowed",
}


class MergePolicyError(ValueError):
    """Raised when history semantics are ambiguous or unavailable."""


@dataclass(frozen=True)
class MergeContext:
    commit_count: int
    enabled_methods: frozenset[str]
    has_open_children: bool = False


def enabled_merge_methods(repo: Mapping[str, object]) -> frozenset[str]:
    return frozenset(
        method for method, field in _REPO_FLAGS.items() if repo.get(field) is True
    )


def choose_merge_strategy(
    context: MergeContext,
    requested: str = "auto",
) -> str:
    """Choose a strategy only when its history meaning is unambiguous."""

    strategy = str(requested or "").strip().lower()
    if strategy not in MERGE_STRATEGIES:
        raise MergePolicyError(
            "merge strategy must be one of: auto, merge, rebase, squash"
        )
    if not context.enabled_methods:
        raise MergePolicyError("repository has no enabled pull-request merge method")
    if context.commit_count < 1:
        raise MergePolicyError("pull request has no commits")
    if context.has_open_children:
        if strategy not in {"auto", "merge"}:
            raise MergePolicyError(
                "open child PRs require a merge commit to preserve live topology"
            )
        if "merge" not in context.enabled_methods:
            raise MergePolicyError(
                "open child PRs require a merge commit to preserve live topology"
            )
        return "merge"
    if strategy != "auto":
        if strategy not in context.enabled_methods:
            raise MergePolicyError(
                f"requested merge strategy {strategy!r} is disabled by repository policy"
            )
        return strategy
    if context.commit_count == 1 and "rebase" in context.enabled_methods:
        return "rebase"
    if len(context.enabled_methods) == 1:
        return next(iter(context.enabled_methods))
    raise MergePolicyError(
        "multi-commit history is ambiguous; choose rebase for truthful revert "
        "units, squash for disposable checkpoints, or merge to retain the PR boundary"
    )
