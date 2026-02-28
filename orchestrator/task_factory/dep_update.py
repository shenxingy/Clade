"""Dependency updater — detects outdated packages and creates update tasks."""

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def check_outdated_deps(task_queue: Any, project_dir: str) -> list[str]:
    """
    Check for outdated Python and Node.js dependencies and create update tasks.

    Args:
        task_queue: TaskQueue instance to add tasks to
        project_dir: Path to project directory

    Returns:
        List of created task IDs
    """
    created_ids: list[str] = []

    try:
        project_path = Path(project_dir)

        # Get existing tasks to deduplicate
        existing_tasks = await task_queue.list()
        existing_refs = {t.get("source_ref") for t in existing_tasks if t.get("source_ref")}

        # Check Python dependencies
        python_deps = []
        has_python_deps = (project_path / "requirements.txt").exists() or (
            project_path / "pyproject.toml"
        ).exists()

        if has_python_deps:
            try:
                result = subprocess.run(
                    ["pip", "list", "--outdated", "--format=json"],
                    cwd=project_dir,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    deps = json.loads(result.stdout)
                    # Cap at 10 packages
                    python_deps = deps[:10]
            except Exception as e:
                logger.warning("Failed to check Python dependencies: %s", e)

        # Check Node.js dependencies
        node_deps = []
        if (project_path / "package.json").exists():
            try:
                result = subprocess.run(
                    ["npm", "outdated", "--json"],
                    cwd=project_dir,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 or result.returncode == 1:  # npm outdated returns 1 if outdated exist
                    try:
                        data = json.loads(result.stdout)
                        # data is a dict with package names as keys
                        node_deps = list(data.items())[:10]
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                logger.warning("Failed to check Node.js dependencies: %s", e)

        # Create tasks for Python dependencies
        for dep in python_deps:
            name = dep.get("name", "")
            latest = dep.get("latest", "")
            current = dep.get("version", "")

            if not name or not latest:
                continue

            source_ref = f"dep_{name}_{latest}"

            # Skip if already processed
            if source_ref in existing_refs:
                continue

            description = f"Update Python dependency: {name} from {current} to {latest}"

            try:
                task = await task_queue.add(description=description, source_ref=source_ref)
                created_ids.append(task["id"])
                logger.info("Created task %s for Python dependency %s", task["id"], name)
            except Exception as e:
                logger.warning("Failed to create task for Python dependency %s: %s", name, e)

        # Create tasks for Node.js dependencies
        for name, dep_info in node_deps:
            latest = dep_info.get("latest", "")
            current = dep_info.get("current", "")

            if not name or not latest:
                continue

            source_ref = f"dep_{name}_{latest}"

            # Skip if already processed
            if source_ref in existing_refs:
                continue

            description = f"Update Node.js dependency: {name} from {current} to {latest}"

            try:
                task = await task_queue.add(description=description, source_ref=source_ref)
                created_ids.append(task["id"])
                logger.info("Created task %s for Node.js dependency %s", task["id"], name)
            except Exception as e:
                logger.warning("Failed to create task for Node.js dependency %s: %s", name, e)

    except Exception as e:
        logger.warning("Error checking outdated dependencies: %s", e)

    return created_ids
