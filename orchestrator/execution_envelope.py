"""Versioned, immutable execution contract for every Clade worker.

This stdlib-only leaf separates the agent runtime, inference provider, wire
protocol, connection, model, capability profile, and task policy. It contains
no credentials or raw endpoint URLs and can be attached safely to status,
events, handoffs, and delivery records.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "clade.execution/v1"
_VALID_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,199}$")
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
    }
)


class CapabilityState(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    CONDITIONAL = "conditional"


class RequirementLevel(str, Enum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    OPTIONAL = "optional"
    FORBIDDEN = "forbidden"


class ExecutionResolutionError(ValueError):
    """Base class for typed preflight failures."""


class InvalidExecutionConfig(ExecutionResolutionError):
    """Raised when connection or request configuration is malformed."""


class RequiredCapabilityUnavailable(ExecutionResolutionError):
    """Raised before execution when a required capability is not proven."""

    def __init__(self, capability: str, state: CapabilityState):
        super().__init__(
            f"Required capability {capability!r} is {state.value}; "
            "Clade will not spend tokens or change the repository."
        )
        self.capability = capability
        self.state = state


class ForbiddenCapabilityPresent(ExecutionResolutionError):
    """Raised when a candidate violates a forbidden capability boundary."""

    def __init__(self, capability: str, state: CapabilityState):
        super().__init__(
            f"Forbidden capability {capability!r} is {state.value}; "
            "select a compatible runtime or profile."
        )
        self.capability = capability
        self.state = state


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return tuple(sorted(_freeze(item) for item in value))
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _identifier(value: Any, *, field_name: str, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    candidate = str(value or "").strip()
    if not candidate or not _VALID_ID.fullmatch(candidate):
        raise InvalidExecutionConfig(
            f"{field_name} must be a non-empty opaque identifier without whitespace/control characters"
        )
    return candidate


def validate_model_id(value: Any, *, allow_none: bool = True) -> str | None:
    """Validate an opaque provider-scoped model id without a stale allowlist."""

    return _identifier(value, field_name="model", allow_none=allow_none)


def _assert_secret_free(value: Any, *, path: str = "connection") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            lowered = str(key).lower().replace("-", "_")
            if lowered in _SECRET_KEYS or any(
                marker in lowered for marker in ("api_key", "auth_token", "secret")
            ):
                raise InvalidExecutionConfig(
                    f"{path}.{key} is secret-bearing; keep credentials in the native runtime/provider store"
                )
            _assert_secret_free(nested, path=f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            _assert_secret_free(nested, path=f"{path}[{index}]")


@dataclass(frozen=True)
class CapabilityRequirement:
    capability: str
    level: RequirementLevel

    def __post_init__(self) -> None:
        _identifier(self.capability, field_name="capability")

    def to_dict(self) -> dict[str, str]:
        return {"capability": self.capability, "level": self.level.value}


@dataclass(frozen=True)
class CapabilitySet:
    """Immutable four-state capabilities with source/probe provenance."""

    states: Mapping[str, CapabilityState] = field(default_factory=dict)
    sources: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized: dict[str, CapabilityState] = {}
        for name, raw in self.states.items():
            key = _identifier(name, field_name="capability")
            assert key is not None
            normalized[key] = (
                raw if isinstance(raw, CapabilityState) else CapabilityState(str(raw))
            )
        object.__setattr__(self, "states", MappingProxyType(normalized))
        object.__setattr__(
            self,
            "sources",
            MappingProxyType({str(k): str(v) for k, v in self.sources.items()}),
        )

    def state(self, capability: str) -> CapabilityState:
        return self.states.get(capability, CapabilityState.UNKNOWN)

    def to_dict(self) -> dict[str, dict[str, str]]:
        return {
            name: {
                "state": state.value,
                "source": self.sources.get(name, "unknown"),
            }
            for name, state in sorted(self.states.items())
        }


@dataclass(frozen=True)
class Degradation:
    capability: str
    requested: str
    resolved: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "capability": self.capability,
            "requested": self.requested,
            "resolved": self.resolved,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ExecutionRequest:
    profile: str
    requested_runtime: str
    requested_connection: str
    requested_model: str | None
    requested_effort: str | None
    requirements: tuple[CapabilityRequirement, ...] = ()
    preferences: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _identifier(self.profile, field_name="profile")
        _identifier(self.requested_runtime, field_name="requested runtime")
        _identifier(self.requested_connection, field_name="requested connection")
        validate_model_id(self.requested_model)
        if self.requested_effort is not None:
            _identifier(self.requested_effort, field_name="requested effort")
        object.__setattr__(self, "requirements", tuple(self.requirements))
        object.__setattr__(self, "preferences", _freeze(self.preferences))

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "runtime": self.requested_runtime,
            "connection": self.requested_connection,
            "model": self.requested_model,
            "effort": self.requested_effort,
            "requirements": [item.to_dict() for item in self.requirements],
            "preferences": _thaw(self.preferences),
        }


@dataclass(frozen=True)
class ResolvedExecution:
    surface: str
    runtime_id: str
    runtime_version: str | None
    connection: str
    inference_provider: str
    wire_protocol: str
    endpoint_identity: str
    model: str | None
    effort: str | None
    resume: str
    capabilities: CapabilitySet

    def __post_init__(self) -> None:
        for field_name in (
            "surface",
            "runtime_id",
            "connection",
            "inference_provider",
            "wire_protocol",
            "endpoint_identity",
            "resume",
        ):
            _identifier(getattr(self, field_name), field_name=field_name)
        validate_model_id(self.model)
        if self.effort is not None:
            _identifier(self.effort, field_name="effort")

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "runtime": {"id": self.runtime_id, "version": self.runtime_version},
            "inference": {
                "connection": self.connection,
                "provider": self.inference_provider,
                "protocol": self.wire_protocol,
                "endpoint_identity": self.endpoint_identity,
                "model": self.model,
            },
            "controls": {"effort": self.effort},
            "resume": self.resume,
            "capabilities": self.capabilities.to_dict(),
        }


@dataclass(frozen=True)
class ExecutionEnvelope:
    schema_version: str
    run_id: str
    created_at: str
    request: ExecutionRequest
    resolved: ResolvedExecution
    degradations: tuple[Degradation, ...]
    provenance: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise InvalidExecutionConfig(
                f"unsupported execution schema: {self.schema_version!r}"
            )
        _identifier(self.run_id, field_name="run id")
        object.__setattr__(self, "degradations", tuple(self.degradations))
        object.__setattr__(
            self,
            "provenance",
            MappingProxyType({str(k): str(v) for k, v in self.provenance.items()}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "request": self.request.to_dict(),
            "resolved": self.resolved.to_dict(),
            "degradations": [item.to_dict() for item in self.degradations],
            "provenance": dict(self.provenance),
        }


def parse_requirements(
    raw: Any,
    *,
    defaults: Iterable[CapabilityRequirement] = (),
) -> tuple[CapabilityRequirement, ...]:
    """Parse list/dict requirement forms into a stable tuple."""

    if raw is None:
        return tuple(defaults)
    parsed: list[CapabilityRequirement] = []
    items: list[tuple[Any, Any]]
    if isinstance(raw, Mapping):
        items = list(raw.items())
    elif isinstance(raw, list | tuple):
        items = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise InvalidExecutionConfig("capability requirements must be objects")
            items.append((item.get("capability"), item.get("level")))
    else:
        raise InvalidExecutionConfig("capability requirements must be a mapping or list")
    for capability, level in items:
        try:
            parsed.append(
                CapabilityRequirement(
                    capability=str(capability),
                    level=(
                        level
                        if isinstance(level, RequirementLevel)
                        else RequirementLevel(str(level))
                    ),
                )
            )
        except (TypeError, ValueError) as exc:
            raise InvalidExecutionConfig(
                f"invalid capability requirement {capability!r}: {level!r}"
            ) from exc
    return tuple(parsed)


def resolve_capabilities(
    capabilities: CapabilitySet,
    requirements: Iterable[CapabilityRequirement],
) -> tuple[Degradation, ...]:
    degradations: list[Degradation] = []
    for requirement in requirements:
        state = capabilities.state(requirement.capability)
        if requirement.level is RequirementLevel.REQUIRED and state is not CapabilityState.SUPPORTED:
            raise RequiredCapabilityUnavailable(requirement.capability, state)
        if requirement.level is RequirementLevel.FORBIDDEN and state in {
            CapabilityState.SUPPORTED,
            CapabilityState.CONDITIONAL,
        }:
            raise ForbiddenCapabilityPresent(requirement.capability, state)
        if requirement.level is RequirementLevel.PREFERRED and state is not CapabilityState.SUPPORTED:
            degradations.append(
                Degradation(
                    capability=requirement.capability,
                    requested=RequirementLevel.PREFERRED.value,
                    resolved=state.value,
                    reason="preferred capability is not proven supported",
                )
            )
    return tuple(degradations)


def resolve_connection(
    *,
    connection_id: str,
    runtime_id: str,
    connections: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a secret-free user connection identity."""

    connection = connections.get(connection_id)
    if not isinstance(connection, Mapping):
        raise InvalidExecutionConfig(f"Unknown connection {connection_id!r}.")
    _assert_secret_free(connection)
    configured_runtime = _identifier(
        connection.get("agent_runtime"),
        field_name="connection.agent_runtime",
    )
    if configured_runtime != runtime_id:
        raise InvalidExecutionConfig(
            f"Connection {connection_id!r} belongs to runtime "
            f"{configured_runtime!r}, not {runtime_id!r}."
        )
    return {
        "connection": connection_id,
        "agent_runtime": configured_runtime,
        "inference_provider": _identifier(
            connection.get("inference_provider"),
            field_name="connection.inference_provider",
        ),
        "wire_protocol": _identifier(
            connection.get("wire_protocol"),
            field_name="connection.wire_protocol",
        ),
        "endpoint_identity": _identifier(
            connection.get("endpoint_identity") or "runtime-config",
            field_name="connection.endpoint_identity",
        ),
        "models": dict(connection.get("models") or {}),
        "pinned_models": list(connection.get("pinned_models") or []),
        "discovery": (
            dict(connection["discovery"])
            if isinstance(connection.get("discovery"), Mapping)
            else connection.get("discovery")
        ),
        "capabilities": dict(connection.get("capabilities") or {}),
    }


def build_execution_envelope(
    *,
    request: ExecutionRequest,
    surface: str,
    runtime_version: str | None,
    connection: Mapping[str, Any],
    runtime_capabilities: CapabilitySet,
    resolved_model: str | None,
    resolved_effort: str | None,
    resume: str,
    degradations: Iterable[Degradation] = (),
    provenance: Mapping[str, str] | None = None,
    run_id: str | None = None,
) -> ExecutionEnvelope:
    capability_degradations = resolve_capabilities(
        runtime_capabilities, request.requirements
    )
    all_degradations = tuple(degradations) + capability_degradations
    resolved = ResolvedExecution(
        surface=surface,
        runtime_id=request.requested_runtime,
        runtime_version=runtime_version,
        connection=str(connection["connection"]),
        inference_provider=str(connection["inference_provider"]),
        wire_protocol=str(connection["wire_protocol"]),
        endpoint_identity=str(connection["endpoint_identity"]),
        model=validate_model_id(resolved_model),
        effort=resolved_effort,
        resume=resume,
        capabilities=runtime_capabilities,
    )
    return ExecutionEnvelope(
        schema_version=SCHEMA_VERSION,
        run_id=run_id or f"run-{uuid.uuid4().hex}",
        created_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        request=request,
        resolved=resolved,
        degradations=all_degradations,
        provenance=provenance or {},
    )
