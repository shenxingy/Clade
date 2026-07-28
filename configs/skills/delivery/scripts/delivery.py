#!/usr/bin/env python3
"""Resumable Clade Git delivery controller.

The controller persists delivery facts under Git's common directory so state
survives worktree, process, and agent-runtime changes without modifying the
target repository. External publication and integration remain explicit
actions; this tool records and validates them instead of inventing authority.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import git_context

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]


SCHEMA_VERSION = "clade.delivery/v1"
STATES = (
    "START",
    "BUILD",
    "CHECKPOINT",
    "PUBLISHED",
    "READY",
    "MERGED",
    "CLEAN",
    "BLOCKED",
    "ABANDONED",
)
TERMINAL_STATES = {"CLEAN", "ABANDONED"}
SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


class DeliveryError(RuntimeError):
    """Typed user-facing delivery failure."""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _run(
    args: list[str],
    *,
    cwd: Path,
    timeout: float = 15,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeliveryError(f"command failed: {' '.join(args)}: {exc}") from exc
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise DeliveryError(f"command failed: {' '.join(args)}: {detail}")
    return result


def _git(root: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=root, check=check)


def _root(repo: Path) -> Path:
    result = _git(repo, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise DeliveryError(f"not a Git repository: {repo}")
    return Path(result.stdout.strip()).resolve()


def _common_dir(root: Path) -> Path:
    result = _git(
        root,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
        check=True,
    )
    return Path(result.stdout.strip())


def _state_dir(root: Path) -> Path:
    return _common_dir(root) / "clade" / "deliveries"


def _safe_id(value: str) -> str:
    candidate = SAFE_ID.sub("-", value.strip()).strip("-")
    if not candidate or candidate in {".", ".."}:
        raise DeliveryError("delivery id must contain a letter or number")
    return candidate[:120]


def _state_path(root: Path, delivery_id: str) -> Path:
    return _state_dir(root) / f"{_safe_id(delivery_id)}.json"


@contextmanager
def _locked_state_dir(root: Path) -> Iterator[Path]:
    directory = _state_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield directory
        finally:
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _read_state(root: Path, delivery_id: str) -> dict[str, Any]:
    path = _state_path(root, delivery_id)
    if not path.is_file():
        raise DeliveryError(f"delivery does not exist: {delivery_id}")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeliveryError(f"delivery state is unreadable: {path}: {exc}") from exc
    if state.get("schema_version") != SCHEMA_VERSION:
        raise DeliveryError(
            f"unsupported delivery schema: {state.get('schema_version')!r}"
        )
    return state


def _write_state(root: Path, state: dict[str, Any]) -> None:
    path = _state_path(root, state["delivery_id"])
    state["updated_at"] = _now()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            json.dump(state, tmp, ensure_ascii=False, indent=2, sort_keys=True)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _head(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD", check=True).stdout.strip()


def _branch(root: Path) -> str | None:
    result = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def _verify_delivery_checkout(root: Path, state: dict[str, Any]) -> str:
    current = _branch(root)
    expected = state.get("branch")
    if expected and current != expected:
        raise DeliveryError(
            f"delivery {state['delivery_id']} owns {expected!r}, "
            f"but current branch is {current!r}"
        )
    return _head(root)


def _active_branch_lease(
    root: Path,
    branch: str,
    *,
    excluding: str | None = None,
) -> dict[str, Any] | None:
    directory = _state_dir(root)
    if not directory.is_dir():
        return None
    for path in directory.glob("*.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            state.get("delivery_id") != excluding
            and state.get("branch") == branch
            and state.get("state") not in TERMINAL_STATES
        ):
            return state
    return None


def _evidence(command: str, result: str, sha: str) -> dict[str, str]:
    return {
        "command": command,
        "result": result,
        "head_sha": sha,
        "recorded_at": _now(),
    }


def _invalidate_candidate(state: dict[str, Any], head_sha: str) -> None:
    candidate = state.get("verification", {}).get("candidate")
    if candidate and candidate.get("head_sha") != head_sha:
        state["verification"]["candidate"] = None
        state["ready"] = None
        if state["state"] == "READY":
            state["state"] = "BUILD"


def cmd_context(args: argparse.Namespace) -> dict[str, Any]:
    profile = git_context.probe(
        args.repo.resolve(),
        runtime=args.runtime,
        surface=args.surface,
        task_source=args.task_source,
    )
    if not profile.get("repository", {}).get("present"):
        raise DeliveryError("not a Git repository")
    return profile


def cmd_start(args: argparse.Namespace) -> dict[str, Any]:
    root = _root(args.repo.resolve())
    profile = git_context.probe(
        root,
        runtime=args.runtime,
        surface=args.surface,
        task_source=args.task_source,
    )
    repository = profile["repository"]
    if repository["dirty"] and not args.allow_dirty:
        raise DeliveryError(
            "refusing to start delivery with unrelated dirty files; "
            "preserve or disposition them first"
        )

    delivery_id = _safe_id(args.id or f"delivery-{uuid.uuid4().hex[:12]}")
    path = _state_path(root, delivery_id)
    requested_branch = args.branch or repository["current_branch"]
    current = repository["current_branch"]
    default_branch = repository["default_branch"]
    base_ref = args.base or (
        f"{repository['remote']}/{default_branch}"
        if repository["remote"] and default_branch
        else default_branch
    )
    if args.create_branch:
        if not requested_branch:
            raise DeliveryError("--create-branch requires --branch")
        if current and default_branch and current != default_branch and not args.parent:
            raise DeliveryError(
                f"current branch {current!r} is not default {default_branch!r}; "
                "record --parent for a stack instead of creating accidental ancestry"
            )
        if not base_ref:
            raise DeliveryError("cannot resolve a base; pass --base explicitly")
        if _git(
            root,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{requested_branch}",
        ).returncode == 0:
            raise DeliveryError(f"branch already exists: {requested_branch}")
        _git(root, "switch", "-c", requested_branch, base_ref, check=True)
        current = requested_branch
    elif requested_branch and requested_branch != current:
        raise DeliveryError(
            f"requested branch {requested_branch!r} is not checked out; "
            "use --create-branch or switch explicitly"
        )

    if requested_branch:
        lease = _active_branch_lease(root, requested_branch, excluding=delivery_id)
        if lease:
            raise DeliveryError(
                f"branch {requested_branch!r} is owned by active delivery "
                f"{lease.get('delivery_id')!r}"
            )
    if not base_ref:
        base_ref = "HEAD"
    base_sha = _git(root, "rev-parse", base_ref, check=True).stdout.strip()
    now = _now()
    state = {
        "schema_version": SCHEMA_VERSION,
        "delivery_id": delivery_id,
        "task_source": args.task_source,
        "owner": args.owner,
        "runtime": args.runtime,
        "surface": args.surface,
        "repository_root": str(root),
        "forge": repository["forge"],
        "remote": repository["remote"],
        "default_branch": default_branch,
        "base_ref": base_ref,
        "base_sha": base_sha,
        "parent": args.parent,
        "branch": current,
        "detached_ref": None,
        "head_sha": _head(root),
        "state": "BUILD",
        "published": False,
        "pull_request": None,
        "verification": {"checkpoints": [], "candidate": None},
        "restacks": [],
        "authorization": {
            "push": args.push_authority,
            "open_pr": args.pr_authority,
            "merge": args.merge_authority,
            "delete_remote_branch": args.delete_authority,
        },
        "ready": None,
        "merge": None,
        "cleanup": None,
        "artifacts": [],
        "created_at": now,
        "updated_at": now,
    }
    with _locked_state_dir(root):
        if path.exists():
            existing = _read_state(root, delivery_id)
            immutable = ("branch", "base_sha", "owner", "repository_root")
            if all(existing.get(key) == state.get(key) for key in immutable):
                return existing
            raise DeliveryError(f"delivery id already exists with different facts: {delivery_id}")
        _write_state(root, state)
    return state


def cmd_show(args: argparse.Namespace) -> dict[str, Any]:
    root = _root(args.repo.resolve())
    return _read_state(root, args.id)


def cmd_list(args: argparse.Namespace) -> dict[str, Any]:
    root = _root(args.repo.resolve())
    directory = _state_dir(root)
    deliveries: list[dict[str, Any]] = []
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if args.all or state.get("state") not in TERMINAL_STATES:
                deliveries.append(state)
    return {"schema_version": SCHEMA_VERSION, "deliveries": deliveries}


def cmd_checkpoint(args: argparse.Namespace) -> dict[str, Any]:
    root = _root(args.repo.resolve())
    with _locked_state_dir(root):
        state = _read_state(root, args.id)
        sha = _verify_delivery_checkout(root, state)
        record = _evidence(args.command, args.result, sha)
        checkpoints = state["verification"]["checkpoints"]
        if not any(
            item["head_sha"] == sha
            and item["command"] == args.command
            and item["result"] == args.result
            for item in checkpoints
        ):
            checkpoints.append(record)
        state["head_sha"] = sha
        state["state"] = "CHECKPOINT"
        _invalidate_candidate(state, sha)
        _write_state(root, state)
    return state


def cmd_candidate(args: argparse.Namespace) -> dict[str, Any]:
    root = _root(args.repo.resolve())
    with _locked_state_dir(root):
        state = _read_state(root, args.id)
        sha = _verify_delivery_checkout(root, state)
        if args.head_sha and args.head_sha != sha:
            raise DeliveryError(
                f"candidate SHA mismatch: expected {args.head_sha}, checkout is {sha}"
            )
        base_sha = _git(root, "rev-parse", state["base_ref"], check=True).stdout.strip()
        candidate = {
            **_evidence(args.command, args.result, sha),
            "base_ref": state["base_ref"],
            "base_sha": base_sha,
        }
        state["head_sha"] = sha
        state["base_sha"] = base_sha
        state["verification"]["candidate"] = candidate
        state["state"] = "BUILD"
        _write_state(root, state)
    return state


def cmd_restack(args: argparse.Namespace) -> dict[str, Any]:
    """Record verified new ancestry after an owned rebase/restack."""

    root = _root(args.repo.resolve())
    if _git(root, "status", "--porcelain=v1").stdout.strip():
        raise DeliveryError("refusing to record restack with a dirty working tree")
    with _locked_state_dir(root):
        state = _read_state(root, args.id)
        sha = _verify_delivery_checkout(root, state)
        previous = state.get("head_sha")
        if args.previous_head != previous:
            raise DeliveryError(
                f"restack lease mismatch: expected recorded head {previous}, "
                f"received {args.previous_head}"
            )
        base_sha = _git(root, "rev-parse", args.base, check=True).stdout.strip()
        if _git(
            root,
            "merge-base",
            "--is-ancestor",
            base_sha,
            sha,
        ).returncode != 0:
            raise DeliveryError(
                f"new base {args.base!r} ({base_sha}) is not an ancestor of HEAD {sha}"
            )
        if state.get("published") and not args.pr_base_updated:
            raise DeliveryError(
                "published delivery requires --pr-base-updated after retargeting "
                "the pull request"
            )
        restacks = state.setdefault("restacks", [])
        restacks.append(
            {
                "previous_head_sha": previous,
                "head_sha": sha,
                "previous_base_ref": state.get("base_ref"),
                "previous_base_sha": state.get("base_sha"),
                "base_ref": args.base,
                "base_sha": base_sha,
                "parent": args.parent,
                "recorded_at": _now(),
            }
        )
        state["head_sha"] = sha
        state["base_ref"] = args.base
        state["base_sha"] = base_sha
        state["parent"] = args.parent
        state["verification"]["candidate"] = None
        if state.get("pull_request") and args.pr_base_updated:
            state["pull_request"]["base"] = args.pr_base or args.base
            state["pull_request"]["head_sha"] = sha
        state["state"] = "PUBLISHED" if state.get("published") else "BUILD"
        _write_state(root, state)
    return state


def cmd_publish(args: argparse.Namespace) -> dict[str, Any]:
    root = _root(args.repo.resolve())
    with _locked_state_dir(root):
        state = _read_state(root, args.id)
        sha = _verify_delivery_checkout(root, state)
        authority = state["authorization"].get("open_pr")
        if args.pr and authority not in {"task-request", "repository-policy"}:
            raise DeliveryError(
                "PR publication is not authorized in delivery state; "
                "record task-request or repository-policy at START"
            )
        if args.head_sha and args.head_sha != sha:
            raise DeliveryError(
                f"published SHA mismatch: expected {args.head_sha}, checkout is {sha}"
            )
        _invalidate_candidate(state, sha)
        state["head_sha"] = sha
        state["published"] = True
        state["pull_request"] = {
            "number": args.pr,
            "url": args.url,
            "head_sha": sha,
            "base": args.base or state["default_branch"],
            "draft": args.draft,
        }
        state["state"] = "PUBLISHED"
        _write_state(root, state)
    return state


def _check_rollup(checks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    pending: list[str] = []
    failing: list[str] = []
    for item in checks:
        name = item.get("name") or item.get("context") or "unnamed-check"
        status = str(item.get("status") or "").upper()
        conclusion = str(item.get("conclusion") or "").upper()
        if status and status != "COMPLETED":
            pending.append(name)
        elif conclusion not in {"SUCCESS", "NEUTRAL", "SKIPPED"}:
            failing.append(name)
    return pending, failing


def _gh_pr(root: Path, pr: str) -> dict[str, Any]:
    fields = (
        "number,url,state,isDraft,mergeable,mergeStateStatus,headRefName,"
        "headRefOid,baseRefName,statusCheckRollup,commits"
    )
    result = _run(
        ["gh", "pr", "view", pr, "--json", fields],
        cwd=root,
        timeout=15,
    )
    if result.returncode != 0:
        raise DeliveryError(result.stderr.strip() or "unable to inspect PR")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DeliveryError("gh returned invalid PR JSON") from exc


def _gh_methods(root: Path) -> list[str]:
    result = _run(
        [
            "gh",
            "repo",
            "view",
            "--json",
            "mergeCommitAllowed,rebaseMergeAllowed,squashMergeAllowed",
        ],
        cwd=root,
        timeout=15,
    )
    if result.returncode != 0:
        raise DeliveryError(result.stderr.strip() or "unable to inspect merge policy")
    data = json.loads(result.stdout)
    return [
        method
        for field, method in (
            ("squashMergeAllowed", "squash"),
            ("rebaseMergeAllowed", "rebase"),
            ("mergeCommitAllowed", "merge"),
        )
        if data.get(field)
    ]


def _gh_children(root: Path, branch: str) -> list[dict[str, Any]]:
    result = _run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--base",
            branch,
            "--json",
            "number,url,headRefName,baseRefName",
        ],
        cwd=root,
        timeout=15,
    )
    if result.returncode != 0:
        raise DeliveryError(result.stderr.strip() or "unable to inspect child PRs")
    return json.loads(result.stdout)


def cmd_merge_plan(args: argparse.Namespace) -> dict[str, Any]:
    root = _root(args.repo.resolve())
    state = _read_state(root, args.id)
    if state["authorization"].get("merge") not in {
        "task-request",
        "repository-policy",
    }:
        raise DeliveryError("merge is not authorized in delivery state")
    if state.get("forge") != "github":
        raise DeliveryError("GitHub merge adapter is unavailable for this delivery")
    pr_number = str(args.pr or (state.get("pull_request") or {}).get("number") or "")
    if not pr_number:
        raise DeliveryError("delivery has no PR; pass --pr")

    pr = _gh_pr(root, pr_number)
    if str(pr.get("state")).upper() != "OPEN":
        raise DeliveryError(f"PR is not open: {pr.get('state')}")
    if pr.get("isDraft"):
        raise DeliveryError("PR is still draft")
    if str(pr.get("mergeable")).upper() != "MERGEABLE":
        raise DeliveryError(f"PR is not mergeable: {pr.get('mergeable')}")
    pending, failing = _check_rollup(pr.get("statusCheckRollup") or [])
    if pending:
        raise DeliveryError(f"required checks are pending: {', '.join(pending)}")
    if failing:
        raise DeliveryError(f"required checks failed: {', '.join(failing)}")
    candidate = state.get("verification", {}).get("candidate")
    if not candidate:
        raise DeliveryError("no candidate verification is recorded")
    if candidate.get("head_sha") != pr.get("headRefOid"):
        raise DeliveryError(
            "candidate evidence is stale: "
            f"{candidate.get('head_sha')} != PR head {pr.get('headRefOid')}"
        )

    methods = _gh_methods(root)
    children = _gh_children(root, pr["headRefName"])
    requested = args.strategy
    if requested != "auto":
        if requested not in methods:
            raise DeliveryError(
                f"requested merge strategy {requested!r} is disabled; "
                f"allowed: {', '.join(methods) or 'none'}"
            )
        strategy = requested
        reason = "explicit strategy allowed by repository policy"
    elif children:
        if "merge" not in methods:
            raise DeliveryError(
                "live child PRs depend on this head and merge commits are disabled; "
                "restack every child before rewriting parent ancestry"
            )
        strategy = "merge"
        reason = "preserve ancestry for live child PRs"
    elif "squash" in methods:
        strategy = "squash"
        reason = "atomic unstacked PR; working commits are review checkpoints"
    elif len(pr.get("commits") or []) == 1 and "rebase" in methods:
        strategy = "rebase"
        reason = "single verified commit and squash is unavailable"
    elif "merge" in methods:
        strategy = "merge"
        reason = "repository merge policy fallback"
    elif "rebase" in methods:
        strategy = "rebase"
        reason = "repository permits only rebase integration"
    else:
        raise DeliveryError("repository exposes no supported merge strategy")

    return {
        "schema_version": SCHEMA_VERSION,
        "delivery_id": state["delivery_id"],
        "pr": pr["number"],
        "url": pr["url"],
        "base": pr["baseRefName"],
        "head": pr["headRefName"],
        "head_sha": pr["headRefOid"],
        "strategy": strategy,
        "reason": reason,
        "children": children,
        "command": [
            "gh",
            "pr",
            "merge",
            str(pr["number"]),
            f"--{strategy}",
            "--match-head-commit",
            pr["headRefOid"],
        ],
    }


def cmd_ready(args: argparse.Namespace) -> dict[str, Any]:
    plan = cmd_merge_plan(args)
    root = _root(args.repo.resolve())
    with _locked_state_dir(root):
        state = _read_state(root, args.id)
        state["state"] = "READY"
        state["ready"] = {**plan, "recorded_at": _now()}
        _write_state(root, state)
    return state


def cmd_merged(args: argparse.Namespace) -> dict[str, Any]:
    root = _root(args.repo.resolve())
    with _locked_state_dir(root):
        state = _read_state(root, args.id)
        ready = state.get("ready")
        if not ready:
            raise DeliveryError("delivery was not READY")
        if args.head_sha and args.head_sha != ready.get("head_sha"):
            raise DeliveryError("merged head SHA does not match locked READY head")
        state["state"] = "MERGED"
        state["merge"] = {
            "strategy": args.strategy or ready["strategy"],
            "head_sha": ready["head_sha"],
            "merge_sha": args.merge_sha,
            "merged_at": _now(),
        }
        _write_state(root, state)
    return state


def cmd_preserve_ref(args: argparse.Namespace) -> dict[str, Any]:
    root = _root(args.repo.resolve())
    with _locked_state_dir(root):
        state = _read_state(root, args.id)
        sha = _verify_delivery_checkout(root, state)
        ref = f"refs/clade/deliveries/{_safe_id(args.id)}"
        _git(root, "update-ref", ref, sha, check=True)
        state["detached_ref"] = ref
        state["head_sha"] = sha
        artifact = {"kind": "git-ref", "path": ref, "head_sha": sha, "created_at": _now()}
        if artifact not in state["artifacts"]:
            state["artifacts"].append(artifact)
        _write_state(root, state)
    return state


def cmd_export_patch(args: argparse.Namespace) -> dict[str, Any]:
    root = _root(args.repo.resolve())
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    tracked = _git(root, "diff", "--binary", "HEAD")
    if tracked.returncode != 0:
        raise DeliveryError(tracked.stderr.strip() or "unable to export tracked diff")
    pieces = [tracked.stdout]
    untracked_result = _git(
        root, "ls-files", "--others", "--exclude-standard", "-z"
    )
    for relative in filter(None, untracked_result.stdout.split("\0")):
        patch = _run(
            ["git", "diff", "--binary", "--no-index", "--", "/dev/null", relative],
            cwd=root,
        )
        if patch.returncode not in {0, 1}:
            raise DeliveryError(patch.stderr.strip() or f"unable to export {relative}")
        pieces.append(patch.stdout)
    content = "".join(pieces)
    if not content:
        raise DeliveryError("working tree has no changes to export")
    output.write_text(content, encoding="utf-8")
    with _locked_state_dir(root):
        state = _read_state(root, args.id)
        artifact = {
            "kind": "patch",
            "path": str(output),
            "head_sha": _head(root),
            "created_at": _now(),
        }
        state["artifacts"].append(artifact)
        _write_state(root, state)
    return state


def cmd_verify_clean(args: argparse.Namespace) -> dict[str, Any]:
    root = _root(args.repo.resolve())
    state = _read_state(root, args.id)
    default_branch = state.get("default_branch")
    remote = state.get("remote")
    branch = state.get("branch")
    failures: list[str] = []
    dirty = bool(_git(root, "status", "--porcelain=v1").stdout.strip())
    if dirty:
        failures.append("working-tree-dirty")
    current = _branch(root)
    if default_branch and current != default_branch:
        failures.append(f"not-on-default-branch:{current}")
    ahead_behind = None
    if remote and default_branch:
        comparison = _git(
            root,
            "rev-list",
            "--left-right",
            "--count",
            f"{default_branch}...{remote}/{default_branch}",
        )
        if comparison.returncode != 0:
            failures.append("default-branch-remote-comparison-unavailable")
        else:
            ahead_behind = comparison.stdout.strip()
            if ahead_behind != "0\t0":
                failures.append(f"default-branch-diverged:{ahead_behind}")
    local_exists = bool(
        branch
        and _git(
            root,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
        ).returncode
        == 0
    )
    if local_exists:
        failures.append("local-topic-branch-present")
    remote_exists: bool | str = "unknown"
    if remote and branch:
        lookup = _git(root, "ls-remote", "--exit-code", "--heads", remote, branch)
        if lookup.returncode == 0:
            remote_exists = True
            failures.append("remote-topic-branch-present")
        elif lookup.returncode == 2:
            remote_exists = False
        else:
            failures.append("remote-topic-branch-check-failed")
    result = {
        "clean": not failures,
        "failures": failures,
        "current_branch": current,
        "default_branch": default_branch,
        "ahead_behind": ahead_behind,
        "topic_branch": branch,
        "local_topic_present": local_exists,
        "remote_topic_present": remote_exists,
    }
    if failures:
        raise DeliveryError("cleanup verification failed: " + ", ".join(failures))
    with _locked_state_dir(root):
        state = _read_state(root, args.id)
        state["state"] = "CLEAN"
        state["cleanup"] = {**result, "verified_at": _now()}
        _write_state(root, state)
    return state


def _common_repo(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", type=Path, default=Path.cwd())


def _add_runtime(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--runtime",
        default=os.environ.get("CLADE_AGENT_RUNTIME", "unknown"),
    )
    parser.add_argument(
        "--surface",
        default=os.environ.get("CLADE_SURFACE", "local-interactive"),
        choices=("local-interactive", "managed-worktree", "cloud-vm", "ci-action"),
    )
    parser.add_argument(
        "--task-source",
        default=os.environ.get("CLADE_TASK_SOURCE", "prompt"),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compact", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    context = sub.add_parser("context")
    _common_repo(context)
    _add_runtime(context)
    context.set_defaults(handler=cmd_context)

    start = sub.add_parser("start")
    _common_repo(start)
    _add_runtime(start)
    start.add_argument("--id")
    start.add_argument("--owner", required=True)
    start.add_argument("--branch")
    start.add_argument("--base")
    start.add_argument("--parent")
    start.add_argument("--create-branch", action="store_true")
    start.add_argument("--allow-dirty", action="store_true")
    start.add_argument("--push-authority", default="pending")
    start.add_argument("--pr-authority", default="pending")
    start.add_argument("--merge-authority", default="pending")
    start.add_argument("--delete-authority", default="pending")
    start.set_defaults(handler=cmd_start)

    show = sub.add_parser("show")
    _common_repo(show)
    show.add_argument("--id", required=True)
    show.set_defaults(handler=cmd_show)

    listing = sub.add_parser("list")
    _common_repo(listing)
    listing.add_argument("--all", action="store_true")
    listing.set_defaults(handler=cmd_list)

    for name, handler in (("checkpoint", cmd_checkpoint), ("candidate", cmd_candidate)):
        command = sub.add_parser(name)
        _common_repo(command)
        command.add_argument("--id", required=True)
        command.add_argument("--command", required=True)
        command.add_argument("--result", required=True)
        command.add_argument("--head-sha")
        command.set_defaults(handler=handler)

    restack = sub.add_parser("restack")
    _common_repo(restack)
    restack.add_argument("--id", required=True)
    restack.add_argument("--previous-head", required=True)
    restack.add_argument("--base", required=True)
    restack.add_argument("--parent")
    restack.add_argument("--pr-base-updated", action="store_true")
    restack.add_argument("--pr-base")
    restack.set_defaults(handler=cmd_restack)

    publish = sub.add_parser("publish")
    _common_repo(publish)
    publish.add_argument("--id", required=True)
    publish.add_argument("--pr", type=int)
    publish.add_argument("--url")
    publish.add_argument("--base")
    publish.add_argument("--head-sha")
    publish.add_argument("--draft", action="store_true")
    publish.set_defaults(handler=cmd_publish)

    for name, handler in (("merge-plan", cmd_merge_plan), ("ready", cmd_ready)):
        command = sub.add_parser(name)
        _common_repo(command)
        command.add_argument("--id", required=True)
        command.add_argument("--pr")
        command.add_argument(
            "--strategy",
            choices=("auto", "squash", "rebase", "merge"),
            default="auto",
        )
        command.set_defaults(handler=handler)

    merged = sub.add_parser("merged")
    _common_repo(merged)
    merged.add_argument("--id", required=True)
    merged.add_argument("--head-sha")
    merged.add_argument("--merge-sha", required=True)
    merged.add_argument("--strategy", choices=("squash", "rebase", "merge"))
    merged.set_defaults(handler=cmd_merged)

    preserve = sub.add_parser("preserve-ref")
    _common_repo(preserve)
    preserve.add_argument("--id", required=True)
    preserve.set_defaults(handler=cmd_preserve_ref)

    export = sub.add_parser("export-patch")
    _common_repo(export)
    export.add_argument("--id", required=True)
    export.add_argument("--output", type=Path, required=True)
    export.set_defaults(handler=cmd_export_patch)

    clean = sub.add_parser("verify-clean")
    _common_repo(clean)
    clean.add_argument("--id", required=True)
    clean.set_defaults(handler=cmd_verify_clean)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.handler(args)
    except DeliveryError as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": False,
                    "error": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
