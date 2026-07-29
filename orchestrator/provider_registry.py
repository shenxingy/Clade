"""Secret-safe live model discovery with TTL and explicit pinned fallback."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from execution_envelope import (
    CapabilityState,
    InvalidExecutionConfig,
    validate_model_id,
)


SCHEMA_VERSION = "clade.provider_registry/v1"
ADAPTER_VERSION = "1"
DEFAULT_TTL_SECONDS = 300
DEFAULT_TIMEOUT_SECONDS = 2.0
_ADAPTERS = {
    "anthropic",
    "openai",
    "minimax",
    "moonshot",
    "custom-openai",
    "native-static",
}
_STORES = {"claude-providers", "codex-config"}
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ModelCatalogUnavailable(InvalidExecutionConfig):
    """Raised when a discovery-managed model cannot be selected truthfully."""


class DiscoveryFailure(RuntimeError):
    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


@dataclass(frozen=True)
class NativeProfile:
    adapter: str
    base_url: str | None
    api_key: str | None
    models: tuple[str, ...]


@dataclass(frozen=True)
class CatalogResolution:
    model: str | None
    models: tuple[str, ...]
    capabilities: Mapping[str, str]
    state: str
    selection: str
    source: str
    observed_at: str | None
    catalog_digest: str | None
    last_error: str | None = None

    def provenance(self) -> dict[str, str]:
        values = {
            "model_catalog_state": self.state,
            "model_catalog_source": self.source,
            "model_selection": self.selection,
        }
        if self.observed_at:
            values["model_catalog_observed_at"] = self.observed_at
        if self.catalog_digest:
            values["model_catalog_digest"] = self.catalog_digest
        if self.last_error:
            values["model_catalog_error"] = self.last_error
        return values


def _iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def _safe_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, parsed))


def _safe_float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, parsed))


def _discovery_config(connection: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = connection.get("discovery")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise InvalidExecutionConfig("connection.discovery must be an object")
    adapter = str(raw.get("adapter") or "").strip()
    store = str(raw.get("store") or "").strip()
    profile = str(raw.get("profile") or "").strip()
    if adapter not in _ADAPTERS:
        raise InvalidExecutionConfig(f"unsupported discovery adapter {adapter!r}")
    if store not in _STORES:
        raise InvalidExecutionConfig(f"unsupported native discovery store {store!r}")
    if not profile:
        raise InvalidExecutionConfig("connection.discovery.profile is required")
    default_model = raw.get("default_model")
    if default_model is not None:
        default_model = validate_model_id(default_model, allow_none=False)
    return {
        "adapter": adapter,
        "store": store,
        "profile": profile,
        "ttl_seconds": _safe_int(
            raw.get("ttl_seconds"),
            DEFAULT_TTL_SECONDS,
            minimum=30,
            maximum=86400,
        ),
        "timeout_seconds": _safe_float(
            raw.get("timeout_seconds"),
            DEFAULT_TIMEOUT_SECONDS,
            minimum=0.1,
            maximum=10.0,
        ),
        "default_model": default_model,
    }


def _validated_models(values: Any) -> tuple[str, ...]:
    if isinstance(values, Mapping):
        values = list(values.values())
    if not isinstance(values, (list, tuple)):
        return ()
    models = []
    for value in values:
        try:
            model = validate_model_id(value, allow_none=False)
        except InvalidExecutionConfig:
            continue
        if model and model not in models:
            models.append(model)
    return tuple(models)


class NativeProfileResolver:
    """Resolve trusted user profile references without serializing secrets."""

    def __init__(self, home: Path | None = None):
        self.home = home or Path.home()

    def resolve(self, discovery: Mapping[str, Any]) -> NativeProfile:
        store = discovery["store"]
        profile_id = discovery["profile"]
        if store == "claude-providers":
            path = Path(
                os.environ.get(
                    "CLADE_CLAUDE_PROVIDERS_FILE",
                    self.home / ".claude" / "providers.json",
                )
            )
            try:
                root = json.loads(path.read_text(encoding="utf-8"))
                profile = root["providers"][profile_id]
            except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise DiscoveryFailure("profile_unavailable") from exc
            if not isinstance(profile, Mapping):
                raise DiscoveryFailure("profile_invalid")
            env_name = profile.get("api_key_env")
            if env_name is not None and (
                not isinstance(env_name, str) or not _ENV_NAME.fullmatch(env_name)
            ):
                raise DiscoveryFailure("profile_invalid")
            return NativeProfile(
                adapter=discovery["adapter"],
                base_url=(
                    str(profile.get("base_url")).rstrip("/")
                    if profile.get("base_url")
                    else None
                ),
                api_key=os.environ.get(env_name) if env_name else None,
                models=_validated_models(profile.get("models")),
            )

        path = Path(
            os.environ.get(
                "CLADE_CODEX_CONFIG_FILE",
                self.home / ".codex" / "config.toml",
            )
        )
        try:
            root = tomllib.loads(path.read_text(encoding="utf-8"))
            profile = root["model_providers"][profile_id]
        except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
            raise DiscoveryFailure("profile_unavailable") from exc
        if not isinstance(profile, Mapping):
            raise DiscoveryFailure("profile_invalid")
        env_name = profile.get("env_key")
        if env_name is not None and (
            not isinstance(env_name, str) or not _ENV_NAME.fullmatch(env_name)
        ):
            raise DiscoveryFailure("profile_invalid")
        models = profile.get("models")
        return NativeProfile(
            adapter=discovery["adapter"],
            base_url=(
                str(profile.get("base_url")).rstrip("/")
                if profile.get("base_url")
                else None
            ),
            api_key=os.environ.get(env_name) if env_name else None,
            models=_validated_models(models),
        )


Transport = Callable[[str, Mapping[str, str], float], Mapping[str, Any]]


def _default_transport(
    url: str,
    headers: Mapping[str, str],
    timeout: float,
) -> Mapping[str, Any]:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        category = "auth" if exc.code in {401, 403} else "remote_error"
        raise DiscoveryFailure(category) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise DiscoveryFailure("timeout_or_unreachable") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscoveryFailure("invalid_response") from exc
    if not isinstance(payload, Mapping):
        raise DiscoveryFailure("invalid_response")
    return payload


def _models_url(base_url: str) -> str:
    if base_url.endswith("/models"):
        return base_url
    if base_url.endswith("/v1"):
        return f"{base_url}/models"
    return f"{base_url}/v1/models"


def _parse_catalog(payload: Mapping[str, Any]) -> tuple[tuple[str, ...], dict[str, dict[str, str]]]:
    raw_models = payload.get("data", payload.get("models"))
    if not isinstance(raw_models, list):
        raise DiscoveryFailure("invalid_response")
    models: list[str] = []
    capabilities: dict[str, dict[str, str]] = {}
    for raw in raw_models:
        if isinstance(raw, str):
            model_value, raw_capabilities = raw, {}
        elif isinstance(raw, Mapping):
            model_value = raw.get("id") or raw.get("name")
            raw_capabilities = raw.get("capabilities") or {}
        else:
            continue
        try:
            model = validate_model_id(model_value, allow_none=False)
        except InvalidExecutionConfig:
            continue
        if not model or model in models:
            continue
        models.append(model)
        if isinstance(raw_capabilities, Mapping):
            states = {}
            for name, state_value in raw_capabilities.items():
                raw_state = (
                    state_value.get("state")
                    if isinstance(state_value, Mapping)
                    else state_value
                )
                try:
                    state = CapabilityState(str(raw_state)).value
                    validate_model_id(name, allow_none=False)
                except (InvalidExecutionConfig, ValueError):
                    continue
                states[str(name)] = state
            if states:
                capabilities[model] = states
    if not models:
        raise DiscoveryFailure("empty_catalog")
    return tuple(models), capabilities


def _discover(
    profile: NativeProfile,
    *,
    timeout: float,
    transport: Transport,
) -> tuple[tuple[str, ...], dict[str, dict[str, str]]]:
    if profile.adapter == "native-static":
        if not profile.models:
            raise DiscoveryFailure("empty_catalog")
        return profile.models, {}
    if not profile.base_url:
        raise DiscoveryFailure("endpoint_unavailable")
    headers = {"Accept": "application/json"}
    if profile.adapter == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
        if profile.api_key:
            headers["x-api-key"] = profile.api_key
    elif profile.api_key:
        headers["Authorization"] = f"Bearer {profile.api_key}"
    payload = transport(_models_url(profile.base_url), headers, timeout)
    return _parse_catalog(payload)


def _catalog_digest(models: tuple[str, ...], capabilities: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {"models": models, "capabilities": capabilities},
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _discovery_digest(discovery: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {
            key: discovery.get(key)
            for key in (
                "adapter",
                "store",
                "profile",
                "ttl_seconds",
                "timeout_seconds",
                "default_model",
            )
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


class ProviderRegistry:
    def __init__(
        self,
        *,
        cache_path: Path | None = None,
        clock: Callable[[], float] = time.time,
        transport: Transport = _default_transport,
        profile_resolver: NativeProfileResolver | None = None,
    ):
        self.cache_path = cache_path or (
            Path.home() / ".claude" / "orchestrator" / "provider-registry-cache.json"
        )
        self.clock = clock
        self.transport = transport
        self.profile_resolver = profile_resolver or NativeProfileResolver()
        self._cache = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": SCHEMA_VERSION, "connections": {}}
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != SCHEMA_VERSION
            or not isinstance(payload.get("connections"), dict)
        ):
            return {"schema_version": SCHEMA_VERSION, "connections": {}}
        return payload

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.cache_path.name}.",
            suffix=".tmp",
            dir=self.cache_path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(self._cache, handle, sort_keys=True, indent=2)
                handle.write("\n")
            os.chmod(temporary, 0o600)
            temporary.replace(self.cache_path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _pinned(connection: Mapping[str, Any]) -> tuple[str, ...]:
        model_map = connection.get("models")
        values = list(model_map.values()) if isinstance(model_map, Mapping) else []
        explicit = connection.get("pinned_models")
        if isinstance(explicit, (list, tuple)):
            values.extend(explicit)
        return _validated_models(values)

    @staticmethod
    def validate_connection(connection: Mapping[str, Any]) -> None:
        """Validate registry metadata without reading profiles or making I/O."""

        discovery = _discovery_config(connection)
        runtime = connection.get("agent_runtime")
        if discovery:
            expected_store = {
                "claude": "claude-providers",
                "codex": "codex-config",
            }.get(runtime)
            if expected_store and discovery["store"] != expected_store:
                raise InvalidExecutionConfig(
                    f"{runtime} connections require discovery.store={expected_store!r}"
                )
        model_map = connection.get("models")
        if model_map is not None and not isinstance(model_map, Mapping):
            raise InvalidExecutionConfig("connection.models must be an object")
        pinned = connection.get("pinned_models")
        if pinned is not None and not isinstance(pinned, (list, tuple)):
            raise InvalidExecutionConfig("connection.pinned_models must be a list")
        candidates = list(model_map.values()) if isinstance(model_map, Mapping) else []
        if isinstance(pinned, (list, tuple)):
            candidates.extend(pinned)
        for model in candidates:
            validate_model_id(model, allow_none=False)

    def _refresh(
        self,
        connection_id: str,
        connection: Mapping[str, Any],
        discovery: Mapping[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None]:
        now = self.clock()
        try:
            profile = self.profile_resolver.resolve(discovery)
            models, capabilities = _discover(
                profile,
                timeout=discovery["timeout_seconds"],
                transport=self.transport,
            )
            entry = {
                "adapter": discovery["adapter"],
                "discovery_digest": _discovery_digest(discovery),
                "models": list(models),
                "capabilities": capabilities,
                "observed_at": now,
                "expires_at": now + discovery["ttl_seconds"],
                "catalog_digest": _catalog_digest(models, capabilities),
                "last_error": None,
            }
            self._cache["connections"][connection_id] = entry
            self._save()
            return entry, None
        except DiscoveryFailure as exc:
            existing = self._cache["connections"].get(connection_id)
            if (
                not isinstance(existing, Mapping)
                or existing.get("discovery_digest") != _discovery_digest(discovery)
            ):
                existing = None
            if isinstance(existing, dict):
                existing["last_error"] = exc.category
                existing["failed_at"] = now
            else:
                self._cache["connections"][connection_id] = {
                    "adapter": discovery["adapter"],
                    "discovery_digest": _discovery_digest(discovery),
                    "models": [],
                    "capabilities": {},
                    "observed_at": None,
                    "expires_at": None,
                    "catalog_digest": None,
                    "last_error": exc.category,
                    "failed_at": now,
                }
            self._save()
            return existing if isinstance(existing, dict) else None, exc.category

    def resolve(
        self,
        *,
        connection_id: str,
        connection: Mapping[str, Any],
        requested_model: str | None,
        force_refresh: bool = False,
    ) -> CatalogResolution:
        self.validate_connection(connection)
        discovery = _discovery_config(connection)
        if discovery is None:
            return CatalogResolution(
                model=requested_model,
                models=self._pinned(connection),
                capabilities={},
                state="declared",
                selection="declared_opaque",
                source=f"connection:{connection_id}",
                observed_at=None,
                catalog_digest=None,
            )
        pinned = self._pinned(connection)
        model = requested_model
        if model is None:
            default_model = discovery.get("default_model")
            model = validate_model_id(default_model) if default_model else None
            if model is None and len(pinned) == 1:
                model = pinned[0]
        entry = self._cache["connections"].get(connection_id)
        now = self.clock()
        fresh = (
            isinstance(entry, Mapping)
            and entry.get("discovery_digest") == _discovery_digest(discovery)
            and isinstance(entry.get("expires_at"), int | float)
            and float(entry["expires_at"]) > now
            and not force_refresh
        )
        error = None
        if not fresh:
            entry, error = self._refresh(
                connection_id,
                connection,
                discovery,
            )
        if entry and not error and float(entry.get("expires_at") or 0) > now:
            models = _validated_models(entry.get("models"))
            if model is None:
                raise ModelCatalogUnavailable(
                    f"Connection {connection_id!r} requires an explicit discovered or pinned model."
                )
            if model not in models:
                raise ModelCatalogUnavailable(
                    f"Model {model!r} is not in the fresh catalog for connection {connection_id!r}."
                )
            capabilities = (entry.get("capabilities") or {}).get(model, {})
            return CatalogResolution(
                model=model,
                models=models,
                capabilities=dict(capabilities),
                state="fresh",
                selection="discovered",
                source=f"{discovery['adapter']}@{ADAPTER_VERSION}:{discovery['profile']}",
                observed_at=_iso(entry.get("observed_at")),
                catalog_digest=entry.get("catalog_digest"),
            )
        if model is not None and model in pinned:
            return CatalogResolution(
                model=model,
                models=pinned,
                capabilities={},
                state="stale",
                selection="explicit_pinned_fallback",
                source=f"{discovery['adapter']}@{ADAPTER_VERSION}:{discovery['profile']}",
                observed_at=_iso(entry.get("observed_at")) if entry else None,
                catalog_digest=entry.get("catalog_digest") if entry else None,
                last_error=error or (entry or {}).get("last_error") or "expired",
            )
        raise ModelCatalogUnavailable(
            f"Live model catalog for connection {connection_id!r} is unavailable; "
            f"model {model!r} is not an explicit pinned fallback."
        )

    def inspect_connection(
        self,
        connection_id: str,
        connection: Mapping[str, Any],
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        self.validate_connection(connection)
        discovery = _discovery_config(connection)
        pinned = self._pinned(connection)
        if discovery is None:
            state = "declared"
            models = pinned
            observed_at = expires_at = last_error = digest = None
        else:
            entry = self._cache["connections"].get(connection_id)
            now = self.clock()
            if force_refresh or not (
                isinstance(entry, Mapping)
                and entry.get("discovery_digest") == _discovery_digest(discovery)
                and isinstance(entry.get("expires_at"), int | float)
                and float(entry["expires_at"]) > now
            ):
                entry, last_error = self._refresh(
                    connection_id, connection, discovery
                )
            else:
                last_error = entry.get("last_error")
            models = _validated_models((entry or {}).get("models")) or pinned
            observed_at = _iso((entry or {}).get("observed_at"))
            expires_at = _iso((entry or {}).get("expires_at"))
            digest = (entry or {}).get("catalog_digest")
            if entry and float(entry.get("expires_at") or 0) > now and not last_error:
                state = "fresh"
            elif entry and entry.get("models"):
                state = "stale"
            else:
                state = "unavailable"
        health = {
            "fresh": "healthy",
            "stale": "degraded",
            "unavailable": "unreachable",
            "declared": "unknown",
        }[state]
        return {
            "id": connection_id,
            "agent_runtime": connection.get("agent_runtime"),
            "inference_provider": connection.get("inference_provider"),
            "wire_protocol": connection.get("wire_protocol"),
            "endpoint_identity": connection.get("endpoint_identity"),
            "models": list(models),
            "capabilities": dict(connection.get("capabilities") or {}),
            "catalog": {
                "state": state,
                "source": (
                    f"{discovery['adapter']}@{ADAPTER_VERSION}:{discovery['profile']}"
                    if discovery
                    else f"connection:{connection_id}"
                ),
                "observed_at": observed_at,
                "expires_at": expires_at,
                "digest": digest,
                "last_error": last_error,
                "model_capabilities": dict(
                    (entry or {}).get("capabilities") or {}
                ),
            },
            "health": {"state": health},
            "selection": {
                "pinned_models": list(pinned),
                "stale_fallback": bool(pinned),
            },
        }

    def inspect(
        self,
        settings: Mapping[str, Any],
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        connections = settings.get("connections")
        if not isinstance(connections, Mapping):
            connections = {}
        projected = []
        for connection_id, connection in sorted(connections.items()):
            if not isinstance(connection, Mapping):
                continue
            try:
                projected.append(
                    self.inspect_connection(
                        str(connection_id),
                        connection,
                        force_refresh=force_refresh,
                    )
                )
            except InvalidExecutionConfig as exc:
                projected.append({
                    "id": str(connection_id),
                    "agent_runtime": connection.get("agent_runtime"),
                    "inference_provider": connection.get("inference_provider"),
                    "wire_protocol": connection.get("wire_protocol"),
                    "endpoint_identity": connection.get("endpoint_identity"),
                    "models": [],
                    "capabilities": {},
                    "catalog": {
                        "state": "unavailable",
                        "source": "invalid-config",
                        "observed_at": None,
                        "expires_at": None,
                        "digest": None,
                        "last_error": type(exc).__name__,
                        "model_capabilities": {},
                    },
                    "health": {"state": "unreachable"},
                    "selection": {
                        "pinned_models": [],
                        "stale_fallback": False,
                    },
                })
        return {
            "schema_version": SCHEMA_VERSION,
            "observed_at": _iso(self.clock()),
            "connections": projected,
        }


DEFAULT_REGISTRY = ProviderRegistry()
