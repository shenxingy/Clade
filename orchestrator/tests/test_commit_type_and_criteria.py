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

from config import _infer_commit_type
from worker_hydrate import _extract_acceptance_criteria


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
