#!/usr/bin/env python3
"""Read-only Git/forge/runtime capability probe for Clade delivery workflows.

The probe intentionally separates technical capability from authorization.
Missing tools, API failures, detached checkouts, and unknown ownership remain
explicit instead of being converted into permission.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


SCHEMA_VERSION = "clade.git-context/v1"
AGENT_BRANCH_PREFIXES = ("agent/", "ai/", "clade/", "claude/", "codex/", "wt/")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def _run(
    args: Iterable[str],
    *,
    cwd: Path,
    timeout: float = 5,
    env: dict[str, str] | None = None,
) -> CommandResult:
    try:
        completed = subprocess.run(
            list(args),
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(127, "", str(exc))
    return CommandResult(
        completed.returncode,
        completed.stdout.strip(),
        completed.stderr.strip(),
    )


def _git(cwd: Path, *args: str) -> CommandResult:
    return _run(("git", *args), cwd=cwd)


def _nullable(value: str) -> str | None:
    value = value.strip()
    return value or None


def _git_root(cwd: Path) -> Path | None:
    result = _git(cwd, "rev-parse", "--show-toplevel")
    return Path(result.stdout).resolve() if result.returncode == 0 else None


def _git_common_dir(root: Path) -> Path | None:
    result = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(result.stdout) if result.returncode == 0 else None


def _current_branch(root: Path) -> str | None:
    result = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    return _nullable(result.stdout) if result.returncode == 0 else None


def _upstream(root: Path) -> str | None:
    result = _git(
        root,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
    )
    return _nullable(result.stdout) if result.returncode == 0 else None


def _remotes(root: Path) -> list[dict[str, str]]:
    result = _git(root, "remote", "-v")
    seen: set[tuple[str, str, str]] = set()
    remotes: list[dict[str, str]] = []
    if result.returncode != 0:
        return remotes
    for raw in result.stdout.splitlines():
        parts = raw.split()
        if len(parts) < 3:
            continue
        kind = parts[2].strip("()")
        key = (parts[0], parts[1], kind)
        if key not in seen:
            seen.add(key)
            remotes.append({"name": parts[0], "url": parts[1], "kind": kind})
    return remotes


def _select_remote(remotes: list[dict[str, str]], upstream: str | None) -> str | None:
    names = [item["name"] for item in remotes if item["kind"] == "fetch"]
    if upstream and "/" in upstream and upstream.split("/", 1)[0] in names:
        return upstream.split("/", 1)[0]
    if "origin" in names:
        return "origin"
    return names[0] if names else None


def _remote_url(remotes: list[dict[str, str]], remote: str | None) -> str | None:
    return next(
        (
            item["url"]
            for item in remotes
            if item["name"] == remote and item["kind"] == "fetch"
        ),
        None,
    )


def _forge_from_url(url: str | None) -> str:
    if not url:
        return "none"
    lowered = url.lower()
    if "github.com" in lowered:
        return "github"
    if "gitlab" in lowered:
        return "gitlab"
    if "bitbucket" in lowered:
        return "bitbucket"
    return "other"


def _repo_slug(url: str | None) -> str | None:
    if not url:
        return None
    if "://" in url:
        parsed = urlparse(url)
        path = parsed.path
    elif ":" in url and not url.startswith("/"):
        path = url.split(":", 1)[1]
    else:
        path = url
    slug = path.strip("/")
    if slug.endswith(".git"):
        slug = slug[:-4]
    return slug if slug.count("/") >= 1 else None


def _local_default_branch(root: Path, remote: str | None) -> tuple[str | None, str]:
    if remote:
        result = _git(
            root,
            "symbolic-ref",
            "--quiet",
            "--short",
            f"refs/remotes/{remote}/HEAD",
        )
        if result.returncode == 0 and "/" in result.stdout:
            return result.stdout.split("/", 1)[1], "remote-head"

        refs = _git(
            root,
            "for-each-ref",
            "--format=%(refname:short)",
            f"refs/remotes/{remote}",
        )
        candidates = {
            ref.split("/", 1)[1]
            for ref in refs.stdout.splitlines()
            if "/" in ref and not ref.endswith("/HEAD")
        }
        for name in ("main", "master", "trunk", "develop"):
            if name in candidates:
                return name, "remote-ref-heuristic"

    for name in ("main", "master", "trunk", "develop"):
        if _git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{name}").returncode == 0:
            return name, "local-ref-heuristic"
    return None, "unknown"


def _gh_json(root: Path, args: Iterable[str]) -> tuple[Any | None, str | None]:
    if shutil.which("gh") is None:
        return None, "gh-unavailable"
    result = _run(("gh", *args), cwd=root, timeout=8)
    if result.returncode != 0:
        return None, result.stderr or "gh-command-failed"
    try:
        return json.loads(result.stdout), None
    except json.JSONDecodeError:
        return None, "gh-invalid-json"


def _github_profile(
    root: Path,
    slug: str | None,
    branch: str | None,
) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "available": shutil.which("gh") is not None,
        "authenticated": "unknown",
        "repository": slug,
        "default_branch": None,
        "merge_methods": [],
        "delete_branch_on_merge": "unknown",
        "branch_protected": "unknown",
        "error": None,
    }
    if not slug or not profile["available"]:
        return profile

    repo, error = _gh_json(
        root,
        (
            "repo",
            "view",
            slug,
            "--json",
            (
                "nameWithOwner,defaultBranchRef,mergeCommitAllowed,"
                "rebaseMergeAllowed,squashMergeAllowed,deleteBranchOnMerge"
            ),
        ),
    )
    if error:
        profile["error"] = error
        profile["authenticated"] = False if "auth" in error.lower() else "unknown"
        return profile

    profile["authenticated"] = True
    profile["repository"] = repo.get("nameWithOwner") or slug
    default_ref = repo.get("defaultBranchRef") or {}
    profile["default_branch"] = default_ref.get("name")
    for field, method in (
        ("squashMergeAllowed", "squash"),
        ("rebaseMergeAllowed", "rebase"),
        ("mergeCommitAllowed", "merge"),
    ):
        if repo.get(field):
            profile["merge_methods"].append(method)
    profile["delete_branch_on_merge"] = bool(repo.get("deleteBranchOnMerge"))

    if branch:
        owner, name = profile["repository"].split("/", 1)
        query = (
            "query($owner:String!,$name:String!,$branch:String!){"
            "repository(owner:$owner,name:$name){"
            "ref(qualifiedName:$branch){branchProtectionRule{pattern}}}}"
        )
        protected, protection_error = _gh_json(
            root,
            (
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"owner={owner}",
                "-F",
                f"name={name}",
                "-F",
                f"branch=refs/heads/{branch}",
            ),
        )
        if not protection_error:
            repository = protected.get("data", {}).get("repository") or {}
            ref = repository.get("ref") or {}
            rule = ref.get("branchProtectionRule")
            profile["branch_protected"] = rule is not None
    return profile


def _pull_request(root: Path, forge: str) -> dict[str, Any]:
    empty = {
        "number": None,
        "state": None,
        "base": None,
        "head": None,
        "same_repository": None,
        "author": None,
        "error": None,
    }
    if forge != "github":
        return empty
    pr, error = _gh_json(
        root,
        (
            "pr",
            "view",
            "--json",
            "number,state,baseRefName,headRefName,isCrossRepository,author",
        ),
    )
    if error:
        empty["error"] = error
        return empty
    author = pr.get("author") or {}
    return {
        "number": pr.get("number"),
        "state": str(pr.get("state") or "").lower() or None,
        "base": pr.get("baseRefName"),
        "head": pr.get("headRefName"),
        "same_repository": not bool(pr.get("isCrossRepository")),
        "author": author.get("login"),
        "error": None,
    }


def _worktrees(root: Path) -> list[dict[str, Any]]:
    result = _git(root, "worktree", "list", "--porcelain")
    if result.returncode != 0:
        return []
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in (*result.stdout.splitlines(), ""):
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current["path"] = str(Path(value).resolve())
        elif key == "HEAD":
            current["head"] = value
        elif key == "branch":
            current["branch"] = value.removeprefix("refs/heads/")
        elif key == "detached":
            current["detached"] = True
        elif key == "locked":
            current["locked"] = value or True
        elif key == "prunable":
            current["prunable"] = value or True
    return entries


def _instructions(root: Path, cwd: Path) -> list[dict[str, Any]]:
    try:
        relative = cwd.resolve().relative_to(root)
    except ValueError:
        relative = Path(".")
    chain = [root]
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        chain.append(cursor)

    found: list[dict[str, Any]] = []
    for directory in chain:
        for name in ("AGENTS.md", "CLAUDE.md"):
            path = directory / name
            if path.is_file():
                found.append(
                    {
                        "path": str(path.relative_to(root)),
                        "kind": name,
                        "scope": str(directory.relative_to(root)) or ".",
                    }
                )
    for name in ("CONTRIBUTING.md", "CONTRIBUTING.rst", "CODEOWNERS"):
        candidates = [root / name]
        if name == "CODEOWNERS":
            candidates.extend((root / ".github" / name, root / "docs" / name))
        for path in candidates:
            if path.is_file():
                found.append(
                    {
                        "path": str(path.relative_to(root)),
                        "kind": name,
                        "scope": ".",
                    }
                )
                break
    return found


def _state_owner(root: Path, branch: str | None) -> tuple[str, str | None]:
    if not branch:
        return "runtime", None
    git_dir = _git_common_dir(root)
    if not git_dir:
        return "unknown", None
    state_dir = git_dir / "clade" / "deliveries"
    if not state_dir.is_dir():
        return "unknown", None
    for state_path in state_dir.glob("*.json"):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if state.get("branch") == branch and state.get("state") not in {
            "CLEAN",
            "ABANDONED",
        }:
            return "session", state.get("owner")
    return "unknown", None


def _authorization(
    *,
    branch: str | None,
    default_branch: str | None,
    protected: Any,
    owner: str,
    forge_ready: bool,
    pr: dict[str, Any],
) -> dict[str, dict[str, str]]:
    def decision(value: str, reason: str) -> dict[str, str]:
        return {"decision": value, "reason": reason}

    result = {
        "inspect": decision("allowed", "read-only repository inspection"),
        "commit": decision("requires-authority", "branch ownership is unknown"),
        "push": decision("requires-authority", "publication is a separate action"),
        "open_pr": decision(
            "requires-authority" if forge_ready else "unsupported",
            "PR publication requires task or repository authority"
            if forge_ready
            else "no authenticated forge adapter",
        ),
        "merge_pr": decision(
            "requires-authority" if forge_ready else "unsupported",
            "integration requires explicit task or repository automation authority"
            if forge_ready
            else "no authenticated forge adapter",
        ),
        "delete_remote_branch": decision(
            "requires-authority", "remote deletion is an external destructive action"
        ),
        "force_push": decision(
            "denied", "plain force is never allowed; lease requires owned branch"
        ),
    }
    if branch is None:
        result["commit"] = decision(
            "allowed", "detached checkpoints are local and require a reachable ref before cleanup"
        )
        result["push"] = decision(
            "blocked", "detached HEAD must be attached to an owned branch before push"
        )
    elif default_branch and branch == default_branch:
        result["commit"] = decision(
            "requires-authority", "current branch is the repository default branch"
        )
        result["push"] = decision(
            "denied" if protected is True else "requires-authority",
            "direct default-branch publication is never inferred",
        )
    elif owner == "session":
        result["commit"] = decision("allowed", "active Clade delivery owns this branch")
        result["push"] = decision(
            "requires-authority", "owned branch is safe to publish only when requested/policy allows"
        )
        result["force_push"] = decision(
            "requires-authority",
            "force-with-lease allowed only for verified owned restack",
        )

    if pr.get("number"):
        result["open_pr"] = decision("not-needed", "current branch already has a PR")
    return result


def probe(
    cwd: Path,
    *,
    runtime: str,
    surface: str,
    task_source: str,
) -> dict[str, Any]:
    root = _git_root(cwd)
    if root is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "runtime": {"id": runtime, "surface": surface},
            "task": {"source": task_source},
            "repository": {"present": False, "root": None, "forge": "none"},
            "errors": ["not-a-git-repository"],
        }

    branch = _current_branch(root)
    upstream = _upstream(root)
    remotes = _remotes(root)
    remote = _select_remote(remotes, upstream)
    remote_url = _remote_url(remotes, remote)
    forge = _forge_from_url(remote_url)
    slug = _repo_slug(remote_url)
    local_default, default_source = _local_default_branch(root, remote)
    github = _github_profile(root, slug, branch) if forge == "github" else {}
    default_branch = github.get("default_branch") or local_default
    if github.get("default_branch"):
        default_source = "forge-api"
    protected = github.get("branch_protected", "unknown")
    pr = _pull_request(root, forge)
    worktrees = _worktrees(root)
    owner, owner_id = _state_owner(root, branch)
    current_path = str(root.resolve())
    current_worktree = next(
        (item for item in worktrees if item.get("path") == current_path),
        None,
    )
    branch_elsewhere = next(
        (
            item.get("path")
            for item in worktrees
            if branch and item.get("branch") == branch and item.get("path") != current_path
        ),
        None,
    )
    if branch_elsewhere:
        owner = "shared"

    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    dirty_files = [line for line in status.stdout.splitlines() if line]
    forge_ready = bool(
        forge == "github"
        and github.get("available")
        and github.get("authenticated") is True
    )
    trust_override = os.environ.get("CLADE_TRUSTED_CHECKOUT", "").strip().lower()
    if trust_override in {"1", "true", "yes"}:
        trusted_checkout: bool | str = True
    elif trust_override in {"0", "false", "no"}:
        trusted_checkout = False
    elif os.environ.get("GITHUB_EVENT_NAME") in {"pull_request_target", "workflow_run"}:
        trusted_checkout = "unknown"
    else:
        trusted_checkout = True if surface == "local-interactive" else "unknown"

    return {
        "schema_version": SCHEMA_VERSION,
        "runtime": {
            "id": runtime,
            "surface": surface,
            "trusted_checkout": trusted_checkout,
        },
        "task": {"source": task_source},
        "repository": {
            "present": True,
            "root": str(root),
            "common_git_dir": str(_git_common_dir(root) or ""),
            "forge": forge,
            "slug": slug,
            "remote": remote,
            "remote_url": remote_url,
            "default_branch": default_branch,
            "default_branch_source": default_source,
            "current_branch": branch,
            "detached": branch is None,
            "head_sha": _nullable(_git(root, "rev-parse", "HEAD").stdout),
            "upstream": upstream,
            "dirty": bool(dirty_files),
            "dirty_entries": dirty_files,
            "instructions": _instructions(root, cwd),
        },
        "branch": {
            "name": branch,
            "protected": protected,
            "owner": owner,
            "owner_id": owner_id,
            "worktree": current_worktree,
            "worktree_owner_elsewhere": branch_elsewhere,
            "agent_named_hint": bool(
                branch and branch.startswith(AGENT_BRANCH_PREFIXES)
            ),
        },
        "pull_request": pr,
        "forge": {
            "adapter": forge,
            "github": github if forge == "github" else None,
        },
        "capabilities": {
            "commit": True,
            "detached_checkpoint": True,
            "push": remote is not None,
            "open_pr": forge_ready,
            "merge_pr": forge_ready,
            "delete_remote_branch": remote is not None,
        },
        "authorization": _authorization(
            branch=branch,
            default_branch=default_branch,
            protected=protected,
            owner=owner,
            forge_ready=forge_ready,
            pr=pr,
        ),
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
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
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    profile = probe(
        args.repo.resolve(),
        runtime=args.runtime,
        surface=args.surface,
        task_source=args.task_source,
    )
    print(
        json.dumps(
            profile,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
    )
    return 0 if profile.get("repository", {}).get("present") else 2


if __name__ == "__main__":
    raise SystemExit(main())
