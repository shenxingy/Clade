"""
Progress entries, PR review, and oracle review utilities.
Leaf module — no internal project imports.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
import uuid
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Model for review/oracle/progress claude calls. This is a documented leaf
# (no project imports — config included), so worker.py overwrites this at
# import time with config.HAIKU_MODEL (the pinned dated snapshot). The alias
# fallback keeps standalone imports (tests, REPL) working via the claude CLI.
HAIKU_MODEL = "haiku"

# Pure-judge containment: every claude -p call in this module has its stdout
# parsed, so user settings must not load — a prompt-type Stop hook's
# {"ok":true} decision replaces the real -p reply (see _oracle_pass, commit
# 386a862). Default mirrors config.SETTING_SOURCES_NONE; worker.py re-asserts
# it at import time (leaf module — cannot import config).
SETTING_SOURCES_NONE = '--setting-sources ""'

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
            f'claude -p {shlex.quote(prompt)} --model {HAIKU_MODEL} --no-input-prompt {SETTING_SOURCES_NONE}',
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
            f'claude -p {shlex.quote(prompt)} --model {HAIKU_MODEL} {SETTING_SOURCES_NONE}',
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
            f'claude -p {shlex.quote(prompt)} --model {HAIKU_MODEL} {SETTING_SOURCES_NONE}',
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


_ORACLE_CHUNK_SIZE = 2500  # chars per diff chunk (Qodo §Gap3: chunked review for large diffs)
_ORACLE_PROMPT_TEMPLATE = (
    "You are an independent code reviewer. Review the diff against the task description.\n"
    "Respond with ONLY a JSON object — no preamble, no markdown. Format:\n"
    '{{"decision":"APPROVED","confidence":"high",'
    '"dimensions":{{"correctness":"pass","completeness":"pass","code_quality":"pass"}},'
    '"findings":[],"fix_guidance":""}}\n'
    "OR for rejection:\n"
    '{{"decision":"REJECTED","confidence":"high|medium|low",'
    '"dimensions":{{"correctness":"fail — <why>","completeness":"warn — <what missing>",'
    '"code_quality":"pass"}},'
    '"findings":['
    '{{"dimension":"correctness","severity":"error","fix_suggestion":"<specific fix 1>"}},'
    '{{"dimension":"code_quality","severity":"warning","fix_suggestion":"<specific fix 2>"}}'
    '],'
    '"fix_guidance":"<overall summary of changes needed>"}}\n\n'
    "Dimension values: 'pass', 'fail — <reason>', or 'warn — <reason>'.\n"
    "confidence: 'high' (clear violation), 'medium' (likely issue), 'low' (style preference).\n"
    "findings: ordered list of issues, most critical first. severity: 'error'|'warning'|'info'.\n"
    "decision MUST be 'APPROVED' unless at least one finding has severity 'error'. "
    "warning/info findings NEVER justify rejection — include them as findings with "
    "decision 'APPROVED'; they are logged as follow-ups, not discarded.\n"
    "Each finding's fix_suggestion must cite concrete file:line evidence from the diff.\n"
    "Do NOT reject for: style preferences, pre-existing issues this diff does not touch, "
    "or issues outside the task scope.\n"
    "fix_guidance: empty string if APPROVED, else summary of all needed changes.\n\n"
    "Task: {task}\n\nDiff:\n{diff}"
)


_ORACLE_SPEC_PROMPT = (
    "You are a spec compliance checker. Does this diff correctly implement the required task?\n"
    "Focus ONLY on correctness (does it do what was asked?) and completeness (all requirements met?).\n"
    "For EACH acceptance criterion (when listed): verdict 'satisfied' is allowed ONLY with concrete\n"
    "evidence from the diff (cite file:line or the relevant hunk); otherwise add a specific\n"
    "violation to issues.\n"
    "Do NOT fail for: style preferences, pre-existing issues this diff does not touch,\n"
    "hypothetical edge cases outside the task scope, or missing tests for unrelated code.\n"
    "Respond with ONLY a JSON object — no preamble, no markdown:\n"
    '{{"pass":true,"confidence":"high","issues":[],'
    '"criteria":[{{"criterion":"<text>","verdict":"satisfied","evidence":"<file:line>"}}]}}\n'
    "OR:\n"
    '{{"pass":false,"confidence":"high|medium|low","issues":["<specific spec violation>"],'
    '"criteria":[{{"criterion":"<text>","verdict":"violated","evidence":"<what is missing>"}}]}}\n\n'
    "Task: {task}\n\nDiff:\n{diff}"
)

_ORACLE_QUALITY_PROMPT = (
    "You are a code quality reviewer. Does this diff introduce bugs, security issues, or serious defects?\n"
    "Focus ONLY on implementation quality — not spec compliance.\n"
    "Every reported issue must cite concrete evidence from the diff (file:line or hunk).\n"
    "Do NOT fail for: style preferences, pre-existing issues this diff does not touch,\n"
    "or hypothetical edge cases with no evidence in the diff.\n"
    "Respond with ONLY a JSON object — no preamble, no markdown:\n"
    '{{"pass":true,"confidence":"high","issues":[]}}\n'
    "OR:\n"
    '{{"pass":false,"confidence":"high|medium|low","issues":["<specific quality issue>"]}}\n\n'
    "{evidence}"
    "Diff:\n{diff}"
)


_ORACLE_TASK_DESC_CAP = 4000  # full task context for the grader (was 400 — criteria never reached the oracle)

# Haiku routinely wraps its JSON verdict in a markdown fence despite the
# "no markdown" instruction. Strict json.loads(raw) then misread every
# healthy review as an infra error — the 2026-06-12 live eval run
# (orchestrator/evals/) scored 17/17 live cases 'unreviewed' because of this:
# the oracle was effectively dead in production, fail-open on every commit.
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)


def _strip_json_fence(raw: str) -> str:
    """Unwrap a full-string markdown code fence around a JSON reply.

    Only a fence spanning the whole (stripped) reply is unwrapped; anything
    else returns unchanged, so legacy plain-text verdicts ("APPROVED: ...")
    and true garbage keep their existing handling.
    """
    m = _JSON_FENCE_RE.match(raw.strip())
    return m.group(1).strip() if m else raw


# Judge framing (live eval 2026-06-12, second finding): without this, the CC
# coding-agent system prompt makes the grader treat "Task: ... Diff: ..." as a
# work order — it hunts for the files, tries to apply fixes, and replies with
# prose ("I don't see tool/cli.py...") instead of the JSON verdict. Combined
# with NOT passing --dangerously-skip-permissions (mutating tools are auto-
# denied in non-interactive -p mode), the grader becomes a pure judge.
_ORACLE_JUDGE_SYSTEM_PROMPT = (
    "You are a non-interactive code-review oracle. You have NO repository or "
    "filesystem access: judge ONLY from the task description and diff text "
    "given in the prompt. Never use tools, never try to fix the code, never "
    "ask questions. Respond with ONLY the requested JSON object."
)

# Fix-intent detection (controversial + felixrieseberg): bug-fix tasks get an
# extra completeness criterion — a fix with no test covering the failing input
# is incomplete history (the regression can silently return).
_FIX_INTENT_RE = re.compile(r"(?:^|\n)\s*fix:|\b(?:bug|bugfix|regression|hotfix)\b", re.IGNORECASE)

_FIX_INTENT_CRITERION = (
    "Additional completeness criterion (bug-fix task): the diff must include a NEW or "
    "UPDATED test covering the previously-failing input. "
    "Test infrastructure present in this project: {infra}. "
    "If no covering test is in the diff: when test infrastructure is present, mark "
    "completeness as violated (add a specific issue); when it is unknown, report it as "
    "a warning-level issue instead of failing the review."
)


def _detect_fix_intent(task_description: str) -> bool:
    """True when the task is a bug fix (fix:/bug/regression/hotfix in the description)."""
    return bool(_FIX_INTENT_RE.search(task_description or ""))


def _build_oracle_task_block(
    task_description: str,
    acceptance_criteria: list[str] | None,
    test_evidence: str = "",
) -> str:
    """Build the task block injected into oracle prompts.

    claude-cookbooks rubric: the grader must see the FULL task description and
    the parsed acceptance criteria — the old 400-char truncation silently
    dropped both, reducing 'spec compliance' to a title check.
    test_evidence (mic92): pre-push test results so verdicts rest on evidence.
    """
    block = task_description[:_ORACLE_TASK_DESC_CAP]
    if acceptance_criteria:
        lines = ["", "", "Acceptance criteria (give a verdict for EACH):"]
        for i, criterion in enumerate(acceptance_criteria[:10], 1):
            lines.append(f"{i}. {str(criterion)[:200]}")
        block += "\n".join(lines)
    if _detect_fix_intent(task_description):
        # Bug-fix tasks: require a covering test (test infra known via evidence)
        block += "\n\n" + _FIX_INTENT_CRITERION.format(
            infra="yes" if test_evidence else "unknown"
        )
    if test_evidence:
        block += f"\n\nTest results (run before this review):\n{test_evidence[:800]}"
    return block


def _build_test_evidence(tests_passed: bool, test_output: str, reg_warning: str) -> str:
    """Compact evidence block from the pre-push test run for oracle prompts.

    Returns "" when nothing ran (no test command configured) — the prompts
    then carry no test section rather than implying a green suite.
    """
    if not test_output and not reg_warning:
        return ""
    parts = [f"Project tests {'PASSED' if tests_passed else 'FAILED'}."]
    if test_output:
        parts.append(test_output[-600:])
    if reg_warning:
        parts.append(reg_warning[:200])
    return "\n".join(parts)


async def _oracle_pass(
    prompt: str, claude_dir: Path
) -> tuple[bool, str, str, bool]:
    """Run a single oracle pass. Returns (passed, confidence, issues_text, infra_error).

    infra_error=True means NO review happened (timeout, subprocess failure,
    unparseable output). Callers must surface that as 'unreviewed' — a fail-open
    approval is not a review (lovesegfault: oracle liveness).
    """
    prompt_file = claude_dir / f"oracle-{uuid.uuid4().hex[:8]}.md"
    try:
        prompt_file.write_text(prompt)
        # Grader containment: the oracle is a pure judge — everything it needs
        # is in the prompt. Live eval 2026-06-12 findings, each flag earned:
        # - NO --dangerously-skip-permissions: skip-permissions graders
        #   implemented a fixture's stub function in the repo, invented
        #   hooks/tests, committed, and pushed (mutating tools stay denied).
        # - --setting-sources "": user-level hooks hijack -p output — a
        #   prompt-type Stop hook's {"ok":...} decision got printed as the
        #   reply, and user CLAUDE.md ground rules made the grader act as an
        #   autonomous worker instead of a judge.
        # - judge system prompt appended; cwd pinned to the .claude scratch
        #   dir; stdin closed (CC otherwise waits 3s for piped input).
        proc = await asyncio.create_subprocess_shell(
            f'claude -p "$(cat {shlex.quote(str(prompt_file))})" '
            f'--model {HAIKU_MODEL} {SETTING_SOURCES_NONE} '
            f'--append-system-prompt {shlex.quote(_ORACLE_JUDGE_SYSTEM_PROMPT)}',
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(claude_dir),
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=45)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return True, "none", "oracle timeout (45s)", True
        raw = out.decode().strip()
        try:
            data = json.loads(_strip_json_fence(raw))
            passed = bool(data.get("pass", True))
            confidence = str(data.get("confidence", "medium"))
            issues = data.get("issues", [])
            issues_text = "; ".join(str(i)[:100] for i in issues[:3]) if issues else ""
            return passed, confidence, issues_text, False
        except (json.JSONDecodeError, AttributeError):
            return True, "none", "oracle returned unparseable output", True
    except Exception:
        return True, "none", "oracle subprocess error", True
    finally:
        prompt_file.unlink(missing_ok=True)


def _format_oracle_rejection(
    confidence: str,
    fix_guidance: str,
    dims: dict,
    findings: list,
) -> str:
    """Format oracle rejection into ordered fix list (Qodo §Gap2).

    Produces a numbered list of findings for worker to apply in order.
    Falls back to fix_guidance string if no findings.
    """
    lines: list[str] = [f"[{confidence}] Oracle rejected."]
    if findings:
        lines.append("Fix in order:")
        for i, f in enumerate(findings[:5], 1):
            sev = f.get("severity", "error")
            dim = f.get("dimension", "?")
            fix = f.get("fix_suggestion", "")[:120]
            if fix:
                lines.append(f"  {i}. [{sev}/{dim}] {fix}")
        if fix_guidance:
            lines.append(f"Summary: {fix_guidance[:120]}")
    elif fix_guidance:
        lines.append(fix_guidance[:200])
    else:
        fails = [f"{k}: {v}" for k, v in dims.items() if not str(v).startswith("pass")]
        if fails:
            lines.append("; ".join(fails)[:200])
    return "\n".join(lines)[:400]


def _append_followup_findings(claude_dir: Path, findings: list, source_label: str) -> None:
    """Persist non-blocking (warning/info) oracle findings as follow-ups.

    domdomegg: optional findings become follow-ups in .claude/skipped.md —
    neither lost (discarded on approval) nor fatal (a style-preference REJECTED
    on a single chunk nuking a whole commit). Fail-open: never break review.
    """
    try:
        non_blocking = [
            f for f in findings
            if isinstance(f, dict) and f.get("severity") in ("warning", "info")
            and str(f.get("fix_suggestion", "")).strip()
        ]
        if not non_blocking:
            return
        path = claude_dir / "skipped.md"
        lines: list[str] = []
        if not path.exists():
            lines.append("# Skipped / Follow-up Findings\n")
        stamp = date.today().isoformat()
        for f in non_blocking[:5]:
            sev = f.get("severity", "info")
            dim = f.get("dimension", "?")
            fix = str(f.get("fix_suggestion", ""))[:200]
            lines.append(f"- [AI][{stamp}] oracle follow-up ({source_label}): [{sev}/{dim}] {fix}")
        with open(path, "a") as fh:
            fh.write("\n".join(lines) + "\n")
    except Exception:
        pass


async def _oracle_review_chunk(
    task_description: str, diff_chunk: str, chunk_label: str, claude_dir: Path
) -> tuple[bool, str, bool]:
    """Review a single diff chunk. Returns (approved, reason, infra_error).

    infra_error=True means the chunk was NOT reviewed (timeout, subprocess
    failure, unparseable output) — never report that as an approval.
    """
    # Caller passes a pre-built task block (description + criteria); cap defensively.
    prompt = _ORACLE_PROMPT_TEMPLATE.format(
        task=task_description[:_ORACLE_TASK_DESC_CAP + 2500], diff=diff_chunk
    )
    if chunk_label:
        prompt = f"[Reviewing chunk: {chunk_label}]\n\n" + prompt
    prompt_file = claude_dir / f"oracle-{uuid.uuid4().hex[:8]}.md"
    try:
        prompt_file.write_text(prompt)
        # Grader containment — see _oracle_pass: pure judge (no skip-
        # permissions, no user settings/hooks, judge system prompt, scratch
        # cwd, closed stdin).
        proc = await asyncio.create_subprocess_shell(
            f'claude -p "$(cat {shlex.quote(str(prompt_file))})" '
            f'--model {HAIKU_MODEL} {SETTING_SOURCES_NONE} '
            f'--append-system-prompt {shlex.quote(_ORACLE_JUDGE_SYSTEM_PROMPT)}',
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(claude_dir),
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return True, "oracle timeout (60s)", True
        raw = out.decode().strip()
        try:
            data = json.loads(_strip_json_fence(raw))
            approved = data.get("decision", "").upper() == "APPROVED"
            fix_guidance = data.get("fix_guidance", "")
            dims = data.get("dimensions", {})
            confidence = data.get("confidence", "medium")
            findings = data.get("findings", [])
            if not isinstance(findings, list):
                findings = []
            # Severity gate (domdomegg, mirrors the two-pass confidence gate):
            # REJECTED requires >=1 severity:error finding. A rejection backed
            # only by warning/info findings is demoted to approval and the
            # findings are logged as follow-ups. Findings-less rejections keep
            # their decision (legacy fix_guidance/dimensions-only responses).
            has_error = any(
                isinstance(f, dict) and f.get("severity") == "error" for f in findings
            )
            label = f"chunk {chunk_label}" if chunk_label else "chunk 1/1"
            if not approved and findings and not has_error:
                _append_followup_findings(claude_dir, findings, label)
                return True, "approved (non-blocking findings logged as follow-ups)", False
            if not approved:
                reason = _format_oracle_rejection(confidence, fix_guidance, dims, findings)
            else:
                reason = "approved"
                _append_followup_findings(claude_dir, findings, label)
            return approved, reason, False
        except (json.JSONDecodeError, AttributeError):
            pass
        # Legacy plain-text verdicts ("APPROVED: ..." / "REJECTED: ...")
        if raw.startswith(("APPROVED", "REJECTED")):
            reason = raw.split(":", 1)[-1].strip()[:80] if ":" in raw else raw[:80]
            return raw.startswith("APPROVED"), reason, False
        # Anything else (empty output, API error text) is not a review
        return True, "oracle returned unparseable output", True
    except Exception as e:
        logger.warning("oracle chunk review error: %s", e)
        return True, "oracle subprocess error", True
    finally:
        prompt_file.unlink(missing_ok=True)


async def _oracle_review(
    task_description: str,
    diff_text: str,
    claude_dir: Path,
    acceptance_criteria: list[str] | None = None,
    test_evidence: str = "",
) -> tuple[bool, str, bool]:
    """Independent second-model review of a diff (Self-RAG multi-dimensional critique).

    For large diffs (> ORACLE_CHUNK_SIZE chars), reviews in chunks and merges findings.
    Qodo §Gap3: chunked review prevents large refactors from being auto-approved.
    acceptance_criteria (claude-cookbooks rubric): parsed task-schema criteria the
    grader must verdict one-by-one; injected with the FULL task description.
    test_evidence (mic92): pre-push test results threaded into every prompt.
    Returns (approved, reason, infra_error) where reason contains structured fix
    guidance on rejection. infra_error=True means the diff was NOT (fully)
    reviewed — callers must tag the result 'unreviewed', never 'approved'
    (lovesegfault: fail-open must not masquerade as a review).
    """
    task_block = _build_oracle_task_block(task_description, acceptance_criteria, test_evidence)
    # Chunk large diffs (Qodo §Gap3)
    if len(diff_text) > _ORACLE_CHUNK_SIZE:
        chunks = [
            diff_text[i:i + _ORACLE_CHUNK_SIZE]
            for i in range(0, len(diff_text), _ORACLE_CHUNK_SIZE)
        ]
        # Review first 3 chunks max to avoid excessive API calls
        chunks = chunks[:3]
        results = await asyncio.gather(*[
            _oracle_review_chunk(task_block, chunk, f"{i+1}/{len(chunks)}", claude_dir)
            for i, chunk in enumerate(chunks)
        ])
        # Aggregate: any real rejection → overall rejection (review DID happen);
        # otherwise any infra error → unreviewed; else approved.
        rejections = [reason for approved, reason, infra in results if not approved and not infra]
        if rejections:
            return False, rejections[0], False
        infra_reasons = [reason for _, reason, infra in results if infra]
        if infra_reasons:
            reason = f"oracle infra error on {len(infra_reasons)}/{len(results)} chunks: {infra_reasons[0]}"
            return True, reason[:300], True
        return True, "approved (all chunks passed)", False

    # Short diff: two-pass review (Qodo §Gap1 — spec-check first, quality-check second)
    diff_excerpt = diff_text[:_ORACLE_CHUNK_SIZE]
    spec_prompt = _ORACLE_SPEC_PROMPT.format(
        task=task_block, diff=diff_excerpt
    )
    evidence_block = (
        f"Test results (run before this review):\n{test_evidence[:800]}\n\n"
        if test_evidence else ""
    )
    quality_prompt = _ORACLE_QUALITY_PROMPT.format(diff=diff_excerpt, evidence=evidence_block)

    # Pass 1: spec compliance check
    spec_passed, spec_conf, spec_issues, spec_infra = await _oracle_pass(spec_prompt, claude_dir)
    if spec_infra:
        return True, f"oracle infra error (spec pass): {spec_issues}"[:300], True
    if not spec_passed and spec_conf in ("high", "medium"):
        reason = f"[{spec_conf}/spec] " + (spec_issues or "spec compliance failed")
        return False, reason[:300], False

    # Pass 2: quality check (only runs if spec passed)
    quality_passed, quality_conf, quality_issues, quality_infra = await _oracle_pass(quality_prompt, claude_dir)
    if quality_infra:
        return True, f"oracle infra error (quality pass): {quality_issues}"[:300], True
    if not quality_passed and quality_conf in ("high", "medium"):
        reason = f"[{quality_conf}/quality] " + (quality_issues or "quality check failed")
        return False, reason[:300], False

    return True, "approved (spec+quality passed)", False


# ─── Oracle Liveness (lovesegfault) ──────────────────────────────────────────
# Infra failures must surface as 'unreviewed', never as approvals. A streak of
# consecutive infra errors means the oracle is effectively dead — escalate
# loudly (webhook + .claude/blockers.md) instead of rubber-stamping commits.

_ORACLE_INFRA_THRESHOLD = 3
_oracle_infra_streaks: dict[str, int] = {}  # str(claude_dir) → consecutive infra errors


def _record_oracle_infra_error(claude_dir: Path) -> int:
    """Increment and return the consecutive infra-error streak for this session."""
    key = str(claude_dir)
    _oracle_infra_streaks[key] = _oracle_infra_streaks.get(key, 0) + 1
    return _oracle_infra_streaks[key]


def _reset_oracle_infra_streak(claude_dir: Path) -> None:
    """A real review completed — clear the consecutive infra-error streak."""
    _oracle_infra_streaks.pop(str(claude_dir), None)


async def _escalate_oracle_outage(
    project_dir: Path, claude_dir: Path, webhook: str, streak: int
) -> None:
    """Oracle is dead — write a blocker entry + fire the notification webhook.

    blockers.md is watched by session.py:_check_blockers, so this also pauses
    the newest running worker. Fail-open: escalation must never break commits.
    """
    try:
        blockers = claude_dir / "blockers.md"
        entry = (
            f"\n## Blocker [{datetime.now().isoformat(timespec='seconds')}]\n"
            f"Oracle review infrastructure failing — {streak} consecutive infra errors. "
            f"Commits are being tagged 'unreviewed' (oracle dead — approvals are not reviews).\n"
            f"Tried: claude -p oracle subprocess (timeout/error/unparseable output each attempt). "
            f"Check Claude CLI availability and quota; the streak resets on the next successful review.\n"
        )
        existing = blockers.read_text(errors="replace") if blockers.exists() else ""
        blockers.write_text(existing + entry)
    except Exception:
        pass
    if not webhook:
        return
    try:
        payload = json.dumps({
            "event": "oracle_outage",
            "project_path": str(project_dir),
            "consecutive_infra_errors": streak,
        })
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "-X", "POST", "--max-time", "10",
            "-H", "Content-Type: application/json",
            "-d", payload, webhook,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=15)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
    except Exception:
        pass  # fail-open
