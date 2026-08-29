"""
Orchestrator config — constants, settings, utilities.
Leaf module: no internal dependencies.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import signal
import subprocess
import time
from pathlib import Path

from execution_envelope import InvalidExecutionConfig, validate_model_id
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

DEFAULT_LOG_FORMAT = "%(levelname)-8s %(name)s:%(filename)s:%(lineno)d %(message)s"

_ALLOWED_TASK_COLS = {"status", "description", "model", "depends_on", "score",
                      "worker_id", "started_at", "elapsed_s", "last_commit", "log_file",
                      "failed_reason", "score_note", "own_files", "forbidden_files",
                      "gh_issue_number", "is_critical_path",
                      "input_tokens", "output_tokens", "estimated_cost",
                      "task_type", "source_ref", "parent_task_id", "priority_score",
                      "handoff_type", "handoff_payload", "completion_summary",
                      "token_budget", "context_version", "attempt_count",
                      "phase", "oracle_result", "oracle_reason", "pgid", "provider",
                      "agent_runtime", "connection", "execution_profile",
                      "execution_requirements", "execution_envelope",
                      "effort", "route_reason", "redaction_metadata"}

_ALLOWED_LOOP_COLS = {
    "name", "artifact_path", "context_dir", "status", "iteration",
    "changes_history", "deferred_items", "convergence_k", "convergence_n",
    "max_iterations", "supervisor_model", "mode", "plan_phase", "updated_at",
    "plan_item_reject_streak",
}

_MODEL_ALIASES = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-5",
}

# Canonical model IDs — single source of truth. Dated model snapshots may
# appear ONLY in this file (enforced by tests/test_conventions.py). Non-leaf
# modules import these; documented leaf modules (worker_review, worker_tldr,
# worker_utils, condensers) must not import config, so worker.py threads
# HAIKU_MODEL into them at import time (they default to the 'haiku' alias).
HAIKU_MODEL = _MODEL_ALIASES["haiku"]
SONNET_MODEL = _MODEL_ALIASES["sonnet"]
OPUS_MODEL = _MODEL_ALIASES["opus"]

# Pinned built-in Claude metadata retained for aliases, routing defaults, and
# offline tests. This is not a universal model allowlist: gateways and custom
# providers use opaque model IDs validated and shell-quoted at the adapter
# boundary.
ALLOWED_MODEL_IDS = set(_MODEL_ALIASES.values()) | {
    # Superseded generations stay accepted: task rows, evidence bundles, and
    # `model:` pins written before an alias moved must keep resolving.
    "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5",
}

# Pure-judge containment flag — single source of truth for the Python layer.
# Nested `claude -p` calls whose stdout is PARSED (oracle, TLDR/localize,
# scoring, distill, condense, supervisor/planner, idea eval) must NOT load
# user settings: a prompt-type Stop hook's {"ok":true} decision is printed as
# the -p result instead of the model reply (see worker_review._oracle_pass,
# commit 386a862), poisoning every JSON-extraction pipeline downstream.
# WORKER spawns (worker.py Worker.start / _run_with_context) keep full user
# settings deliberately — commit-discipline hooks are core value. Leaf modules
# carry the same literal as a module default; worker.py re-asserts it at
# import time so this constant stays authoritative.
# Shell-string sites embed it verbatim; exec-argv sites use shlex.split().
SETTING_SOURCES_NONE = '--setting-sources ""'
# Judges must not mutate files — denies Edit, Write, Bash on all judge invocations.
DISALLOWED_TOOLS_JUDGE = "--disallowed-tools Edit,Write,Bash"

# ─── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
WEB_DIR = BASE_DIR / "web"

# Kept for backward compat / default session init; not used in new code paths
PROJECT_DIR = Path(os.environ.get("ORCHESTRATOR_PROJECT_DIR", str(Path.cwd())))

# ─── Global Settings ──────────────────────────────────────────────────────────

_settings_file = Path.home() / ".claude" / "orchestrator-settings.json"


_SETTINGS_DEFAULTS = {
    "max_workers": 0,
    "auto_start": True,
    "auto_push": True,
    "auto_merge": True,
    "auto_merge_strategy": "auto",
    "auto_review": True,
    "default_model": "sonnet",
    "loop_supervisor_model": "sonnet",
    "loop_convergence_k": 2,
    "loop_convergence_n": 3,
    "loop_max_iterations": 20,
    "loop_context_mode": "carry",  # carry=current hydration; reset=typed clean handoff
    # Spawn workers with --output-format stream-json so the agent reports its
    # own token usage and total_cost_usd. Off means falling back to scraping
    # prose for a `tokens: N/N` line the CLI does not emit, i.e. cost 0.0 and a
    # token budget that cannot fire. Kill switch only — see agent_output.py.
    "worker_structured_output": True,
    "run_budget_usd": 0.0,  # max cost per autonomous run (0 = unlimited)
    "run_budget_tokens": 0,  # max tokens per autonomous run (0 = unlimited)
    "auto_oracle": False,
    # Additive lifecycle observability. False records declared phase transitions
    # without inspecting legality; True tags/logs illegal edges but never blocks.
    "phase_graph_validate": False,
    # Independent, non-LLM review evidence recorded alongside the oracle verdict.
    # Advisory by default; the separate block flag promotes only the dangerous
    # oracle-approved/deterministic-failed disagreement to a hard gate.
    "judge_diversity_enabled": False,
    "judge_diversity_block": False,
    # Reproduction-test filter (Agentless §6B validation half). When a fix task's
    # generated repro test was confirmed FAILING pre-fix, re-run it post-fix: its
    # result always flows into oracle evidence. With this True, a still-failing
    # repro ALSO hard-blocks the commit (undo + requeue); default False keeps it
    # advisory (oracle decides) to avoid false-blocks from an imperfect repro.
    "repro_test_gate": False,
    "auto_model_routing": False,
    "verifier_cascade_enabled": False,
    "verifier_cascade_min_score": 80,
    "verifier_cascade_max_files": 8,
    "verifier_cascade_task_types": ["test", "tldr"],
    "context_budget_warning": True,
    "github_issues_sync": False,
    "github_issues_label": "orchestrator",
    "agent_teams": False,
    "stuck_timeout_minutes": 15,
    "cost_budget": 0,
    "worker_token_budget": 0,  # max tokens per worker (0 = unlimited)
    # Spawn-time env denylist (prompt-injection exfil hardening — Round 3 sliver).
    # Workers run --dangerously-skip-permissions with full env passthrough while
    # hydrating untrusted GitHub issue/PR text; every key listed here is popped
    # from the worker's env before spawn. Default [] = off. Workers still need
    # ANTHROPIC_* / gh creds to function, so deny only truly worker-irrelevant secrets.
    "worker_env_deny": [],
    "notification_webhook": "",
    "auto_scale": False,
    "min_workers": 1,
    "webhook_secret": "",
    "coverage_scan": False,
    "dep_update_scan": False,
    "mutation_scan": False,  # patrol lane: mutmut survivors → test-gap tasks (ratchet)
    "mutation_targets": [],  # paths to mutate (project-relative); empty = lane no-ops
    "patrol_schedule": "",
    "patrol_auto_ideas": False,
    "research_schedule": "",
    "usage_provider": "claude",
    "minimax_api_key": "",
    "minimax_group_id": "",
    "parallel_fix_samples": 3,  # Agentless §6C: diverse samples spawned on PLATEAU (the 2nd oracle rejection, where sequential retry has demonstrably failed) or critical-path. Escapes a wrong first approach. 1=disable.
    # Reject-round circuit breaker (Round-4, fennu2333/Chorus). oracle_retry_sample_count
    # bounds the FAN-OUT WIDTH on plateau but not the TOTAL round count — a legitimately
    # persistent rejection (the task is genuinely wrong/impossible as scoped) could requeue
    # forever with no ceiling. Once a task's reject depth reaches this many rounds, stop
    # requeuing and escalate instead (blockers.md + notification_webhook), mirroring the
    # oracle-infra-outage escalation pattern. 0 = disabled (unbounded, prior behavior).
    "oracle_max_reject_rounds": 5,
    # Oracle verdict resampling (judge non-determinism — Round 3 gap B). LLM judges
    # flip on identical inputs; run each oracle pass K× and require a CLEAN MAJORITY
    # to APPROVE (safe bias: disagreement → reject). This is GENERATOR-independent —
    # distinct from parallel_fix_samples (diverse generation). Default 1 = single-shot
    # (today's behavior, no extra cost). Use an ODD value (3 recommended); when >1 it
    # applies to every oracle review, so weigh the Haiku cost (K× per pass).
    "oracle_verdict_samples": 1,
    # ── Auto retry on classified API failures (Hermes-inspired error_classifier)
    # Default OFF — opt-in to avoid surprising existing users with retry storms.
    "auto_classify_retry": False,
    "auto_classify_retry_max": 2,        # total attempts (initial + retries combined)
    "auto_classify_retry_model_fallback": {  # model downgrade when classifier asks for compression / fallback
        "opus": "sonnet",
        "sonnet": "haiku",
    },
    # Native overload failover (Round 3 gap C). When set, worker spawns pass
    # --fallback-model so a mid-turn 529/overload switches model for THAT TURN
    # ONLY (lossless, in-process) instead of exhausting retries → process exit →
    # a whole-fresh-task requeue (new session, in-session progress lost). Values:
    # "" = off; "auto" = derive per-worker from auto_classify_retry_model_fallback
    # (opus→sonnet, sonnet→haiku; haiku has no fallback); or an explicit alias/id
    # ("haiku"/"sonnet"/full id) used for every worker. Default off.
    "worker_fallback_model": "",
    "context_span_budget": 6000,  # Moatless §Gap3: max chars for TLDR span block; excess spans evicted
    "task_type_model_routing": {},  # per-task type model override e.g. {"tldr": "haiku", "fix": "sonnet"}
    # Task-class-aware resampling (Round-4, Armin Ronacher). oracle_verdict_samples
    # is a bare global with zero content-awareness, and the one task-aware resampler
    # (oracle_retry_sample_count) is reactive — only kicks in AFTER a rejection.
    # This decides resample count BEFORE the first failure, by content class:
    # e.g. {"generate": 3, "transform": 1} gives judgment-heavy tasks (new logic,
    # design decisions) more oracle scrutiny up front than mechanical ones (rename,
    # reformat, move). Empty dict = no override (oracle_verdict_samples alone decides).
    "task_class_resampling": {},
    "replay_interrupted_on_startup": False,  # re-queue interrupted tasks on server restart (opt-in)
    "execution_backend": "local",  # how workers spawn: "local" (OS subprocess+setsid). See execution_backend.py.
    # The agent runtime is the CLI that owns the loop, not the inference
    # provider. Historical ``worker_provider`` files are migrated on load.
    "agent_runtime": "claude",
    # Secret-free connection identities. Native runtime/provider configuration
    # owns endpoints and credentials; envelopes record only these identities.
    "runtime_connections": {
        "claude": "claude-default",
        "codex": "codex-default",
    },
    "connections": {
        "claude-default": {
            "agent_runtime": "claude",
            "inference_provider": "runtime-default",
            "wire_protocol": "runtime-native",
            "endpoint_identity": "claude-user-config",
            "models": {},
            "capabilities": {},
        },
        "codex-default": {
            "agent_runtime": "codex",
            "inference_provider": "runtime-default",
            "wire_protocol": "runtime-native",
            "endpoint_identity": "codex-user-config",
            "models": {},
            "capabilities": {},
        },
    },
    "codex_cheap_model": "gpt-5.6-terra",  # cheap bounded-task tier; Spark remains an explicit opt-in
    "codex_strong_model": "gpt-5.6-sol",  # low-readiness / critical-path tier
    # Usage tracking (multi-machine ccusage aggregation — see usage_tracker.py)
    "usage_poll_enabled": True,         # poll ccusage on this machine and store locally
    "usage_poll_interval_sec": 900,     # 15 min default; min 60s
    "usage_poll_since_days": 7,         # only poll/push last N days each cycle (0 = all-time)
    "usage_hub_url": "",                # if set, push to this orchestrator (e.g. http://hub:8000)
    "usage_hub_token": "",              # bearer token shared with hub for ingest auth
    "usage_ingest_token": "",           # hub-side: required Bearer token for /api/usage/ingest (empty = open)
    # Clean-room hydration distillation (Round-4 study, Salvatore Sanfilippo).
    # When True, untrusted GitHub issue/PR text is first passed through a
    # pinned, contained Haiku judge (same containment as the oracle —
    # worker_review._oracle_pass_once) that produces a compact, neutral
    # factual summary and strips anything that reads as an embedded
    # instruction to the coding agent, BEFORE it reaches the SAME
    # --dangerously-skip-permissions session that runs shell. Default False =
    # today's behavior (raw text hydrated verbatim). Fail-open: a distillation
    # error/timeout falls back to the raw text — this never blocks hydration.
    "hydration_distillation": False,
    "reactions_enabled": True,
    "reaction_configs": [
        {
            "name": "repeated_tool_failure",
            "event_type": "error",
            "event_match": r"(?:tool|command).*failed|exit code [1-9]",
            "threshold": 3,
            "window_seconds": 300,
            "action": "escalate",
            "action_payload": {"strategy": "suggest_alternative"},
        },
        {
            "name": "same_tool_repeated",
            "event_type": "tool_call",
            "event_match": r"^(?:bash|shell|exec):",
            "threshold": 5,
            "window_seconds": 180,
            "action": "warn",
            "action_payload": {"message": "Same tool called 5+ times — consider alternative approach"},
        },
        {
            "name": "loop_detected",
            "event_type": "state_change",
            "event_match": r"loop.*detected",
            "threshold": 1,
            "window_seconds": 0,
            "action": "abort",
            "action_payload": {"message": "Behavioral loop detected — aborting task"},
        },
    ],
}


def _load_settings() -> dict:
    settings = dict(_SETTINGS_DEFAULTS)
    if not _settings_file.exists():
        return settings
    try:
        loaded = json.loads(_settings_file.read_text())
    except Exception as exc:
        # Fail open to defaults, but never silently: a corrupt settings file
        # would otherwise revert every setting with no signal at all.
        logger.warning(
            "orchestrator-settings.json is unreadable (%s); using defaults", exc
        )
        return settings
    if not isinstance(loaded, dict):
        logger.warning(
            "orchestrator-settings.json is not a JSON object; using defaults"
        )
        return settings
    migrated = dict(loaded)
    legacy_runtime = migrated.pop("worker_provider", None)
    if "worker_provider" in loaded:
        from compatibility_telemetry import (
            SETTINGS_WORKER_PROVIDER,
            record_compatibility_use,
        )

        record_compatibility_use(SETTINGS_WORKER_PROVIDER)
        if "agent_runtime" not in migrated:
            migrated["agent_runtime"] = legacy_runtime
        elif migrated["agent_runtime"] != legacy_runtime:
            logger.warning(
                "agent_runtime conflicts with legacy worker_provider; "
                "keeping canonical agent_runtime"
            )
        try:
            _settings_file.write_text(json.dumps(migrated, indent=2) + "\n")
            _secure_file(_settings_file)
        except Exception as exc:
            logger.warning("could not persist canonical settings migration: %s", exc)
    # Surface unknown keys (like Codex's deny_unknown_fields): a typo'd setting
    # is otherwise merged-but-ignored, silently disabling the feature it meant
    # to configure. Warn only — keep merging so behavior is unchanged.
    unknown = sorted(k for k in migrated if k not in _SETTINGS_DEFAULTS)
    if unknown:
        logger.warning(
            "orchestrator-settings.json has unknown setting keys (ignored): %s",
            ", ".join(unknown),
        )
    settings.update(migrated)
    return settings


def _secure_file(path: Path, mode: int = 0o600) -> None:
    """Restrict a file to the owner. No-op on platforms without chmod."""
    try:
        if path.exists():
            os.chmod(path, mode)
    except (OSError, NotImplementedError):
        pass


def _secure_dir(path: Path, mode: int = 0o700) -> None:
    """Restrict a directory to the owner. No-op on platforms without chmod."""
    try:
        os.chmod(path, mode)
    except (OSError, NotImplementedError):
        pass


def _save_settings(s: dict) -> None:
    _settings_file.parent.mkdir(parents=True, exist_ok=True)
    canonical = {key: value for key, value in s.items() if key != "worker_provider"}
    _settings_file.write_text(json.dumps(canonical, indent=2))
    # settings.json holds secrets (webhook_secret, hub_token, minimax_api_key) —
    # tighten to owner-only after every write.
    _secure_file(_settings_file)


GLOBAL_SETTINGS: dict = _load_settings()

# ─── Project Scanner ──────────────────────────────────────────────────────────


def scan_projects(base: Path | None = None, max_depth: int = 3) -> list[dict]:
    """Find git repos under base dir (default: home)."""
    if base is None:
        base = Path.home()
    results = []

    def _scan(p: Path, depth: int) -> None:
        if depth > max_depth or not p.is_dir():
            return
        try:
            if (p / ".git").exists():
                results.append({"name": p.name, "path": str(p)})
                return  # don't recurse into git repos
            for child in sorted(p.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    _scan(child, depth + 1)
        except PermissionError:
            pass

    _scan(base, 0)
    return results[:50]  # cap at 50

# ─── Dependency Check ─────────────────────────────────────────────────────────


def _deps_met(task: dict, done_ids: set) -> bool:
    """Return True if all depends_on task IDs are done."""
    deps = task.get("depends_on") or []
    if isinstance(deps, str):
        try:
            deps = json.loads(deps)
        except Exception:
            deps = []
    return all(dep_id in done_ids for dep_id in deps)


def _detect_dep_cycle(tasks: list[dict]) -> list[str] | None:
    """Detect circular dependencies in a task list using DFS.

    Returns a list of task IDs forming the cycle, or None if no cycle found.
    Used before importing tasks or starting a swarm batch to prevent deadlock.
    """
    # Build adjacency: task_id → set of dependency IDs (only within this task set)
    task_ids = {t["id"] for t in tasks if t.get("id")}
    adj: dict[str, set[str]] = {}
    for task in tasks:
        tid = task.get("id")
        if not tid:
            continue
        deps = task.get("depends_on") or []
        if isinstance(deps, str):
            try:
                deps = json.loads(deps)
            except Exception:
                deps = []
        # Only consider deps that exist in the same batch (intra-batch cycles)
        adj[tid] = {d for d in deps if d in task_ids}

    # DFS cycle detection (white/grey/black coloring)
    WHITE, GREY, BLACK = 0, 1, 2
    color = {tid: WHITE for tid in adj}
    path: list[str] = []

    def dfs(node: str) -> list[str] | None:
        color[node] = GREY
        path.append(node)
        for neighbor in adj.get(node, set()):
            if color.get(neighbor) == GREY:
                # Cycle found — extract the cycle portion of path
                cycle_start = path.index(neighbor)
                return path[cycle_start:]
            if color.get(neighbor) == WHITE:
                result = dfs(neighbor)
                if result is not None:
                    return result
        path.pop()
        color[node] = BLACK
        return None

    for tid in list(adj.keys()):
        if color[tid] == WHITE:
            cycle = dfs(tid)
            if cycle is not None:
                return cycle
    return None

# ─── Token/Cost Tracking ─────────────────────────────────────────────────────

_TOKEN_PATTERNS = [
    # Claude CLI: "Total tokens: input=1234, output=5678"
    re.compile(r"[Tt]otal\s+tokens?.*?input\s*=\s*(\d+).*?output\s*=\s*(\d+)"),
    # "Input tokens: 1234" / "Output tokens: 5678" on separate lines
    re.compile(r"[Ii]nput\s+tokens?\s*[:=]\s*(\d+)"),
    re.compile(r"[Oo]utput\s+tokens?\s*[:=]\s*(\d+)"),
    # Compact: "tokens: 1234/5678" or "1234 in / 5678 out"
    re.compile(r"(\d+)\s*(?:in|input)\s*/\s*(\d+)\s*(?:out|output)"),
]


def _parse_token_usage(log_path: Path) -> tuple[int, int]:
    """Scan log file bottom-up for token usage. Returns (input_tokens, output_tokens)."""
    try:
        text = log_path.read_text(errors="replace")
    except Exception:
        return 0, 0
    lines = text.splitlines()
    input_t, output_t = 0, 0
    # Scan from bottom (most likely near end)
    for line in reversed(lines[-200:]):
        m = _TOKEN_PATTERNS[0].search(line)
        if m:
            return int(m.group(1)), int(m.group(2))
        m3 = _TOKEN_PATTERNS[3].search(line)
        if m3:
            return int(m3.group(1)), int(m3.group(2))
    # Fallback: separate input/output lines
    for line in reversed(lines[-200:]):
        if not input_t:
            m1 = _TOKEN_PATTERNS[1].search(line)
            if m1:
                input_t = int(m1.group(1))
        if not output_t:
            m2 = _TOKEN_PATTERNS[2].search(line)
            if m2:
                output_t = int(m2.group(1))
        if input_t and output_t:
            break
    return input_t, output_t


# USD per million tokens, (input, output). Anthropic first-party API rates as
# published 2026-08-29. Bedrock and Vertex are partner-operated and priced
# separately; a gateway model id that is not listed falls back to SONNET_RATE.
#
# Only ever used when the agent does not report its own spend. `claude -p
# --output-format json` returns `total_cost_usd` and a per-model `modelUsage`
# breakdown, which is authoritative and covers cache reads and server tools
# this table cannot see — prefer it and treat this as the degraded path.
SONNET_RATE = (3.0, 15.0)
_MODEL_RATES: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-sonnet-5": SONNET_RATE,
    "claude-sonnet-4-6": SONNET_RATE,
    "claude-sonnet-4-5": SONNET_RATE,
    "claude-haiku-4-5": (1.0, 5.0),
}


def _model_rate(model: str | None) -> tuple[float, float]:
    """Resolve a model id (alias, dated snapshot, or gateway id) to its rate."""
    if not model:
        return SONNET_RATE
    resolved = _MODEL_ALIASES.get(model, model)
    if resolved in _MODEL_RATES:
        return _MODEL_RATES[resolved]
    # Dated snapshots (claude-haiku-4-5-20251001) share their base model's rate.
    for known, rate in _MODEL_RATES.items():
        if resolved.startswith(known + "-"):
            return rate
    return SONNET_RATE


def _estimate_cost(input_tokens: int, output_tokens: int, model: str | None = None) -> float:
    """Estimate USD cost for a model.

    Every model was billed at Sonnet's rate until 2026-08-29, so an Opus task
    was reported at 60% of its real price and a Haiku task at 300% of it — on
    the same figure `run_budget` enforces against and `routing_break_even`
    divides by. The model argument defaults to Sonnet so existing two-argument
    calls keep their old behaviour rather than silently changing price.
    """
    rate_in, rate_out = _model_rate(model)
    return round(
        input_tokens * rate_in / 1_000_000 + output_tokens * rate_out / 1_000_000, 4
    )

def resolve_worker_usage(
    agent_result: Any, log_path: Path | None, model: str | None
) -> tuple[int, int, float]:
    """Tokens and USD for a finished worker, best source first.

    `agent_result` is an agent_output.AgentResult when the run emitted
    structured output — that is the agent's own accounting, so it already
    includes cache reads and server-tool use that no local estimate can see.
    Duck-typed rather than imported to keep this module free of project
    imports.

    Falls back to scraping the prose only when there is no result event
    (text-mode output, a crash before the run finished). That path returns
    (0, 0, 0.0) in practice, which is precisely why the structured path
    exists — see agent_output's module docstring.
    """
    if agent_result is not None:
        cost = getattr(agent_result, "total_cost_usd", None)
        tokens_in = getattr(agent_result, "input_tokens", 0)
        tokens_out = getattr(agent_result, "output_tokens", 0)
        if cost is None:
            cost = _estimate_cost(tokens_in, tokens_out, model)
        return tokens_in, tokens_out, float(cost)
    if log_path is None:
        return 0, 0, 0.0
    tokens_in, tokens_out = _parse_token_usage(log_path)
    return tokens_in, tokens_out, _estimate_cost(tokens_in, tokens_out, model)


# ─── Session Recovery ─────────────────────────────────────────────────────────


def _pgid_alive_and_claude_like(pgid: int) -> bool:
    """Best-effort check that `pgid` is still a live claude-worker process
    before it gets killed. PIDs are reused by the OS, so after a restart a
    remembered pgid could — in the worst case — belong to a totally unrelated
    process by the time recovery runs; killing on cmdline content is a cheap
    extra check, not a guarantee.

    Two readers, because the orchestrator runs on both: /proc where it exists,
    and `ps` where it does not. The /proc-only version returned True on macOS
    for EVERY pgid, which meant the PID-reuse net was simply absent on the
    machine most of this development happens on — recovery there would killpg
    a recycled pgid belonging to someone else's process. CI is Linux-only, so
    it could never see that; the macOS test failed for a year's worth of
    commits and read as an environment quirk.

    Returns True (safe to kill) whenever the check genuinely cannot be
    performed, so recovery still reaps real orphans rather than silently
    never reaping. "Already gone" also returns True — killpg's own
    ProcessLookupError handles that case harmlessly.
    """
    cmdline_path = Path(f"/proc/{pgid}/cmdline")
    try:
        if cmdline_path.exists():
            cmdline = cmdline_path.read_bytes().replace(b"\x00", b" ").decode(errors="replace")
            return "claude" in cmdline
    except Exception:
        return True  # unreadable /proc — proceed rather than silently never-reap

    # No /proc: macOS/BSD. `ps -p <pgid> -o command=` prints the group leader's
    # argv (empty with rc=1 when the pid is gone), which is the same question
    # /proc/<pid>/cmdline answers. Bounded, because a hung ps must not wedge
    # startup recovery.
    try:
        proc = subprocess.run(
            ["ps", "-p", str(int(pgid)), "-o", "command="],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return True  # no usable ps — same fail-open contract as above
    command = (proc.stdout or "").strip()
    if not command:
        return True  # already exited, or ps could not see it
    return "claude" in command


async def _recover_orphaned_tasks(task_queue: Any) -> int:
    """Mark running/starting tasks as interrupted after server restart.

    A worker's OS process group (setsid) survives the orchestrator's own exit
    — the in-memory Worker object is gone, but the subprocess keeps running.
    Guillermo Rauch (open-agents): check-and-kill the persisted pgid BEFORE
    marking the task interrupted, so a fresh retry can never race a still-alive
    process into the same branch/worktree (the old bug: this only relabeled
    DB rows and left the real process running). Fail-open throughout — a
    machine where killpg isn't permitted must not block recovery.
    """
    try:
        await task_queue._ensure_db()
        async with aiosqlite.connect(str(task_queue._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, pgid FROM tasks WHERE status IN ('running', 'starting')"
            ) as cur:
                rows = [dict(r) for r in await cur.fetchall()]
            for row in rows:
                pgid = row.get("pgid")
                if not pgid:
                    continue
                if not _pgid_alive_and_claude_like(pgid):
                    logger.warning(
                        "_recover_orphaned_tasks: pgid %d (task %s) no longer looks like "
                        "a claude worker — skipping kill (likely PID reuse)", pgid, row["id"],
                    )
                    continue
                try:
                    os.killpg(pgid, signal.SIGTERM)
                    logger.warning(
                        "_recover_orphaned_tasks: killed orphaned process group %d (task %s)",
                        pgid, row["id"],
                    )
                except ProcessLookupError:
                    pass  # already dead — nothing to reap
                except Exception as e:
                    logger.warning(
                        "_recover_orphaned_tasks: killpg(%d) failed for task %s: %s",
                        pgid, row["id"], e,
                    )
            cursor = await db.execute(
                "UPDATE tasks SET status = 'interrupted' WHERE status IN ('running', 'starting')"
            )
            count = cursor.rowcount
            await db.commit()
            return count
    except Exception as e:
        logger.warning("_recover_orphaned_tasks failed (fail-open): %s", e)
        return 0

async def _replay_interrupted_tasks(task_queue: Any, claude_dir: Path) -> list[tuple[str, str]]:
    """Build resume descriptions for interrupted tasks with prior event context.

    Reads events.jsonl to find workers that started but never completed, then
    reads per-worker JSONL for the last 3 state changes as resume context.
    Returns list of (task_id, resume_description) for the caller to re-queue.
    Only runs when replay_interrupted_on_startup=True.
    """
    if not GLOBAL_SETTINGS.get("replay_interrupted_on_startup", False):
        return []
    try:
        await task_queue._ensure_db()
        async with aiosqlite.connect(str(task_queue._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, description, worker_id FROM tasks WHERE status = 'interrupted'"
            ) as cur:
                interrupted = [dict(r) for r in await cur.fetchall()]
        if not interrupted:
            return []

        # Load global events.jsonl to find which worker_ids actually started
        started_workers: set[str] = set()
        done_workers: set[str] = set()
        global_bus = claude_dir / "events.jsonl"
        if global_bus.exists():
            try:
                with open(global_bus) as f:
                    for line in f:
                        try:
                            obj = json.loads(line.strip())
                        except Exception:
                            continue
                        wid = obj.get("worker_id", "")
                        state = ""
                        try:
                            state = json.loads(obj.get("data", "{}")).get("state", "")
                        except Exception:
                            pass
                        if state == "started":
                            started_workers.add(wid)
                        elif state in ("done", "failed"):
                            done_workers.add(wid)
            except Exception:
                pass

        results: list[tuple[str, str]] = []
        for task in interrupted:
            worker_id = task.get("worker_id") or ""
            # Skip if worker never started or completed cleanly
            if worker_id and worker_id in done_workers:
                continue

            # Read per-worker JSONL for last 3 state_change events
            prior_context = ""
            log_dir = claude_dir / "orchestrator-logs"
            worker_jsonl = log_dir / f"events-{worker_id}.jsonl" if worker_id else None
            if worker_jsonl and worker_jsonl.exists():
                state_events: list[str] = []
                try:
                    with open(worker_jsonl) as f:
                        for line in f:
                            try:
                                obj = json.loads(line.strip())
                            except Exception:
                                continue
                            if obj.get("event_type") == "state_change":
                                try:
                                    content = json.loads(obj.get("content", "{}"))
                                    state_events.append(
                                        f"  - {content.get('state', '?')}: {content.get('reason', '')}"
                                    )
                                except Exception:
                                    pass
                    if state_events:
                        prior_context = (
                            "\n\n---\n**Prior execution context (last events before interruption):**\n"
                            + "\n".join(state_events[-3:])
                            + "\nCheck git log for any partial commits before continuing."
                        )
                except Exception:
                    pass

            resume_desc = (
                f"{task['description']}\n\n"
                f"**Note:** This task was previously interrupted mid-execution and is being resumed."
                f"{prior_context}"
            )
            results.append((task["id"], resume_desc))
        return results
    except Exception as e:
        logger.warning("_replay_interrupted_tasks failed (fail-open): %s", e)
        return []

# ─── Notifications ────────────────────────────────────────────────────────────


async def _fire_notification(event: str, session: Any, extra: dict | None = None) -> None:
    """Fire webhook notification. Fail-open (no deps, follows _gh_update_issue_status pattern)."""
    webhook = GLOBAL_SETTINGS.get("notification_webhook", "")
    if not webhook:
        return
    try:
        tasks = await session.task_queue.list()
        done = sum(1 for t in tasks if t["status"] == "done")
        failed = sum(1 for t in tasks if t["status"] == "failed")
        failed_list = [t["description"][:120] for t in tasks if t["status"] == "failed"]
        payload = json.dumps({
            "event": event,
            "session_id": session.session_id,
            "project_name": session.name,
            "project_path": str(session.project_dir),
            "total": len(tasks), "done": done, "failed": failed,
            "failed_tasks": failed_list[:10],
            **(extra or {}),
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


# ─── Tool Subsets per Task Type ────────────────────────────────────────────────
# Stripe Blueprint pattern: different agent types get different tool subsets.
# Claude Code supports --allowed-tools and --disallowed-tools to constrain tools.

_TOOL_SUBSETS: dict[str, tuple[list[str], list[str]]] = {
    # review: read-only — no editing, no file creation
    "review": (
        ["Read", "Grep", "Glob", "Bash", "WebSearch", "WebFetch", "NotebookRead"],
        ["Edit", "Write", "NotebookEdit", "MultiEdit"],
    ),
    # fix: same as implement but focused. mcp__playwright allows browser
    # end-to-end verification when the Playwright MCP is wired in (no-op
    # otherwise — the tool simply does not exist). See setup-browser-verify.sh.
    "fix": (
        ["Read", "Edit", "Write", "Bash", "Grep", "Glob", "mcp__playwright"],
        [],
    ),
    # implement: full tools (default — no restriction needed)
    "implement": ([], []),
    # test: allows test file creation but not broad refactoring. mcp__playwright
    # lets a test task drive a real browser for end-to-end verification.
    "test": (
        ["Read", "Edit", "Write", "Bash", "Grep", "Glob", "NotebookEdit", "mcp__playwright"],
        [],
    ),
}


def _parse_task_type(description: str) -> str | None:
    """Infer task type from description text.

    Looks for patterns like:
    - ===TASK=== metadata: "type: review"
    - Keywords: "review", "fix", "implement", "test"
    Returns None for implement (default = full tools).
    """
    desc_lower = description.lower()
    meta_match = re.search(r"type:\s*(\w+)", desc_lower)
    if meta_match:
        t = meta_match.group(1)
        if t in _TOOL_SUBSETS:
            return t

    if any(k in desc_lower for k in ["review", "code review", "static analysis", "audit"]):
        return "review"
    if any(k in desc_lower for k in ["fix", "bug", "patch", "hotfix"]):
        return "fix"
    if any(k in desc_lower for k in ["test", "spec", "e2e"]):
        return "test"
    if any(k in desc_lower for k in ["tldr", "summarize", "summary"]):
        return "tldr"
    return None  # default: implement (full tools)


# Mechanical/low-judgment vs. creative/judgment-heavy — deliberately coarse
# (2 buckets), the same granularity task_class_resampling routes on.
_TASK_CLASS_TRANSFORM_KEYWORDS = (
    "rename", "reformat", "reorganize", "move ", "extract ", "cleanup",
    "lint", "typo", "formatting", "dedupe", "de-duplicate",
)
_TASK_CLASS_GENERATE_KEYWORDS = (
    "implement", "design", "add feature", "create", "build", "new endpoint",
    "new feature",
)


def _parse_task_class(description: str) -> str | None:
    """Classify a task as 'transform' (mechanical, low-judgment) or 'generate'
    (creative/judgment-heavy) for content-aware oracle resampling. None when
    ambiguous — the caller falls back to the base oracle_verdict_samples."""
    desc_lower = description.lower()
    meta_match = re.search(r"class:\s*(\w+)", desc_lower)
    if meta_match and meta_match.group(1) in ("transform", "generate"):
        return meta_match.group(1)
    if any(k in desc_lower for k in _TASK_CLASS_TRANSFORM_KEYWORDS):
        return "transform"
    if any(k in desc_lower for k in _TASK_CLASS_GENERATE_KEYWORDS):
        return "generate"
    return None


def _infer_commit_type(description: str) -> str:
    """Infer a conventional-commit type from a task description.

    The worker previously hardcoded `feat:` for every auto-commit. That
    (a) mislabels fixes/refactors/tests/docs and (b) silently zeroes the
    agent fix-rate metric — `commit-archeology.sh` keys `fix` off `/^fix/`,
    so an agent fix committed as `feat:` never counts (the `agent fix-rate
    0% (0/N)` you see in the statusline). Order matters: fix before feat.
    Returns a bare conventional type; always falls back to `feat`.
    """
    d = description.lower()
    # Honor an explicit conventional prefix already in the task text.
    m = re.search(r"\b(fix|feat|refactor|test|docs|perf|chore)\b\s*[:(]", d)
    if m:
        return m.group(1)

    # Word-boundary match so e.g. "patch" doesn't fire inside "dispatch".
    def _has(words: list[str]) -> bool:
        return re.search(r"\b(?:" + "|".join(words) + r")\b", d) is not None

    # Order matters: fix outranks feat so the fix-rate metric counts it.
    if _has(["fix", "bug", "bugfix", "hotfix", "patch", "regression", "broken", "crash"]):
        return "fix"
    if _has(["refactor", "restructure", "cleanup", "clean up", "extract", "rename"]):
        return "refactor"
    if _has(["perf", "performance", "optimize", "optimise", "speed up", "latency"]):
        return "perf"
    if _has(["document", "documentation", "readme", "docstring", "docs", "comment"]):
        return "docs"
    if _has(["bump", "dependency", "dependencies", "chore", "lint"]):
        return "chore"
    if _has(["test", "tests", "coverage", "spec", "e2e", "pytest"]):
        return "test"
    return "feat"


def _build_tool_flags(task_type: str | None) -> str:
    """Build --allowed-tools or --disallowed-tools flags for claude -p.

    Returns empty string if task_type is None (default full tools).
    """
    if not task_type or task_type not in _TOOL_SUBSETS:
        return ""
    allowed, disallowed = _TOOL_SUBSETS[task_type]
    if allowed:
        return f' --allowed-tools "{",".join(allowed)}"'
    elif disallowed:
        return f' --disallowed-tools "{",".join(disallowed)}"'
    return ""


def _resolve_fallback_model(requested_model: str) -> str | None:
    """Resolve the native --fallback-model target for a worker spawn (Round 3 gap C).

    Reads the `worker_fallback_model` setting:
      "" (default) → None (feature off)
      "auto"       → per-worker downgrade via auto_classify_retry_model_fallback
                     (opus→sonnet, sonnet→haiku; haiku has no fallback → None)
      else         → an explicit alias/id used for every worker
    Aliases are resolved to full model ids; unknown values pass through unchanged.
    """
    setting = str(GLOBAL_SETTINGS.get("worker_fallback_model", "") or "").strip()
    if not setting:
        return None
    if setting.lower() != "auto":
        candidate = _MODEL_ALIASES.get(setting, setting)
    else:
        # auto: reduce the requested model to its short alias, then map-derive.
        alias = requested_model
        if alias not in _MODEL_ALIASES:  # a full id → recover its short alias
            for a, full in _MODEL_ALIASES.items():
                if full == requested_model:
                    alias = a
                    break
        fb_alias = (GLOBAL_SETTINGS.get("auto_classify_retry_model_fallback") or {}).get(alias)
        if not fb_alias:
            return None
        candidate = _MODEL_ALIASES.get(fb_alias, fb_alias)
    # Model ids are provider-scoped and opaque. The command adapter validates
    # control characters and shell-quotes this value before execution.
    return candidate or None


def _fallback_flag(requested_model: str) -> str:
    """--fallback-model flag string for a worker spawn, or '' when disabled/none."""
    fb = _resolve_fallback_model(requested_model)
    if not fb:
        return ""
    try:
        validated = validate_model_id(fb, allow_none=False)
    except InvalidExecutionConfig:
        return ""
    assert validated is not None
    return f" --fallback-model {shlex.quote(validated)}"


# ─── Task Schema / JSON Envelope (Multi-agent Gap 3) ─────────────────────────


def _format_task_schema_block(task_schema: dict) -> str:
    """Format a parsed task schema into a markdown block for injection into task files."""
    if not task_schema:
        return ""
    lines = ["\n\n---\n\n## Task Contracts (Multi-agent §Gap3)"]
    if criteria := task_schema.get("acceptance_criteria"):
        lines.append("**Acceptance Criteria** (oracle will check these):")
        for c in criteria:
            lines.append(f"- {c}")
    if inputs := task_schema.get("input_files"):
        lines.append("\n**Expected Input Files:**")
        for f in inputs:
            lines.append(f"- `{f}`")
    if provides := task_schema.get("provides"):
        lines.append("\n**This task provides:**")
        for p in provides:
            lines.append(f"- {p}")
    if requires := task_schema.get("requires"):
        lines.append("\n**This task requires:**")
        for r in requires:
            lines.append(f"- {r}")
    return "\n".join(lines)


def _parse_task_schema(description: str) -> dict:
    """Extract optional JSON schema envelope from a task description.

    Multi-agent Gap 3: structured input/output contracts for swarm tasks.
    Workers that include a JSON block specify explicit acceptance criteria,
    required input files, and expected output artifacts for the oracle to check.

    Format (embedded JSON block in description):
    ```json
    {
      "acceptance_criteria": ["All auth tests pass", "No imports added"],
      "input_files": ["src/auth.py"],
      "provides": ["AuthService class"],
      "requires": ["UserModel from users.py"]
    }
    ```

    Returns parsed dict or {} if no valid JSON block found.
    """
    # Look for ```json ... ``` or raw JSON object embedded in description
    m = re.search(r'```json\s*(\{.*?\})\s*```', description, re.DOTALL)
    if not m:
        # Try inline JSON object
        m = re.search(r'\{[^{}]*"acceptance_criteria"[^{}]*\}', description, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1) if m.lastindex else m.group())
        if not isinstance(data, dict):
            return {}
        # Normalize fields — only keep known keys
        result: dict = {}
        for key in ("acceptance_criteria", "input_files", "provides", "requires"):
            if key in data and isinstance(data[key], list):
                result[key] = [str(v)[:200] for v in data[key][:10]]
        return result
    except (json.JSONDecodeError, AttributeError):
        return {}
