"""
worker_hydrate.py — Pre-hydration: fetch linked resources before agent starts.

Stripe Blueprint pattern: deterministically fetch GitHub issues, PRs, CI run
logs, and URLs referenced in the task description so the agent does not waste
tool calls on retrieval. Called from Worker._build_task_file() before writing
the task file.

Imports:
    from worker_hydrate import _pre_hydrate, _parse_linked_references
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path


def _extract_acceptance_criteria(body: str) -> str:
    """Lift an 'Acceptance Criteria' / 'Definition of Done' section out of a
    GitHub issue body (Reflection §G5 / Agentless spec-checklist).

    The full body is already injected (truncated), but a done-criteria section
    buried in 2 KB of prose is easy for the worker to skim past and the oracle
    never sees as an explicit contract. Pulling it into its own callout makes it
    a first-class acceptance gate. Returns '' when no such section exists.
    """
    if not body:
        return ""
    m = re.search(
        r"(?ims)^[#>*\s]*"
        r"(?:acceptance\s+criteria|definition\s+of\s+done|acceptance\s+tests|done\s+when)"
        r"[:\-*]*[ \t]*\n(.*?)(?=\n[ \t]*#{1,6}\s|\n[ \t]*\*\*|\Z)",
        body,
    )
    if not m:
        return ""
    return m.group(1).strip()[:800]


def _parse_linked_references(text: str) -> dict[str, list[str]]:
    """Parse task description for explicit resource references.

    Returns dict with keys: 'issues', 'prs', 'urls', 'ci_runs'
    Matches: #123, owner/repo#123, https://github.com/owner/repo/issues/123,
    https://github.com/owner/repo/actions/runs/123456
    """
    refs: dict[str, list[str]] = {"issues": [], "prs": [], "urls": [], "ci_runs": []}

    # GitHub issue/PR references: #123, owner/repo#123
    issue_refs = re.findall(r"(?:([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+))?#(\d+)", text)
    for owner, repo, num in issue_refs:
        ref = f"{owner}/{repo}#{num}" if owner else f"#{num}"
        refs["issues"].append(ref)

    # GitHub full URLs: https://github.com/owner/repo/issues/123
    gh_urls = re.findall(
        r"https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)/(issues|pull)/(\d+)",
        text,
    )
    for owner, repo, kind, num in gh_urls:
        if kind == "issues":
            refs["issues"].append(f"{owner}/{repo}#{num}")
        elif kind == "pull":
            refs["prs"].append(f"{owner}/{repo}#{num}")

    # GitHub Actions run URLs: https://github.com/owner/repo/actions/runs/123456
    # (also matches deep links like .../runs/123456/job/789)
    ci_urls = re.findall(
        r"https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)/actions/runs/(\d+)",
        text,
    )
    for owner, repo, run_id in ci_urls:
        refs["ci_runs"].append(f"{owner}/{repo}#{run_id}")

    # Generic URLs
    urls = re.findall(r"https?://[^\s\)>\]\"']+", text)
    refs["urls"] = [u.rstrip(".,;:") for u in urls if u.startswith("http")]

    return refs


async def _pre_hydrate(task_description: str, project_dir: Path | None = None) -> str:
    """Fetch linked resources before agent starts (Stripe Blueprint pre-hydration).

    Deterministically fetches GitHub issues/PRs referenced in the task description.
    Saves tokens + latency by giving the agent content it would otherwise fetch.

    Returns a markdown block with fetched content, or empty string if nothing found.
    """
    refs = _parse_linked_references(task_description)
    blocks: list[str] = []
    fetched: set[str] = set()

    # Fetch GitHub issues
    for ref in refs["issues"]:
        if ref in fetched:
            continue
        try:
            if "#" in ref:
                parts = ref.split("#")
                if len(parts) == 2 and "/" in parts[0]:
                    owner_repo, num = parts
                else:
                    num = parts[1]
                    owner_repo = None
                    if project_dir:
                        try:
                            proc = await asyncio.create_subprocess_exec(
                                "gh", "repo", "view", "--json", "nameWithOwner",
                                "-q", ".nameWithOwner",
                                cwd=str(project_dir),
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                            )
                            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                            if proc.returncode == 0:
                                owner_repo = json.loads(stdout.decode()).get("nameWithOwner")
                        except Exception:
                            pass
                    if not owner_repo:
                        continue
                proc = await asyncio.create_subprocess_exec(
                    "gh", "issue", "view", num,
                    "--json", "title,body,state,labels",
                    cwd=str(project_dir) if project_dir else None,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                if proc.returncode == 0:
                    data = json.loads(stdout.decode())
                    labels = [lb["name"] for lb in data.get("labels", [])]
                    label_str = f" [{', '.join(labels)}]" if labels else ""
                    body = data.get("body") or "(no body)"
                    ac = _extract_acceptance_criteria(body)
                    ac_block = (
                        f"\n**✅ Acceptance Criteria (from issue — oracle will check these):**\n{ac}\n"
                        if ac else ""
                    )
                    blocks.append(
                        f"## Pre-hydrated Issue {owner_repo}#{num}{label_str}\n"
                        f"**State**: {data['state']}\n"
                        f"**Title**: {data['title']}\n"
                        f"{ac_block}\n"
                        f"{body[:2000]}"
                    )
                    fetched.add(ref)
        except Exception:
            pass

    # Fetch GitHub PRs
    for ref in refs["prs"]:
        if ref in fetched:
            continue
        try:
            parts = ref.split("#")
            if len(parts) == 2:
                owner_repo, num = parts
                proc = await asyncio.create_subprocess_exec(
                    "gh", "pr", "view", num,
                    "--json", "title,body,state,additions,deletions",
                    cwd=str(project_dir) if project_dir else None,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                if proc.returncode == 0:
                    data = json.loads(stdout.decode())
                    blocks.append(
                        f"## Pre-hydrated PR {owner_repo}#{num}\n"
                        f"**State**: {data['state']}\n"
                        f"**Title**: {data['title']}\n"
                        f"**Changes**: +{data.get('additions', 0)} -{data.get('deletions', 0)}\n\n"
                        f"{data.get('body', '(no body)')[:2000]}"
                    )
                    fetched.add(ref)
        except Exception:
            pass

    # Fetch failed-step log tails for CI run URLs — the agent needs the error
    # text, not a link it cannot click. Fail-open: a fetch error skips the ref.
    for ref in refs.get("ci_runs", []):
        if ref in fetched:
            continue
        try:
            owner_repo, run_id = ref.split("#", 1)
            proc = await asyncio.create_subprocess_exec(
                "gh", "run", "view", run_id, "--log-failed", "-R", owner_repo,
                cwd=str(project_dir) if project_dir else None,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode == 0 and stdout:
                tail = "\n".join(
                    stdout.decode(errors="replace").splitlines()[-60:]
                )
                blocks.append(
                    f"## Pre-hydrated CI run {owner_repo} run {run_id} "
                    f"(failed-step log tail)\n```\n{tail}\n```"
                )
                fetched.add(ref)
        except Exception:
            pass

    if not blocks:
        return ""

    return (
        "\n\n---\n\n# Pre-hydrated Resources (fetched before agent start)\n\n"
        + "\n\n---\n\n".join(blocks)
    )
