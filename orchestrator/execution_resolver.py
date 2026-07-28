"""Resolve worker routes into immutable execution envelopes."""

from __future__ import annotations

from typing import Any, Mapping

from execution_envelope import (
    CapabilityRequirement,
    CapabilitySet,
    CapabilityState,
    Degradation,
    ExecutionRequest,
    RequirementLevel,
    build_execution_envelope,
    parse_requirements,
    resolve_connection,
)
from worker_provider import WorkerProvider
from worker_routing import WorkerRoute


_IMPLEMENT_REQUIREMENTS = (
    CapabilityRequirement("tools", RequirementLevel.REQUIRED),
    CapabilityRequirement("repository_read", RequirementLevel.REQUIRED),
    CapabilityRequirement("repository_write", RequirementLevel.REQUIRED),
    CapabilityRequirement("native_resume", RequirementLevel.PREFERRED),
)
_REVIEW_REQUIREMENTS = (
    CapabilityRequirement("repository_read", RequirementLevel.REQUIRED),
    CapabilityRequirement("structured_events", RequirementLevel.PREFERRED),
)


def _connection_capabilities(
    runtime: CapabilitySet,
    raw: Mapping[str, Any],
    *,
    source: str,
) -> CapabilitySet:
    """Overlay explicitly declared transport/model capabilities conservatively."""

    states = dict(runtime.states)
    sources = dict(runtime.sources)
    for name, raw_state in raw.items():
        connection_state = CapabilityState(str(raw_state))
        runtime_state = runtime.state(str(name))
        if runtime_state is CapabilityState.UNSUPPORTED or connection_state is CapabilityState.UNSUPPORTED:
            combined = CapabilityState.UNSUPPORTED
        elif runtime_state is CapabilityState.UNKNOWN or connection_state is CapabilityState.UNKNOWN:
            combined = CapabilityState.UNKNOWN
        elif runtime_state is CapabilityState.CONDITIONAL or connection_state is CapabilityState.CONDITIONAL:
            combined = CapabilityState.CONDITIONAL
        else:
            combined = CapabilityState.SUPPORTED
        states[str(name)] = combined
        sources[str(name)] = source
    return CapabilitySet(states, sources)


def resolve_execution(
    *,
    task: Mapping[str, Any],
    settings: Mapping[str, Any],
    route: WorkerRoute,
    adapter: WorkerProvider,
) -> Any:
    """Create a secret-free execution envelope before worker construction."""

    runtime_id = route.agent_runtime
    runtime_connections = settings.get("runtime_connections") or {}
    connection_id = (
        task.get("connection")
        or (
            runtime_connections.get(runtime_id)
            if isinstance(runtime_connections, Mapping)
            else None
        )
        or f"{runtime_id}-default"
    )
    connections = settings.get("connections") or {}
    if not isinstance(connections, Mapping):
        connections = {}
    connection = resolve_connection(
        connection_id=str(connection_id),
        runtime_id=runtime_id,
        connections=connections,
    )

    profile = str(task.get("execution_profile") or task.get("phase") or "implement")
    defaults = (
        _REVIEW_REQUIREMENTS
        if profile in {"review", "research", "explore"}
        else _IMPLEMENT_REQUIREMENTS
    )
    requirements = parse_requirements(
        task.get("execution_requirements"),
        defaults=defaults,
    )
    model_map = connection.get("models") or {}
    resolved_model = str(model_map.get(route.model, route.model)) if route.model else None
    resolved_model = adapter.resolve_model(resolved_model)
    resolved_effort, effort_degradation = adapter.resolve_effort(
        route.effort, resolved_model
    )
    degradations: list[Degradation] = []
    if effort_degradation:
        degradations.append(
            Degradation(
                capability="reasoning_control",
                requested=route.effort or "none",
                resolved=resolved_effort or "provider-default",
                reason=effort_degradation,
            )
        )

    capabilities = _connection_capabilities(
        adapter.capabilities(),
        connection.get("capabilities") or {},
        source=f"connection:{connection_id}",
    )
    request = ExecutionRequest(
        profile=profile,
        requested_runtime=runtime_id,
        requested_connection=str(connection_id),
        requested_model=str(task.get("model") or route.model) if route.model else None,
        requested_effort=route.effort,
        requirements=requirements,
        preferences={
            "route_reason": route.reason,
            "critical_path": bool(task.get("is_critical_path")),
        },
    )
    return build_execution_envelope(
        request=request,
        surface="headless-orchestrator",
        runtime_version=adapter.runtime_version(),
        connection=connection,
        runtime_capabilities=capabilities,
        resolved_model=resolved_model,
        resolved_effort=resolved_effort,
        resume=(
            "native"
            if capabilities.state("native_resume") is CapabilityState.SUPPORTED
            else "reconstructed"
        ),
        degradations=degradations,
        provenance={
            "runtime_adapter": f"{adapter.name}@{adapter.adapter_version}",
            "connection": str(connection_id),
            "repository_policy": str(task.get("policy_source") or "clade-default"),
            "route_reason": route.reason,
        },
    )
