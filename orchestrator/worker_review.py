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
from typing import Any

# Leaf-to-leaf import (worker_utils.py is itself a leaf, no project imports —
# same precedent as worker_tldr.py importing fault_localize.py). Settings-derived
# values still come in as explicit params from worker.py, never via GLOBAL_SETTINGS
# here, to keep this module's "no config.py" invariant intact.
from worker_utils import (
    oracle_reject_depth, oracle_retry_sample_count, ORACLE_REJECT_MARKER,
    _strip_error_context,
)

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
# Judges must not mutate files — denies Edit, Write, Bash. Leaf default mirrors
# config.DISALLOWED_TOOLS_JUDGE; worker.py re-asserts at import time.
DISALLOWED_TOOLS_JUDGE = "--disallowed-tools Edit,Write,Bash"

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
            f'claude -p {shlex.quote(prompt)} --model {HAIKU_MODEL} --no-input-prompt {SETTING_SOURCES_NONE} {DISALLOWED_TOOLS_JUDGE}',
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
    task_description: str, log_path: Path | None, project_dir: Path,
    estimated_cost: float | None = None,
) -> None:
    """After merge: summarize worker log and append a lesson entry to PROGRESS.md.

    estimated_cost (Simon Willison: cost-logged agent releases) is appended
    deterministically to the model-written entry rather than asked of the
    model itself — a dollar figure is exact data, not something to paraphrase.
    """
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
            f'claude -p {shlex.quote(prompt)} --model {HAIKU_MODEL} {SETTING_SOURCES_NONE} {DISALLOWED_TOOLS_JUDGE}',
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
            if estimated_cost:
                entry = entry.rstrip() + f"\n- Cost: ${estimated_cost:.4f}"
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
            f'claude -p {shlex.quote(prompt)} --model {HAIKU_MODEL} {SETTING_SOURCES_NONE} {DISALLOWED_TOOLS_JUDGE}',
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
        else:
            # Non-critical (no comment posted), but must not be SILENT — a bare
            # `pass` here left zero trace that a review was supposed to happen
            # and didn't (diff fetch timeout, review-gen timeout, or an empty
            # model reply all land here).
            logger.warning(
                "PR review skipped for %s — no review text generated "
                "(diff/review subprocess timeout or empty reply)", pr_url,
            )
    except Exception as e:
        logger.warning("PR review post failed for %s: %s", pr_url, e)


_ORACLE_CHUNK_SIZE = 2500  # chars per diff chunk (Qodo §Gap3: chunked review for large diffs)

# Risk-based dispatch (Takanori Sano: 6-agent diff-risk-routed review). Review
# depth today is SIZE-only (_ORACLE_CHUNK_SIZE) — a 1-line change to a
# security/data-sensitive path gets the same shallow single-shot review as a
# docstring typo. This is a cheap, no-LLM path/keyword classifier that forces
# extra resample votes on risky diffs regardless of size.
_RISK_PATH_RE = re.compile(
    r"(?:^|[/\\])(?:billing|payment\w*|auth\w*|security|secrets?|credentials?|"
    r"permissions?|migrations?|schema\w*|crypto\w*|password\w*|token\w*|acl|iam)"
    r"(?:[/\\]|\.\w+|$)",
    re.IGNORECASE | re.MULTILINE,
)
_RISK_KEYWORD_RE = re.compile(
    r"drop\s+table|delete\s+from\b|rm\s+-rf|\bsudo\b|eval\(|exec\(|"
    r"os\.system|shell\s*=\s*true|chmod\s+777|--force\b|--no-verify\b|"
    r"disable\w*\s+auth|skip\w*\s+permission",
    re.IGNORECASE,
)


def _classify_diff_risk(diff_text: str) -> bool:
    """True when the diff touches a security/data-sensitive surface (path or
    keyword match) and should get extra scrutiny regardless of its size."""
    if not diff_text:
        return False
    return bool(_RISK_PATH_RE.search(diff_text) or _RISK_KEYWORD_RE.search(diff_text))


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

# Constitutional AI for code (reflection-agents §Gap4): the generic quality pass
# checks for bugs/security, but never sees the project's own declared rules, so an
# agent can drift from them undetected. Inject the project's CLAUDE.md "Code Rules"
# as a binding constitution; violations surface as ordinary issues and ride the
# existing findings → fix → requeue path. Reused by both the two-pass (quality) and
# chunked oracle routes so coverage does not depend on diff size.
_ORACLE_CONSTITUTION_HEADER = (
    "PROJECT CODE RULES (constitution) — the diff MUST comply with these "
    "project-declared rules. Flag any hunk that violates one as an issue, citing "
    "file:line evidence. Do NOT flag pre-existing code the diff does not touch:\n"
    "{rules}\n\n"
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

# Verifier one step removed (lovesegfault REVIEW.md r25: 8/12 regressions were
# introduced BY fixes that were only verified against the original claim).
_FIX_ONE_STEP_CRITERION = (
    "Verify one step removed from the reported case — do not stop at the original "
    "claim. Walk a concrete example (not a yes/no) through each of: "
    "(a) the inverse input case of the fixed path, "
    "(b) the next state or lifecycle transition after the fixed path, "
    "(c) one sibling consumer of the changed code. "
    "If the diff predicts a failure mode it does not fix, report it as an issue, "
    "not a side note."
)

# Test-assertion-integrity check (Kent Beck: TDD discipline — a test that gets
# WEAKER to pass is not a fix). Repro-test generation/gating (worker_taskfile.py
# _generate_repro_test) is already superset-level solid, but nothing checked the
# opposite failure mode: a diff that reaches "tests pass" by weakening or
# deleting the failing assertion instead of fixing the underlying code.
_TEST_INTEGRITY_CRITERION = (
    "Additional integrity criterion: check whether the diff reaches a passing test "
    "suite by WEAKENING OR DELETING an existing test rather than fixing the "
    "underlying code. Red flags: removed assertions, loosened assertion values "
    "(exact equality relaxed to a range, a strict check replaced with a truthy check), "
    "deleted test cases, newly skipped/xfail/disabled tests, or a test rewritten to "
    "match the (buggy) new behavior instead of the originally-intended expected "
    "behavior. If the diff touches test code, verify the change preserves or "
    "tightens the assertion's strength — a test that got weaker to pass is a "
    "violation, not a fix, even if the stated result is 'tests now pass'."
)


def _detect_fix_intent(task_description: str) -> bool:
    """True when the task is a bug fix (fix:/bug/regression/hotfix in the description)."""
    return bool(_FIX_INTENT_RE.search(task_description or ""))


# Magnitude-anomaly skepticism (Mitchell Hashimoto: "agent psychosis" — models
# routinely overstate self-reported wins). The oracle already gates bug-fix
# tasks with _FIX_ONE_STEP_CRITERION but had no equivalent skepticism for
# perf/optimization claims — a huge before/after ratio was graded at face value.
_PERF_INTENT_RE = re.compile(
    r"\bperf(?:ormance)?\b|\boptimiz\w*\b|\bspeed\s*up\b|\bsped\s*up\b|"
    r"\bfaster\b|\blatency\b|\bthroughput\b|\bbenchmark\w*\b",
    re.IGNORECASE,
)

_PERF_MAGNITUDE_CRITERION = (
    "Additional completeness criterion (performance/optimization task): treat a large "
    "self-reported improvement with skepticism — models routinely overstate wins "
    "('agent psychosis'). Before accepting an order-of-magnitude or larger claimed "
    "improvement (e.g. 10x+, '99% faster', a huge before/after ratio), verify from the "
    "diff and any reported numbers: "
    "(a) the benchmark methodology is sound (same workload/environment, warm-up "
    "accounted for, not a degenerate or trivially-small input); "
    "(b) the diff explains a REAL mechanism for the speedup and does not simply skip "
    "the work being measured (caching that bypasses the correctness path, a smaller "
    "test input, dead-code elimination that removes the very thing benchmarked); "
    "(c) correctness is preserved for the ORIGINAL input space, not just the fast path. "
    "If a claimed number cannot be independently justified from the diff and the "
    "reported methodology, report it as an issue and require re-verification — never "
    "accept a magnitude claim at face value just because it is large."
)


def _detect_perf_intent(task_description: str) -> bool:
    """True when the task claims a performance/optimization win worth extra scrutiny."""
    return bool(_PERF_INTENT_RE.search(task_description or ""))


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
        block += "\n\n" + _FIX_ONE_STEP_CRITERION
        block += "\n\n" + _TEST_INTEGRITY_CRITERION
    if _detect_perf_intent(task_description):
        block += "\n\n" + _PERF_MAGNITUDE_CRITERION
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


_CONF_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


def _aggregate_oracle_votes(
    votes: list[tuple[bool, str, str, bool]],
) -> tuple[bool, str, str, bool]:
    """Majority-vote K oracle samples with a SAFE bias (Round 3 gap B).

    Each vote is (passed, confidence, issues_text, infra_error). LLM judges flip
    on identical inputs, so we resample and require a CLEAN MAJORITY of valid
    (non-infra) samples to PASS — a tie or disagreement resolves to FAIL, because
    a false-approve gates auto-merge while a false-reject only costs a retry.
    All samples infra → unreviewed (the streak logic upstream handles it).
    """
    valid = [v for v in votes if not v[3]]
    if not valid:
        issues = next((v[2] for v in votes if v[2]), "oracle infra error")
        return True, "none", issues, True
    pass_votes = [v for v in valid if v[0]]
    passed = len(pass_votes) * 2 > len(valid)  # strict majority; odd K avoids ties
    agreeing = pass_votes if passed else [v for v in valid if not v[0]]
    confidence = max((v[1] for v in agreeing), key=lambda c: _CONF_ORDER.get(c, 0))
    issues = "" if passed else next((v[2] for v in agreeing if v[2]), "")
    return passed, confidence, issues, False


async def _oracle_pass(
    prompt: str, claude_dir: Path, samples: int = 1
) -> tuple[bool, str, str, bool]:
    """Run an oracle pass, optionally resampled K× with majority vote (gap B).

    samples<=1 is the single-shot path (unchanged, no extra cost). samples>1 runs
    K concurrent passes and aggregates via _aggregate_oracle_votes (safe bias).
    Returns (passed, confidence, issues_text, infra_error).
    """
    n = max(1, int(samples or 1))
    if n == 1:
        return await _oracle_pass_once(prompt, claude_dir)
    votes = await asyncio.gather(*[_oracle_pass_once(prompt, claude_dir) for _ in range(n)])
    return _aggregate_oracle_votes(list(votes))


async def _oracle_pass_once(
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
            f'--model {HAIKU_MODEL} {SETTING_SOURCES_NONE} {DISALLOWED_TOOLS_JUDGE} '
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
    task_description: str, diff_chunk: str, chunk_label: str, claude_dir: Path,
    constitution: str = "", samples: int = 1,
) -> tuple[bool, str, bool]:
    """Review a single diff chunk. Returns (approved, reason, infra_error).

    infra_error=True means the chunk was NOT reviewed (timeout, subprocess
    failure, unparseable output) — never report that as an approval.
    samples>1 (gap B) resamples the judge and requires a CLEAN MAJORITY to
    APPROVE; follow-up findings are written exactly once, for the winning sample.
    """
    # Caller passes a pre-built task block (description + criteria); cap defensively.
    prompt = _ORACLE_PROMPT_TEMPLATE.format(
        task=task_description[:_ORACLE_TASK_DESC_CAP + 2500], diff=diff_chunk
    )
    if constitution:
        prompt = _ORACLE_CONSTITUTION_HEADER.format(rules=constitution) + prompt
    if chunk_label:
        prompt = f"[Reviewing chunk: {chunk_label}]\n\n" + prompt
    label = f"chunk {chunk_label}" if chunk_label else "chunk 1/1"

    n = max(1, int(samples or 1))
    results = await asyncio.gather(*[
        _oracle_review_chunk_once(prompt, claude_dir) for _ in range(n)
    ])
    # results: list of (approved, reason, infra, findings, log_findings)
    valid = [r for r in results if not r[2]]
    if not valid:  # every sample was a non-review → unreviewed
        reason = next((r[1] for r in results if r[1]), "oracle infra error")
        return True, reason[:300], True
    approve_votes = [r for r in valid if r[0]]
    approved = len(approve_votes) * 2 > len(valid)  # strict majority; safe bias
    if approved:
        rep = approve_votes[0]
        if rep[4]:  # log_findings — write the winning sample's follow-ups ONCE
            _append_followup_findings(claude_dir, rep[3], label)
        return True, rep[1], False
    rep = next(r for r in valid if not r[0])
    return False, rep[1], False


async def _oracle_review_chunk_once(
    prompt: str, claude_dir: Path
) -> tuple[bool, str, bool, list, bool]:
    """One chunk-review subprocess, NO side effects (gap B resampling core).

    Returns (approved, reason, infra_error, findings, log_findings). The severity
    gate (domdomegg) is applied here so `approved` is the effective decision, but
    follow-up findings are NOT written — the caller writes them once for the
    sample that wins the vote, avoiding K× duplicate skipped.md entries.
    """
    prompt_file = claude_dir / f"oracle-{uuid.uuid4().hex[:8]}.md"
    try:
        prompt_file.write_text(prompt)
        # Grader containment — see _oracle_pass_once: pure judge (no skip-
        # permissions, no user settings/hooks, judge system prompt, scratch
        # cwd, closed stdin).
        proc = await asyncio.create_subprocess_shell(
            f'claude -p "$(cat {shlex.quote(str(prompt_file))})" '
            f'--model {HAIKU_MODEL} {SETTING_SOURCES_NONE} {DISALLOWED_TOOLS_JUDGE} '
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
            return True, "oracle timeout (60s)", True, [], False
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
            # only by warning/info findings is demoted to approval and its
            # findings are logged as follow-ups. Findings-less rejections keep
            # their decision (legacy fix_guidance/dimensions-only responses).
            has_error = any(
                isinstance(f, dict) and f.get("severity") == "error" for f in findings
            )
            if not approved and findings and not has_error:
                return True, "approved (non-blocking findings logged as follow-ups)", False, findings, True
            if not approved:
                reason = _format_oracle_rejection(confidence, fix_guidance, dims, findings)
                return False, reason, False, [], False
            return True, "approved", False, findings, True
        except (json.JSONDecodeError, AttributeError):
            pass
        # Legacy plain-text verdicts ("APPROVED: ..." / "REJECTED: ...")
        if raw.startswith(("APPROVED", "REJECTED")):
            reason = raw.split(":", 1)[-1].strip()[:80] if ":" in raw else raw[:80]
            return raw.startswith("APPROVED"), reason, False, [], False
        # Anything else (empty output, API error text) is not a review
        return True, "oracle returned unparseable output", True, [], False
    except Exception as e:
        logger.warning("oracle chunk review error: %s", e)
        return True, "oracle subprocess error", True, [], False
    finally:
        prompt_file.unlink(missing_ok=True)


_CODE_RULES_RE = re.compile(
    r"^#{1,3}[ \t]+Code Rules[ \t]*$(.*?)(?=^#{1,3}[ \t]|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _read_constitution(project_dir: Path) -> str:
    """Extract the project's binding code rules from CLAUDE.md (Constitutional AI).

    Returns the body of the '## Code Rules' section (capped), or '' if there is no
    CLAUDE.md or no such section. Fail-open by design: any read/parse error yields
    '' so the oracle behaves exactly as it did before this check existed. Project-
    agnostic — repos without a Code Rules section are simply un-gated on rules.
    """
    try:
        md = (project_dir / "CLAUDE.md").read_text(encoding="utf-8")
    except Exception:
        return ""
    m = _CODE_RULES_RE.search(md)
    if not m:
        return ""
    text = m.group(1).strip()
    if len(text) > 1500:
        # Truncate on a line boundary so the grader never sees a half-rule.
        text = text[:1500].rsplit("\n", 1)[0]
    return text


async def _oracle_review(
    task_description: str,
    diff_text: str,
    claude_dir: Path,
    acceptance_criteria: list[str] | None = None,
    test_evidence: str = "",
    constitution: str = "",
    verdict_samples: int = 1,
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
    # Risk-based dispatch (Takanori Sano): a diff touching a security/data-
    # sensitive surface gets extra resample votes regardless of its size — a
    # 1-line change to billing/auth code must not get the same single-shot
    # scrutiny as a docstring typo just because it's small.
    if _classify_diff_risk(diff_text) and verdict_samples < 3:
        verdict_samples = 3
    # Chunk large diffs (Qodo §Gap3)
    if len(diff_text) > _ORACLE_CHUNK_SIZE:
        chunks = [
            diff_text[i:i + _ORACLE_CHUNK_SIZE]
            for i in range(0, len(diff_text), _ORACLE_CHUNK_SIZE)
        ]
        # Review first 3 chunks max to avoid excessive API calls
        chunks = chunks[:3]
        results = await asyncio.gather(*[
            _oracle_review_chunk(task_block, chunk, f"{i+1}/{len(chunks)}", claude_dir,
                                 constitution=constitution, samples=verdict_samples)
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
    # Constitution rides the quality pass (project rules are a quality concern, not
    # a spec one) via its evidence slot — reflection-agents §Gap4.
    if constitution:
        evidence_block += _ORACLE_CONSTITUTION_HEADER.format(rules=constitution)
    quality_prompt = _ORACLE_QUALITY_PROMPT.format(diff=diff_excerpt, evidence=evidence_block)

    # Pass 1: spec compliance check
    spec_passed, spec_conf, spec_issues, spec_infra = await _oracle_pass(spec_prompt, claude_dir, verdict_samples)
    if spec_infra:
        return True, f"oracle infra error (spec pass): {spec_issues}"[:300], True
    if not spec_passed and spec_conf in ("high", "medium"):
        reason = f"[{spec_conf}/spec] " + (spec_issues or "spec compliance failed")
        return False, reason[:300], False

    # Pass 2: quality check (only runs if spec passed)
    quality_passed, quality_conf, quality_issues, quality_infra = await _oracle_pass(quality_prompt, claude_dir, verdict_samples)
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


async def _escalate_oracle_reject_plateau(
    project_dir: Path, claude_dir: Path, webhook: str, task_id: str, rounds: int
) -> None:
    """Reject-round circuit breaker (Round-4, fennu2333): a task's oracle-reject
    depth hit the configured ceiling — the requeue loop is NOT infinite, so this
    fires instead of another requeue. Distinct event name from
    _escalate_oracle_outage (this is a real, LIVE oracle repeatedly rejecting the
    same lineage — the opposite failure mode from a dead/unreachable oracle).
    Fail-open: escalation must never raise into the caller's requeue logic.
    """
    try:
        blockers = claude_dir / "blockers.md"
        entry = (
            f"\n## Blocker [{datetime.now().isoformat(timespec='seconds')}]\n"
            f"Oracle has rejected task {task_id} {rounds} times in a row — hit the "
            f"reject-round cap (oracle_max_reject_rounds). Requeuing stopped; this task "
            f"likely needs a human to re-scope it (the approach may be fundamentally "
            f"wrong, or the task as described may not be achievable).\n"
            f"Tried: sequential retry + diverse-sample fan-out on plateau, both rejected.\n"
        )
        existing = blockers.read_text(errors="replace") if blockers.exists() else ""
        blockers.write_text(existing + entry)
    except Exception:
        pass
    if not webhook:
        return
    try:
        payload = json.dumps({
            "event": "oracle_reject_plateau",
            "project_path": str(project_dir),
            "task_id": task_id,
            "reject_rounds": rounds,
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


async def handle_oracle_requeue(
    w: Any, task_queue: Any,
    max_reject_rounds: int, notification_webhook: str, parallel_fix_samples: int,
) -> None:
    """Fan out retry/diverse-sample tasks after an oracle rejection, or escalate
    instead once the reject-round cap is hit (fennu2333: an unbounded lineage
    could otherwise requeue forever). Moved out of WorkerPool.poll_all to keep
    worker.py under the 1500-line convention cap — pure extraction, same logic.
    """
    error_summary = _strip_error_context(w._oracle_requeue_reason)
    orig_task = await task_queue.get(w.task_id)
    is_critical = bool(orig_task and orig_task.get("is_critical_path"))
    depth = oracle_reject_depth(w.description)
    if max_reject_rounds > 0 and depth >= max_reject_rounds:
        logger.warning(
            "Oracle rejected task %s — hit reject-round cap (%d rounds), "
            "escalating instead of requeuing again", w.task_id, max_reject_rounds,
        )
        try:
            await _escalate_oracle_reject_plateau(
                w._project_dir, w._claude_dir, notification_webhook, w.task_id, depth,
            )
        except Exception:
            pass  # escalation must never break poll_all
        return
    n_samples = oracle_retry_sample_count(w.description, is_critical, parallel_fix_samples)
    _diverse_hints = [
        "Try a different algorithmic approach than your previous attempt.",
        "Focus on the root cause rather than symptoms — consider upstream fixes.",
        "Prefer minimal diff — find the smallest correct change.",
    ]
    for i in range(n_samples):
        hint = f"\n{_diverse_hints[i % len(_diverse_hints)]}" if n_samples > 1 else ""
        retry_desc = (
            f"{w.description}\n\n---\n"
            f"Previous attempt was {ORACLE_REJECT_MARKER}:\n"
            f"{error_summary}\n"
            f"Fix the issue described above. Do NOT repeat the same approach.{hint}"
        )
        await task_queue.add(
            retry_desc, w.model, own_files=w.own_files,
            forbidden_files=w.forbidden_files,
            provider=getattr(w, "provider", None), effort=getattr(w, "effort", None),
            parent_task_id=w.task_id,
        )
    if n_samples > 1:
        logger.info("Oracle rejected task %s — plateau, spawned %d diverse samples", w.task_id, n_samples)
    else:
        logger.info("Oracle rejected task %s — re-queued (sequential retry)", w.task_id)


async def handle_test_requeue(w: Any, task_queue: Any, is_loop_task: bool) -> None:
    """Pre-push test failure → re-queue with test output (mic92: evidence
    before verdict). Loop/plan-managed tasks are exempt from spawning an
    untracked retry (same rationale as handle_oracle_requeue) — the
    diagnostic failed_reason update still happens regardless, since it only
    annotates the existing row rather than creating a new one."""
    error_summary = _strip_error_context(w._test_requeue_reason)
    if not is_loop_task:
        retry_desc = (
            f"{w.description}\n\n---\n"
            f"Previous attempt FAILED the project test suite (commit undone, never pushed):\n"
            f"{error_summary}\n"
            f"Fix the failures, run the project tests locally, then complete the task."
        )
        await task_queue.add(retry_desc, w.model,
                             own_files=w.own_files, forbidden_files=w.forbidden_files,
                             provider=getattr(w, "provider", None),
                             effort=getattr(w, "effort", None),
                             parent_task_id=w.task_id)
    await task_queue.update(
        w.task_id, failed_reason=f"Pre-push tests failed: {error_summary[:200]}"
    )
    if not is_loop_task:
        logger.info("Pre-push tests failed for task %s — re-queued with test output", w.task_id)
    else:
        logger.info(
            "Pre-push tests failed for task %s — loop/plan-managed, not requeuing "
            "(failed_reason recorded on the existing row)", w.task_id,
        )


async def handle_ownership_requeue(w: Any, task_queue: Any, is_loop_task: bool) -> None:
    """File ownership violation → re-queue with violation context. Same
    loop/plan exemption as handle_test_requeue."""
    error_summary = _strip_error_context(w._ownership_violation_reason)
    if not is_loop_task:
        retry_desc = (
            f"{w.description}\n\n---\n"
            f"Previous attempt REJECTED — file ownership violation:\n"
            f"{error_summary}\n\n"
            f"You MUST only edit files matching your OWN_FILES patterns. "
            f"Do NOT touch FORBIDDEN_FILES. Find an alternative approach."
        )
        await task_queue.add(retry_desc, w.model,
                            own_files=w.own_files, forbidden_files=w.forbidden_files,
                            provider=getattr(w, "provider", None),
                            effort=getattr(w, "effort", None),
                            parent_task_id=w.task_id)
    await task_queue.update(
        w.task_id, failed_reason=f"Ownership violation: {error_summary[:200]}"
    )
    if not is_loop_task:
        logger.info("Ownership violation task %s — re-queued with reason", w.task_id)
    else:
        logger.info(
            "Ownership violation task %s — loop/plan-managed, not requeuing "
            "(failed_reason recorded on the existing row)", w.task_id,
        )


async def handle_handoff_requeue(w: Any, task_queue: Any, is_loop_task: bool) -> None:
    """Worker wrote a handoff file → create a continuation task. Same
    loop/plan exemption as handle_oracle_requeue — no diagnostic update here
    (unlike test/ownership) since there is nothing to annotate on the row."""
    if not is_loop_task:
        continuation_desc = (
            f"{w.description}\n\n---\n"
            f"**Continuation — previous session handed off:**\n"
            f"{w._handoff_content}\n\n"
            f"Run /pickup if available, then continue from where the previous worker left off."
        )
        await task_queue.add(continuation_desc, w.model,
                            own_files=w.own_files, forbidden_files=w.forbidden_files,
                            provider=getattr(w, "provider", None),
                            effort=getattr(w, "effort", None),
                            parent_task_id=w.task_id)
        logger.info("Handoff task %s → continuation queued", w.task_id)
    else:
        logger.info(
            "Worker %s handed off but is loop/plan-managed — not "
            "spawning a continuation task (has its own retry pipeline)",
            w.task_id,
        )
