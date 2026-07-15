"""Compact, typed context seeds for clean loop resets.

This stdlib-only leaf is the reset alternative to ``condensers.py``'s carry
strategies.  Python workers consume it in ``worker_taskfile.build_task_file``.
The standalone Bash loop has one corresponding hook: when its setting is
``reset``, ``configs/scripts/loop-runner.sh:node_hydrate_context`` should render
the previous worker envelope through this module instead of appending git/state
hydration to ``.claude/loop-context.md``.  Keep that hook mode-gated; the Bash
loop is deliberately not imported or rewritten here.
"""

from __future__ import annotations

import json
from typing import Any, Final


LoopContextMode: Final = frozenset({"carry", "reset"})

_MAX_ITEMS = 12
_MAX_FILES = 24
_MAX_TEXT = 480
_MAX_SEED_BYTES = 8192

_EMPTY_SEED = {
    "goal_status": "unknown",
    "done": [],
    "next": [],
    "key_files": [],
    "blockers": [],
    "invariants": [],
}


def _text(value: Any, limit: int = _MAX_TEXT) -> str:
    """Return bounded one-line text, or an empty string for non-text values."""
    if not isinstance(value, str):
        return ""
    compact = " ".join(value.split())
    if len(compact.encode("utf-8")) <= limit:
        return compact
    raw = compact.encode("utf-8")[: max(0, limit - 3)]
    return raw.decode("utf-8", errors="ignore").rstrip() + "..."


def _strings(value: Any, *, limit: int = _MAX_ITEMS) -> list[str]:
    """Normalize a string/list value to a small, de-duplicated string list."""
    values = value if isinstance(value, (list, tuple)) else [value]
    result: list[str] = []
    for item in values:
        normalized = _text(item)
        if normalized and normalized not in result:
            result.append(normalized)
        if len(result) >= limit:
            break
    return result


def _payload_items(payload: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        if key in payload:
            values = _strings(payload[key])
            if values:
                return values
    return []


def _fit(seed: dict[str, Any]) -> dict[str, Any]:
    """Deterministically trim list tails until the serialized seed fits."""
    while len(json.dumps(seed, ensure_ascii=False).encode("utf-8")) > _MAX_SEED_BYTES:
        largest = max(
            (key for key in seed if isinstance(seed[key], list) and seed[key]),
            key=lambda key: len(json.dumps(seed[key], ensure_ascii=False)),
            default="",
        )
        if not largest:
            return {
                key: list(value) if isinstance(value, list) else value
                for key, value in _EMPTY_SEED.items()
            }
        seed[largest].pop()
    return seed


def build_handoff_seed(
    prior_envelope: dict, progress_tail: str = ""
) -> dict:
    """Distill a worker envelope into the bounded state needed after a reset.

    Malformed or future-version envelopes are treated defensively: recognized
    fields are projected, unknown structure is ignored, and an empty input
    yields a safe minimal seed.  The returned object always has the same six
    typed fields and never retains references to the input.
    """
    if not isinstance(prior_envelope, dict):
        prior_envelope = {}

    status = _text(prior_envelope.get("status"), 40) or "unknown"
    summary = _text(prior_envelope.get("summary"))
    done = [summary] if summary else []
    tail = _text(progress_tail)
    if tail and tail not in done:
        done.append(tail)

    artifacts = prior_envelope.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    key_files = _strings(artifacts.get("changed_files"), limit=_MAX_FILES)

    handoff = prior_envelope.get("next_handoff")
    handoff = handoff if isinstance(handoff, dict) else {}
    payload = handoff.get("payload")
    payload = payload if isinstance(payload, dict) else {}

    next_items = _payload_items(
        payload, "next", "next_steps", "steps", "tasks", "todo", "action"
    )
    handoff_type = _text(handoff.get("type"), 80)
    if handoff_type and not next_items:
        next_items = [f"Continue typed handoff: {handoff_type}"]

    blockers = _strings(prior_envelope.get("blockers"))
    blockers.extend(
        item for item in _payload_items(payload, "blockers", "risks")
        if item not in blockers
    )
    blockers = blockers[:_MAX_ITEMS]
    invariants = _payload_items(
        payload, "invariants", "constraints", "must_preserve", "assumptions"
    )

    seed = {
        "goal_status": status,
        "done": done[:_MAX_ITEMS],
        "next": next_items[:_MAX_ITEMS],
        "key_files": key_files,
        "blockers": blockers,
        "invariants": invariants[:_MAX_ITEMS],
    }

    # Per-field bounds above normally stay well below this cap.  This final
    # deterministic trim makes the size guarantee explicit for unusual Unicode
    # or adversarial envelopes without ever dropping the schema itself.
    return _fit(seed)


def render_seed(seed: dict) -> str:
    """Render a stable Markdown context block containing parseable JSON."""
    normalized = build_handoff_seed({})
    if isinstance(seed, dict):
        normalized = _fit({
            "goal_status": _text(seed.get("goal_status"), 40) or "unknown",
            "done": _strings(seed.get("done")),
            "next": _strings(seed.get("next")),
            "key_files": _strings(seed.get("key_files"), limit=_MAX_FILES),
            "blockers": _strings(seed.get("blockers")),
            "invariants": _strings(seed.get("invariants")),
        })
    payload = json.dumps(normalized, indent=2, ensure_ascii=False)
    return (
        "# Clean Reset Handoff\n\n"
        "Use this typed seed as the complete prior-iteration context. "
        "Re-read files before relying on repository state.\n\n"
        f"```json\n{payload}\n```"
    )
