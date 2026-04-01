"""
Reaction System — configurable event reactions with attempt counting (Composio pattern).

Architecture:
- ReactionConfig: per-event-type config (threshold, action, cooldown)
- Reaction: a specific reaction instance tied to an event
- ReactionExecutor: evaluates events against configs, triggers actions

This implements the Composio pattern where certain events trigger escalation
actions after repeated failures (e.g., 3 failed tool calls → suggest alternative,
5 timeouts → abort task).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ─── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class ReactionConfig:
    """Configuration for a single reaction type."""
    name: str
    # Event matching
    event_type: str  # "tool_call" | "llm_call" | "error" | "timeout" | "state_change"
    event_match: str | None = None  # regex pattern to match against event name/content
    # Trigger conditions
    threshold: int = 3  # trigger after N occurrences
    window_seconds: float = 300.0  # reset counter after this window
    # Action
    action: str = "warn"  # "warn" | "escalate" | "abort" | "retry" | "notify"
    action_payload: dict[str, Any] = field(default_factory=dict)
    # Cooldown
    cooldown_seconds: float = 60.0  # don't re-trigger within this window

    def matches(self, event_type: str, event_name: str = "", event_content: str = "") -> bool:
        if self.event_type != event_type:
            return False
        if self.event_match:
            import re
            try:
                if not re.search(self.event_match, event_name + event_content):
                    return False
            except re.error:
                pass
        return True


# ─── Reaction Instances ─────────────────────────────────────────────────────────

@dataclass
class Reaction:
    """A triggered reaction with its context."""
    config: ReactionConfig
    count: int
    first_seen: float
    last_triggered: float
    status: str = "pending"  # "pending" | "triggered" | "cooldown" | "resolved"
    message: str = ""


# ─── Reaction Executor ─────────────────────────────────────────────────────────

class ReactionExecutor:
    """Evaluates events against reaction configs and triggers actions.

    Composio pattern: tracks attempt counts and durations per event type,
    escalates when thresholds are exceeded.
    """

    # Default reaction configs (can be overridden)
    DEFAULT_CONFIGS: list[ReactionConfig] = [
        ReactionConfig(
            name="repeated_tool_failure",
            event_type="error",
            event_match=r"(?:tool|command).*failed|exit code [1-9]",
            threshold=3,
            window_seconds=300,
            action="escalate",
            action_payload={"strategy": "suggest_alternative"},
        ),
        ReactionConfig(
            name="same_tool_repeated",
            event_type="tool_call",
            event_match=r"^(?:bash|shell|exec):",
            threshold=5,
            window_seconds=180,
            action="warn",
            action_payload={"message": "Same tool called 5+ times — consider alternative approach"},
        ),
        ReactionConfig(
            name="long_duration_task",
            event_type="state_change",
            event_match=r"task.*running",
            threshold=1,
            window_seconds=0,
            action="notify",
            action_payload={"message": "Task running >10min"},
        ),
        ReactionConfig(
            name="loop_detected",
            event_type="state_change",
            event_match=r"loop.*detected",
            threshold=1,
            window_seconds=0,
            action="abort",
            action_payload={"message": "Behavioral loop detected — aborting task"},
        ),
        ReactionConfig(
            name="context_near_limit",
            event_type="state_change",
            event_match=r"context.*warning",
            threshold=1,
            window_seconds=0,
            action="warn",
            action_payload={"message": "Context window >80% — consider condensing"},
        ),
    ]

    def __init__(self, configs: list[ReactionConfig] | None = None):
        self.configs = configs or list(self.DEFAULT_CONFIGS)
        self._reactions: dict[str, list[Reaction]] = {c.name: [] for c in self.configs}
        self._event_counts: dict[str, list[tuple[float, int]]] = {}  # event_key → [(timestamp, count)]
        self._last_action: dict[str, float] = {}  # reaction_name → last_triggered timestamp

    def reset(self) -> None:
        """Reset all reaction state."""
        self._reactions = {c.name: [] for c in self.configs}
        self._event_counts.clear()
        self._last_action.clear()

    def record_event(self, event_type: str, event_name: str = "",
                     event_content: str = "", count: int = 1) -> list[Reaction]:
        """Record an event and return any triggered reactions."""
        now = time.time()
        triggered = []

        for config in self.configs:
            if not config.matches(event_type, event_name, event_content):
                continue

            # Track event counts in the sliding window
            key = f"{config.name}:{event_name}"
            if key not in self._event_counts:
                self._event_counts[key] = []

            # Add this occurrence
            self._event_counts[key].append((now, count))

            # Prune old entries outside the window
            if config.window_seconds > 0:
                cutoff = now - config.window_seconds
                self._event_counts[key] = [
                    (ts, c) for ts, c in self._event_counts[key] if ts > cutoff
                ]

            # Sum counts within window
            total_count = sum(c for _, c in self._event_counts[key])

            # Check cooldown
            last_action = self._last_action.get(config.name, 0)
            if now - last_action < config.cooldown_seconds:
                continue

            # Check threshold
            if total_count >= config.threshold:
                reaction = Reaction(
                    config=config,
                    count=total_count,
                    first_seen=self._event_counts[key][0][0] if self._event_counts[key] else now,
                    last_triggered=now,
                    status="triggered",
                    message=self._build_message(config, total_count, event_name),
                )
                self._reactions[config.name].append(reaction)
                self._last_action[config.name] = now
                triggered.append(reaction)
                logger.info(
                    "Reaction triggered: %s (count=%d, threshold=%d) — action=%s",
                    config.name, total_count, config.threshold, config.action
                )

        return triggered

    def _build_message(self, config: ReactionConfig, count: int, event_name: str) -> str:
        """Build the reaction message."""
        base = config.action_payload.get("message", f"Reaction {config.name} triggered")
        if "{count}" in base:
            return base.format(count=count)
        return f"{base} (occurred {count} times)"

    def get_active_reactions(self) -> list[Reaction]:
        """Get all reactions that are currently triggered and not in cooldown."""
        now = time.time()
        active = []
        for reactions in self._reactions.values():
            for r in reactions:
                if r.status == "triggered" and now - r.last_triggered < r.config.cooldown_seconds:
                    active.append(r)
        return active

    def acknowledge_reaction(self, reaction_name: str) -> None:
        """Mark a reaction as acknowledged/resolved."""
        for r in self._reactions.get(reaction_name, []):
            if r.status == "triggered":
                r.status = "resolved"

    def get_reaction_summary(self) -> dict[str, Any]:
        """Get a summary of all reaction states."""
        return {
            "active": [
                {
                    "name": r.config.name,
                    "action": r.config.action,
                    "count": r.count,
                    "message": r.message,
                }
                for r in self.get_active_reactions()
            ],
            "configs": [
                {
                    "name": c.name,
                    "event_type": c.event_type,
                    "threshold": c.threshold,
                    "action": c.action,
                }
                for c in self.configs
            ],
        }


# ─── Integration helpers ───────────────────────────────────────────────────────

def create_executor_from_config(config_dict: dict[str, Any] | None = None) -> ReactionExecutor:
    """Create a ReactionExecutor from a config dict (for settings loading)."""
    if not config_dict:
        return ReactionExecutor()

    configs = []
    for c in config_dict.get("reactions", []):
        try:
            configs.append(ReactionConfig(**c))
        except Exception:
            logger.warning("Invalid reaction config: %s", c)
            continue

    return ReactionExecutor(configs if configs else None)
