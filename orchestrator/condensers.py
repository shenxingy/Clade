"""
condensers.py — Context compression strategies (OpenHands pattern).

Clade applies these at distillation time (large tool output) and when building
task-file context to prevent oversized task files from overwhelming workers.

Usage:
    from condensers import ObservationMaskingCondenser, RecentEventsCondenser

    condenser = ObservationMaskingCondenser(max_obs_bytes=8192)
    condensed = condenser.condense([{"type": "observation", "content": big_str}])
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from pathlib import Path


# ─── Abstract Base ────────────────────────────────────────────────────────────

class Condenser(ABC):
    """Abstract base for context compression strategies."""

    @abstractmethod
    def condense(self, events: list[dict], **kwargs) -> list[dict]:
        """Compress event list. Returns compressed list."""
        ...


# ─── Implementations ──────────────────────────────────────────────────────────

class NoOpCondenser(Condenser):
    """Pass through unchanged."""
    def condense(self, events: list[dict], **kwargs) -> list[dict]:
        return events


class RecentEventsCondenser(Condenser):
    """Keep only the last N events. Drop older ones."""
    def __init__(self, keep: int = 50):
        self.keep = keep

    def condense(self, events: list[dict], **kwargs) -> list[dict]:
        if len(events) <= self.keep:
            return events
        removed = len(events) - self.keep
        summary = {
            "type": "summary",
            "role": "system",
            "content": f"[{removed} earlier events omitted — showing last {self.keep}]",
        }
        return [summary] + events[-self.keep:]


class LLMSummarizingCondenser(Condenser):
    """Summarize older events with LLM. Keep recent events intact."""

    def __init__(self, keep_recent: int = 20, summarize_older: bool = True):
        self.keep_recent = keep_recent
        self.summarize_older = summarize_older

    async def _summarize(self, events: list[dict], project_dir: Path) -> str:
        """Use haiku to summarize a list of events."""
        import tempfile
        events_text = "\n".join(
            f"[{e.get('type','?')}] {e.get('content','')[:300]}"
            for e in events[:50]
        )
        prompt = (
            "Summarize this agent conversation history. Return a concise paragraph capturing:\n"
            "- What was accomplished\n"
            "- What errors or issues were encountered\n"
            "- What the current state is\n\n"
            f"Conversation:\n{events_text[:3000]}\n\nSummary:"
        )

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", prefix="clade-condense-", delete=False
        )
        tmp.write(prompt)
        tmp.close()

        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", prompt,
                "--model", "claude-haiku-4-5-20251001",
                "--dangerously-skip-permissions", "--no-input-prompt",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                cwd=str(project_dir),
            )
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            summary = stdout_bytes.decode("utf-8", errors="replace").strip()
            return summary[:500] if summary else "[no summary]"
        except Exception:
            return "[summarization failed]"
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    def condense(self, events: list[dict], **kwargs) -> list[dict]:
        if len(events) <= self.keep_recent:
            return events
        # Return placeholder — actual LLM summarization is async, call separately
        older = events[:-self.keep_recent]
        summary = {
            "type": "summary",
            "role": "system",
            "content": f"[{len(older)} events summarized — async LLM condense pending]",
        }
        return [summary] + events[-self.keep_recent:]


class ObservationMaskingCondenser(Condenser):
    """Mask or truncate large observation/tool result content."""

    def __init__(self, max_obs_bytes: int = 2000):
        self.max_obs_bytes = max_obs_bytes

    def condense(self, events: list[dict], **kwargs) -> list[dict]:
        result = []
        for e in events:
            if e.get("type") in ("tool_result", "observation", "compaction"):
                content = e.get("content", "")
                if len(content.encode()) > self.max_obs_bytes:
                    e = dict(e)
                    e["content"] = (
                        content[:self.max_obs_bytes]
                        + f"\n[...output truncated by condenser "
                        f"({len(content) - self.max_obs_bytes} bytes omitted)...]\n"
                    )
            result.append(e)
        return result
