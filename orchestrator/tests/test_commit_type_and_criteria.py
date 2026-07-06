"""Two small worker-quality fixes surfaced by the 2026-06-18 study sweep:

1. `_infer_commit_type` (config.py) — the worker hardcoded `feat:` for every
   auto-commit, which mislabels fixes/refactors and zeroes the agent fix-rate
   metric (`commit-archeology.sh` keys `fix` off `/^fix/`). Found via the
   Agent-Fingerprint deep-dive.
2. `_extract_acceptance_criteria` (worker_hydrate.py) — lift a done-criteria
   section out of a pre-hydrated GitHub issue body into its own contract
   callout (Reflection §G5).
"""

from __future__ import annotations

import pytest

from config import _infer_commit_type, _parse_task_class
from worker_hydrate import _extract_acceptance_criteria
from worker_utils import (
    _is_test_file, oracle_retry_sample_count, ORACLE_REJECT_MARKER, oracle_reject_depth,
)


# ─── _infer_commit_type ──────────────────────────────────────────────────────

class TestInferCommitType:
    def test_fix_keywords(self):
        for desc in [
            "Fix the login crash on empty password",
            "Bug: SBFL regex matches newlines",
            "hotfix for the broken install path",
        ]:
            assert _infer_commit_type(desc) == "fix"

    def test_explicit_conventional_prefix_wins(self):
        assert _infer_commit_type("fix(patrol): drain on timeout") == "fix"
        assert _infer_commit_type("docs: refresh skill counts") == "docs"

    def test_refactor_perf_docs_test_chore(self):
        assert _infer_commit_type("Refactor the worker pool dispatch") == "refactor"
        assert _infer_commit_type("Optimize the TLDR localizer for latency") == "perf"
        assert _infer_commit_type("Update the README and add a docstring") == "docs"
        assert _infer_commit_type("Add unit test for the repro filter") == "test"
        assert _infer_commit_type("Bump the pytest dependency") == "chore"

    def test_default_is_feat(self):
        assert _infer_commit_type("Implement a dark-mode toggle") == "feat"
        assert _infer_commit_type("Add an export button to the dashboard") == "feat"

    def test_fix_beats_feat_ordering(self):
        # A task that mentions both: fix must win so the metric counts it.
        assert _infer_commit_type("Add a guard to fix the null-pointer bug") == "fix"

    def test_never_empty(self):
        assert _infer_commit_type("") == "feat"


# ─── _extract_acceptance_criteria ────────────────────────────────────────────

class TestExtractAcceptanceCriteria:
    def test_markdown_heading_section(self):
        body = (
            "Some context about the feature.\n\n"
            "## Acceptance Criteria\n"
            "- Endpoint returns 200\n"
            "- Response is cached\n\n"
            "## Notes\n"
            "irrelevant trailing prose\n"
        )
        out = _extract_acceptance_criteria(body)
        assert "Endpoint returns 200" in out
        assert "Response is cached" in out
        assert "irrelevant trailing prose" not in out

    def test_definition_of_done_bold_label(self):
        body = "Intro.\n\n**Definition of Done:**\n1. Tests pass\n2. Docs updated\n"
        out = _extract_acceptance_criteria(body)
        assert "Tests pass" in out
        assert "Docs updated" in out

    def test_stops_at_next_bold_section(self):
        body = "**Done when:**\n- it works\n**Out of scope:**\n- everything else\n"
        out = _extract_acceptance_criteria(body)
        assert "it works" in out
        assert "everything else" not in out

    def test_no_section_returns_empty(self):
        assert _extract_acceptance_criteria("Just a plain issue body, no criteria.") == ""

    def test_empty_body(self):
        assert _extract_acceptance_criteria("") == ""

    def test_truncates_long_section(self):
        body = "## Acceptance Criteria\n" + ("x" * 2000)
        assert len(_extract_acceptance_criteria(body)) <= 800


# ─── _is_test_file (Agent-Fingerprint test-inclusion signal) ─────────────────

class TestIsTestFile:
    def test_pytest_names(self):
        assert _is_test_file("test_foo.py")
        assert _is_test_file("orchestrator/tests/test_recovery_e2e.py")

    def test_suffix_names(self):
        assert _is_test_file("pkg/foo_test.py")
        assert _is_test_file("pkg/foo_test.go")
        assert _is_test_file("src/app.test.ts")
        assert _is_test_file("src/app.spec.tsx")
        assert _is_test_file("src/button.test.jsx")

    def test_test_directories(self):
        assert _is_test_file("tests/helpers.py")
        assert _is_test_file("__tests__/foo.js")
        assert _is_test_file("a/b/spec/thing.rb")

    def test_windows_separators(self):
        assert _is_test_file("tests\\test_foo.py")

    def test_non_test_files(self):
        assert not _is_test_file("worker.py")
        assert not _is_test_file("src/app.ts")
        assert not _is_test_file("README.md")
        assert not _is_test_file("contest.py")   # "test" substring, not a test file
        assert not _is_test_file("latest_changes.py")


# ─── oracle_retry_sample_count (Agentless §6C plateau escape) ────────────────

def _desc(n_rejections: int) -> str:
    """A task description carrying n prior oracle rejections in its lineage."""
    base = "Fix the login bug"
    return base + "".join(f"\n--- Previous attempt was {ORACLE_REJECT_MARKER}: ..." for _ in range(n_rejections))


class TestOracleRetrySampleCount:
    def test_first_rejection_is_sequential(self):
        # depth 0, non-critical → ONE sequential retry (cheap, often enough)
        assert oracle_retry_sample_count(_desc(0), is_critical=False, configured_n=3) == 1

    def test_second_rejection_fans_out(self):
        # depth 1 (sequential retry also rejected) → plateau → diverse fan-out
        assert oracle_retry_sample_count(_desc(1), is_critical=False, configured_n=3) == 3

    def test_bounded_no_blowup(self):
        # depth 2 (a diverse sample rejected) → back to sequential, no re-fanout
        assert oracle_retry_sample_count(_desc(2), is_critical=False, configured_n=3) == 1
        assert oracle_retry_sample_count(_desc(5), is_critical=False, configured_n=3) == 1

    def test_critical_path_fans_out_immediately(self):
        assert oracle_retry_sample_count(_desc(0), is_critical=True, configured_n=3) == 3

    def test_disabled_when_configured_one(self):
        # parallel_fix_samples=1 disables fan-out entirely
        assert oracle_retry_sample_count(_desc(1), is_critical=False, configured_n=1) == 1
        assert oracle_retry_sample_count(_desc(0), is_critical=True, configured_n=1) == 1


class TestOracleRejectDepth:
    """oracle_reject_depth is the extracted helper shared by oracle_retry_sample_count
    (fan-out width) and the Round-4 reject-round cap (worker.py, total round count)."""

    def test_no_rejections_is_depth_zero(self):
        assert oracle_reject_depth(_desc(0)) == 0

    def test_depth_matches_marker_count(self):
        assert oracle_reject_depth(_desc(1)) == 1
        assert oracle_reject_depth(_desc(3)) == 3
        assert oracle_reject_depth(_desc(7)) == 7

    def test_used_internally_by_sample_count_consistently(self):
        # oracle_retry_sample_count's own depth-based branching must still see
        # exactly what oracle_reject_depth reports — same source of truth.
        for n in (0, 1, 2, 5):
            depth = oracle_reject_depth(_desc(n))
            assert depth == n


# ─── _parse_task_class (Round-4, Armin Ronacher: task-class-aware resampling) ──


class TestParseTaskClass:
    @pytest.mark.parametrize("desc", [
        "rename the config keys across the module",
        "reformat this file to match the style guide",
        "reorganize the imports alphabetically",
        "move the helper function to utils.py",
        "extract this block into its own function",
        "cleanup unused imports",
        "fix a typo in the docstring",
        "de-duplicate the two near-identical blocks",
    ])
    def test_transform_keywords_detected(self, desc):
        assert _parse_task_class(desc) == "transform"

    @pytest.mark.parametrize("desc", [
        "implement the new billing webhook handler",
        "design a caching layer for the API",
        "add feature: dark mode toggle",
        "create a new onboarding flow",
        "build the notification system",
        "add a new endpoint for user preferences",
    ])
    def test_generate_keywords_detected(self, desc):
        assert _parse_task_class(desc) == "generate"

    def test_explicit_class_metadata_wins(self):
        # "class: generate" in the description overrides keyword sniffing —
        # same precedence convention as _parse_task_type's "type: X" metadata.
        assert _parse_task_class("class: generate\nrename the variable") == "generate"
        assert _parse_task_class("class: transform\nimplement a new feature") == "transform"

    def test_invalid_explicit_class_falls_back_to_keywords(self):
        assert _parse_task_class("class: bogus\nrename the variable") == "transform"

    def test_ambiguous_description_returns_none(self):
        assert _parse_task_class("update the README") is None
        assert _parse_task_class("") is None

    def test_case_insensitive(self):
        assert _parse_task_class("RENAME the Config Keys") == "transform"
        assert _parse_task_class("IMPLEMENT the new feature") == "generate"
