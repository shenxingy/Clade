"""The one definition of how a spawned agent's own output is read back.

Workers spawn `claude -p` and the orchestrator then has to answer two
questions from whatever landed in the log: what did the agent say, and what
did it cost. Until 2026-08-29 the spawn carried no `--output-format`, so the
log held plain assistant prose and the answer to the second question was
always zero — `config._parse_token_usage` scans for `tokens: N/N`-shaped
strings that text mode has never emitted. Measured, not inferred:

    $ claude -p "Reply with exactly: OK" --output-format text
    OK
    $ python -c "from config import _parse_token_usage, _estimate_cost; ..."
    (0, 0) -> $0.0

That zero was the comparand for the token-budget gate in `worker.py` (so
`transition_reason="token_budget_exceeded"` could never fire), the figure
`worker_evidence` persisted as `usage.estimated_cost`, and the denominator
`routing_break_even` divides by for success-per-dollar. The routing economics
were a division by a constant.

`--output-format stream-json` fixes it at the source: the agent reports its
own spend. Why the streaming variant and not plain `json` — plain `json`
writes one object at the very end, and `WorkerPool` declares a worker stuck
from `log_path.stat().st_mtime`, so a silent log would get every long task
killed as hung. stream-json emits an event per step, so mtime keeps
advancing, and the terminal `type: "result"` event carries the same
`total_cost_usd`, `usage`, and per-model `modelUsage` the single-object form
does.

Everything downstream — failure-context extraction, TLDR, distillation, the
observation contract — reads the log as prose. So the contract here is: parse
the events once, then project them back to the assistant text those consumers
already expect. The log a consumer sees is unchanged; only its provenance is.

Stdlib only, no project imports: a leaf, like `pytest_report`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# The terminal event of a `--output-format stream-json` run, and the single
# object emitted by `--output-format json`. Both carry the usage totals.
RESULT_EVENT_TYPE = "result"


@dataclass
class AgentResult:
    """What the agent reported about its own run."""

    text: str
    total_cost_usd: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    model_usage: dict[str, dict] = field(default_factory=dict)
    is_error: bool = False
    subtype: str = ""
    num_turns: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _assistant_text(event: dict) -> str:
    """Prose from one assistant event, ignoring thinking and tool-call blocks."""
    content = (event.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _from_result_event(event: dict, text_parts: list[str], streamed: bool) -> AgentResult:
    usage = event.get("usage") or {}
    # Which field holds the prose depends on the format, and the presence of
    # assistant events is what distinguishes them. `--output-format json` emits
    # one object whose `result` is the whole answer. `stream-json` emits an
    # event per turn and a `result` that repeats only the LAST one, so taking
    # it there would silently drop everything a multi-turn run said before its
    # final message.
    joined = "\n".join(p for p in text_parts if p)
    final = event.get("result")
    text = joined if streamed else (final if isinstance(final, str) else joined)
    cost = event.get("total_cost_usd")
    return AgentResult(
        text=text or "",
        total_cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        cache_read_input_tokens=int(usage.get("cache_read_input_tokens") or 0),
        cache_creation_input_tokens=int(usage.get("cache_creation_input_tokens") or 0),
        model_usage=event.get("modelUsage") or {},
        is_error=bool(event.get("is_error")),
        subtype=str(event.get("subtype") or ""),
        num_turns=int(event.get("num_turns") or 0),
    )


def parse_agent_output(raw: str) -> AgentResult | None:
    """Read `--output-format json` or `stream-json` output.

    Returns None for anything else — plain text mode, an empty log, or a run
    that died before emitting its result event. Callers must keep their
    existing behaviour for that case rather than treating a missing result as
    a zero-cost run, which is the exact confusion this module exists to end.
    """
    if not raw or not raw.lstrip().startswith("{"):
        return None
    text_parts: list[str] = []
    streamed = False
    result: AgentResult | None = None
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "assistant":
            streamed = True
            chunk = _assistant_text(event)
            if chunk:
                text_parts.append(chunk)
        elif event.get("type") == RESULT_EVENT_TYPE:
            result = _from_result_event(event, text_parts, streamed)
    return result


def absorb_agent_result(log_path: Path | None) -> AgentResult | None:
    """Parse the log and collapse it to the prose every consumer expects.

    The write-back is the point: it keeps `--output-format stream-json` from
    leaking JSONL into failure contexts, TLDR prompts, distillation input, and
    the observation contract. Call this once, at the seam right after log
    capture finishes and before anything reads the log.

    Never raises — a worker must not fail because its log was unusual.
    """
    if log_path is None:
        return None
    try:
        if not log_path.exists():
            return None
        raw = log_path.read_text(errors="replace")
    except OSError:
        return None
    result = parse_agent_output(raw)
    if result is None:
        return None
    try:
        log_path.write_text(result.text, encoding="utf-8")
    except OSError:
        pass  # the parsed numbers are still good; the prose projection is not
    return result
