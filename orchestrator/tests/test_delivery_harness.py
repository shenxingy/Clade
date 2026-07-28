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


def _fake_gh(bin_dir: Path, *, pending: bool = False) -> Path:
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
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "headRefName": "agent/fixture",
        "headRefOid": {json.dumps(_git(bin_dir.parent, "rev-parse", "HEAD"))},
        "baseRefName": "main",
        "statusCheckRollup": [{check}],
        "commits": [{{"oid": "one"}}, {{"oid": "two"}}],
    }}))
elif args[:2] == ["repo", "view"]:
    print(json.dumps({{
        "mergeCommitAllowed": True,
        "rebaseMergeAllowed": True,
        "squashMergeAllowed": True,
    }}))
elif args[:2] == ["pr", "list"]:
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
    plan = _delivery(
        git_repo,
        "merge-plan",
        "--id",
        "fixture",
        "--pr",
        "17",
        env=env,
    )
    assert plan["strategy"] == "squash"
    assert plan["head_sha"] == _git(git_repo, "rev-parse", "HEAD")
    assert plan["command"][-2:] == ["--match-head-commit", plan["head_sha"]]
