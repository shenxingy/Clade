"""Coverage gap scanner — finds modules below coverage threshold and creates tasks."""

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def check_coverage_gaps(
    task_queue: Any, project_dir: str, threshold: float = 80.0
) -> list[str]:
    """
    Scan code coverage and create tasks for modules below threshold.

    Args:
        task_queue: TaskQueue instance to add tasks to
        project_dir: Path to project directory
        threshold: Minimum coverage percentage (default 80.0)

    Returns:
        List of created task IDs
    """
    created_ids: list[str] = []

    try:
        project_path = Path(project_dir)
        coverage_file = project_path / "coverage.json"

        # Generate coverage.json from .coverage if missing
        if not coverage_file.exists():
            coverage_data_file = project_path / ".coverage"
            if not coverage_data_file.exists():
                logger.warning("No .coverage file found, skipping coverage scan")
                return created_ids

            try:
                subprocess.run(
                    ["python", "-m", "coverage", "json"],
                    cwd=project_dir,
                    capture_output=True,
                    timeout=30,
                )
            except Exception as e:
                logger.warning("Failed to generate coverage.json: %s", e)
                return created_ids

        # Read coverage data
        if not coverage_file.exists():
            logger.warning("coverage.json not found after generation attempt")
            return created_ids

        try:
            data = json.loads(coverage_file.read_text())
        except Exception as e:
            logger.warning("Failed to parse coverage.json: %s", e)
            return created_ids

        # Get existing tasks to deduplicate
        existing_tasks = await task_queue.list()
        existing_refs = {t.get("source_ref") for t in existing_tasks if t.get("source_ref")}

        # Find files below threshold
        files_data = data.get("files", {})
        gaps: list[tuple[str, float]] = []

        for filepath, file_info in files_data.items():
            if not isinstance(file_info, dict):
                continue

            summary = file_info.get("summary", {})
            if not summary:
                continue

            covered = summary.get("num_statements", 0)
            missing = summary.get("missing_lines", 0)
            total = covered + missing

            if total == 0:
                continue

            coverage_pct = (covered / total) * 100
            if coverage_pct < threshold:
                gaps.append((filepath, coverage_pct))

        # Sort by coverage percentage (lowest first)
        gaps.sort(key=lambda x: x[1])

        # Create tasks for gaps
        for filepath, coverage_pct in gaps:
            source_ref = f"coverage_{filepath.replace('/', '_')}"

            # Skip if already processed
            if source_ref in existing_refs:
                continue

            description = f"Improve test coverage for {filepath} (currently {coverage_pct:.1f}%, target {threshold}%)"

            try:
                task = await task_queue.add(description=description, source_ref=source_ref)
                created_ids.append(task["id"])
                logger.info("Created task %s for coverage gap in %s", task["id"], filepath)
            except Exception as e:
                logger.warning("Failed to create task for coverage gap in %s: %s", filepath, e)

    except Exception as e:
        logger.warning("Error checking coverage gaps: %s", e)

    return created_ids
