"""`subagents` was declared for both providers and read by nothing.

Two definitions, zero consumers, and Codex's was CONDITIONAL with no condition
expressed anywhere — which reads as "sometimes, depending" when the truth is
that `codex exec` spawns no sub-agent at all. The routing machinery to act on it
already existed: a task declaring `execution_requirements` gets them enforced in
execution_envelope against the runtime's capabilities. Nothing had ever declared
this one, and the wrong state would have given the wrong answer if anything had.

These tests are the missing consumer: a run that must subdivide is refused on a
runtime that cannot subdivide, and accepted on one that can.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from execution_envelope import (  # noqa: E402
    CapabilityRequirement,
    CapabilityState,
    RequirementLevel,
    RequiredCapabilityUnavailable,
    resolve_capabilities,
)
from worker_provider import ClaudeProvider, CodexProvider  # noqa: E402


def _caps(provider):
    return provider().capabilities()


def test_claude_can_subdivide_and_codex_cannot() -> None:
    assert _caps(ClaudeProvider).state("subagents") is CapabilityState.SUPPORTED
    assert _caps(CodexProvider).state("subagents") is CapabilityState.UNSUPPORTED


def test_codex_subagents_is_not_a_shrug() -> None:
    """CONDITIONAL with no condition written down is not a state."""
    caps = _caps(CodexProvider)
    assert caps.state("subagents") is not CapabilityState.CONDITIONAL
    assert "codex exec" in caps.sources["subagents"]


@pytest.mark.parametrize("provider", [ClaudeProvider, CodexProvider])
def test_every_conditional_capability_states_its_condition(provider) -> None:
    """A CONDITIONAL whose source is only the adapter name explains nothing."""
    caps = _caps(provider)
    adapter_only = {
        name
        for name, state in caps.states.items()
        if state is CapabilityState.CONDITIONAL and ":" not in caps.sources.get(name, "")
    }
    assert not adapter_only, f"conditional with no condition expressed: {sorted(adapter_only)}"


def _require_subagents(capabilities, level=RequirementLevel.REQUIRED):
    """The enforcement path a task reaches through execution_requirements."""
    return resolve_capabilities(
        capabilities,
        (CapabilityRequirement("subagents", level),),
    )


def test_a_fanout_task_is_refused_on_a_runtime_that_cannot_subdivide() -> None:
    with pytest.raises(RequiredCapabilityUnavailable):
        _require_subagents(_caps(CodexProvider))


def test_a_fanout_task_is_admitted_on_a_runtime_that_can() -> None:
    _require_subagents(_caps(ClaudeProvider))  # must not raise


def test_a_preferred_fanout_degrades_rather_than_failing() -> None:
    """Preferred, not required: the run proceeds and the loss is recorded."""
    degradations = _require_subagents(_caps(CodexProvider), RequirementLevel.PREFERRED)
    assert [d.capability for d in degradations] == ["subagents"]
    assert degradations[0].resolved == "unsupported"

    assert _require_subagents(_caps(ClaudeProvider), RequirementLevel.PREFERRED) == ()
