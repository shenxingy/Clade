#!/usr/bin/env python3
"""scorecard_fixtures.py — synthetic Workflow runs for workflow-scorecard.py's sweep self-test.

Data only. Every check on these runs lives in ``self_test_sweep()`` in
workflow-scorecard.py, beside the code it checks, and every mutation that proves
those checks can fire targets that file. This module holds no guard of its own;
it was split out on 2026-10-23 because the scorecard had reached its 1500-line
cap.

The runs are written the way Claude Code writes them. Every API call is TWO
assistant records sharing one ``message.id``, the second carrying the final
output count. That two-records-one-call shape is what the ~1.9x double count
summed. Each agent also gets an ``agent-*.meta.json``, and some runs get a
``journal.jsonl``.

Stdlib only: the syntax-check CI job installs no dependencies.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

T0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
# A typical subagent call: a 30k cached prefix re-read, 1k of new context written.
CALL: dict[str, Any] = {"cache_read_input_tokens": 30_000, "cache_creation_input_tokens": 1_000}
RUNS = (
    "wf_barrier", "wf_fanout_build", "wf_queue", "wf_sequential", "wf_edge_hit", "wf_edge_miss",
)


def stamp(minutes: float) -> str:
    return (T0 + datetime.timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _usage(extra: dict, output: int) -> dict[str, Any]:
    usage: dict[str, Any] = {"input_tokens": 2, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    usage.update(extra)
    usage["output_tokens"] = output
    # Without an explicit split every write is a 5-minute write, as for a subagent.
    usage.setdefault("cache_creation", {
        "ephemeral_5m_input_tokens": usage["cache_creation_input_tokens"],
        "ephemeral_1h_input_tokens": 0,
    })
    return usage


def write_agent(
    run: Path,
    agent: str,
    start: float,
    end: float,
    *,
    phase: str | None = None,
    model: str = "claude-opus-5-5",
    calls: list[tuple[float, dict]] | None = None,
    synthetic_at: float | None = None,
) -> None:
    """One agent transcript (minutes from ``T0``), plus its meta.json.

    ``calls`` is ``(minute, usage overrides)`` per API call; by default two
    ``CALL``s at a third and two thirds of the span. ``synthetic_at`` adds the
    record Claude Code writes for a message it made itself (a usage-limit
    notice): model ``<synthetic>``, a UUID id, all-zero usage. It is not a call.
    """

    if calls is None:
        third = (end - start) / 3
        calls = [(start + third, CALL), (start + 2 * third, CALL)]
    rows: list[dict] = [{
        "type": "user",
        "timestamp": stamp(start),
        "message": {"role": "user", "content": f"Fixture brief for {agent}"},
    }]
    for index, (at, extra) in enumerate(calls):
        for part, output in ((0, 5), (1, 120)):
            rows.append({
                "type": "assistant",
                "timestamp": stamp(at + part * 0.1),
                "effort": "xhigh",
                "perTurnEffort": "xhigh",
                "message": {
                    "id": f"msg_{agent}_{index}",
                    "model": model,
                    "role": "assistant",
                    "content": [{"type": "text", "text": "fixture"}],
                    "usage": _usage(extra, output),
                },
            })
    if synthetic_at is not None:
        rows.append({
            "type": "assistant",
            "timestamp": stamp(synthetic_at),
            "isApiErrorMessage": True,
            "message": {
                "id": "00000000-0000-4000-8000-000000000000",
                "model": "<synthetic>",
                "role": "assistant",
                "content": [{"type": "text", "text": "usage limit reached"}],
                "usage": _usage({}, 0),
            },
        })
    rows.append({"type": "attachment", "timestamp": stamp(end)})
    (run / f"agent-{agent}.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    meta = {"agentType": "workflow-subagent", "description": agent, "workflowPhase": phase}
    (run / f"agent-{agent}.meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _edge_run(run: Path, makespan: float, outlived: float, serial: float) -> None:
    """scan → one lone merge → test pairs, with the lone shares set exactly.

    scan-2 outlives scan-1 by ``outlived`` minutes. merge runs alone for
    ``serial`` and is the LONGEST agent, so the slowest agent is a serial stage
    while a shorter fan-out agent is the straggler. Test pairs of at most 9
    minutes fill the rest and finish together, so they leave no lone time.
    """

    write_agent(run, "scan-1", 0, 9 - outlived, phase="Scan")
    write_agent(run, "scan-2", 0, 9, phase="Scan")
    write_agent(run, "merge", 9, 9 + serial, phase="Merge")
    begin, pair = 9 + serial, 0
    while begin < makespan:
        finish = min(begin + 9, makespan)
        for side in "ab":
            write_agent(run, f"test-{pair}{side}", begin, finish, phase="Test")
        begin, pair = finish, pair + 1


def write_sweep_fixtures(root: Path) -> None:
    """The runs in ``RUNS``, under ``root/<project>/<session>/subagents/workflows/``."""

    base = root / "-fixture-project" / "fixture-session" / "subagents" / "workflows"

    def run_dir(name: str) -> Path:
        path = base / name
        path.mkdir(parents=True)
        return path

    # A: a barrier with one 3x agent. Six start together; the 25- and 30-minute
    # agents hold the run open while four slots sit finished.
    barrier = run_dir("wf_barrier")
    for index, minutes in enumerate((10, 10, 10, 10, 25, 30), 1):
        write_agent(barrier, f"unit-{index}", 0, minutes, phase="Fan-out")

    # B: fan-out -> one lone build -> fan-out, with a one-minute lead-side gap.
    # The build is 20 of 44 minutes alone and overlapped nothing: serial, which
    # pipeline() cannot shorten. The merged tail called this run a straggler.
    chain = run_dir("wf_fanout_build")
    for index, end in enumerate((10, 10, 10, 12), 1):
        write_agent(chain, f"scout-{index}", 0, end, phase="Scout")
    write_agent(
        chain, "build", 12, 32, phase="Build",
        calls=[
            (12.5, CALL),
            # 7.4 minutes after the last call: past the 5-minute TTL, and the
            # 40k context is all re-written. A long-gap cache miss.
            (20.0, {"cache_creation_input_tokens": 40_000}),
            # Also past the TTL, but a 15k context: under the 20k floor.
            (26.0, {"cache_creation_input_tokens": 15_000}),
            # Past the TTL with a 40k context, but only a quarter re-written.
            (31.5, {"cache_read_input_tokens": 30_000, "cache_creation_input_tokens": 10_000}),
        ],
    )
    for index, end in enumerate((43, 43, 43, 44), 1):
        write_agent(chain, f"check-{index}", 33, end, phase="Check")
    # The journal labels and phases differ from meta.json on purpose: meta.json
    # is what the script passed and must win.
    journal: list[dict[str, Any]] = [{"type": "launched"}]
    names = [f"scout-{i}" for i in range(1, 5)] + ["build"] + [f"check-{i}" for i in range(1, 5)]
    for name in names:
        journal.append({"type": "started", "agentId": name, "label": f"journal-{name}", "phase": "?"})
    for name in names[:4]:
        journal.append({"type": "result", "agentId": name, "result": "s" * 400})
    journal.append({"type": "result", "agentId": "build", "result": {"built": True}})
    journal.append({"type": "result", "agentId": "check-1", "result": "c" * 100})
    journal.append({"type": "result", "agentId": "check-2", "result": None})  # a silent null
    journal.append({"type": "failed", "agentId": "check-4"})  # check-3: started, nothing after
    (chain / "journal.jsonl").write_text("".join(json.dumps(e) + "\n" for e in journal), encoding="utf-8")

    # C: a queued pipeline with a 6x spread. Four slots; 2-minute units queue
    # behind two 12-minute ones and every slot drains within 30 seconds of the
    # others. Back-to-back agents on one slot touch, and must not count as two.
    queue = run_dir("wf_queue")
    slots: list[list[tuple[float, float]]] = [
        [(0.0, 12.0)] + [(12.0 + 2 * k, 14.0 + 2 * k) for k in range(4)],
        [(2.0 * k, 2.0 * k + 2) for k in range(10)],
        [(2.0 * k, 2.0 * k + 2) for k in range(4)] + [(8.0, 20.0)],
        [(2.0 * k, 2.0 * k + 2) for k in range(9)] + [(18.0, 20.5)],
    ]
    for slot, spans in enumerate(slots):
        for index, (begin, finish) in enumerate(spans):
            write_agent(queue, f"q{slot}-{index:02d}", begin, finish, phase="Pipeline")

    # D: four agents back to back, carrying the pricing edges. `first` also
    # holds a <synthetic> record; `second` is on a model the rate table does not
    # carry; `dated` is a dated snapshot id with 1-hour cache writes; `fast` is
    # a known model in fast mode, which bills at a rate the table does not hold.
    sequential = run_dir("wf_sequential")
    write_agent(sequential, "first", 0, 5, synthetic_at=4.5)
    write_agent(sequential, "second", 5, 9, model="claude-imaginary-9")
    write_agent(
        sequential, "dated", 9, 12, model="claude-haiku-4-5-20251001",
        calls=[(t, {
            "cache_read_input_tokens": 30_000,
            "cache_creation_input_tokens": 3_000,
            "cache_creation": {"ephemeral_5m_input_tokens": 1_000, "ephemeral_1h_input_tokens": 2_000},
        }) for t in (10, 11)],
    )
    write_agent(sequential, "fast", 12, 15, calls=[(13, dict(CALL, speed="fast"))])

    # E, F: the two thresholds held from both sides. E sits exactly ON them
    # (outlived 6 of 40 min = 0.15, serial 10 of 40 = 0.25), which the verdicts'
    # `>=` must flag. F sits just under them (7.25 of 50 = 0.145, 12.25 of 50 =
    # 0.245) and must not be flagged, though its 7.25 lone minutes are more than
    # E's 6: the largest flagged tail is E's, not F's.
    _edge_run(run_dir("wf_edge_hit"), 40, 6, 10)
    _edge_run(run_dir("wf_edge_miss"), 50, 7.25, 12.25)
