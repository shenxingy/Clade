#!/usr/bin/env python3
"""GitHub forge adapter for the Clade delivery controller.

Everything here answers one question for `delivery.py`: what does the forge
say about a pull request, and what does that fact project onto a delivery
record? It is the half of the controller that talks to `gh`; `delivery.py`
owns the state machine and the CLI and imports from here, never the reverse
(`git_context.py` is the sibling read-only probe). The typed failure and the
subprocess wrapper live here too so that this module can raise the same
user-facing error the CLI prints without importing the state machine.

Split out of `delivery.py` when the forge-confirmed merge path pushed it past
the 1500-line ceiling. Stdlib only.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import time
from pathlib import Path
from typing import Any


# ─── Failure type and process primitives ─────────────────────────────────────


class DeliveryError(RuntimeError):
    """Typed user-facing delivery failure."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run_command(
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



# ─── gh queries ──────────────────────────────────────────────────────────────


def check_rollup(checks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
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


def gh_pr(root: Path, pr: str) -> dict[str, Any]:
    fields = (
        "number,url,state,isDraft,mergeable,mergeStateStatus,headRefName,"
        "headRefOid,baseRefName,statusCheckRollup,commits,"
        "mergeCommit,mergedAt,mergedBy"
    )
    result = run_command(
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


def settle_mergeability(
    root: Path,
    pr_number: str,
    pr: dict[str, Any],
    *,
    timeout: float,
) -> tuple[dict[str, Any], int]:
    """Re-query while GitHub still reports ``mergeable: UNKNOWN``.

    GitHub documents ``mergeable`` as computed asynchronously; right after a
    parent lands and a child is retargeted it reads UNKNOWN for tens of
    seconds. Backoff doubles from one second and the whole wait is bounded by
    ``timeout``; the caller decides what a still-UNKNOWN answer means.
    Returns the last PR snapshot and how many queries were made in total.
    """

    queries = 1
    deadline = time.monotonic() + max(timeout, 0.0)
    delay = 1.0
    while str(pr.get("mergeable") or "").upper() == "UNKNOWN":
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(delay, remaining))
        pr = gh_pr(root, pr_number)
        queries += 1
        delay = min(delay * 2, 16.0)
    return pr, queries


def gh_prs_by_head(root: Path, branch: str) -> list[dict[str, Any]]:
    result = run_command(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "all",
            "--head",
            branch,
            "--limit",
            "100",
            "--json",
            "number,url,state,headRefOid",
        ],
        cwd=root,
        timeout=15,
    )
    if result.returncode != 0:
        raise DeliveryError(
            result.stderr.strip() or "unable to discover PRs for delivery branch"
        )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DeliveryError("gh returned invalid branch PR JSON") from exc
    if not isinstance(data, list):
        raise DeliveryError("gh returned non-list branch PR JSON")
    return data


def pr_abandonment_fact(pr: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": pr.get("number"),
        "url": pr.get("url"),
        "state": str(pr.get("state") or "").upper(),
        "head_sha": pr.get("headRefOid"),
    }


def gh_methods(root: Path) -> list[str]:
    result = run_command(
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


def gh_children(root: Path, branch: str) -> list[dict[str, Any]]:
    result = run_command(
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



# ─── Forge fact → delivery merge record ──────────────────────────────────────


def infer_merge_strategy(root: Path, merge_sha: str) -> str | None:
    """Return "merge" for a multi-parent landed commit; otherwise None.

    The forge does not expose the merge method. A single-parent landed commit
    could be a squash or a rebase of one commit, and telling those apart
    needs the base at merge time, which is gone — so only the unambiguous
    case is inferred and the rest is recorded as unknown.
    """

    result = run_command(["git", "rev-list", "--parents", "-n", "1", merge_sha], cwd=root)
    if result.returncode != 0:
        return None
    return "merge" if len(result.stdout.split()) >= 3 else None


def merge_record_from_pr(
    root: Path,
    state: dict[str, Any],
    pr: dict[str, Any],
    *,
    merge_sha: str | None = None,
    head_sha: str | None = None,
    strategy: str | None = None,
) -> dict[str, Any]:
    """Build the `merge` record for a PR the forge reports as MERGED.

    Raises DeliveryError when the forge does not confirm: the PR is open or
    closed-unmerged, exposes no merge commit, or the caller's `--merge-sha` /
    `--head-sha` disagree with it. Never weakens `ready`: this path is only
    reachable once the forge already says the merge happened.
    """

    number = pr.get("number")
    live_state = str(pr.get("state") or "").upper()
    if live_state != "MERGED":
        raise DeliveryError(
            f"PR #{number} is not merged on the forge: {live_state or 'UNKNOWN'}"
        )
    forge_merge_sha = (pr.get("mergeCommit") or {}).get("oid")
    if not forge_merge_sha:
        raise DeliveryError(
            f"forge reports PR #{number} merged but exposes no merge commit"
        )
    if merge_sha and merge_sha != forge_merge_sha:
        raise DeliveryError(
            f"merge SHA mismatch: forge landed {forge_merge_sha}, received {merge_sha}"
        )
    forge_head = pr.get("headRefOid")
    if not forge_head:
        raise DeliveryError(f"forge exposes no head SHA for merged PR #{number}")
    if head_sha and head_sha != forge_head:
        raise DeliveryError(
            f"merged head SHA mismatch: forge head {forge_head}, received {head_sha}"
        )

    candidate = (state.get("verification") or {}).get("candidate") or None
    candidate_head = candidate.get("head_sha") if candidate else None
    ready = state.get("ready") or None
    ready_head = ready.get("head_sha") if ready else None

    if strategy:
        strategy_source = "argument"
    elif ready and ready_head == forge_head and ready.get("strategy"):
        strategy, strategy_source = ready["strategy"], "ready"
    else:
        strategy = infer_merge_strategy(root, forge_merge_sha)
        strategy_source = "inferred" if strategy else "unknown"

    merged_by = pr.get("mergedBy")
    return {
        "strategy": strategy,
        "strategy_source": strategy_source,
        "head_sha": forge_head,
        "merge_sha": forge_merge_sha,
        # Forge time, not record time: `recorded_at` carries the latter.
        "merged_at": pr.get("mergedAt") or utc_now(),
        "recorded_at": utc_now(),
        "merged_by": merged_by.get("login") if isinstance(merged_by, dict) else None,
        "pull_request": {
            "number": number,
            "url": pr.get("url"),
            "base": pr.get("baseRefName"),
        },
        "reconciled_from_forge": True,
        # True when no READY lock exists or the lock named a different head.
        "ready_skipped": ready_head != forge_head,
        # True when the recorded candidate evidence does not cover the merged
        # head — including when no candidate was recorded at all.
        "candidate_head": candidate_head,
        "candidate_stale": candidate_head != forge_head,
    }
