"""
Append-only JSONL session tree — Pi Coding Agent pattern.

Each entry has an `id` and optional `parentId`, forming a tree in one file.
Supports: branching from any point, efficient replay, crash recovery.

Entry types:
  - "session_start": session metadata
  - "user": human input / task description
  - "assistant": LLM output
  - "tool_call": tool invocation
  - "tool_result": tool output
  - "compaction": summary with firstKeptEntryId
  - "branch": branch point marker
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SessionTree:
    """Append-only JSONL session tree with parentId references."""

    def __init__(self, path: Path):
        self.path = path
        self._entry_index: dict[str, dict] = {}  # id -> entry (loaded lazily)
        self._loaded = False
        self._branch_count = 0

    # ─── Writing ─────────────────────────────────────────────────────────────

    def _new_id(self) -> str:
        return str(uuid.uuid4())[:8]

    def _write(self, entry: dict) -> str:
        """Append entry to JSONL file. Returns entry id."""
        entry["id"] = entry.get("id") or self._new_id()
        entry["ts"] = datetime.now(timezone.utc).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._entry_index[entry["id"]] = entry
        return entry["id"]

    def session_start(self, metadata: dict[str, Any]) -> str:
        """Record session start with metadata."""
        return self._write({
            "type": "session_start",
            **metadata,
        })

    def user(self, content: str, parent_id: str | None = None) -> str:
        """Record user input / task description."""
        return self._write({
            "type": "user",
            "parentId": parent_id,
            "content": content,
        })

    def assistant(
        self,
        content: str,
        parent_id: str | None = None,
        model: str | None = None,
    ) -> str:
        """Record LLM assistant output."""
        return self._write({
            "type": "assistant",
            "parentId": parent_id,
            "content": content,
            "model": model,
        })

    def tool_call(
        self,
        tool: str,
        input_data: dict[str, Any],
        parent_id: str | None = None,
    ) -> str:
        """Record a tool invocation."""
        return self._write({
            "type": "tool_call",
            "parentId": parent_id,
            "tool": tool,
            "input": input_data,
        })

    def tool_result(
        self,
        tool_call_id: str,
        output: str,
        parent_id: str | None = None,
    ) -> str:
        """Record a tool result."""
        return self._write({
            "type": "tool_result",
            "parentId": parent_id,
            "toolCallId": tool_call_id,
            "output": output,
        })

    def branch(
        self,
        label: str,
        from_entry_id: str,
        parent_id: str | None = None,
    ) -> str:
        """Create a new branch from a given entry."""
        self._branch_count += 1
        return self._write({
            "type": "branch",
            "parentId": parent_id,
            "label": label,
            "fromEntryId": from_entry_id,
            "branchIndex": self._branch_count,
        })

    def compaction(
        self,
        summary: str,
        first_kept_entry_id: str,
        parent_id: str | None = None,
    ) -> str:
        """Record a context compaction (summary + kept entry boundary)."""
        return self._write({
            "type": "compaction",
            "parentId": parent_id,
            "summary": summary,
            "firstKeptEntryId": first_kept_entry_id,
        })

    # ─── Reading / Replay ───────────────────────────────────────────────────

    def entries(self, type_filter: str | None = None) -> list[dict]:
        """Load all entries, optionally filtered by type."""
        if not self.path.exists():
            return []
        entries = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if type_filter and entry.get("type") != type_filter:
                    continue
                entries.append(entry)
        return entries

    def get_entry(self, entry_id: str) -> dict | None:
        """Get entry by id (lazy load from file)."""
        if entry_id in self._entry_index:
            return self._entry_index[entry_id]
        if not self.path.exists():
            return None
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get("id") == entry_id:
                        self._entry_index[entry_id] = entry
                        return entry
                except json.JSONDecodeError:
                    continue
        return None

    def build_context(
        self,
        up_to_entry_id: str | None = None,
        max_entries: int = 200,
    ) -> list[dict]:
        """Build context by walking from current leaf to root.

        Stops at:
          - up_to_entry_id (if provided)
          - firstKeptEntryId of nearest compaction entry
          - max_entries limit
        Returns entries in chronological order (oldest first).
        """
        all_entries = self.entries()
        if not all_entries:
            return []

        if up_to_entry_id:
            # Walk backwards from up_to_entry_id to root
            id_to_entry = {e["id"]: e for e in all_entries}
            result = []
            current_id = up_to_entry_id
            while current_id and len(result) < max_entries:
                entry = id_to_entry.get(current_id)
                if not entry:
                    break
                result.insert(0, entry)
                current_id = entry.get("parentId")
            return result
        else:
            # Return most recent entries (up to max_entries)
            return all_entries[-max_entries:]

    def latest_id(self) -> str | None:
        """Get id of the most recent entry."""
        entries = self.entries()
        return entries[-1]["id"] if entries else None

    def children_of(self, entry_id: str) -> list[dict]:
        """Get all direct children of an entry."""
        return [
            e for e in self.entries()
            if e.get("parentId") == entry_id
        ]

    def root_id(self) -> str | None:
        """Get id of the root entry (session_start)."""
        entries = self.entries("session_start")
        return entries[0]["id"] if entries else None

    def compact(
        self,
        summary: str,
        first_kept_entry_id: str,
        parent_id: str | None = None,
    ) -> str:
        """Compact entries older than first_kept_entry_id.

        Marks boundary so future replay can skip to first_kept_entry_id.
        """
        return self.compaction(summary, first_kept_entry_id, parent_id)
