"""
Progress entries, PR review, and oracle review utilities.
Leaf module — no internal project imports.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import uuid
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── Progress / PR Review / Oracle ────────────────────────────────────────────


async def _summarize_worker_completion(
    task_description: str, log_path: Path | None, project_dir: Path
) -> str:
    """Generate a 1-sentence completion summary for a worker (multi-agent context archival).

    Called after verify_and_commit() succeeds. Returns compact summary that subsequent
    workers can use as context — prevents context rot in long orchestrations.
    Falls back to first line of task description on any error.
    """
    title = task_description.splitlines()[0][:100] if task_description else "Unknown task"
    log_tail = ""
    if log_path and log_path.exists():
        try:
            text = log_path.read_text(errors="replace")
            log_tail = "\n".join(text.splitlines()[-30:])
        except Exception:
            pass

    fallback = f"Completed: {title[:80]}"
    if not log_tail:
        return fallback

    prompt = (
        f"Task: {title}\n\n"
        f"Worker log (last 30 lines):\n{log_tail[:2000]}\n\n"
        "In ONE sentence (max 120 chars), describe what was accomplished. "
        "Start with an action verb. Example: 'Added OAuth2 flow to auth.py, "
        "all 12 tests pass.' RESPOND WITH ONLY the sentence."
    )
    try:
        proc = await asyncio.create_subprocess_shell(
            f'claude -p {shlex.quote(prompt)} --model claude-haiku-4-5-20251001 --no-input-prompt',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return fallback
        summary = out.decode().strip()
        # Reject multi-line or empty responses
        summary = summary.splitlines()[0].strip() if summary else ""
        return summary[:150] if summary else fallback
    except Exception:
        return fallback


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
    """Independent second-model review of a diff (Self-RAG multi-dimensional critique).

    Returns (approved, reason) where reason contains structured fix guidance on rejection.
    Asks haiku to return JSON with per-dimension scores so the worker gets targeted feedback.
    Falls open on any error.
    """
    prompt = (
        "You are an independent code reviewer. Review the diff against the task description.\n"
        "Respond with ONLY a JSON object — no preamble, no markdown. Format:\n"
        '{"decision":"APPROVED","dimensions":{"correctness":"pass","completeness":"pass",'
        '"code_quality":"pass"},"fix_guidance":""}\n'
        "OR for rejection:\n"
        '{"decision":"REJECTED","dimensions":{"correctness":"fail — <why>",'
        '"completeness":"warn — <what missing>","code_quality":"pass"},'
        '"fix_guidance":"<one specific actionable fix>"}\n\n'
        "Dimension values: 'pass', 'fail — <reason>', or 'warn — <reason>'.\n"
        "fix_guidance: empty string if APPROVED, else ONE concrete fix instruction.\n\n"
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
            await proc.communicate()
            out = b""
        raw = out.decode().strip()

        # Try to parse structured JSON response (Self-RAG pattern)
        try:
            data = json.loads(raw)
            approved = data.get("decision", "").upper() == "APPROVED"
            fix_guidance = data.get("fix_guidance", "")
            dims = data.get("dimensions", {})
            if not approved and fix_guidance:
                reason = fix_guidance[:200]
            elif not approved:
                # Format dimension failures as compact reason
                fails = [f"{k}: {v}" for k, v in dims.items() if not str(v).startswith("pass")]
                reason = "; ".join(fails)[:200] if fails else "oracle rejected"
            else:
                reason = "approved"
            return approved, reason
        except (json.JSONDecodeError, AttributeError):
            pass

        # Fallback: legacy APPROVED/REJECTED text format
        approved = raw.startswith("APPROVED")
        reason = raw.split(":", 1)[-1].strip()[:80] if ":" in raw else raw[:80]
        return approved, reason
    except Exception as e:
        logger.warning("oracle review error: %s", e)
        return True, "oracle error (fail-open)"
    finally:
        prompt_file.unlink(missing_ok=True)
