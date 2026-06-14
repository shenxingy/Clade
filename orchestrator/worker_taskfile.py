"""
worker_taskfile.py — Task file construction for workers.

Extracted from worker.py (Worker._build_task_file) to keep that file under
1500 lines. Builds the per-worker task-{id}.md with injected context:
CLAUDE.md/AGENTS.md, TLDR (localized + fault-located + span-evicted),
pre-hydrated GitHub issues, sibling completions, staleness warnings,
unread messages, task schema, and the fix-task two-phase directive.

The worker is passed duck-typed (Any) to avoid a worker.py import cycle.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from config import (
    GLOBAL_SETTINGS,
    _parse_task_type,
    _parse_task_schema,
    _format_task_schema_block,
)
from worker_tldr import (
    _generate_code_tldr, _localize_tldr_for_task, _localize_fault,
    _prune_tldr_to_entities, _parse_fault_entity_names, _find_caller_hints,
    _generate_repro_test, _sbfl_prepass, _span_evict_tldr,
)
from condensers import ObservationMaskingCondenser
from worker_utils import (
    _capture_test_baseline,
    EDIT_DISCIPLINE_BLOCK, SEARCH_CONVENTIONS_BLOCK, COMPLETION_CONTRACT_BLOCK,
)
from worker_hydrate import _pre_hydrate

logger = logging.getLogger(__name__)

# History carries the payload: workers commit via committer.sh, and the body
# is the only place mechanism/root-cause survives for future debugging — the
# task file and worker log are ephemeral, git history is not.
FRICTION_LOG_BLOCK = (
    "\n\n---\n\n"
    "## Friction Log\n"
    "If a tool or harness feature fights you (wrong output, unexpected workaround needed, "
    "blocks progress), append ≤2 lines to `BRAINSTORM.md` under `## [AI] Friction Log`:\n"
    "```\n"
    "[YYYY-MM-DD] tool: <what happened> / workaround: <what you did>\n"
    "```\n"
    "One entry per incident, max 2 lines. Skip if nothing noteworthy.\n"
)

COMMIT_GUIDANCE_BLOCK = (
    "\n\n---\n\n"
    "## Commit Messages\n"
    "- Commit via `committer \"type: subject\" file1 file2` (NEVER `git add .`).\n"
    "- Substantive commits (feat/fix/refactor/perf) need a 2-4 line body after "
    "the subject: the **mechanism** (how the change works), the **hazard avoided "
    "or root cause** (for fixes), and any **constraint honored**. Put it in the "
    "same quoted message — committer accepts multi-line messages.\n"
    "- Trivial chore/docs commits may stay subject-only.\n"
)


def _clear_stale_inbox(w: Any) -> None:
    """Remove a leftover mid-flight inbox file from a previous spawn of this task.

    The file's messages are still unread in the worker_messages table (a drain
    never marks them read), so the at-spawn injection in build_task_file has
    already delivered them — leaving the file would double-deliver on this
    spawn's first tool call. Worktree spawns get a fresh _project_dir, where
    this is a no-op; shared-project-dir spawns are the case that matters.
    """
    try:
        inbox = Path(w._project_dir) / ".claude" / f"worker-inbox-{w.task_id}.md"
        inbox.unlink(missing_ok=True)
    except OSError:
        pass


async def build_task_file(w: Any, task_queue: Any | None) -> Path:
    """Set up log path and write the task file with injected context. Returns task file path.

    `w` is the Worker instance (duck-typed to keep this module import-light).
    """
    logs = w._claude_dir / "orchestrator-logs"
    logs.mkdir(parents=True, exist_ok=True)
    w._log_path = logs / f"worker-{w.id}.log"
    w.log_file = str(w._log_path)

    # Initialize EventStream JSONL path for crash-safe event logging
    jsonl_path = logs / f"events-{w.id}.jsonl"
    w._event_stream.set_jsonl_path(jsonl_path)
    w._event_stream.emit(
        event_type="state_change",
        event_kind="state_change",
        source="supervisor",
        content={"state": "started", "task_id": w.task_id, "model": w.model},
    )

    task_file = w._claude_dir / f"task-{w.id}.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)

    # Prepend project CLAUDE.md + AGENTS.md for context injection
    effective_description = w.description
    context_blocks = []
    claude_md = w._claude_dir / "CLAUDE.md"
    if claude_md.exists():
        try:
            claude_content = claude_md.read_text(errors="replace").strip()
            if claude_content:
                context_blocks.append(f"# Project Context (from .claude/CLAUDE.md)\n\n{claude_content}")
        except Exception:
            pass
    agents_md = w._claude_dir / "AGENTS.md"
    if not agents_md.exists():
        agents_md = w._project_dir / "AGENTS.md"
    if agents_md.exists():
        try:
            agents_content = agents_md.read_text(errors="replace").strip()
            if agents_content:
                context_blocks.append(f"# File Ownership (from AGENTS.md)\n\n{agents_content}")
        except Exception:
            pass
    try:
        tldr = _generate_code_tldr(str(w._original_project_dir))
        if tldr:
            # Two-phase localization (Moatless pattern): when TLDR is large,
            # ask haiku to narrow to the top-5 most relevant files for this task.
            if len(tldr) > 4096:
                tldr = await _localize_tldr_for_task(
                    w.description, tldr, w._original_project_dir
                )
            # Fault localization pre-pass (Agentless §6A): for fix/bug tasks,
            # predict likely change locations to tighten worker focus.
            # Run before appending TLDR so we can entity-prune it (Sweep §Gap1).
            task_type = _parse_task_type(w.description)
            fault_locs = ""
            if task_type == "fix":
                fault_locs = await _localize_fault(
                    w.description, tldr, w._original_project_dir
                )
                if fault_locs:
                    # Sweep §Gap1: entity-level TLDR pruning.
                    # Use suspect_functions from fault localization to filter
                    # TLDR down to only the relevant entities in each file.
                    entity_names = _parse_fault_entity_names(fault_locs)
                    if entity_names:
                        tldr = _prune_tldr_to_entities(tldr, entity_names)
                    # Sweep §Gap2: add caller hints for suspect functions.
                    caller_hints = await _find_caller_hints(
                        fault_locs, w._original_project_dir
                    )
                    if caller_hints:
                        fault_locs += f"\n\n{caller_hints}"
            # Moatless §Gap3: span-level FileContext with token budget.
            # Preserve fault-localized files; evict others. Inject hint
            # when spans dropped so worker fetches more via MCP tools.
            span_budget = int(GLOBAL_SETTINGS.get("context_span_budget", 6000))
            priority_files = re.findall(r'`([^`]+\.(?:py|js|ts|tsx))`', fault_locs) if fault_locs else []
            tldr, n_evicted = _span_evict_tldr(tldr, span_budget, priority_files)
            context_blocks.append(f"# Codebase Structure (auto-generated)\n\n{tldr}")
            if n_evicted > 0:
                context_blocks.append(
                    f"# Context Retrieval\n\n{n_evicted} file span(s) evicted to fit budget. "
                    f"Use clade_search_class / clade_search_method / clade_search_code "
                    f"MCP tools to retrieve additional spans on demand."
                )
            if fault_locs:
                context_blocks.append(fault_locs)
            # For fix tasks: run repro test generation + SBFL pre-pass concurrently.
            if task_type == "fix":
                repro_task = asyncio.create_task(
                    _generate_repro_test(
                        w.description, tldr, w._original_project_dir,
                        w._claude_dir, w.task_id,
                    )
                )
                sbfl_task = asyncio.create_task(
                    _sbfl_prepass(w._original_project_dir)
                )
                repro_test, sbfl_block = await asyncio.gather(repro_task, sbfl_task)
                if sbfl_block:
                    context_blocks.append(sbfl_block)
                if repro_test:
                    context_blocks.append(repro_test)
    except Exception:
        pass
    # Pre-hydration: fetch linked GitHub issues/PRs before agent starts (Stripe Blueprint pattern)
    try:
        hydrate_block = await _pre_hydrate(w.description, w._project_dir)
        if hydrate_block:
            context_blocks.append(hydrate_block)
    except Exception:
        pass
    # Apply ObservationMaskingCondenser to truncate any oversized context block before
    # writing the task file — prevents multi-hundred-KB task files from large GitHub issues
    # or deeply nested project structures. Each block treated as an observation event.
    if context_blocks:
        _ctx_condenser = ObservationMaskingCondenser(max_obs_bytes=8192)
        _ctx_events = [{"type": "observation", "content": b} for b in context_blocks]
        context_blocks = [e["content"] for e in _ctx_condenser.condense(_ctx_events)]
        effective_description = "\n\n---\n\n".join(context_blocks) + f"\n\n---\n\n# Task\n\n{w.description}"
    # Inject recent sibling completions (multi-agent context archival).
    # Workers gain awareness of what was recently accomplished — prevents duplicate
    # work and allows continuation of previously established patterns.
    if task_queue:
        try:
            recent = await task_queue.get_recent_completions(
                exclude_task_id=w.task_id, limit=5, since_seconds=86400
            )
            if recent:
                lines = ["## Recently Completed Tasks"]
                for r in recent:
                    lines.append(f"- [{r['id']}] {r['completion_summary']}")
                effective_description += "\n\n---\n\n" + "\n".join(lines) + "\n"
        except Exception:
            pass
        # Context versioning (Multi-agent Gap 1): stamp this worker's task file
        # with the current completion count. If codebase has changed since the task
        # was queued, inject a staleness warning so the agent knows to re-read key files.
        try:
            current_version = await task_queue.get_context_version()
            task_context_version = 0
            task = await task_queue.get(w.task_id)
            if task:
                task_context_version = task.get("context_version") or 0
            w.context_version = current_version
            await task_queue.stamp_context_version(w.task_id)
            stale_count = current_version - task_context_version
            if stale_count > 0:
                effective_description += (
                    f"\n\n---\n\n"
                    f"⚠ **Context Staleness Warning**: {stale_count} task(s) completed since "
                    f"this task was queued. Codebase may have changed — re-read key files "
                    f"before making assumptions about current state.\n"
                )
        except Exception:
            pass
    # Inject unread messages from other tasks — also condense individual messages
    # to prevent a large tool-output dump from one worker flooding another's context
    if task_queue:
        try:
            messages = await task_queue.get_messages(w.task_id, unread_only=True)
            if messages:
                _msg_condenser = ObservationMaskingCondenser(max_obs_bytes=2000)
                msg_block = "\n\n---\n**Messages from other tasks:**\n"
                for m in messages:
                    sender = m.get("from_task_id") or "human"
                    condensed = _msg_condenser.condense(
                        [{"type": "observation", "content": m["content"]}]
                    )
                    msg_block += f"- [{sender}]: {condensed[0]['content']}\n"
                effective_description += msg_block
                await task_queue.mark_messages_read(w.task_id)
        except Exception:
            pass
    # Mid-flight steering hygiene: the unread-message injection above is the
    # AT-SPAWN channel; .claude/worker-inbox-<task_id>.md (written by
    # routes/tasks.py:_write_worker_inbox, drained by mailbox-drain.sh) is the
    # MID-FLIGHT channel. Both read from the same worker_messages rows, so an
    # inbox file the previous spawn never drained (worker exited before its
    # next tool call) was already re-delivered above — remove the stale file
    # so this spawn's first tool call doesn't deliver it a second time.
    _clear_stale_inbox(w)
    # Multi-agent Gap 3: inject task schema (acceptance criteria + contracts) if present.
    _schema_block = _format_task_schema_block(_parse_task_schema(w.description))

    # AutoCodeRover §Gap2 + ECC strategic-compact: for fix tasks, inject explicit
    # two-phase directive with phase-boundary checkpoint (not arbitrary token count).
    _fix_two_phase = ""
    if _parse_task_type(w.description) == "fix":
        _fix_two_phase = (
            "\n\n---\n\n"
            "## Two-Phase Approach (AutoCodeRover §Gap2)\n"
            "**Phase 1 — Explore first (make NO code changes):**\n"
            "1. Read the suspect files identified above\n"
            "2. Trace the execution path to the root cause\n"
            "3. Identify the exact 1-5 lines that need to change\n"
            "4. **Phase boundary**: write your findings to `.claude/ctx-checkpoint.md` "
            "before making any edits (root cause, affected lines, intended fix).\n\n"
            "**Phase 2 — Patch (after checkpoint written):**\n"
            "1. Make the minimal targeted change — prefer 1-3 line edits\n"
            "2. Verify the reproduction test passes (if provided above)\n"
            "3. Run lint before committing\n\n"
            "**Phase 3 — Structural close (lovesegfault; after the patch works):**\n"
            "1. Sibling sweep: grep for the same defective shape elsewhere — cover "
            "the whole edited file plus ±50 lines around each edit, and the rest of "
            "the module. Fix every hit or list the ones you deliberately left.\n"
            "2. Dead-code sweep: remove state, branches, or comments the fix "
            "obsoleted.\n"
            "3. End your completion summary with a `Done-gate:` line listing the "
            "literal grep/test commands that verify sweeps 1-2 — the reviewer runs "
            "them, so they must be copy-pasteable.\n"
        )
    task_file.write_text(
        effective_description + _schema_block + _fix_two_phase
        + EDIT_DISCIPLINE_BLOCK + SEARCH_CONVENTIONS_BLOCK
        + COMMIT_GUIDANCE_BLOCK + FRICTION_LOG_BLOCK + COMPLETION_CONTRACT_BLOCK
    )

    # OpenHands §Gap3: capture test baseline before worker edits (fix tasks only).
    if _parse_task_type(w.description) == "fix" and w._project_dir:
        try:
            baseline = await _capture_test_baseline(w._project_dir, timeout=30)
            if baseline:
                # Namespaced by task_id: claude_dir is shared across concurrent
                # swarm workers — a fixed filename races (one worker's baseline
                # clobbers another's, producing bogus regression warnings).
                (w._claude_dir / f"test-baseline-{w.task_id}.json").write_text(
                    json.dumps(baseline)
                )
                logger.debug("Intramorphic baseline: %d tests for %s", len(baseline), w.task_id)
        except Exception:
            pass

    return task_file
