"""Mutation-testing patrol lane: parser, ratchet, and mutmut-absent no-op.

The mutmut subprocess can't run in CI, so these cover the durable logic — parsing
`mutmut results` text and the run-over-run ratchet (seed run creates nothing; only
NEW survivors fire; killed mutants leave the baseline).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from task_factory.mutation_scan import (
    _parse_mutmut_survivors,
    _ratchet_new_survivors,
    check_mutation_survivors,
)


_RESULTS_SAMPLE = """
To apply a surviving mutant: mutmut apply <id>

Killed 🎉 (40)

---- worker_review.py (40) ----
1, 2, 3-5

Survived 🙁 (3)

---- worker_review.py (2) ----
12-13

---- error_classifier.py (1) ----
27

Timeout ⏰ (0)
"""


class TestParseMutmutSurvivors:
    def test_extracts_only_survived_section(self):
        s = _parse_mutmut_survivors(_RESULTS_SAMPLE)
        assert s == {"worker_review.py:12", "worker_review.py:13", "error_classifier.py:27"}

    def test_killed_section_is_ignored(self):
        s = _parse_mutmut_survivors(_RESULTS_SAMPLE)
        # ids 1-5 are under "Killed" — must not leak in
        assert "worker_review.py:1" not in s
        assert "worker_review.py:3" not in s

    def test_empty_or_no_survivors(self):
        assert _parse_mutmut_survivors("") == set()
        assert _parse_mutmut_survivors("Killed 🎉 (5)\n---- a.py (5) ----\n1-5\n") == set()


class TestRatchet:
    def test_first_run_seeds_baseline_creates_nothing(self, tmp_path):
        bp = tmp_path / "mutation-baseline.json"
        current = {"a.py:1", "a.py:2"}
        new = _ratchet_new_survivors(current, bp)
        assert new == set()                       # seed run: no tasks
        assert bp.exists()
        assert set(json.loads(bp.read_text())["survivors"]) == current

    def test_second_run_returns_only_new(self, tmp_path):
        bp = tmp_path / "mutation-baseline.json"
        _ratchet_new_survivors({"a.py:1"}, bp)            # seed
        new = _ratchet_new_survivors({"a.py:1", "a.py:9"}, bp)  # a.py:9 is new
        assert new == {"a.py:9"}

    def test_killed_mutant_drops_from_baseline(self, tmp_path):
        bp = tmp_path / "mutation-baseline.json"
        _ratchet_new_survivors({"a.py:1", "a.py:2"}, bp)  # seed
        _ratchet_new_survivors({"a.py:1"}, bp)            # a.py:2 got killed
        assert set(json.loads(bp.read_text())["survivors"]) == {"a.py:1"}
        # if a.py:2 survives again later, it's NEW again (correct regression signal)
        new = _ratchet_new_survivors({"a.py:1", "a.py:2"}, bp)
        assert new == {"a.py:2"}

    def test_corrupt_baseline_is_treated_as_present_but_empty(self, tmp_path):
        bp = tmp_path / "mutation-baseline.json"
        bp.write_text("{not json")
        new = _ratchet_new_survivors({"a.py:1"}, bp)
        # file existed → not a seed run → unreadable prev = empty → a.py:1 is "new"
        assert new == {"a.py:1"}


class FakeQueue:
    def __init__(self):
        self.added = []

    async def list(self):
        return []

    async def add(self, description, source_ref=None, task_type="AUTO", **kw):
        t = {"id": f"t{len(self.added)}", "description": description, "source_ref": source_ref}
        self.added.append(t)
        return t


class TestCheckMutationSurvivors:
    async def test_no_op_when_mutmut_absent(self, tmp_path, monkeypatch):
        import task_factory.mutation_scan as ms
        monkeypatch.setattr(ms.shutil, "which", lambda _: None)
        q = FakeQueue()
        created = await check_mutation_survivors(q, str(tmp_path))
        assert created == []
        assert q.added == []  # never touches the queue

    async def test_no_op_when_no_targets_configured(self, tmp_path, monkeypatch):
        # mutmut present but no targets → must not run mutmut or touch the queue.
        import task_factory.mutation_scan as ms
        monkeypatch.setattr(ms.shutil, "which", lambda _: "/usr/bin/mutmut")
        q = FakeQueue()
        created = await check_mutation_survivors(q, str(tmp_path), targets=[])
        assert created == []
        assert q.added == []
