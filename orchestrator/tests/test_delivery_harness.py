"""Contract tests for the provider-neutral Git delivery controller."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "configs" / "skills" / "delivery" / "scripts"
DELIVERY = SCRIPTS / "delivery.py"


def _load_git_context():
    spec = importlib.util.spec_from_file_location(
        "clade_delivery_git_context", SCRIPTS / "git_context.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


git_context = _load_git_context()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "Clade Test")
    _git(tmp_path, "config", "user.email", "clade@example.test")
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-q", "-m", "initial")
    return tmp_path


def _delivery(
    repo: Path,
    *args: str,
    env: dict[str, str] | None = None,
    expected: int = 0,
) -> dict:
    result = subprocess.run(
        [sys.executable, str(DELIVERY), "--compact", *args, "--repo", str(repo)],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == expected, result.stderr or result.stdout
    return json.loads(result.stdout)


def _start(
    repo: Path,
    *,
    delivery_id: str = "fixture",
    authorities: bool = True,
    attempt_id: str | None = None,
) -> dict:
    _git(repo, "switch", "-q", "-c", "agent/fixture")
    args = [
        "start",
        "--id",
        delivery_id,
        "--owner",
        "test:session",
        "--runtime",
        "codex",
        "--branch",
        "agent/fixture",
        "--base",
        "main",
    ]
    if attempt_id:
        args.extend(["--attempt-id", attempt_id])
    if authorities:
        args.extend(
            [
                "--push-authority",
                "task-request",
                "--pr-authority",
                "task-request",
                "--merge-authority",
                "task-request",
                "--delete-authority",
                "task-request",
            ]
        )
    return _delivery(repo, *args)


def test_delivery_evidence_projection_links_attempt_and_omits_private_state(
    git_repo: Path,
) -> None:
    started = _start(git_repo, attempt_id="attempt-17")
    candidate = _delivery(
        git_repo,
        "candidate",
        "--id",
        "fixture",
        "--command",
        "pytest -q",
        "--result",
        "passed",
    )
    _delivery(
        git_repo,
        "publish",
        "--id",
        "fixture",
        "--pr",
        "17",
        "--url",
        "https://github.com/acme/repo/pull/17",
    )

    evidence = _delivery(git_repo, "evidence", "--id", "fixture")

    assert evidence == {
        "schema_version": "clade.delivery-evidence/v1",
        "attempt_id": "attempt-17",
        "delivery_id": "fixture",
        "state": "PUBLISHED",
        "base": {"ref": "main", "sha": started["base_sha"]},
        "head": {"branch": "agent/fixture", "sha": candidate["head_sha"]},
        "candidate": candidate["verification"]["candidate"],
        "pull_request": {
            "number": 17,
            "url": "https://github.com/acme/repo/pull/17",
            "base": "main",
            "head_sha": candidate["head_sha"],
            "draft": False,
        },
        "ready": None,
        "merge": None,
        "abandonment": None,
        "cleanup": None,
        "updated_at": evidence["updated_at"],
    }
    assert "repository_root" not in evidence
    assert "authorization" not in evidence


def test_context_probe_keeps_plain_git_and_unknown_ownership_explicit(
    git_repo: Path,
) -> None:
    profile = git_context.probe(
        git_repo,
        runtime="codex",
        surface="local-interactive",
        task_source="prompt",
    )

    assert profile["repository"]["forge"] == "none"
    assert profile["repository"]["default_branch"] == "main"
    assert profile["branch"]["owner"] == "unknown"
    assert profile["capabilities"]["open_pr"] is False
    assert profile["authorization"]["push"]["decision"] == "requires-authority"
    assert profile["authorization"]["open_pr"]["decision"] == "unsupported"


def test_context_probe_represents_detached_checkpoint_without_push(
    git_repo: Path,
) -> None:
    _git(git_repo, "switch", "-q", "--detach")

    profile = git_context.probe(
        git_repo,
        runtime="codex",
        surface="managed-worktree",
        task_source="prompt",
    )

    assert profile["repository"]["detached"] is True
    assert profile["authorization"]["commit"]["decision"] == "allowed"
    assert profile["authorization"]["push"]["decision"] == "blocked"


def test_start_is_idempotent_and_creates_branch_lease(git_repo: Path) -> None:
    first = _start(git_repo)
    second = _delivery(
        git_repo,
        "start",
        "--id",
        "fixture",
        "--owner",
        "test:session",
        "--runtime",
        "codex",
        "--branch",
        "agent/fixture",
        "--base",
        "main",
        "--push-authority",
        "task-request",
        "--pr-authority",
        "task-request",
        "--merge-authority",
        "task-request",
        "--delete-authority",
        "task-request",
    )
    profile = git_context.probe(
        git_repo,
        runtime="claude-code",
        surface="local-interactive",
        task_source="prompt",
    )

    assert first["delivery_id"] == second["delivery_id"]
    assert profile["branch"]["owner"] == "session"
    assert profile["branch"]["owner_id"] == "test:session"
    assert profile["authorization"]["commit"]["decision"] == "allowed"


def test_new_head_invalidates_candidate_evidence(git_repo: Path) -> None:
    _start(git_repo)
    (git_repo / "one.txt").write_text("one\n", encoding="utf-8")
    _git(git_repo, "add", "one.txt")
    _git(git_repo, "commit", "-q", "-m", "first checkpoint")
    _delivery(
        git_repo,
        "checkpoint",
        "--id",
        "fixture",
        "--command",
        "pytest one",
        "--result",
        "passed",
    )
    candidate = _delivery(
        git_repo,
        "candidate",
        "--id",
        "fixture",
        "--command",
        "pytest all",
        "--result",
        "passed",
    )
    assert candidate["verification"]["candidate"]["head_sha"] == _git(
        git_repo, "rev-parse", "HEAD"
    )

    (git_repo / "two.txt").write_text("two\n", encoding="utf-8")
    _git(git_repo, "add", "two.txt")
    _git(git_repo, "commit", "-q", "-m", "second checkpoint")
    updated = _delivery(
        git_repo,
        "checkpoint",
        "--id",
        "fixture",
        "--command",
        "pytest two",
        "--result",
        "passed",
    )

    assert updated["verification"]["candidate"] is None
    assert updated["state"] == "CHECKPOINT"


def test_publish_does_not_infer_pr_authority(git_repo: Path) -> None:
    _start(git_repo, authorities=False)

    result = _delivery(
        git_repo,
        "publish",
        "--id",
        "fixture",
        "--pr",
        "17",
        expected=2,
    )

    assert result["ok"] is False
    assert "not authorized" in result["error"]


def test_authorize_records_late_user_authority_and_enables_publish(
    git_repo: Path,
) -> None:
    _start(git_repo, authorities=False)

    updated = _delivery(
        git_repo,
        "authorize",
        "--id",
        "fixture",
        "--push",
        "task-request",
        "--open-pr",
        "task-request",
        "--merge",
        "task-request",
        "--delete-remote-branch",
        "task-request",
    )
    published = _delivery(
        git_repo,
        "publish",
        "--id",
        "fixture",
        "--pr",
        "17",
    )

    assert updated["authorization"] == {
        "push": "task-request",
        "open_pr": "task-request",
        "merge": "task-request",
        "delete_remote_branch": "task-request",
    }
    assert updated["authorization_history"][-1]["previous"]["open_pr"] == "pending"
    assert published["pull_request"]["number"] == 17


def test_authorize_rejects_silent_authority_replacement(git_repo: Path) -> None:
    _start(git_repo)

    result = _delivery(
        git_repo,
        "authorize",
        "--id",
        "fixture",
        "--merge",
        "repository-policy",
        expected=2,
    )

    assert "refusing to replace existing merge authority" in result["error"]


def test_abandon_uses_exact_head_lease_is_idempotent_and_allows_cleanup(
    git_repo: Path,
) -> None:
    started = _start(git_repo)
    head = started["head_sha"]

    stale = _delivery(
        git_repo,
        "abandon",
        "--id",
        "fixture",
        "--head-sha",
        "not-the-recorded-head",
        "--reason",
        "superseded",
        expected=2,
    )
    assert "does not match recorded delivery head" in stale["error"]

    abandoned = _delivery(
        git_repo,
        "abandon",
        "--id",
        "fixture",
        "--head-sha",
        head,
        "--reason",
        "superseded by atomic deliveries",
    )
    repeated = _delivery(
        git_repo,
        "abandon",
        "--id",
        "fixture",
        "--head-sha",
        head,
        "--reason",
        "superseded by atomic deliveries",
    )
    active = _delivery(git_repo, "list")
    all_deliveries = _delivery(git_repo, "list", "--all")
    evidence = _delivery(git_repo, "evidence", "--id", "fixture")

    assert abandoned["state"] == "ABANDONED"
    assert abandoned["abandonment"]["head_sha"] == head
    assert repeated["abandonment"] == abandoned["abandonment"]
    assert active["deliveries"] == []
    assert [item["delivery_id"] for item in all_deliveries["deliveries"]] == [
        "fixture"
    ]
    assert evidence["abandonment"] == abandoned["abandonment"]

    changed_reason = _delivery(
        git_repo,
        "abandon",
        "--id",
        "fixture",
        "--head-sha",
        head,
        "--reason",
        "a different disposition",
        expected=2,
    )
    assert "already abandoned with different recorded facts" in changed_reason["error"]

    _git(git_repo, "switch", "-q", "main")
    _git(git_repo, "branch", "-D", "agent/fixture")
    cleaned = _delivery(git_repo, "verify-clean", "--id", "fixture")
    assert cleaned["state"] == "CLEAN"
    assert cleaned["cleanup"]["clean"] is True


def test_abandon_rejects_empty_reason_and_open_pr_then_accepts_closed_pr(
    git_repo: Path,
) -> None:
    _git(git_repo, "remote", "add", "origin", "https://github.com/acme/repo.git")
    started = _start(git_repo)
    head = started["head_sha"]

    empty = _delivery(
        git_repo,
        "abandon",
        "--id",
        "fixture",
        "--head-sha",
        head,
        "--reason",
        "",
        expected=2,
    )
    assert "reason must not be empty" in empty["error"]

    _delivery(
        git_repo,
        "publish",
        "--id",
        "fixture",
        "--pr",
        "17",
        "--url",
        "https://github.com/acme/repo/pull/17",
    )
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    _fake_gh(bin_dir, pr_state="OPEN")
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    open_pr = _delivery(
        git_repo,
        "abandon",
        "--id",
        "fixture",
        "--head-sha",
        head,
        "--reason",
        "superseded",
        env=env,
        expected=2,
    )
    assert "published delivery PR is not closed: OPEN" in open_pr["error"]

    _fake_gh(bin_dir, pr_state="CLOSED")
    abandoned = _delivery(
        git_repo,
        "abandon",
        "--id",
        "fixture",
        "--head-sha",
        head,
        "--reason",
        "superseded",
        env=env,
    )
    assert abandoned["state"] == "ABANDONED"
    assert abandoned["abandonment"]["closed_pull_request"]["state"] == "CLOSED"


def test_abandon_discovers_unrecorded_branch_prs(git_repo: Path) -> None:
    _git(git_repo, "remote", "add", "origin", "https://github.com/acme/repo.git")
    started = _start(git_repo)
    recorded_head = started["head_sha"]
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    _fake_gh(bin_dir, listed_pr_state="OPEN")
    open_pr = _delivery(
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
    assert "unrecorded PR #17 is still open" in open_pr["error"]

    _fake_gh(bin_dir, listed_pr_state="MERGED")
    merged_same_head = _delivery(
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
    assert "reconcile it instead of abandoning" in merged_same_head["error"]

    (git_repo / "later.txt").write_text("later delivery\n", encoding="utf-8")
    _git(git_repo, "add", "later.txt")
    _git(git_repo, "commit", "-q", "-m", "later delivery")
    _fake_gh(bin_dir, listed_pr_state="MERGED")
    superseded = _delivery(
        git_repo,
        "abandon",
        "--id",
        "fixture",
        "--head-sha",
        recorded_head,
        "--reason",
        "superseded before later branch delivery",
        env=env,
    )

    assert superseded["state"] == "ABANDONED"
    assert superseded["abandonment"]["closed_pull_request"] is None
    assert superseded["abandonment"]["related_pull_requests"] == [
        {
            "number": 17,
            "url": "https://github.com/acme/repo/pull/17",
            "state": "MERGED",
            "head_sha": _git(git_repo, "rev-parse", "HEAD"),
        }
    ]


def test_restack_updates_ancestry_with_head_lease(git_repo: Path) -> None:
    _start(git_repo)
    (git_repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(git_repo, "add", "feature.txt")
    _git(git_repo, "commit", "-q", "-m", "feature")
    old_head = _git(git_repo, "rev-parse", "HEAD")
    _delivery(
        git_repo,
        "checkpoint",
        "--id",
        "fixture",
        "--command",
        "focused tests",
        "--result",
        "passed",
    )

    _git(git_repo, "switch", "-q", "main")
    _git(git_repo, "switch", "-q", "-c", "agent/parent")
    (git_repo / "parent.txt").write_text("parent\n", encoding="utf-8")
    _git(git_repo, "add", "parent.txt")
    _git(git_repo, "commit", "-q", "-m", "parent")
    _git(git_repo, "switch", "-q", "agent/fixture")
    _git(git_repo, "rebase", "agent/parent")

    restacked = _delivery(
        git_repo,
        "restack",
        "--id",
        "fixture",
        "--previous-head",
        old_head,
        "--base",
        "agent/parent",
        "--parent",
        "parent-delivery",
    )

    assert restacked["base_ref"] == "agent/parent"
    assert restacked["base_sha"] == _git(git_repo, "rev-parse", "agent/parent")
    assert restacked["head_sha"] == _git(git_repo, "rev-parse", "HEAD")
    assert restacked["parent"] == "parent-delivery"
    assert restacked["verification"]["candidate"] is None
    assert restacked["restacks"][-1]["previous_head_sha"] == old_head


def test_restack_rejects_stale_head_lease(git_repo: Path) -> None:
    _start(git_repo)

    result = _delivery(
        git_repo,
        "restack",
        "--id",
        "fixture",
        "--previous-head",
        "not-the-recorded-head",
        "--base",
        "main",
        expected=2,
    )

    assert "restack lease mismatch" in result["error"]


def test_export_patch_preserves_tracked_and_untracked_changes(
    git_repo: Path,
) -> None:
    _start(git_repo)
    (git_repo / "README.md").write_text("changed\n", encoding="utf-8")
    (git_repo / "new.txt").write_text("new\n", encoding="utf-8")
    patch = git_repo.parent / "recovery.patch"

    state = _delivery(
        git_repo,
        "export-patch",
        "--id",
        "fixture",
        "--output",
        str(patch),
    )

    content = patch.read_text(encoding="utf-8")
    assert "README.md" in content
    assert "new.txt" in content
    assert state["artifacts"][-1]["kind"] == "patch"


def _fake_gh(
    bin_dir: Path,
    *,
    pending: bool = False,
    commit_count: int = 2,
    pr_state: str = "OPEN",
    listed_pr_state: str | None = None,
) -> Path:
    check = (
        '{"name":"Tests","status":"IN_PROGRESS","conclusion":""}'
        if pending
        else '{"name":"Tests","status":"COMPLETED","conclusion":"SUCCESS"}'
    )
    script = bin_dir / "gh"
    script.write_text(
        f"""#!/usr/bin/env python3
import json
import sys
args = sys.argv[1:]
if args[:2] == ["pr", "view"]:
    print(json.dumps({{
        "number": 17,
        "url": "https://github.com/acme/repo/pull/17",
        "state": {json.dumps(pr_state)},
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "headRefName": "agent/fixture",
        "headRefOid": {json.dumps(_git(bin_dir.parent, "rev-parse", "HEAD"))},
        "baseRefName": "main",
        "statusCheckRollup": [{check}],
        "commits": [{{"oid": str(index)}} for index in range({commit_count})],
    }}))
elif args[:2] == ["repo", "view"]:
    print(json.dumps({{
        "mergeCommitAllowed": True,
        "rebaseMergeAllowed": True,
        "squashMergeAllowed": True,
    }}))
elif args[:2] == ["pr", "list"]:
    if "--head" in args and {json.dumps(listed_pr_state)} is not None:
        print(json.dumps([{{
            "number": 17,
            "url": "https://github.com/acme/repo/pull/17",
            "state": {json.dumps(listed_pr_state)},
            "headRefOid": {json.dumps(_git(bin_dir.parent, "rev-parse", "HEAD"))},
        }}]))
    else:
        print("[]")
else:
    print("unsupported", file=sys.stderr)
    sys.exit(1)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_merge_plan_blocks_pending_checks_and_locks_exact_head(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(git_repo, "remote", "add", "origin", "https://github.com/acme/repo.git")
    _start(git_repo)
    _delivery(
        git_repo,
        "candidate",
        "--id",
        "fixture",
        "--command",
        "full CI",
        "--result",
        "passed",
    )
    _delivery(
        git_repo,
        "publish",
        "--id",
        "fixture",
        "--pr",
        "17",
        "--url",
        "https://github.com/acme/repo/pull/17",
    )
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    _fake_gh(bin_dir, pending=True)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    blocked = _delivery(
        git_repo,
        "merge-plan",
        "--id",
        "fixture",
        "--pr",
        "17",
        env=env,
        expected=2,
    )
    assert "pending" in blocked["error"]

    _fake_gh(bin_dir, pending=False)
    ambiguous = _delivery(
        git_repo,
        "merge-plan",
        "--id",
        "fixture",
        "--pr",
        "17",
        env=env,
        expected=2,
    )
    assert "ambiguous for a multi-commit PR" in ambiguous["error"]

    plan = _delivery(
        git_repo,
        "merge-plan",
        "--id",
        "fixture",
        "--pr",
        "17",
        "--strategy",
        "rebase",
        env=env,
    )
    assert plan["strategy"] == "rebase"
    assert plan["head_sha"] == _git(git_repo, "rev-parse", "HEAD")
    assert plan["command"][-2:] == ["--match-head-commit", plan["head_sha"]]


def test_merge_plan_auto_prefers_rebase_for_one_verified_commit(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(git_repo, "remote", "add", "origin", "https://github.com/acme/repo.git")
    _start(git_repo)
    _delivery(
        git_repo,
        "candidate",
        "--id",
        "fixture",
        "--command",
        "full CI",
        "--result",
        "passed",
    )
    _delivery(
        git_repo,
        "publish",
        "--id",
        "fixture",
        "--pr",
        "17",
        "--url",
        "https://github.com/acme/repo/pull/17",
    )
    bin_dir = git_repo / "fake-bin"
    bin_dir.mkdir()
    _fake_gh(bin_dir, commit_count=1)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    plan = _delivery(
        git_repo,
        "merge-plan",
        "--id",
        "fixture",
        "--pr",
        "17",
        env=env,
    )

    assert plan["strategy"] == "rebase"
    assert "single verified commit" in plan["reason"]
