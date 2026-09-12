"""Forge-confirmed merge recording: `merged` without a READY lock, `reconcile`,
and the mergeability settle in `ready`.

Split from test_delivery_harness.py to keep both under the 1500-line ceiling;
the fixtures, CLI runner, and `gh` stub are shared from there.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import tests.test_delivery_harness as harness

DELIVERY = harness.DELIVERY
MERGE_SHA = harness.MERGE_SHA
MOVED_HEAD = harness.MOVED_HEAD
git_repo = harness.git_repo  # pytest fixture, re-exported into this module
_delivery = harness._delivery
_fake_gh = harness._fake_gh
_git = harness._git
_start = harness._start

def _gh_env(bin_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return env


def _published(git_repo: Path, *, pr: str = "17", delivery_id: str = "fixture") -> str:
    """start → candidate → publish on a GitHub-shaped repo; returns HEAD."""

    if not _git(git_repo, "remote"):
        _git(git_repo, "remote", "add", "origin", "https://github.com/acme/repo.git")
    _start(git_repo, delivery_id=delivery_id)
    _delivery(
        git_repo,
        "candidate",
        "--id",
        delivery_id,
        "--command",
        "full CI",
        "--result",
        "passed",
    )
    _delivery(
        git_repo,
        "publish",
        "--id",
        delivery_id,
        "--pr",
        pr,
        "--url",
        f"https://github.com/acme/repo/pull/{pr}",
    )
    return _git(git_repo, "rev-parse", "HEAD")


def test_candidate_after_publish_keeps_published_state(git_repo: Path) -> None:
    _published(git_repo)

    again = _delivery(
        git_repo,
        "candidate",
        "--id",
        "fixture",
        "--command",
        "full CI (re-run)",
        "--result",
        "passed",
    )

    assert again["state"] == "PUBLISHED"
    assert again["published"] is True


def test_merged_without_ready_is_reconciled_from_forge(git_repo: Path) -> None:
    head = _published(git_repo)
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    _fake_gh(bin_dir, pr_state="MERGED", merge_sha=MERGE_SHA)

    merged = _delivery(
        git_repo,
        "merged",
        "--id",
        "fixture",
        "--merge-sha",
        MERGE_SHA,
        "--strategy",
        "squash",
        env=_gh_env(bin_dir),
    )

    assert merged["state"] == "MERGED"
    merge = merged["merge"]
    assert merge["reconciled_from_forge"] is True
    assert merge["ready_skipped"] is True
    assert merge["candidate_stale"] is False
    assert merge["candidate_head"] == head
    assert merge["head_sha"] == head
    assert merge["merge_sha"] == MERGE_SHA
    assert merge["strategy"] == "squash"
    assert merge["strategy_source"] == "argument"
    assert merge["merged_by"] == "integrator"
    assert merge["merged_at"] == "2026-09-12T03:00:29Z"
    assert merge["pull_request"] == {
        "number": 17,
        "url": "https://github.com/acme/repo/pull/17",
        "base": "main",
    }
    evidence = _delivery(git_repo, "evidence", "--id", "fixture")
    assert evidence["merge"] == merge


def test_merged_without_ready_refuses_when_forge_does_not_confirm(
    git_repo: Path,
) -> None:
    _published(git_repo)
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    env = _gh_env(bin_dir)

    _fake_gh(bin_dir, pr_state="OPEN")
    still_open = _delivery(
        git_repo,
        "merged",
        "--id",
        "fixture",
        "--merge-sha",
        MERGE_SHA,
        env=env,
        expected=2,
    )
    assert "PR #17 is not merged on the forge: OPEN" in still_open["error"]

    _fake_gh(bin_dir, pr_state="CLOSED")
    closed = _delivery(
        git_repo,
        "merged",
        "--id",
        "fixture",
        "--merge-sha",
        MERGE_SHA,
        env=env,
        expected=2,
    )
    assert "not merged on the forge: CLOSED" in closed["error"]

    _fake_gh(bin_dir, pr_state="MERGED", merge_sha=MERGE_SHA)
    wrong_sha = _delivery(
        git_repo,
        "merged",
        "--id",
        "fixture",
        "--merge-sha",
        "b" * 40,
        env=env,
        expected=2,
    )
    assert "merge SHA mismatch" in wrong_sha["error"]
    assert MERGE_SHA in wrong_sha["error"]

    wrong_head = _delivery(
        git_repo,
        "merged",
        "--id",
        "fixture",
        "--head-sha",
        "c" * 40,
        "--merge-sha",
        MERGE_SHA,
        env=env,
        expected=2,
    )
    assert "merged head SHA mismatch" in wrong_head["error"]

    # Every refusal left the record where it was.
    assert _delivery(git_repo, "show", "--id", "fixture")["state"] == "PUBLISHED"


def test_merged_without_ready_requires_a_forge_and_a_pr(git_repo: Path) -> None:
    # `forge` is snapshotted at START, so the two refusals need two records.
    _start(git_repo)  # no remote yet -> forge "none"
    no_forge = _delivery(
        git_repo,
        "merged",
        "--id",
        "fixture",
        "--merge-sha",
        MERGE_SHA,
        expected=2,
    )
    assert "no supported forge" in no_forge["error"]

    _git(git_repo, "remote", "add", "origin", "https://github.com/acme/repo.git")
    _git(git_repo, "switch", "-q", "main")
    _git(git_repo, "switch", "-q", "-c", "agent/github")
    _delivery(
        git_repo,
        "start",
        "--id",
        "github-fixture",
        "--owner",
        "test:session",
        "--runtime",
        "codex",
        "--branch",
        "agent/github",
        "--base",
        "main",
    )
    no_pr = _delivery(
        git_repo,
        "merged",
        "--id",
        "github-fixture",
        "--merge-sha",
        MERGE_SHA,
        expected=2,
    )
    assert "has no PR to confirm the merge; pass --pr" in no_pr["error"]
    assert _delivery(git_repo, "show", "--id", "github-fixture")["state"] == "BUILD"


def test_merged_records_stale_candidate_when_forge_head_moved(
    git_repo: Path,
) -> None:
    candidate_head = _published(git_repo)
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    _fake_gh(bin_dir, pr_state="MERGED", merge_sha=MERGE_SHA, merged_head=MOVED_HEAD)

    merged = _delivery(
        git_repo,
        "merged",
        "--id",
        "fixture",
        "--merge-sha",
        MERGE_SHA,
        env=_gh_env(bin_dir),
    )

    merge = merged["merge"]
    assert merged["state"] == "MERGED"
    assert merge["candidate_stale"] is True
    assert merge["candidate_head"] == candidate_head
    assert merge["head_sha"] == MOVED_HEAD
    assert merge["strategy"] is None
    assert merge["strategy_source"] == "unknown"


def test_merged_is_idempotent_and_refuses_conflicting_or_terminal(
    git_repo: Path,
) -> None:
    _published(git_repo)
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    env = _gh_env(bin_dir)
    _fake_gh(bin_dir, pr_state="MERGED", merge_sha=MERGE_SHA)
    first = _delivery(
        git_repo, "merged", "--id", "fixture", "--merge-sha", MERGE_SHA, env=env
    )

    repeated = _delivery(
        git_repo, "merged", "--id", "fixture", "--merge-sha", MERGE_SHA, env=env
    )
    assert repeated["merge"] == first["merge"]
    assert repeated["updated_at"] == first["updated_at"]

    conflicting = _delivery(
        git_repo,
        "merged",
        "--id",
        "fixture",
        "--merge-sha",
        "b" * 40,
        env=env,
        expected=2,
    )
    assert "already merged with a different merge SHA" in conflicting["error"]

    relock = _delivery(
        git_repo, "ready", "--id", "fixture", "--pr", "17", env=env, expected=2
    )
    assert "cannot lock READY from delivery state MERGED" in relock["error"]

    _git(git_repo, "switch", "-q", "main")
    _git(git_repo, "switch", "-q", "-c", "agent/spare")
    spare = _delivery(
        git_repo,
        "start",
        "--id",
        "spare",
        "--owner",
        "test:session",
        "--runtime",
        "codex",
        "--branch",
        "agent/spare",
        "--base",
        "main",
        "--allow-dirty",
    )
    _fake_gh(bin_dir)  # `pr list --head` answers [] — nothing to discover
    _delivery(
        git_repo,
        "abandon",
        "--id",
        "spare",
        "--head-sha",
        spare["head_sha"],
        "--reason",
        "never needed",
        env=env,
    )
    terminal = _delivery(
        git_repo,
        "merged",
        "--id",
        "spare",
        "--merge-sha",
        MERGE_SHA,
        env=env,
        expected=2,
    )
    assert "terminal delivery state ABANDONED" in terminal["error"]


def test_ready_waits_for_unknown_mergeability_then_locks(git_repo: Path) -> None:
    head = _published(git_repo)
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    _fake_gh(
        bin_dir,
        commit_count=1,
        mergeable_sequence=["UNKNOWN", "UNKNOWN", "MERGEABLE"],
    )

    ready = _delivery(
        git_repo,
        "ready",
        "--id",
        "fixture",
        "--pr",
        "17",
        "--mergeable-timeout",
        "10",
        env=_gh_env(bin_dir),
    )

    assert ready["state"] == "READY"
    assert ready["ready"]["head_sha"] == head
    assert ready["ready"]["mergeability_queries"] == 3
    assert (bin_dir / "mergeable-calls").read_text() == "3"


def test_ready_reports_mergeability_that_never_settles(git_repo: Path) -> None:
    _published(git_repo)
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    _fake_gh(bin_dir, commit_count=1, mergeable_sequence=["UNKNOWN"])

    unsettled = _delivery(
        git_repo,
        "ready",
        "--id",
        "fixture",
        "--pr",
        "17",
        "--mergeable-timeout",
        "1.5",
        env=_gh_env(bin_dir),
        expected=2,
    )

    assert "still UNKNOWN" in unsettled["error"]
    assert "asynchronously" in unsettled["error"]
    # 1s then the 0.5s remainder: three queries, then it gave up.
    assert (bin_dir / "mergeable-calls").read_text() == "3"
    assert _delivery(git_repo, "show", "--id", "fixture")["state"] == "PUBLISHED"


def test_reconcile_all_dry_run_leaves_open_and_closed_prs_alone(
    git_repo: Path,
) -> None:
    _git(git_repo, "remote", "add", "origin", "https://github.com/acme/repo.git")
    for delivery_id, branch, pr in (
        ("landed", "agent/landed", "17"),
        ("still-open", "agent/open", "18"),
        ("closed-unmerged", "agent/closed", "19"),
    ):
        _git(git_repo, "switch", "-q", "main")
        _git(git_repo, "switch", "-q", "-c", branch)
        _delivery(
            git_repo,
            "start",
            "--id",
            delivery_id,
            "--owner",
            "test:session",
            "--runtime",
            "codex",
            "--branch",
            branch,
            "--base",
            "main",
            "--pr-authority",
            "task-request",
        )
        _delivery(
            git_repo,
            "publish",
            "--id",
            delivery_id,
            "--pr",
            pr,
            "--url",
            f"https://github.com/acme/repo/pull/{pr}",
        )
    _git(git_repo, "switch", "-q", "main")
    _git(git_repo, "switch", "-q", "-c", "agent/no-pr")
    _delivery(
        git_repo,
        "start",
        "--id",
        "never-published",
        "--owner",
        "test:session",
        "--runtime",
        "codex",
        "--branch",
        "agent/no-pr",
        "--base",
        "main",
    )
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    _fake_gh(
        bin_dir,
        pr_state="MERGED",
        merge_sha=MERGE_SHA,
        pr_overrides={
            18: {"state": "OPEN", "mergeCommit": None, "mergedAt": None},
            19: {"state": "CLOSED", "mergeCommit": None, "mergedAt": None},
        },
    )
    env = _gh_env(bin_dir)

    dry = _delivery(git_repo, "reconcile", "--all", env=env)

    assert dry["mode"] == "dry-run"
    by_id = {item["delivery_id"]: item for item in dry["results"]}
    assert by_id["landed"]["action"] == "merge"
    assert by_id["landed"]["merge"]["merge_sha"] == MERGE_SHA
    assert by_id["still-open"] == {
        "delivery_id": "still-open",
        "state": "PUBLISHED",
        "pr": "18",
        "action": "skip",
        "reason": "PR is open",
        "merge": None,
    }
    assert by_id["closed-unmerged"]["action"] == "skip"
    assert "abandon" in by_id["closed-unmerged"]["reason"]
    assert by_id["never-published"]["action"] == "skip"
    # Exact: the discovery path's reason shares the prefix, and `--all` must
    # never have searched the forge for this record.
    assert by_id["never-published"]["reason"] == (
        "no recorded PR (reconcile --id discovers one by branch)"
    )
    assert dry["summary"] == {"merge": 1, "skip": 3, "error": 0}
    for delivery_id in ("landed", "still-open", "closed-unmerged"):
        assert _delivery(git_repo, "show", "--id", delivery_id)["state"] == "PUBLISHED"

    applied = _delivery(git_repo, "reconcile", "--all", "--apply", env=env)

    assert applied["mode"] == "apply"
    by_id = {item["delivery_id"]: item for item in applied["results"]}
    assert by_id["landed"]["state_after"] == "MERGED"
    assert _delivery(git_repo, "show", "--id", "landed")["state"] == "MERGED"
    assert _delivery(git_repo, "show", "--id", "still-open")["state"] == "PUBLISHED"
    assert _delivery(git_repo, "show", "--id", "closed-unmerged")["state"] == "PUBLISHED"

    # A second sweep finds nothing left to do and touches nothing.
    again = _delivery(git_repo, "reconcile", "--all", "--apply", env=env)
    assert again["summary"] == {"merge": 0, "skip": 3, "error": 0}


def test_reconcile_id_discovers_unrecorded_merged_pr_at_exact_head(
    git_repo: Path,
) -> None:
    _git(git_repo, "remote", "add", "origin", "https://github.com/acme/repo.git")
    started = _start(git_repo)
    recorded_head = started["head_sha"]
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    env = _gh_env(bin_dir)

    _fake_gh(bin_dir, pr_state="MERGED", merge_sha=MERGE_SHA, listed_pr_state="MERGED")
    abandon = _delivery(
        git_repo,
        "abandon",
        "--id",
        "fixture",
        "--head-sha",
        recorded_head,
        "--reason",
        "superseded",
        env=env,
        expected=2,
    )
    assert "reconcile --id fixture --apply" in abandon["error"]

    reconciled = _delivery(
        git_repo, "reconcile", "--id", "fixture", "--apply", env=env
    )
    assert reconciled["results"][0]["pr"] == "17"
    assert reconciled["results"][0]["state_after"] == "MERGED"
    shown = _delivery(git_repo, "show", "--id", "fixture")
    assert shown["state"] == "MERGED"
    assert shown["merge"]["pull_request"]["number"] == 17
    assert shown["merge"]["candidate_stale"] is True  # no candidate was ever recorded
    assert shown["merge"]["candidate_head"] is None

    # The remedy `abandon` prescribes must survive being run twice.
    again = _delivery(git_repo, "reconcile", "--id", "fixture", "--apply", env=env)
    assert again["results"][0]["action"] == "skip"
    assert again["results"][0]["reason"] == "already merged"
    assert _delivery(git_repo, "show", "--id", "fixture")["merge"] == shown["merge"]


def test_reconcile_id_does_not_adopt_a_merged_pr_at_a_later_head(
    git_repo: Path,
) -> None:
    _git(git_repo, "remote", "add", "origin", "https://github.com/acme/repo.git")
    _start(git_repo)
    (git_repo / "later.txt").write_text("later\n", encoding="utf-8")
    _git(git_repo, "add", "later.txt")
    _git(git_repo, "commit", "-q", "-m", "later commit not in the record")
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    env = _gh_env(bin_dir)
    _fake_gh(bin_dir, pr_state="MERGED", merge_sha=MERGE_SHA, listed_pr_state="MERGED")

    dry = _delivery(git_repo, "reconcile", "--id", "fixture", env=env)
    assert dry["results"][0]["action"] == "skip"
    assert "merged PRs at other heads: #17" in dry["results"][0]["reason"]

    refused = _delivery(
        git_repo, "reconcile", "--id", "fixture", "--apply", env=env, expected=2
    )
    assert "did not record a merge" in refused["error"]
    assert _delivery(git_repo, "show", "--id", "fixture")["state"] == "BUILD"

    # The explicit override names the PR and records the head gap honestly.
    explicit = _delivery(
        git_repo,
        "merged",
        "--id",
        "fixture",
        "--pr",
        "17",
        "--merge-sha",
        MERGE_SHA,
        env=env,
    )
    assert explicit["state"] == "MERGED"
    assert explicit["merge"]["candidate_stale"] is True
    assert explicit["merge"]["head_sha"] == _git(git_repo, "rev-parse", "HEAD")


def test_merged_with_ready_lock_still_uses_the_lock(git_repo: Path) -> None:
    head = _published(git_repo)
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    env = _gh_env(bin_dir)
    _fake_gh(bin_dir, commit_count=1)
    _delivery(git_repo, "ready", "--id", "fixture", "--pr", "17", env=env)

    # No gh on PATH: the locked path must not need the forge at all.
    merged = _delivery(
        git_repo,
        "merged",
        "--id",
        "fixture",
        "--head-sha",
        head,
        "--merge-sha",
        MERGE_SHA,
    )

    assert merged["state"] == "MERGED"
    assert merged["merge"] == {
        "strategy": "rebase",
        "head_sha": head,
        "merge_sha": MERGE_SHA,
        "merged_at": merged["merge"]["merged_at"],
    }
    assert "reconciled_from_forge" not in merged["merge"]


def test_merged_with_stale_ready_lock_falls_back_to_forge(git_repo: Path) -> None:
    _published(git_repo)
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    env = _gh_env(bin_dir)
    _fake_gh(bin_dir, commit_count=1)
    _delivery(git_repo, "ready", "--id", "fixture", "--pr", "17", env=env)

    # The PR moved and merged at a head the lock never covered.
    _fake_gh(bin_dir, pr_state="MERGED", merge_sha=MERGE_SHA, merged_head=MOVED_HEAD)
    merged = _delivery(
        git_repo,
        "merged",
        "--id",
        "fixture",
        "--head-sha",
        MOVED_HEAD,
        "--merge-sha",
        MERGE_SHA,
        env=env,
    )

    merge = merged["merge"]
    assert merged["state"] == "MERGED"
    assert merge["reconciled_from_forge"] is True
    assert merge["ready_skipped"] is True
    assert merge["candidate_stale"] is True
    assert merge["head_sha"] == MOVED_HEAD


def test_ready_refuses_a_merged_pr_before_waiting_on_mergeability(
    git_repo: Path,
) -> None:
    """The six stuck records: PUBLISHED locally, MERGED on the forge, where gh
    reports mergeable=UNKNOWN. `ready` must fail on the state, not spend the
    mergeability timeout first."""

    _published(git_repo)
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    _fake_gh(bin_dir, pr_state="MERGED", merge_sha=MERGE_SHA, mergeable_sequence=["UNKNOWN"])

    refused = _delivery(
        git_repo,
        "ready",
        "--id",
        "fixture",
        "--pr",
        "17",
        "--mergeable-timeout",
        "10",
        env=_gh_env(bin_dir),
        expected=2,
    )

    assert "PR is not open: MERGED" in refused["error"]
    assert (bin_dir / "mergeable-calls").read_text() == "1"


def test_merged_infers_merge_strategy_from_a_multi_parent_landed_commit(
    git_repo: Path,
) -> None:
    _published(git_repo)
    _git(git_repo, "switch", "-q", "main")
    _git(git_repo, "switch", "-q", "-c", "side")
    (git_repo / "side.txt").write_text("side\n", encoding="utf-8")
    _git(git_repo, "add", "side.txt")
    _git(git_repo, "commit", "-q", "-m", "side")
    _git(git_repo, "switch", "-q", "main")
    _git(git_repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    landed = _git(git_repo, "rev-parse", "HEAD")
    _git(git_repo, "switch", "-q", "agent/fixture")
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    _fake_gh(bin_dir, pr_state="MERGED", merge_sha=landed)

    merged = _delivery(
        git_repo,
        "merged",
        "--id",
        "fixture",
        "--merge-sha",
        landed,
        env=_gh_env(bin_dir),
    )

    assert merged["merge"]["strategy"] == "merge"
    assert merged["merge"]["strategy_source"] == "inferred"


def test_reconcile_takes_strategy_from_a_ready_lock_at_the_merged_head(
    git_repo: Path,
) -> None:
    head = _published(git_repo)
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    env = _gh_env(bin_dir)
    _fake_gh(bin_dir, commit_count=1)
    locked = _delivery(git_repo, "ready", "--id", "fixture", "--pr", "17", env=env)
    assert locked["ready"]["strategy"] == "rebase"

    # The lock was taken, the merge happened, only `merged` was never run.
    _fake_gh(bin_dir, pr_state="MERGED", merge_sha=MERGE_SHA)
    reconciled = _delivery(git_repo, "reconcile", "--id", "fixture", "--apply", env=env)

    merge = reconciled["results"][0]["merge"]
    assert reconciled["results"][0]["state_after"] == "MERGED"
    assert merge["head_sha"] == head
    assert merge["ready_skipped"] is False
    assert merge["strategy"] == "rebase"
    assert merge["strategy_source"] == "ready"


def test_reconcile_all_rejects_per_record_flags(git_repo: Path) -> None:
    _git(git_repo, "remote", "add", "origin", "https://github.com/acme/repo.git")
    _start(git_repo)

    for flag in (("--pr", "17"), ("--strategy", "squash")):
        refused = _delivery(git_repo, "reconcile", "--all", *flag, expected=2)
        assert "apply to reconcile --id only" in refused["error"]


def test_ready_rejects_a_non_finite_mergeable_timeout(git_repo: Path) -> None:
    _published(git_repo)

    for value in ("inf", "nan", "-1"):
        result = subprocess.run(
            [
                sys.executable,
                str(DELIVERY),
                "ready",
                "--id",
                "fixture",
                "--pr",
                "17",
                "--mergeable-timeout",
                value,
                "--repo",
                str(git_repo),
            ],
            cwd=git_repo,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 2, value
        assert "finite, non-negative" in result.stderr, value


def test_abandon_points_a_recorded_merged_pr_at_reconcile(git_repo: Path) -> None:
    head = _published(git_repo)
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    _fake_gh(bin_dir, pr_state="MERGED", merge_sha=MERGE_SHA)

    refused = _delivery(
        git_repo,
        "abandon",
        "--id",
        "fixture",
        "--head-sha",
        head,
        "--reason",
        "superseded",
        env=_gh_env(bin_dir),
        expected=2,
    )

    assert "PR #17 is merged; reconcile it instead of abandoning" in refused["error"]
    assert "reconcile --id fixture --apply" in refused["error"]
    assert _delivery(git_repo, "show", "--id", "fixture")["state"] == "PUBLISHED"
