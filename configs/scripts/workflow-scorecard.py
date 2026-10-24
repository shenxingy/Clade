#!/usr/bin/env python3
"""workflow-scorecard.py — measure how well a multi-agent run used its parallelism.

Why this exists
---------------
Clade already mines outcomes. ``/retro`` reads git history, ``session-scorecard.sh``
reads the corrections log, ``commit-archeology.sh`` reads commits. Nothing read
the *process*: every ``Workflow`` run writes a full per-agent transcript under

    ~/.claude*/projects/<slug>/<session>/subagents/workflows/wf_*/agent-*.jsonl

and as of 2026-09-02 not one line of code in this repository opened those files.
80 MB of them existed for this project alone, across 56 projects, and the only
way anyone learned whether a fan-out was efficient was to notice it felt slow.
Beside each transcript sit ``agent-*.meta.json`` (the label and phase the script
gave the agent) and the run's ``journal.jsonl`` (started / result / failed).

What it measures
----------------
A fan-out costs a slot for its whole makespan whether or not the slot is doing
anything, so "how many agents" is not the interesting number. These are:

``peak``          the most agents ever running at once — the parallelism
                  actually reached, which is usually below the configured cap.
``mean``          average concurrency across the run, from a timeline sweep.
``util_vs_peak``  mean/peak. The denominator is the peak REACHED, not the cap
                  the script asked for, so a run that never filled its slots can
                  still score high. Called ``util`` until 2026-10-23, which read
                  as "share of the cap in use".
``serial``        share of the makespan one agent ran alone having overlapped no
                  other agent at all: a deliberate one-agent stage (scout, build,
                  fix, synth, a sequential loop step). pipeline() cannot shorten
                  it; only a shorter stage, or one overlapped with others, can.
``outlived``      share of the makespan one agent ran alone after starting
                  alongside siblings that all finished: the straggler tax.
                  Everyone else has finished and paid, and the run cannot end.
                  This is what pipeline() or finer units fix.
``idle``          share of the makespan with no agent running: lead-side gaps.
``straggler``     slowest/median agent duration.

serial and outlived were one number, ``tail1``, until 2026-10-23. The merged
number called a lone build stage a straggler and prescribed pipeline() for it.
The first run of this script, on the session that wrote it, found a 90-agent
``pipeline()`` at 77% utilisation with a 0% tail despite a 6.7x straggler, and a
10-agent ``parallel()`` barrier at 55% with 19% of its makespan on one agent —
both read with the merged metric, from transcripts since purged.

Tokens and cost
---------------
Claude Code writes one API response as one transcript record per content block
(thinking, text, tool_use), and every record repeats the request's usage. So
usage is keyed by ``message.id``: input fields once, output as the max over the
id's records (the last one is final), and ``turns`` is the number of distinct
ids. Until 2026-10-23 this summed per record and counted every call about 1.9
times. Input, cache read, cache write and output are reported separately
because they are priced differently — the old single ``in_tokens`` added cache
reads at full input weight. ``cost_usd`` is a list-price equivalent from the
rate table below; a model the table does not carry makes the cost null.

Reading the output
------------------
High ``outlived`` means the shape is wrong: a barrier where a pipeline would do,
or units so coarse that one of them dominates. High ``serial`` is a different
problem with a different fix: the one-agent stage is the critical path, so
shorten it or overlap it. High ``straggler`` with low ``outlived`` is fine —
that is a pipeline absorbing variance, which is what it is for. Low
``util_vs_peak`` means the run never had enough queued work to fill the slots
it did reach. Every verdict that holds is printed, worst first. Under a
straggler verdict the table names the agent the outlived time was credited to,
which is often not the slowest agent: that one is frequently the serial stage.

The other two modes
-------------------
``--polls`` counts repeated status reads per background job in a lead session:
the polling rule, with a number attached.

``--codex-children`` counts what a Codex worker delegated. Everything above
reads Claude Code's own transcripts, and a Codex worker leaves no equivalent:
the spawn is absent from ``codex exec --json`` — only the ``wait`` item shows,
with an empty ``receiver_thread_ids`` — so comparing a Claude worker's
wall-clock against a Codex worker's compared a fan-out against an unknown. The
spawns are persisted in ``~/.codex/state_5.sqlite``; ``codex_children.py``
beside this file reads them read-only.

Stdlib only, on purpose: the syntax-check CI job installs no dependencies.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import statistics
import sys
from pathlib import Path
from typing import Any

from codex_children import (
    CodexStateUnavailable,
    print_codex_children,
    scan_codex_children,
    self_test_codex_children,
)

# ─── Rates ──────────────────────────────────────────────────────────────────
# USD per million tokens: (input, cache read, 5-minute cache write, 1-hour cache
# write, output). Source: the model catalog baked into the Claude Code 2.1.283
# binary (its `pricing_tiers` and each model's `pricing` key), read 2026-10-23.
# It agrees with the claude-api skill bundled with that version (model table
# cached 2026-06-24; the cache multipliers are in its shared/prompt-caching.md).
# These are list prices, so a cost here is a list-price EQUIVALENT: an account on
# a subscription pays in quota, not dollars. Keyed by model id; a dated snapshot
# (`claude-haiku-4-5-20251001`) loses its date before the lookup. A model this
# table does not carry is priced as null, never as its nearest neighbour, and so
# is fast mode (`usage.speed == "fast"`), which bills at a different rate.
# Refresh the table when a model launches.
_RATES: dict[str, tuple[float, float, float, float, float]] = {
    "claude-fable-5-1": (10.0, 0.25, 12.5, 20.0, 50.0),
    "claude-mythos-5-1": (10.0, 0.25, 12.5, 20.0, 50.0),
    "claude-fable-5": (10.0, 1.0, 12.5, 20.0, 50.0),
    "claude-mythos-5": (10.0, 1.0, 12.5, 20.0, 50.0),
    "claude-opus-5-5": (4.0, 0.2, 5.0, 8.0, 20.0),
    "claude-opus-5": (5.0, 0.5, 6.25, 10.0, 25.0),
    "claude-opus-4-8": (5.0, 0.5, 6.25, 10.0, 25.0),
    "claude-opus-4-7": (5.0, 0.5, 6.25, 10.0, 25.0),
    "claude-opus-4-6": (5.0, 0.5, 6.25, 10.0, 25.0),
    "claude-sonnet-5": (2.0, 0.2, 2.5, 4.0, 10.0),
    "claude-sonnet-4-6": (3.0, 0.3, 3.75, 6.0, 15.0),
    "claude-haiku-4-5": (1.0, 0.1, 1.25, 2.0, 5.0),
}
_SNAPSHOT_DATE = re.compile(r"-\d{8}$")

# Claude Code writes this as the model of a message it made itself (a usage-limit
# notice, an interrupted turn). It is not an API call and carries no tokens.
_SYNTHETIC = "<synthetic>"

# A cache miss, as the 2026-10-22 audit defined it: a call after the first whose
# context is over 20k tokens and more than half re-written. Subagents get the
# 5-minute cache TTL only, so a miss that follows a gap longer than that is the
# cache expiring under a long tool call, not a prompt that changed.
_CACHE_TTL_S = 300
_MISS_MIN_CONTEXT = 20_000
_MISS_SHARE = 0.5


def _rates_for(model: str | None, speed: str | None) -> tuple[float, ...] | None:
    if not model or speed not in (None, "standard"):
        return None
    return _RATES.get(_SNAPSHOT_DATE.sub("", model.replace("[1m]", "")))


# ─── Transcripts ────────────────────────────────────────────────────────────


def _parse_ts(raw: str) -> datetime.datetime | None:
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _first_text(message: object) -> str:
    """First prose out of a transcript message, whatever shape it is in."""

    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    return block["text"]
    return ""


def _identity(prompt: str) -> str:
    """A short tag for an agent, derived from its brief.

    The fallback only. The ``label`` and ``phase`` a workflow script passes are
    in ``agent-*.meta.json`` and ``journal.jsonl``, and ``scan_workflow`` reads
    those first; this reads the brief for an agent that has neither. Workflow
    prompts in this repository put the distinguishing text on a line starting
    with a heading-ish marker, so prefer one of those; otherwise fall back to
    the first non-empty line.
    """

    lines = [ln.strip() for ln in prompt.splitlines() if ln.strip()]

    # A brief that names plan files is describing itself better than any prose
    # line in it does: those identifiers are what the run was actually about.
    plans = re.findall(r"/([A-Z]\d{2}|R\d{2})\.md\b", prompt)
    if plans:
        seen: list[str] = []
        for item in plans:
            if item not in seen:
                seen.append(item)
        return "plans " + ",".join(seen[:6])

    for line in lines:
        marker = re.match(r"^(?:DIMENSION|LANE)\b[: ]*(.*)", line)
        if marker:
            tail = marker.group(1).strip(" :—-")
            if tail:
                return tail[:58]

    # Otherwise the first line that says something, skipping boilerplate the
    # briefs in this repository all share.
    boilerplate = ("You are ", "READ FIRST", "STRICTLY READ-ONLY", "Do NOT", "Read ")
    for line in lines:
        if not line.startswith(boilerplate) and len(line) > 12:
            return line[:58]
    return (lines[0] if lines else "(empty brief)")[:58]


class Call:
    """One API response, however many transcript records it was written as."""

    __slots__ = ("model", "speed", "input", "cache_read", "write_5m", "write_1h", "output", "first", "last")

    def __init__(self, message: dict, usage: dict, stamp: datetime.datetime | None) -> None:
        self.model = message.get("model")
        self.speed = usage.get("speed")
        self.input = usage.get("input_tokens") or 0
        self.cache_read = usage.get("cache_read_input_tokens") or 0
        split = usage.get("cache_creation")
        self.write_1h = (split.get("ephemeral_1h_input_tokens") or 0) if isinstance(split, dict) else 0
        # Without the split every write is a 5-minute write: the default TTL,
        # and the only one subagents get.
        self.write_5m = (usage.get("cache_creation_input_tokens") or 0) - self.write_1h
        self.output = 0
        self.first = stamp
        self.last = stamp

    @property
    def cache_create(self) -> int:
        return self.write_5m + self.write_1h

    @property
    def context(self) -> int:
        return self.input + self.cache_read + self.cache_create

    def cost(self) -> float | None:
        if not (self.context or self.output):
            return 0.0
        rates = _rates_for(self.model, self.speed)
        if rates is None:
            return None  # unpriced, never a guess
        price_in, price_read, price_5m, price_1h, price_out = rates
        return (
            self.input * price_in
            + self.cache_read * price_read
            + self.write_5m * price_5m
            + self.write_1h * price_1h
            + self.output * price_out
        ) / 1e6


def _most_common(counts: dict[str, int]) -> str | None:
    return max(counts, key=lambda key: (counts[key], key)) if counts else None


class AgentRun:
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self.start: datetime.datetime | None = None
        self.end: datetime.datetime | None = None
        self.calls: dict[str, Call] = {}
        self.synthetic: set[str] = set()
        self.efforts: dict[str, int] = {}
        self.tag = ""
        self.label: str | None = None
        self.phase: str | None = None
        self.outcome = "unknown"
        self.result_chars: int | None = None

    @property
    def seconds(self) -> float:
        if not self.start or not self.end:
            return 0.0
        return (self.end - self.start).total_seconds()

    @property
    def name(self) -> str:
        return self.label or self.tag or self.agent_id[:12]

    @property
    def turns(self) -> int:
        return len(self.calls)

    def total(self, field: str) -> int:
        return sum(getattr(call, field) for call in self.calls.values())

    @property
    def cost(self) -> float | None:
        costs = [call.cost() for call in self.calls.values()]
        return None if any(cost is None for cost in costs) else sum(c for c in costs if c is not None)

    @property
    def unpriced_models(self) -> set[str]:
        return {
            f"{call.model} ({call.speed})" if call.speed not in (None, "standard") else str(call.model)
            for call in self.calls.values()
            if call.cost() is None
        }

    @property
    def models(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for call in self.calls.values():
            key = str(call.model)
            counts[key] = counts.get(key, 0) + 1
        return counts

    @property
    def first_context(self) -> int | None:
        """Context of the agent's first API call: the fixed cost every call re-reads."""
        for call in self.calls.values():
            return call.context
        return None

    def long_gap_miss_writes(self) -> int:
        """Cache writes on calls that missed the cache after a gap longer than its TTL."""
        written = 0
        previous: Call | None = None
        for call in self.calls.values():
            if previous is not None and call.first and previous.last:
                gap = (call.first - previous.last).total_seconds()
                context = call.context
                if (
                    gap > _CACHE_TTL_S
                    and context > _MISS_MIN_CONTEXT
                    and call.cache_create > _MISS_SHARE * context
                ):
                    written += call.cache_create
            previous = call
        return written


def read_agent(path: Path) -> AgentRun:
    run = AgentRun(path.stem.replace("agent-", ""))
    with path.open(encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle):
            try:
                record = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(record, dict):
                continue
            stamp = _parse_ts(record.get("timestamp", ""))
            if stamp:
                run.start = stamp if run.start is None else min(run.start, stamp)
                run.end = stamp if run.end is None else max(run.end, stamp)
            message = record.get("message") or {}
            if record.get("type") == "user" and not run.tag:
                run.tag = _identity(_first_text(message))
            if record.get("type") != "assistant" or not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            if message.get("model") == _SYNTHETIC:
                run.synthetic.add(str(message.get("id") or number))
                continue
            # One API response is written as one record per content block, and
            # each record repeats the request's usage. Summing per record is the
            # ~1.9x double count; the message id is what names one call.
            key = message.get("id") or f"record-{number}"
            call = run.calls.get(key)
            if call is None:
                call = run.calls[key] = Call(message, usage, stamp)
                effort = record.get("perTurnEffort") or record.get("effort")
                if isinstance(effort, str):
                    run.efforts[effort] = run.efforts.get(effort, 0) + 1
            # Output grows as the response streams; the last record is final.
            call.output = max(call.output, usage.get("output_tokens") or 0)
            if stamp:
                call.last = stamp
    return run


def _read_meta(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def read_journal(directory: Path) -> dict[str, dict]:
    """Label, phase, outcome and returned-result size per agent, from journal.jsonl.

    An agent's outcome is its last terminal event: ``ok`` for a result,
    ``null result`` for a result that is null, ``failed`` for a failure. One
    that started and has neither is ``no result`` — a run killed mid-stage, or
    an agent that died on a usage limit. With no journal at all an agent is
    ``unknown``, which is not the same thing as fine.
    """

    entries: dict[str, dict] = {}
    try:
        handle = (directory / "journal.jsonl").open(encoding="utf-8", errors="replace")
    except OSError:
        return entries
    with handle:
        for line in handle:
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                continue
            agent = event.get("agentId") if isinstance(event, dict) else None
            if not isinstance(agent, str):
                continue
            entry = entries.setdefault(agent, {"outcome": "no result"})
            kind = event.get("type")
            if kind == "started":
                entry.setdefault("label", event.get("label"))
                entry.setdefault("phase", event.get("phase"))
            elif kind == "result":
                result = event.get("result")
                entry["outcome"] = "ok" if result is not None else "null result"
                text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
                entry["result_chars"] = len(text)
            elif kind == "failed":
                entry["outcome"] = "failed"
    return entries


# ─── Timeline sweep ─────────────────────────────────────────────────────────


def sweep(runs: list[AgentRun]) -> dict[str, Any]:
    """Timeline sweep over agent spans, crediting every lone second to an agent.

    The sweep keeps the SET of running agents, not a count, so the time one
    agent spends alone belongs to a named agent. That agent is then classified:
    ``serial`` if it overlapped no other agent at any point (a one-agent stage),
    ``outlived`` if it ran alongside siblings and outlasted them (a straggler).
    The two need opposite advice, and a counter cannot tell them apart.
    """

    by_id = {r.agent_id: r for r in runs}
    bounds = {r.agent_id: (r.start, r.end) for r in runs if r.start and r.end}
    if not bounds:
        return {}
    first = min(start for start, _ in bounds.values())
    last = max(end for _, end in bounds.values())
    makespan = (last - first).total_seconds()
    if makespan <= 0:
        return {}

    events: list[tuple[datetime.datetime, int, str]] = []
    for agent, (start, end) in bounds.items():
        if end > start:  # a zero-length span adds nothing, and would never leave the set
            events.append((start, 1, agent))
            events.append((end, -1, agent))
    # At one instant an agent that ends leaves before one that starts joins:
    # back-to-back agents on one slot are a queue, not two agents in flight.
    events.sort(key=lambda event: (event[0], event[1]))

    running: set[str] = set()
    peak = 0
    area = 0.0
    idle = 0.0
    alone_by: dict[str, float] = {}
    previous = first
    for stamp, delta, agent in events:
        width = (stamp - previous).total_seconds()
        area += len(running) * width
        if len(running) == 1:
            only = next(iter(running))
            alone_by[only] = alone_by.get(only, 0.0) + width
        elif not running:
            idle += width
        if delta > 0:
            running.add(agent)
        else:
            running.discard(agent)
        peak = max(peak, len(running))
        previous = stamp

    serial = 0.0
    outlived = 0.0
    lone: list[dict[str, Any]] = []
    for agent, alone in alone_by.items():
        if alone <= 0:
            continue
        start, end = bounds[agent]
        overlapped = any(
            other_start < end and other_end > start
            for other, (other_start, other_end) in bounds.items()
            if other != agent
        )
        kind = "outlived" if overlapped else "serial"
        if kind == "serial":
            serial += alone
        else:
            outlived += alone
        member = by_id[agent]
        lone.append({
            "agent": agent,
            "name": member.name,
            "phase": member.phase,
            "kind": kind,
            "alone_s": alone,
            "seconds": member.seconds,
        })
    lone.sort(key=lambda entry: -entry["alone_s"])
    serial_stages = [entry for entry in lone if entry["kind"] == "serial"]
    stragglers = [entry for entry in lone if entry["kind"] == "outlived"]

    durations = sorted(r.seconds for r in runs if r.seconds)
    median = statistics.median(durations) if durations else 0.0
    slowest = max(durations) if durations else 0.0
    mean_conc = area / makespan
    return {
        "agents": len(bounds),
        "makespan_s": makespan,
        "peak": peak,
        "mean_concurrency": mean_conc,
        "util_vs_peak": (mean_conc / peak) if peak else 0.0,
        # serial + outlived: the old single-agent "tail", kept for continuity.
        "tail_alone": (serial + outlived) / makespan,
        "serial_frac": serial / makespan,
        "outlived_frac": outlived / makespan,
        "idle_frac": idle / makespan,
        "straggler": (slowest / median) if median else 0.0,
        "median_s": median,
        "slowest_s": slowest,
        "started_at": first.isoformat(),
        "lone": lone[:5],
        "longest_serial": serial_stages[0] if serial_stages else None,
        # The agent the straggler verdict is about. Not the slowest agent: when
        # a run has both verdicts the slowest is often the serial stage.
        "top_outlived": stragglers[0] if stragglers else None,
    }


def _phase_rows(runs: list[AgentRun]) -> list[dict[str, Any]]:
    """One row per phase, in the order phases started: n, wall time, spread."""

    groups: dict[str, list[AgentRun]] = {}
    for run in sorted(runs, key=lambda r: r.start or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)):
        groups.setdefault(run.phase or "(no phase)", []).append(run)
    rows = []
    for phase, members in groups.items():
        durations = sorted(member.seconds for member in members)
        median = statistics.median(durations)
        starts = [member.start for member in members if member.start]
        ends = [member.end for member in members if member.end]
        rows.append({
            "phase": phase,
            "n": len(members),
            "wall_s": (max(ends) - min(starts)).total_seconds() if starts and ends else 0.0,
            "median_s": median,
            "max_s": durations[-1],
            "spread": (durations[-1] / median) if median else 0.0,
        })
    return rows


def scan_workflow(directory: Path) -> dict[str, Any] | None:
    journal = read_journal(directory)
    runs: list[AgentRun] = []
    for path in sorted(directory.glob("agent-*.jsonl")):
        run = read_agent(path)
        if not run.start:
            continue
        meta = _read_meta(path.with_name(path.stem + ".meta.json"))
        entry = journal.get(run.agent_id, {})
        run.label = meta.get("description") or entry.get("label")
        run.phase = meta.get("workflowPhase") or entry.get("phase")
        run.outcome = entry.get("outcome", "unknown")
        run.result_chars = entry.get("result_chars")
        runs.append(run)
    if not runs:
        return None
    stats = sweep(runs)
    if not stats:
        return None

    first = min(r.start for r in runs if r.start)
    slowest = max(runs, key=lambda r: r.seconds)
    cache_create = sum(r.total("cache_create") for r in runs)
    unpriced = sorted({model for r in runs for model in r.unpriced_models})
    firsts = [r.first_context for r in runs if r.first_context is not None]
    results = [r.result_chars for r in runs if r.result_chars is not None]
    outcomes: dict[str, int] = {}
    models: dict[str, int] = {}
    efforts: dict[str, int] = {}
    for r in runs:
        outcomes[r.outcome] = outcomes.get(r.outcome, 0) + 1
        for model, count in r.models.items():
            models[model] = models.get(model, 0) + count
        effort = _most_common(r.efforts) or "unknown"
        efforts[effort] = efforts.get(effort, 0) + 1

    stats.update({
        "sequential": stats["peak"] <= 1,
        "run_id": directory.name,
        "turns": sum(r.turns for r in runs),
        "input_tokens": sum(r.total("input") for r in runs),
        "cache_read_tokens": sum(r.total("cache_read") for r in runs),
        "cache_create_tokens": cache_create,
        "out_tokens": sum(r.total("output") for r in runs),
        "cost_usd": None if unpriced else sum(r.cost or 0.0 for r in runs),
        "unpriced_models": unpriced,
        "synthetic_messages": sum(len(r.synthetic) for r in runs),
        "first_turn_context_median": statistics.median(firsts) if firsts else None,
        "long_gap_miss_share": (
            sum(r.long_gap_miss_writes() for r in runs) / cache_create if cache_create else None
        ),
        "result_chars_median": statistics.median(results) if results else None,
        "result_chars_max": max(results) if results else None,
        "outcomes": outcomes,
        "models": models,
        "efforts": efforts,
        "phases": _phase_rows(runs),
        "slowest_tag": slowest.name,
        "slowest_agent": slowest.agent_id,
        "agent_rows": [
            {
                "agent": r.agent_id,
                "name": r.name,
                "phase": r.phase,
                "start_s": (r.start - first).total_seconds() if r.start else None,
                "seconds": r.seconds,
                "turns": r.turns,
                "model": _most_common(r.models),
                "effort": _most_common(r.efforts),
                "outcome": r.outcome,
                "result_chars": r.result_chars,
                "first_context": r.first_context,
                "input_tokens": r.total("input"),
                "cache_read_tokens": r.total("cache_read"),
                "cache_create_tokens": r.total("cache_create"),
                "out_tokens": r.total("output"),
                "cost_usd": r.cost,
            }
            for r in sorted(runs, key=lambda r: r.start or first)
        ],
    })
    stats["verdicts"] = _verdicts(stats)
    return stats


def find_workflow_dirs(roots: list[Path], since_days: float | None) -> list[Path]:
    """Every workflow run in the window, each one once.

    ``sync-link-projects.sh`` symlinks ``~/.claude/projects`` and the per-profile
    projects directory at the same transcripts, so scanning both roots naively
    reports every run twice. Deduplicate on the resolved path rather than on the
    run id: two genuinely different sessions can hold runs with the same id
    prefix, and the resolved path is the only thing that identifies one run.
    """

    found: dict[Path, Path] = {}
    cutoff = None
    if since_days is not None:
        cutoff = datetime.datetime.now().timestamp() - since_days * 86400
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("*/*/subagents/workflows/wf_*"):
            if not path.is_dir():
                continue
            if cutoff is not None and path.stat().st_mtime < cutoff:
                continue
            found.setdefault(path.resolve(), path)
    return sorted(found.values(), key=lambda p: p.stat().st_mtime)


def default_roots() -> list[Path]:
    home = Path.home()
    roots = [home / ".claude" / "projects"]
    profiles = home / ".claude-profiles"
    if profiles.is_dir():
        roots.extend(sorted(p / "projects" for p in profiles.iterdir() if p.is_dir()))
    return roots


# ─── Polling ────────────────────────────────────────────────────────────────
# The polling rule — start one Monitor, then yield, rather than re-running a
# status command until something changes — lived only as prose in the global
# instructions. Nothing enforced it and nothing counted violations, which is the
# same shape as every gate this audit found broken. Measured on the session that
# wrote this code: 81 of 321 Bash calls were pure status reads against work
# already running, against 3 Monitor calls. A quarter of the shell budget spent
# asking "is it done yet".
#
# A poll is a Bash call that (a) only reads status and (b) is not the first of
# its kind. The repetition is what makes it a poll: checking once is a check.

_POLL_SHAPES = (
    re.compile(r"^\s*gh\s+(pr|run)\s+(checks|view|list|watch)\b"),
    re.compile(r"^\s*git\s+(status|log)\b"),
    re.compile(r"^\s*(tail|head|cat|wc)\b[^|;&]*\.(out|output|log|jsonl)\b"),
    re.compile(r"^\s*(ps|pgrep)\b"),
    re.compile(r"^\s*sleep\b"),
    re.compile(r"^\s*(ls|stat)\b[^|;&]*$"),
)
# A command that changes anything is never a poll, however it starts.
#
# The redirect clause used to be a bare `>>?[^&]`, which matched the `>/` of
# `2>/dev/null` — so every status command that silenced stderr was classified as
# mutating and the poll count came out 0 on every session ever recorded. An
# instrument that cannot fire reports a clean run exactly like a clean run does,
# which is why `--self-test` below exists and why CI runs it.
_MUTATES = re.compile(
    r"\b(rm|mv|cp|mkdir|touch|tee|install|npm|pip|pytest|committer)\b"
    r"|\bsed\s+-i\b"
    r"|\bgit\s+(push|commit|add|reset|checkout|merge|rebase)\b"
    r"|(?<![0-9&])>>?\s*(?!/dev/null)\S"
)


def _is_poll_shape(command: str) -> bool:
    if _MUTATES.search(command):
        return False
    return any(shape.search(command) for shape in _POLL_SHAPES)


def scan_session_polls(transcript: Path) -> dict | None:
    """Count repeated status reads against the background work in one session."""
    bash_calls = 0
    poll_candidates: list[str] = []
    monitors = 0
    background = 0
    agents = 0

    try:
        lines = transcript.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    for line in lines:
        try:
            record = json.loads(line)
        except (ValueError, TypeError):
            continue
        content = (record.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            payload = block.get("input") or {}
            if name == "Monitor":
                monitors += 1
            elif name in ("Agent", "Task", "Workflow"):
                agents += 1
            elif name == "Bash":
                bash_calls += 1
                if payload.get("run_in_background"):
                    background += 1
                    continue
                command = str(payload.get("command") or "")
                if _is_poll_shape(command):
                    poll_candidates.append(command.strip()[:80])

    # Only repeats count. The first `gh pr checks` is a check; the fourth is a poll.
    seen: dict[str, int] = {}
    polls = 0
    for command in poll_candidates:
        key = re.sub(r"\s+", " ", command)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            polls += 1

    jobs = monitors + background + agents
    return {
        "session": transcript.stem,
        "bash_calls": bash_calls,
        "poll_shaped": len(poll_candidates),
        "polls": polls,
        "poll_share": (polls / bash_calls) if bash_calls else 0.0,
        "monitors": monitors,
        "background": background,
        "agents": agents,
        "jobs": jobs,
        "polls_per_job": (polls / jobs) if jobs else float(polls),
    }


def find_transcripts(roots: list[Path], since_days: float | None) -> list[Path]:
    found: dict[Path, Path] = {}
    cutoff = None
    if since_days is not None:
        cutoff = datetime.datetime.now().timestamp() - since_days * 86400
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("*/*.jsonl"):
            if cutoff is not None and path.stat().st_mtime < cutoff:
                continue
            found.setdefault(path.resolve(), path)
    return sorted(found.values(), key=lambda p: p.stat().st_mtime)


def self_test_polls() -> int:
    """Can the poll detector still go red?

    A detector that cannot fire reports a disciplined session exactly like an
    undisciplined one — and this one shipped that failure: `2>/dev/null` matched
    the mutation guard, so every session ever scanned reported zero polls. One
    positive and one negative control, the same shape red-phase-audit.py uses.
    """
    import tempfile

    def _session(commands: list[str], monitors: int = 0) -> list[str]:
        rows = []
        for command in commands:
            rows.append(json.dumps({"message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": command}}
            ]}}))
        for _ in range(monitors):
            rows.append(json.dumps({"message": {"content": [
                {"type": "tool_use", "name": "Monitor", "input": {}}
            ]}}))
        return rows

    polling = _session([
        "gh pr checks 90 2>/dev/null",
        "gh pr checks 90 2>/dev/null",
        "gh pr checks 90 2>/dev/null",
        "tail -5 /tmp/run.output 2>/dev/null",
        "tail -5 /tmp/run.output 2>/dev/null",
        "sleep 30",
        "sleep 30",
    ], monitors=0)
    disciplined = _session([
        "gh pr checks 90 2>/dev/null",
        "committer 'fix: x' a.py",
        "python3 -m pytest tests/ -q",
        "npm ci",
    ], monitors=1)

    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        hot = root / "hot.jsonl"
        hot.write_text("\n".join(polling) + "\n", encoding="utf-8")
        cold = root / "cold.jsonl"
        cold.write_text("\n".join(disciplined) + "\n", encoding="utf-8")

        fired = scan_session_polls(hot)
        quiet = scan_session_polls(cold)

    if not fired or fired["polls"] < 4:
        failures.append(
            f"positive control did not fire: expected >=4 polls, got "
            f"{fired['polls'] if fired else 'nothing'}"
        )
    if not quiet or quiet["polls"] != 0:
        failures.append(
            f"negative control fired: expected 0 polls, got "
            f"{quiet['polls'] if quiet else 'nothing'}"
        )
    if quiet and quiet["bash_calls"] != 4:
        failures.append(f"negative control miscounted bash calls: {quiet['bash_calls']}")

    if failures:
        for line in failures:
            print(f"SELF-TEST FAILED: {line}")
        return 1
    print(
        "SELF-TEST PASSED: the poll detector fires on repeated status reads "
        "and stays quiet on real work."
    )
    return 0


# ─── Sweep self-test ────────────────────────────────────────────────────────
# The main mode ran unguarded until 2026-10-23: `--self-test` covered polls and
# Codex children only, and changing the lone-agent check to `== 99` or the
# straggler verdict to `if False:` still printed PASSED. The fixtures, in
# scorecard_fixtures.py, are runs written to disk the way Claude Code writes them
# — every API call as TWO records sharing one message id — and read back through
# find_workflow_dirs() and scan_workflow(), the same path the table takes. The
# table and the summary are then rendered from those rows, because a line the
# owner reads is a claim too: the first version of this test checked only the
# dicts, and deleting "Longest serial stage" stayed green.


def self_test_sweep() -> int:
    """Can the sweep, the verdicts, the token ledger and the table still go red?"""

    import contextlib
    import io
    import tempfile

    from scorecard_fixtures import RUNS, write_sweep_fixtures

    failures: list[str] = []

    def expect(label: str, actual: object, wanted: object) -> None:
        close = (
            isinstance(actual, float) and isinstance(wanted, (int, float))
            and abs(actual - wanted) < 1e-9
        )
        if not close and actual != wanted:
            failures.append(f"{label}: expected {wanted!r}, got {actual!r}")

    def agents(row: dict) -> dict[str, dict]:
        return {agent["name"]: agent for agent in row["agent_rows"]}

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_sweep_fixtures(root)
        rows = {}
        for directory in find_workflow_dirs([root], None):
            row = scan_workflow(directory)
            if row:
                rows[row["run_id"]] = row

    missing = set(RUNS) - set(rows)
    if missing:
        print(f"SELF-TEST FAILED: fixture runs not read back: {sorted(missing)}")
        return 1
    barrier, chain, queue = rows["wf_barrier"], rows["wf_fanout_build"], rows["wf_queue"]
    sequential, hit, miss = rows["wf_sequential"], rows["wf_edge_hit"], rows["wf_edge_miss"]
    straggler = "straggler, pipeline() or finer units — one agent outlived its siblings for {}% of the makespan"

    # A — one agent outlived its siblings for 5 of 30 minutes, and the slots it
    # reached sat mostly empty: both verdicts, straggler first, whole strings.
    expect("barrier peak", barrier["peak"], 6)
    expect("barrier outlived", barrier["outlived_frac"], 5 / 30)
    expect("barrier serial", barrier["serial_frac"], 0.0)
    expect("barrier util_vs_peak", barrier["util_vs_peak"], 95 / 30 / 6)
    expect("barrier verdicts", barrier["verdicts"], [
        straggler.format(17), "low util, not enough queued work to keep the 6 slots it reached busy",
    ])
    # At Opus 5.5 list rates: 12 calls of 2 input, 30k read, 1k write, 120 out.
    expect("barrier cost", barrier["cost_usd"], 12 * (2 * 4 + 30_000 * 0.2 + 1_000 * 5 + 120 * 20) / 1e6)

    # B — the lone build is serial, not a straggler, and the advice says so.
    expect("chain serial", chain["serial_frac"], 20 / 44)
    expect("chain outlived", chain["outlived_frac"], 3 / 44)
    expect("chain idle", chain["idle_frac"], 1 / 44)
    expect("chain verdicts", chain["verdicts"], ["serial stage build alone 20 min, shorten or overlap it"])
    expect("chain longest serial", (chain["longest_serial"] or {}).get("name"), "build")
    expect(
        "chain phases (meta.json wins over the journal)",
        [(p["phase"], p["n"], p["wall_s"] / 60) for p in chain["phases"]],
        [("Scout", 4, 12.0), ("Build", 1, 20.0), ("Check", 4, 11.0)],
    )
    expect("chain outcomes", chain["outcomes"], {"ok": 6, "null result": 1, "no result": 1, "failed": 1})
    expect("chain result chars", (chain["result_chars_median"], chain["result_chars_max"]), (400, 400))
    # Eight agents with two calls and a build with four, every call two records.
    expect("chain turns", chain["turns"], 20)
    expect("chain input", chain["input_tokens"], 40)
    expect("chain output", chain["out_tokens"], 20 * 120)
    expect("chain cache read", chain["cache_read_tokens"], 18 * 30_000)
    expect("chain cache write", chain["cache_create_tokens"], 17 * 1_000 + 40_000 + 15_000 + 10_000)
    # Three build calls follow a gap past the TTL; only the 40k full rewrite is
    # a miss. The 15k one is under the 20k floor, the 10k one under half.
    expect("chain long-gap miss share", chain["long_gap_miss_share"], 40_000 / 82_000)
    expect("chain first-turn context", chain["first_turn_context_median"], 31_002)
    expect("chain effort", chain["efforts"], {"xhigh": 9})

    # C — a 6x spread a pipeline absorbed: no tail to speak of.
    expect("queue peak", queue["peak"], 4)
    expect("queue straggler", queue["straggler"], 6.0)
    expect("queue outlived", queue["outlived_frac"], 0.5 / 20.5)
    expect("queue verdicts", queue["verdicts"], ["wide spread, absorbed — this is what a pipeline is for"])
    expect("queue outcomes", queue["outcomes"], {"unknown": 30})

    # D — back-to-back is sequential; the pricing edges price or refuse to.
    by_agent = agents(sequential)
    expect("sequential verdicts", sequential["verdicts"], ["sequential — one agent at a time, no parallelism to waste"])
    expect("sequential turns (a <synthetic> record is not a call)", sequential["turns"], 7)
    expect("sequential synthetic messages", sequential["synthetic_messages"], 1)
    expect("sequential cost", sequential["cost_usd"], None)
    expect("sequential unpriced", sequential["unpriced_models"], ["claude-imaginary-9", "claude-opus-5-5 (fast)"])
    expect("first cost", by_agent["first"]["cost_usd"], 2 * (2 * 4 + 30_000 * 0.2 + 1_000 * 5 + 120 * 20) / 1e6)
    # Haiku 4.5 once the date is stripped: 1k 5-minute write at 1.25, 2k 1-hour at 2.
    expect(
        "dated snapshot cost, 1-hour writes at their own rate", by_agent["dated"]["cost_usd"],
        2 * (2 * 1 + 30_000 * 0.1 + 1_000 * 1.25 + 2_000 * 2 + 120 * 5) / 1e6,
    )
    expect("fast-mode cost", by_agent["fast"]["cost_usd"], None)

    # E, F — the thresholds from both sides. E sits ON outlived 0.15 and serial
    # 0.25 and gets both verdicts; F sits just under both and gets neither.
    expect("edge hit outlived", hit["outlived_frac"], 0.15)
    expect("edge hit serial", hit["serial_frac"], 0.25)
    expect("edge hit verdicts", hit["verdicts"], [
        straggler.format(15), "serial stage merge alone 10 min, shorten or overlap it",
    ])
    # The straggler is scan-2; the slowest agent is the serial merge.
    expect("edge hit straggler agent", (hit["top_outlived"] or {}).get("name"), "scan-2")
    expect("edge hit slowest agent", hit["slowest_tag"], "merge")
    expect("edge miss shares", (miss["outlived_frac"], miss["serial_frac"]), (0.145, 0.245))
    expect("edge miss verdicts", miss["verdicts"], ["packed"])

    # The table and the summary, as the owner reads them.
    ordered = [rows[name] for name in sorted(rows)]
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _print_runs(ordered)
        _print_summary(ordered)
    printed = [line.strip() for line in buffer.getvalue().splitlines()]
    for wanted in (
        "Totals: 6 runs (5 parallel), 69 agents, 139 API calls;",
        "Largest tail: wf_edge_hit — scan-2 outlived its siblings for 15% of 40.0m (~6 min of "
        "wall clock). Split that unit, or move the stage into a pipeline() so freed slots refill.",
        "Longest serial stage: wf_fanout_build — build ran alone 20 min of 44.0m. pipeline() "
        "cannot shorten a one-agent stage: shorten the stage or overlap it.",
        "straggler: scan-2 (Scan) ran alone 6.0m after its siblings finished "
        "(slowest agent 10.0m vs 9.0m median)",
        "straggler: unit-6 (Fan-out) ran alone 5.0m after its siblings finished "
        "(slowest agent 30.0m vs 10.0m median)",
    ):
        if not any(line.startswith(wanted) for line in printed):
            failures.append(f"table/summary line missing: {wanted!r}")
    stragglers = [line for line in printed if line.startswith("straggler: ")]
    expect("straggler detail lines (one per flagged run)", len(stragglers), 2)

    if failures:
        for line in failures:
            print(f"SELF-TEST FAILED: {line}")
        return 1
    print(
        "SELF-TEST PASSED: the sweep tells a lone build stage from a straggler and "
        "names the right agent, holds both thresholds, lists every verdict that "
        "holds, counts each API call once, and prices only what the table carries."
    )
    return 0


# ─── Verdicts ───────────────────────────────────────────────────────────────

def _poll_verdict(stats: dict) -> str:
    if stats["jobs"] == 0:
        return "no background work — nothing to poll"
    if stats["polls_per_job"] >= 5:
        return "polling instead of yielding — one Monitor replaces all of these"
    if stats["monitors"] == 0 and stats["polls"] > 0:
        return "polled without ever starting a Monitor"
    if stats["poll_share"] >= 0.15:
        return "a sixth of the shell budget spent asking whether it is done"
    return "yielded"


# A run is a straggler run when one agent outlived its siblings for this share
# of the makespan, and serial-bound when one-agent stages took this share.
_OUTLIVED_FLAG = 0.15
_SERIAL_FLAG = 0.25
_UTIL_FLOOR = 0.55


def _verdicts(stats: dict) -> list[str]:
    """Every verdict that holds, worst first — not only the first one.

    Order: sequential, straggler, serial stage, low util. A sequential run gets
    that verdict alone: one agent at a time IS the whole run, so its serial
    share is 100% by construction and tells a reader nothing to act on.
    """

    if stats["peak"] <= 1:
        return ["sequential — one agent at a time, no parallelism to waste"]
    found: list[str] = []
    if stats["outlived_frac"] >= _OUTLIVED_FLAG:
        found.append(
            f"straggler, pipeline() or finer units — one agent outlived its "
            f"siblings for {stats['outlived_frac'] * 100:.0f}% of the makespan"
        )
    if stats["serial_frac"] >= _SERIAL_FLAG:
        stage = stats.get("longest_serial") or {}
        found.append(
            f"serial stage {stage.get('name', '?')} alone "
            f"{stage.get('alone_s', 0.0) / 60:.0f} min, shorten or overlap it"
        )
    if stats["util_vs_peak"] < _UTIL_FLOOR:
        found.append(
            f"low util, not enough queued work to keep the {stats['peak']} "
            f"slots it reached busy"
        )
    if found:
        return found
    if stats["straggler"] >= 4 and stats["outlived_frac"] < 0.05:
        return ["wide spread, absorbed — this is what a pipeline is for"]
    return ["packed"]


# ─── Output ─────────────────────────────────────────────────────────────────


def _human(count: float | None) -> str:
    if count is None:
        return "n/a"
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(count) >= size:
            return f"{count / size:.1f}{suffix}"
    return f"{count:.0f}"


def _cost(value: float | None) -> str:
    return "unpriced" if value is None else f"${value:,.2f}"


def _outcome(row: dict) -> str:
    counts = row["outcomes"]
    if counts.get("unknown") == row["agents"]:
        return "no journal"
    text = f"{counts.get('ok', 0)}/{row['agents']} ok"
    for kind in ("failed", "no result", "null result", "unknown"):
        if counts.get(kind):
            text += f", {counts[kind]} {kind}"
    return text


def _print_runs(rows: list[dict]) -> None:
    print(
        f"{'run':16} {'n':>4} {'makespan':>9} {'peak':>4} {'util_vs_peak':>12} "
        f"{'serial':>6} {'outlived':>8} {'idle':>5} {'strag':>6} {'turns':>6} "
        f"{'cost':>10}  outcome"
    )
    for row in rows:
        print(
            f"{row['run_id'][:16]:16} {row['agents']:4d} "
            f"{row['makespan_s'] / 60:8.1f}m {row['peak']:4d} "
            f"{row['util_vs_peak'] * 100:11.0f}% {row['serial_frac'] * 100:5.0f}% "
            f"{row['outlived_frac'] * 100:7.0f}% {row['idle_frac'] * 100:4.0f}% "
            f"{row['straggler']:5.1f}x {row['turns']:6d} {_cost(row['cost_usd']):>10}  "
            f"{_outcome(row)}"
        )
        pad = " " * 16
        for verdict in row["verdicts"]:
            print(f"{pad} {verdict}")
        top = row["top_outlived"]
        if row["outlived_frac"] >= _OUTLIVED_FLAG and top:
            # Name the agent the lone time was credited to, never the slowest
            # one: in 31 of 106 straggler runs on the author's host (2026-10-23)
            # the slowest agent was a different one, often the serial stage.
            phase = f" ({top['phase']})" if top["phase"] else ""
            print(
                f"{pad} straggler: {top['name']}{phase} ran alone {top['alone_s'] / 60:.1f}m "
                f"after its siblings finished (slowest agent {row['slowest_s'] / 60:.1f}m "
                f"vs {row['median_s'] / 60:.1f}m median)"
            )
        miss = row["long_gap_miss_share"]
        print(
            f"{pad} tokens: input {_human(row['input_tokens'])} · cache read "
            f"{_human(row['cache_read_tokens'])} · cache write {_human(row['cache_create_tokens'])} "
            f"· output {_human(row['out_tokens'])} · first-turn context "
            f"{_human(row['first_turn_context_median'])} · long-gap misses "
            f"{'n/a' if miss is None else f'{miss * 100:.0f}%'} of writes"
        )
        models = ", ".join(f"{name} x{n}" for name, n in sorted(row["models"].items(), key=lambda p: -p[1]))
        efforts = ", ".join(f"{name} x{n}" for name, n in sorted(row["efforts"].items(), key=lambda p: -p[1]))
        results = (
            "results n/a" if row["result_chars_median"] is None
            else f"results median {_human(row['result_chars_median'])} chars, "
                 f"max {_human(row['result_chars_max'])}"
        )
        print(f"{pad} calls by model: {models or 'none'} · agents by effort: {efforts} · {results}")
        if row["unpriced_models"]:
            print(f"{pad} unpriced: {', '.join(row['unpriced_models'])} (not in the rate table)")
        if len(row["phases"]) > 1:
            for phase in row["phases"]:
                print(
                    f"{pad}   phase {phase['phase'][:20]:20} n={phase['n']:<3d} "
                    f"wall {phase['wall_s'] / 60:6.1f}m  median {phase['median_s'] / 60:5.1f}m  "
                    f"spread {phase['spread']:4.1f}x"
                )


def _print_summary(rows: list[dict]) -> None:
    parallel_rows = [r for r in rows if r["peak"] > 1]
    priced = [r for r in rows if r["cost_usd"] is not None]
    print()
    print(
        f"Totals: {len(rows)} runs ({len(parallel_rows)} parallel), "
        f"{sum(r['agents'] for r in rows):,} agents, {sum(r['turns'] for r in rows):,} API calls; "
        f"input {_human(sum(r['input_tokens'] for r in rows))}, cache read "
        f"{_human(sum(r['cache_read_tokens'] for r in rows))}, cache write "
        f"{_human(sum(r['cache_create_tokens'] for r in rows))}, output "
        f"{_human(sum(r['out_tokens'] for r in rows))}; "
        f"{_cost(sum(r['cost_usd'] for r in priced))} list-price equivalent over "
        f"{len(priced)} priced runs ({len(rows) - len(priced)} unpriced)."
    )
    if not parallel_rows:
        return
    # Rank by minutes lost, not by the largest fraction: 19% of 20 minutes is a
    # worse run than 21% of 10, and the fraction alone inverts that. Rank only
    # the runs the straggler verdict flagged: an unflagged run with more lone
    # minutes used to win the ranking and then suppress the line.
    flagged = [r for r in parallel_rows if r["outlived_frac"] >= _OUTLIVED_FLAG]
    if flagged:
        worst = max(flagged, key=lambda r: r["makespan_s"] * r["outlived_frac"])
        recovered = worst["makespan_s"] * worst["outlived_frac"] / 60
        culprit = (worst["top_outlived"] or {}).get("name", "one agent")
        print(
            f"Largest tail: {worst['run_id']} — {culprit} outlived its siblings for "
            f"{worst['outlived_frac'] * 100:.0f}% of {worst['makespan_s'] / 60:.1f}m "
            f"(~{recovered:.0f} min of wall clock). Split that unit, or move the stage "
            f"into a pipeline() so freed slots refill."
        )
    staged = [r for r in parallel_rows if r["longest_serial"]]
    if staged:
        longest = max(staged, key=lambda r: r["longest_serial"]["alone_s"])
        stage = longest["longest_serial"]
        print(
            f"Longest serial stage: {longest['run_id']} — {stage['name']} ran alone "
            f"{stage['alone_s'] / 60:.0f} min of {longest['makespan_s'] / 60:.1f}m. "
            f"pipeline() cannot shorten a one-agent stage: shorten the stage or overlap it."
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure parallel efficiency of past Workflow runs.",
        epilog="With no arguments, scans every profile for runs in the last 7 days.",
    )
    parser.add_argument(
        "--project",
        help="Substring of the project slug to filter on (of the thread cwd, under --codex-children).",
    )
    parser.add_argument(
        "--session",
        help="Session id (or a prefix) to filter on (the parent thread id, under --codex-children).",
    )
    parser.add_argument("--since", type=float, default=7.0, help="Days back (default 7; 0 = all).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    parser.add_argument("--root", action="append", help="Extra projects/ root to scan.")
    parser.add_argument(
        "--polls",
        action="store_true",
        help="Report status-polling per background job from lead-session transcripts.",
    )
    parser.add_argument(
        "--codex-children",
        action="store_true",
        help=(
            "Count a Codex worker's subagent children from ~/.codex/state_5.sqlite "
            "— the spawn never appears in `codex exec --json`."
        ),
    )
    parser.add_argument(
        "--codex-db",
        help="Codex state database to read (default ~/.codex/state_5.sqlite).",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Ask the sweep and verdicts, the poll detector and the Codex child "
            "counter whether they can still go red."
        ),
    )
    args = parser.parse_args()

    if args.self_test:
        results = [self_test_sweep(), self_test_polls(), self_test_codex_children()]
        return 1 if any(results) else 0

    roots = default_roots()
    if args.root:
        roots.extend(Path(os.path.expanduser(r)) for r in args.root)

    window = None if args.since == 0 else args.since

    if args.codex_children:
        try:
            report = scan_codex_children(
                args.codex_db,
                since_days=window,
                cwd_filter=args.project,
                parent_filter=args.session,
            )
        except CodexStateUnavailable as exc:
            # Not an error and not a zero: the children exist or they do not,
            # and without the database this cannot say which.
            if args.json:
                json.dump({"available": False, "reason": str(exc)}, sys.stdout, indent=2)
                sys.stdout.write("\n")
                return 0
            print(f"workflow-scorecard: {exc}.")
            print(
                "That is not 0 children — with no database read, a Codex worker's "
                "fan-out is simply uncounted."
            )
            return 0
        if args.json:
            report["available"] = True
            json.dump(report, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        print_codex_children(report)
        return 0

    if args.polls:
        transcripts = find_transcripts(roots, window)
        if args.project:
            transcripts = [t for t in transcripts if args.project in str(t)]
        if args.session:
            transcripts = [t for t in transcripts if args.session in t.stem]
        poll_rows = [r for r in (scan_session_polls(t) for t in transcripts) if r]
        poll_rows = [r for r in poll_rows if r["bash_calls"]]
        if args.json:
            json.dump(poll_rows, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        if not poll_rows:
            print("workflow-scorecard: no sessions with tool calls in the window.")
            return 0
        print(
            f"{'session':10} {'bash':>5} {'polls':>6} {'share':>6} "
            f"{'jobs':>5} {'mon':>4} {'per job':>8}"
        )
        for row in sorted(poll_rows, key=lambda r: -r["polls_per_job"]):
            print(
                f"{row['session'][:10]:10} {row['bash_calls']:5d} {row['polls']:6d} "
                f"{row['poll_share'] * 100:5.0f}% {row['jobs']:5d} "
                f"{row['monitors']:4d} {row['polls_per_job']:7.1f}"
            )
            print(f"{'':10} {_poll_verdict(row)}")
        return 0

    directories = find_workflow_dirs(roots, window)
    if args.project:
        directories = [d for d in directories if args.project in str(d)]
    if args.session:
        directories = [d for d in directories if args.session in str(d)]

    rows = []
    for directory in directories:
        stats = scan_workflow(directory)
        if stats:
            stats["project"] = directory.parts[-5]
            stats["session"] = directory.parts[-4]
            rows.append(stats)

    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if not rows:
        print("workflow-scorecard: no Workflow runs found in the window.")
        print("Widen it with --since 0, or point at a root with --root.")
        return 0

    _print_runs(rows)
    _print_summary(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
