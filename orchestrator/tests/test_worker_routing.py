"""Provider-aware model/effort routing stays conservative and auditable."""

import pytest

from agent_runtime import AgentRuntimeSelectionError, normalize_agent_runtime
from config import _MODEL_ALIASES
from worker_routing import normalize_effort, normalize_provider, resolve_worker_route


BASE = {
    "worker_provider": "claude",
    "default_model": "sonnet",
    "auto_model_routing": True,
    "codex_cheap_model": "gpt-5.6-terra",
    "codex_strong_model": "gpt-5.6-sol",
    "task_type_model_routing": {},
}


def test_claude_high_readiness_uses_haiku_without_unsupported_effort():
    route = resolve_worker_route({"model": "sonnet", "score": 91}, BASE)
    assert route.provider == "claude"
    assert route.model == _MODEL_ALIASES["haiku"]
    assert route.effort is None
    assert "cheap Claude" in route.reason


def test_claude_critical_task_upgrades_and_uses_high_effort():
    route = resolve_worker_route(
        {"model": "sonnet", "score": 91, "is_critical_path": 1}, BASE
    )
    assert route.model == _MODEL_ALIASES["sonnet"]
    assert route.effort == "high"
    assert "critical-path upgrade" in route.reason


def test_claude_critical_upgrade_handles_persisted_concrete_model_id():
    route = resolve_worker_route(
        {"model": _MODEL_ALIASES["sonnet"], "is_critical_path": 1}, BASE
    )
    assert route.model == _MODEL_ALIASES["opus"]
    assert route.effort == "high"


def test_critical_safety_upgrade_overrides_explicit_low_effort():
    route = resolve_worker_route(
        {"provider": "codex", "model": "gpt-5.6-terra", "effort": "low",
         "is_critical_path": 1},
        BASE,
    )
    assert route.model == "gpt-5.6-sol"
    assert route.effort == "high"


def test_codex_high_readiness_uses_configured_cheap_tier():
    route = resolve_worker_route(
        {"provider": "codex", "model": "sonnet", "score": 88}, BASE
    )
    assert route.model == "gpt-5.6-terra"
    assert route.effort == "low"
    assert "cheap Codex" in route.reason


def test_codex_low_readiness_uses_strong_tier_and_requests_clarification():
    route = resolve_worker_route(
        {"provider": "codex", "model": "sonnet", "score": 30}, BASE
    )
    assert route.model == "gpt-5.6-sol"
    assert route.effort == "high"
    assert route.needs_clarification is True


def test_explicit_effort_wins_over_automatic_default():
    route = resolve_worker_route(
        {"provider": "codex", "model": "sonnet", "score": 90, "effort": "medium"},
        BASE,
    )
    assert route.model == "gpt-5.6-terra"
    assert route.effort == "medium"


def test_auto_routing_off_preserves_requested_envelope():
    route = resolve_worker_route(
        {"provider": "codex", "model": "gpt-5.6-sol", "score": 99, "effort": "xhigh"},
        {**BASE, "auto_model_routing": False},
    )
    assert route.model == "gpt-5.6-sol"
    assert route.effort == "xhigh"


def test_runtime_boundary_normalizes_known_values_and_uses_explicit_default():
    assert normalize_agent_runtime(" CODEX ") == "codex"
    assert normalize_provider(None, "codex") == "codex"


@pytest.mark.parametrize(
    ("task", "settings"),
    [
        ({"provider": "shell; rm"}, BASE),
        ({}, {**BASE, "worker_provider": "also-bad"}),
        ({"provider": ""}, BASE),
    ],
)
def test_invalid_runtime_boundary_fails_closed(task, settings):
    with pytest.raises(AgentRuntimeSelectionError, match="Unsupported agent runtime"):
        resolve_worker_route(task, settings)


def test_valid_task_runtime_override_does_not_use_invalid_default():
    route = resolve_worker_route(
        {"provider": "codex", "model": "gpt-5.6-sol"},
        {**BASE, "worker_provider": "also-bad"},
    )
    assert route.agent_runtime == "codex"
    assert route.provider == "codex"  # legacy compatibility property


def test_invalid_effort_still_degrades_without_shell_injection():
    assert normalize_effort("medium") == "medium"
    assert normalize_effort("high; echo nope") is None


def test_task_type_override_is_provider_specific_and_audited():
    route = resolve_worker_route(
        {"provider": "claude", "model": "sonnet", "task_type": "test",
         "effort": "high"},
        {**BASE, "task_type_model_routing": {"test": "haiku"}},
    )
    assert route.model == _MODEL_ALIASES["haiku"]
    assert route.effort is None
    assert "task-type override (test)" in route.reason


def test_task_type_model_override_is_opaque_for_codex_connection():
    route = resolve_worker_route(
        {"provider": "codex", "model": "gpt-5.6-sol", "task_type": "test"},
        {**BASE, "task_type_model_routing": {"test": "haiku"}},
    )
    assert route.model == "haiku"
    assert "task-type override (test)" in route.reason
