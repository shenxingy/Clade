"""
Progress entries, PR review, and oracle review utilities.
Leaf module — no internal project imports.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
import uuid
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── Progress / PR Review / Oracle ────────────────────────────────────────────


async def _write_progress_entry(
    task_description: str, log_path: Path | None, project_dir: Path
) -> None:
    """After merge: summarize worker log and append a lesson entry to PROGRESS.md."""
    title = task_description.splitlines()[0][:80] if task_description else "Unknown task"
    log_tail = ""
    if log_path and log_path.exists():
        try:
            text = log_path.read_text(errors="replace")
            log_tail = "\n".join(text.splitlines()[-80:])
        except Exception:
            pass

    prompt = (
        f"A Claude Code worker completed this task:\n**{title}**\n\n"
        f"Last 80 lines of worker log:\n```\n{log_tail}\n```\n\n"
        "Write a concise PROGRESS.md entry (2-4 bullet points) in this exact format:\n"
        f"### [{date.today().isoformat()}] Task: {title}\n"
        "- What worked: [1 sentence]\n"
        "- Watch out for: [1 sentence]\n\n"
        "RESPOND WITH ONLY the markdown entry, no preamble."
    )
    try:
        proc = await asyncio.create_subprocess_shell(
            f'claude -p {shlex.quote(prompt)} --model claude-haiku-4-5-20251001',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()  # drain stdout/stderr
            out = b""
        entry = out.decode().strip()
        if entry:
            progress_file = project_dir / "PROGRESS.md"
            existing = await asyncio.to_thread(progress_file.read_text, errors="replace") if progress_file.exists() else "# Progress Log\n"
            lines = existing.splitlines(keepends=True)
            insert_at = 1 if lines and lines[0].startswith("#") else 0
            lines.insert(insert_at, f"\n{entry}\n")
            await asyncio.to_thread(progress_file.write_text, "".join(lines))
    except Exception:
        pass  # non-critical — don't break the merge flow


async def _write_pr_review(pr_url: str, task_description: str, project_dir: Path) -> None:
    """After PR creation: generate AI review and post as PR comment."""
    title = task_description.splitlines()[0][:80] if task_description else "Unknown task"
    try:
        diff_proc = await asyncio.create_subprocess_shell(
            f'gh pr diff {shlex.quote(pr_url)}',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(project_dir),
        )
        try:
            diff_out, _ = await asyncio.wait_for(diff_proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            diff_proc.kill()
            await diff_proc.communicate()  # drain stdout/stderr
            diff_out = b""
        diff_text = diff_out.decode()[:4000]

        prompt = (
            f"Review this PR for the task: **{title}**\n\n"
            f"Diff:\n```diff\n{diff_text}\n```\n\n"
            "Write a brief code review (3-5 bullet points):\n"
            "- **Summary**: what changed\n"
            "- **Correctness**: does it solve the task?\n"
            "- **Risks**: any concerns or edge cases?\n"
            "RESPOND WITH ONLY the review markdown, no preamble."
        )
        review_proc = await asyncio.create_subprocess_shell(
            f'claude -p {shlex.quote(prompt)} --model claude-haiku-4-5-20251001',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            review_out, _ = await asyncio.wait_for(review_proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            review_proc.kill()
            await review_proc.communicate()  # drain stdout/stderr
            review_out = b""
        review_text = review_out.decode().strip()

        if review_text:
            comment_proc = await asyncio.create_subprocess_shell(
                f'gh pr comment {shlex.quote(pr_url)} --body {shlex.quote(review_text)}',
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(project_dir),
            )
            try:
                await asyncio.wait_for(comment_proc.communicate(), timeout=30)
            except asyncio.TimeoutError:
                comment_proc.kill()
                await comment_proc.communicate()  # drain stdout/stderr
    except Exception:
        pass  # non-critical


async def _oracle_review(task_description: str, diff_text: str, claude_dir: Path) -> tuple[bool, str]:
    """Independent second-model review of a diff. Returns (approved, reason). Fails open."""
    prompt = (
        "You are an independent code reviewer with no prior context.\n"
        "Review the diff and task description. Output ONLY one of:\n"
        "  APPROVED: <one-line reason>\n"
        "  REJECTED: <one-line reason>\n\n"
        f"Task: {task_description[:400]}\n\nDiff:\n{diff_text[:3000]}"
    )
    prompt_file = claude_dir / f"oracle-{uuid.uuid4().hex[:8]}.md"
    try:
        prompt_file.write_text(prompt)
        proc = await asyncio.create_subprocess_shell(
            f'claude -p "$(cat {shlex.quote(str(prompt_file))})" '
            f'--model claude-haiku-4-5-20251001 --dangerously-skip-permissions',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()  # drain stdout/stderr
            out = b""
        result = out.decode().strip()
        approved = result.startswith("APPROVED")
        reason = result.split(":", 1)[-1].strip()[:80] if ":" in result else result[:80]
        return approved, reason
    except Exception as e:
        logger.warning("oracle review error: %s", e)
        return True, "oracle error (fail-open)"
    finally:
        prompt_file.unlink(missing_ok=True)
