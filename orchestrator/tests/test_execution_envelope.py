"""Contract tests for provider-neutral execution resolution."""

from types import MappingProxyType

import pytest

from execution_envelope import (
    CapabilityRequirement,
    CapabilitySet,
    CapabilityState,
    ExecutionRequest,
    InvalidExecutionConfig,
    RequiredCapabilityUnavailable,
    RequirementLevel,
    build_execution_envelope,
    resolve_connection,
)
from execution_resolver import resolve_execution
from worker_provider import ClaudeProvider, CodexProvider
from worker_routing import WorkerRoute


def _connection(
    runtime: str,
    provider: str,
    *,
    models: dict[str, str] | None = None,
    capabilities: dict[str, str] | None = None,
) -> dict:
    return {
        "agent_runtime": runtime,
        "inference_provider": provider,
        "wire_protocol": "runtime-native",
        "endpoint_identity": f"{provider}-user-config",
        "models": models or {},
        "capabilities": capabilities or {},
    }


def _request(*requirements: CapabilityRequirement) -> ExecutionRequest:
    return ExecutionRequest(
        profile="implement",
        requested_runtime="codex",
        requested_connection="codex-default",
        requested_model="logical-strong",
        requested_effort="high",
        requirements=requirements,
        preferences={"nested": {"stable": True}},
    )


def test_execution_request_is_deeply_immutable_and_serializable():
    request = _request()

    assert isinstance(request.preferences, MappingProxyType)
    assert isinstance(request.preferences["nested"], MappingProxyType)
    with pytest.raises(TypeError):
        request.preferences["nested"]["stable"] = False
    assert request.to_dict()["preferences"] == {"nested": {"stable": True}}


def test_required_unknown_capability_fails_before_execution():
    with pytest.raises(RequiredCapabilityUnavailable, match="will not spend tokens"):
        build_execution_envelope(
            request=_request(
                CapabilityRequirement("repository_write", RequirementLevel.REQUIRED)
            ),
            surface="test",
            runtime_version=None,
            connection={
                "connection": "codex-default",
                "inference_provider": "openai",
                "wire_protocol": "responses",
                "endpoint_identity": "codex-user-config",
            },
            runtime_capabilities=CapabilitySet(),
            resolved_model="gpt-5.6-sol",
            resolved_effort="high",
            resume="reconstructed",
        )


def test_preferred_capability_records_explicit_degradation():
    envelope = build_execution_envelope(
        request=_request(
            CapabilityRequirement("native_resume", RequirementLevel.PREFERRED)
        ),
        surface="test",
        runtime_version="1.2.3",
        connection={
            "connection": "codex-default",
            "inference_provider": "openai",
            "wire_protocol": "responses",
            "endpoint_identity": "codex-user-config",
        },
        runtime_capabilities=CapabilitySet(
            {"native_resume": CapabilityState.UNSUPPORTED},
            {"native_resume": "adapter"},
        ),
        resolved_model="gpt-5.6-sol",
        resolved_effort="high",
        resume="reconstructed",
        run_id="run-test",
    )

    assert envelope.degradations[0].capability == "native_resume"
    assert envelope.to_dict()["resolved"]["resume"] == "reconstructed"


def test_connection_rejects_secrets_and_runtime_mismatch():
    with pytest.raises(InvalidExecutionConfig, match="secret-bearing"):
        resolve_connection(
            connection_id="unsafe",
            runtime_id="claude",
            connections={
                "unsafe": {
                    **_connection("claude", "minimax"),
                    "api_key": "must-not-enter-clade",
                }
            },
        )
    with pytest.raises(InvalidExecutionConfig, match="belongs to runtime"):
        resolve_connection(
            connection_id="codex-default",
            runtime_id="claude",
            connections={"codex-default": _connection("codex", "openai")},
        )


@pytest.mark.parametrize(
    ("provider_name", "wire_model"),
    [
        ("minimax", "MiniMax-M2.5"),
        ("moonshot", "kimi-k2.5"),
        ("private-gateway", "team/model+2026.07"),
    ],
)
def test_claude_runtime_resolves_third_party_connection_models(
    monkeypatch, provider_name, wire_model
):
    adapter = ClaudeProvider()
    monkeypatch.setattr(adapter, "runtime_version", lambda: "test")
    settings = {
        "runtime_connections": {"claude": "company-connection"},
        "connections": {
            "company-connection": _connection(
                "claude", provider_name, models={"logical-strong": wire_model}
            )
        },
    }
    route = WorkerRoute(
        agent_runtime="claude",
        model="logical-strong",
        effort="high",
        reason="test",
    )

    envelope = resolve_execution(
        task={"model": "logical-strong"},
        settings=settings,
        route=route,
        adapter=adapter,
    ).to_dict()

    assert envelope["resolved"]["runtime"]["id"] == "claude"
    assert envelope["resolved"]["inference"]["provider"] == provider_name
    assert envelope["resolved"]["inference"]["model"] == wire_model
    assert "api_key" not in str(envelope).lower()


def test_codex_runtime_accepts_custom_responses_gateway_model(monkeypatch):
    adapter = CodexProvider()
    monkeypatch.setattr(adapter, "runtime_version", lambda: "test")
    route = WorkerRoute("codex", "gateway/reasoner-v9", "xhigh", "task override")
    envelope = resolve_execution(
        task={"model": "gateway/reasoner-v9"},
        settings={
            "runtime_connections": {"codex": "enterprise-responses"},
            "connections": {
                "enterprise-responses": {
                    **_connection("codex", "private-gateway"),
                    "wire_protocol": "openai-responses-compatible",
                }
            },
        },
        route=route,
        adapter=adapter,
    )

    assert envelope.resolved.model == "gateway/reasoner-v9"
    assert envelope.resolved.inference_provider == "private-gateway"
    assert envelope.resolved.wire_protocol == "openai-responses-compatible"

