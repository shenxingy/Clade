"""Merge policy preserves history meaning instead of preferring squash."""

from __future__ import annotations

import pytest

from merge_policy import (
    MergeContext,
    MergePolicyError,
    choose_merge_strategy,
    enabled_merge_methods,
)


def _context(
    commits: int,
    methods=("merge", "rebase", "squash"),
    *,
    children: bool = False,
) -> MergeContext:
    return MergeContext(commits, frozenset(methods), children)


def test_live_child_topology_requires_merge_commit():
    assert choose_merge_strategy(_context(1, children=True)) == "merge"
    assert choose_merge_strategy(_context(2, children=True), "merge") == "merge"
    with pytest.raises(MergePolicyError, match="preserve live topology"):
        choose_merge_strategy(_context(1, children=True), "squash")
    with pytest.raises(MergePolicyError, match="preserve live topology"):
        choose_merge_strategy(
            _context(1, ("rebase", "squash"), children=True)
        )


def test_one_coherent_commit_prefers_rebase_without_rewriting_it():
    assert choose_merge_strategy(_context(1)) == "rebase"


def test_multi_commit_history_requires_explicit_semantics():
    with pytest.raises(MergePolicyError, match="multi-commit history is ambiguous"):
        choose_merge_strategy(_context(3))

    assert choose_merge_strategy(_context(3), "rebase") == "rebase"
    assert choose_merge_strategy(_context(3), "squash") == "squash"
    assert choose_merge_strategy(_context(3), "merge") == "merge"


def test_sole_enabled_method_is_repository_policy():
    assert choose_merge_strategy(_context(4, ("squash",))) == "squash"


def test_empty_pull_request_never_selects_a_merge_method():
    with pytest.raises(MergePolicyError, match="no commits"):
        choose_merge_strategy(_context(0, ("squash",)))


def test_disabled_or_unknown_explicit_strategy_fails_closed():
    with pytest.raises(MergePolicyError, match="disabled"):
        choose_merge_strategy(_context(1, ("rebase",)), "squash")
    with pytest.raises(MergePolicyError, match="must be one of"):
        choose_merge_strategy(_context(1), "flatten")


def test_repo_capability_fields_map_to_semantic_names():
    assert enabled_merge_methods(
        {
            "mergeCommitAllowed": True,
            "rebaseMergeAllowed": False,
            "squashMergeAllowed": True,
        }
    ) == frozenset({"merge", "squash"})
