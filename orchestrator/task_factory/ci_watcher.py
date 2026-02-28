"""CI failure watcher — polls GitHub Actions for failed runs and creates tasks."""

import logging
import os
import re
import subprocess
from typing import Any

import httpx

logger = logging.getLogger(__name__)


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
            logger.warning(f"Failed to get git remote: {e}")
            return created_ids

        # Parse owner/repo from URL
        # Handles both HTTPS (https://github.com/owner/repo.git) and SSH (git@github.com:owner/repo.git)
        match = re.search(r'github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$', remote_url)
        if not match:
            logger.warning(f"Could not parse owner/repo from remote URL: {remote_url}")
            return created_ids

        owner, repo = match.groups()

        # Fetch failed runs from GitHub API
        url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs?status=failure&per_page=10"
        headers = {"Authorization": f"token {token}"}

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

            # Add task to queue
            try:
                task = await task_queue.add(description=description)
                # Store source_ref as metadata (if task_queue.add supports it, otherwise update separately)
                created_ids.append(task["id"])
                logger.info(f"Created task {task['id']} for CI failure {source_ref}")
            except Exception as e:
                logger.warning(f"Failed to create task for CI run {run['id']}: {e}")

    except Exception as e:
        logger.warning(f"Error checking CI failures: {e}")

    return created_ids
