"""CI failure watcher — polls GitHub Actions for failed runs and creates tasks."""

import logging
import os
import re
import subprocess
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Appended to every CI-failure task: the two bad-fix guardrails. Workers under
# pressure reach for "CI is flaky" or "pin the dep" — both bury the regression.
_GUARDRAILS = (
    "Guardrails:\n"
    "- Do NOT conclude the failure is CI infrastructure — assume this repo's "
    "code or config is at fault until the log proves otherwise.\n"
    "- Do NOT fix by downgrading or pinning dependencies — fix the code that broke."
)


def _log_tail(text: str, lines: int = 40) -> str:
    """Last N lines of a log blob (empty input → empty string)."""
    if not text:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def _summarize_failed_jobs(jobs: list) -> tuple[str, int | None]:
    """Summarize failed jobs + failed step names from an /actions/runs/{id}/jobs payload.

    Returns (markdown summary, id of the first failed job — for log fetching).
    Pure function so tests can drive it with fixture JSON.
    """
    failed = [j for j in jobs if isinstance(j, dict) and j.get("conclusion") == "failure"]
    if not failed:
        return "", None
    lines = []
    for job in failed[:5]:
        steps = [
            s.get("name", "?")
            for s in (job.get("steps") or [])
            if isinstance(s, dict) and s.get("conclusion") == "failure"
        ]
        step_str = f" — failed step(s): {', '.join(steps)}" if steps else ""
        lines.append(f"- {job.get('name', 'unnamed job')}{step_str}")
    first_id = failed[0].get("id")
    return "Failed jobs:\n" + "\n".join(lines), first_id if isinstance(first_id, int) else None


async def _fetch_failure_details(
    client: Any, owner: str, repo: str, run_id: Any, headers: dict
) -> str:
    """Fetch failed job/step names + a log tail for a failed run.

    Fail-open by design: any fetch/parse error returns what we have so far —
    a missing log tail must never kill the task factory.
    """
    try:
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
            headers=headers,
        )
        resp.raise_for_status()
        summary, job_id = _summarize_failed_jobs(resp.json().get("jobs", []))
    except Exception as e:
        logger.warning("Failed to fetch jobs for run %s: %s", run_id, e)
        return ""

    if job_id is not None:
        try:
            # The job-logs endpoint redirects to a plaintext blob
            log_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/actions/jobs/{job_id}/logs",
                headers=headers,
                follow_redirects=True,
            )
            log_resp.raise_for_status()
            tail = _log_tail(log_resp.text, 40)
            if tail:
                summary += (
                    "\n\nLog tail (last 40 lines of first failed job):\n"
                    f"```\n{tail}\n```"
                )
        except Exception as e:
            logger.warning("Failed to fetch log tail for job %s: %s", job_id, e)

    return summary


async def check_ci_failures(task_queue: Any, project_dir: str) -> list[str]:
    """
    Poll GitHub Actions for failed runs and create tasks for each new failure.

    Args:
        task_queue: TaskQueue instance to add tasks to
        project_dir: Path to project directory (for git remote detection)

    Returns:
        List of created task IDs
    """
    created_ids: list[str] = []

    try:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            logger.warning("GITHUB_TOKEN not set, skipping CI failure check")
            return created_ids

        # Detect git remote
        try:
            remote_url = subprocess.check_output(
                ["git", "remote", "get-url", "origin"],
                cwd=project_dir,
                text=True,
            ).strip()
        except Exception as e:
            logger.warning("Failed to get git remote: %s", e)
            return created_ids

        # Parse owner/repo from URL
        # Handles both HTTPS (https://github.com/owner/repo.git) and SSH (git@github.com:owner/repo.git)
        match = re.search(r'github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$', remote_url)
        if not match:
            logger.warning("Could not parse owner/repo from remote URL: %s", remote_url)
            return created_ids

        owner, repo = match.groups()

        # Fetch failed runs from GitHub API
        url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs?status=failure&per_page=10"
        headers = {"Authorization": f"token {token}"}

        # Client stays open for the per-run detail fetches below
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            # Get existing tasks to deduplicate
            existing_tasks = await task_queue.list()
            existing_refs = {t.get("source_ref") for t in existing_tasks if t.get("source_ref")}

            # Process each failed run
            for run in data.get("workflow_runs", []):
                source_ref = f"ci_run_{run['id']}"

                # Skip if already processed
                if source_ref in existing_refs:
                    continue

                # Create task description
                run_name = run.get("name", "Unnamed workflow")
                run_url = run.get("html_url", "")
                branch = run.get("head_branch", "")
                conclusion = run.get("conclusion", "unknown")

                description = f"Fix CI failure: {run_name} on {branch}\nStatus: {conclusion}\nRun: {run_url}"

                # Failed step names + log tail — ship the evidence, not just
                # the URL. Fail-open: an empty string just means no details.
                details = await _fetch_failure_details(client, owner, repo, run["id"], headers)
                if details:
                    description += "\n\n" + details
                description += "\n\n" + _GUARDRAILS

                # Add task to queue
                try:
                    task = await task_queue.add(description=description, source_ref=source_ref)
                    created_ids.append(task["id"])
                    logger.info("Created task %s for CI failure %s", task["id"], source_ref)
                except Exception as e:
                    logger.warning("Failed to create task for CI run %s: %s", run["id"], e)

    except Exception as e:
        logger.warning("Error checking CI failures: %s", e)

    return created_ids
