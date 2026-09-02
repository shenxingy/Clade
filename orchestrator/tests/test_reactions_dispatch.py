"""ReactionConfig.action used to be decorative.

Both consumers in worker.py consumed every triggered reaction with a flat
logger.warning, so "abort", "escalate" and "warn" were the same event with
different spelling, and one DEFAULT_CONFIGS entry carried the message
"Behavioral loop detected — aborting task" while nothing aborted anything.

The field decides the reported level now, and an action this module cannot
dispatch is refused when the executor is built rather than ignored when it
fires. Nothing here kills a worker: mapping a regex match on a poll string to a
kill path is a larger decision than this module makes, and pretending otherwise
in a message string is exactly the defect being fixed.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reactions import (  # noqa: E402
    ACTION_LEVELS,
    ReactionConfig,
    ReactionExecutor,
    UnknownReactionAction,
)


def _config(action: str, name: str = "probe") -> ReactionConfig:
    return ReactionConfig(
        name=name,
        event_type="error",
        threshold=1,
        window_seconds=0,
        cooldown_seconds=0,
        action=action,
        action_payload={"message": f"{action} fired"},
    )


def test_every_action_maps_to_a_level() -> None:
    assert set(ACTION_LEVELS) == {"warn", "notify", "escalate", "abort", "retry"}
    assert ACTION_LEVELS["warn"] < ACTION_LEVELS["escalate"] < ACTION_LEVELS["abort"]


@pytest.mark.parametrize(
    ("action", "level"),
    [
        ("warn", logging.WARNING),
        ("notify", logging.WARNING),
        ("escalate", logging.ERROR),
        ("abort", logging.CRITICAL),
        ("retry", logging.WARNING),
    ],
)
def test_config_level_follows_its_action(action: str, level: int) -> None:
    assert _config(action).level == level


def test_severities_are_distinguishable(caplog: pytest.LogCaptureFixture) -> None:
    """The defect, stated as a test: two actions must not log identically."""
    executor = ReactionExecutor([_config("warn", "soft"), _config("escalate", "hard")])
    with caplog.at_level(logging.DEBUG, logger="reactions"):
        triggered = executor.record_event("error", event_name="boom")

    assert len(triggered) == 2
    levels = {rec.levelno for rec in caplog.records if "Reaction triggered" in rec.message}
    assert levels == {logging.WARNING, logging.ERROR}, "a flat level hides the action"


def test_unknown_action_is_refused_at_construction() -> None:
    with pytest.raises(UnknownReactionAction) as excinfo:
        ReactionExecutor([_config("detonate")])
    assert "detonate" in str(excinfo.value)


def test_default_configs_are_all_dispatchable() -> None:
    """A default this module cannot dispatch would fail every worker at start."""
    executor = ReactionExecutor()
    assert executor.configs
    for config in executor.configs:
        assert config.action in ACTION_LEVELS


def test_no_default_claims_to_abort_a_task() -> None:
    """Nothing aborts a worker, so no shipped message may say it does."""
    for config in ReactionExecutor.DEFAULT_CONFIGS:
        message = config.action_payload.get("message", "")
        assert "aborting" not in message.lower(), (
            f"{config.name} promises an abort that no code performs"
        )
        assert config.action != "abort", (
            f"{config.name} declares abort, which dispatches no kill path"
        )


def test_disabled_executor_still_reports_nothing(caplog: pytest.LogCaptureFixture) -> None:
    executor = ReactionExecutor([_config("escalate")], enabled=False)
    with caplog.at_level(logging.DEBUG, logger="reactions"):
        assert executor.record_event("error", event_name="boom") == []
    assert not [r for r in caplog.records if "Reaction triggered" in r.message]
