"""Provider registry discovery, TTL, provenance, and safe fallback contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from provider_registry import (
    DiscoveryFailure,
    ModelCatalogUnavailable,
    NativeProfile,
    NativeProfileResolver,
    ProviderRegistry,
    _NoRedirect,
    _models_url,
)
from routes import providers as providers_route


def _connection(
    *,
    adapter: str = "openai",
    store: str = "codex-config",
    pinned: tuple[str, ...] = ("provider/model-pinned",),
) -> dict:
    runtime = "claude" if store == "claude-providers" else "codex"
    return {
        "agent_runtime": runtime,
        "inference_provider": "custom",
        "wire_protocol": "responses",
        "endpoint_identity": "trusted-native-profile",
        "models": {"strong": pinned[0]} if pinned else {},
        "pinned_models": list(pinned[1:]),
        "capabilities": {},
        "discovery": {
            "adapter": adapter,
            "store": store,
            "profile": "work",
            "ttl_seconds": 30,
            "timeout_seconds": 1,
        },
    }


class _Profiles:
    def __init__(self, profile: NativeProfile):
        self.profile = profile

    def resolve(self, _discovery):
        return self.profile


def _registry(
    tmp_path: Path,
    *,
    clock,
    transport,
    adapter: str = "openai",
) -> ProviderRegistry:
    return ProviderRegistry(
        cache_path=tmp_path / "registry.json",
        clock=clock,
        transport=transport,
        profile_resolver=_Profiles(
            NativeProfile(
                adapter=adapter,
                base_url="https://models.example.test/api",
                api_key="credential-never-serialized",
                models=(),
            )
        ),
    )


def test_live_discovery_is_cached_with_capability_provenance_and_no_secret(tmp_path):
    now = [1000.0]
    calls = []

    def transport(url, headers, timeout):
        calls.append((url, headers, timeout))
        return {
            "data": [
                {
                    "id": "provider/model-pinned",
                    "capabilities": {"vision": "supported", "tools": "conditional"},
                },
                {"id": "provider/model-new"},
            ]
        }

    registry = _registry(tmp_path, clock=lambda: now[0], transport=transport)
    first = registry.resolve(
        connection_id="work",
        connection=_connection(),
        requested_model="provider/model-pinned",
    )
    second = registry.resolve(
        connection_id="work",
        connection=_connection(),
        requested_model="provider/model-pinned",
    )

    assert len(calls) == 1
    assert calls[0][0] == "https://models.example.test/api/v1/models"
    assert calls[0][1]["Authorization"] == "Bearer credential-never-serialized"
    assert first.state == second.state == "fresh"
    assert first.capabilities == {"vision": "supported", "tools": "conditional"}
    assert first.provenance()["model_catalog_source"] == "openai@1:work"
    cache_text = (tmp_path / "registry.json").read_text(encoding="utf-8")
    assert "credential-never-serialized" not in cache_text
    assert (tmp_path / "registry.json").stat().st_mode & 0o777 == 0o600


def test_expired_catalog_refreshes_and_rejects_missing_model(tmp_path):
    now = [1000.0]
    responses = [
        {"data": [{"id": "provider/model-pinned"}]},
        {"data": [{"id": "provider/model-new"}]},
    ]
    registry = _registry(
        tmp_path,
        clock=lambda: now[0],
        transport=lambda *_args: responses.pop(0),
    )
    registry.resolve(
        connection_id="work",
        connection=_connection(),
        requested_model="provider/model-pinned",
    )
    now[0] += 31

    with pytest.raises(ModelCatalogUnavailable, match="not in the fresh catalog"):
        registry.resolve(
            connection_id="work",
            connection=_connection(),
            requested_model="provider/model-pinned",
        )


def test_changed_profile_identity_never_reuses_a_fresh_old_catalog(tmp_path):
    calls = []

    def transport(_url, _headers, _timeout):
        calls.append(True)
        return {"data": [{"id": "provider/model-pinned"}]}

    registry = _registry(tmp_path, clock=lambda: 1000.0, transport=transport)
    first_connection = _connection()
    registry.resolve(
        connection_id="work",
        connection=first_connection,
        requested_model="provider/model-pinned",
    )
    changed_connection = _connection()
    changed_connection["discovery"]["profile"] = "other-account"
    registry.resolve(
        connection_id="work",
        connection=changed_connection,
        requested_model="provider/model-pinned",
    )

    assert len(calls) == 2


def test_discovery_failure_allows_only_explicit_pinned_stale_fallback(tmp_path):
    registry = _registry(
        tmp_path,
        clock=lambda: 1000.0,
        transport=lambda *_args: (_ for _ in ()).throw(RuntimeError("network")),
    )
    # Transport adapters are expected to surface typed failures. Simulate a
    # missing native profile instead so the registry owns the error category.
    registry.profile_resolver = _Profiles(
        NativeProfile(
            adapter="native-static",
            base_url=None,
            api_key=None,
            models=(),
        )
    )
    connection = _connection(adapter="native-static")

    pinned = registry.resolve(
        connection_id="work",
        connection=connection,
        requested_model="provider/model-pinned",
    )
    assert pinned.state == "stale"
    assert pinned.selection == "explicit_pinned_fallback"
    assert pinned.last_error == "empty_catalog"

    with pytest.raises(ModelCatalogUnavailable, match="not an explicit pinned"):
        registry.resolve(
            connection_id="work",
            connection=connection,
            requested_model="provider/unpinned",
            force_refresh=True,
        )


@pytest.mark.parametrize(
    ("adapter", "expected_header"),
    [
        ("anthropic", "x-api-key"),
        ("openai", "Authorization"),
        ("minimax", "Authorization"),
        ("moonshot", "Authorization"),
        ("custom-openai", "Authorization"),
    ],
)
def test_protocol_adapters_use_expected_auth_shape_without_project_secrets(
    tmp_path, adapter, expected_header
):
    seen = {}

    def transport(_url, headers, _timeout):
        seen.update(headers)
        return {"models": [{"name": "provider/model-pinned"}]}

    registry = _registry(
        tmp_path,
        clock=lambda: 1000.0,
        transport=transport,
        adapter=adapter,
    )
    result = registry.resolve(
        connection_id="work",
        connection=_connection(
            adapter=adapter,
            store="claude-providers" if adapter == "anthropic" else "codex-config",
        ),
        requested_model="provider/model-pinned",
    )

    assert result.state == "fresh"
    assert expected_header in seen
    assert ("x-api-key" in seen) is (adapter == "anthropic")


def test_native_profile_resolver_reads_trusted_stores_and_environment(
    tmp_path, monkeypatch
):
    claude = tmp_path / "providers.json"
    claude.write_text(
        json.dumps(
            {
                "providers": {
                    "work": {
                        "base_url": "https://anthropic.example/v1/",
                        "api_key_env": "CLADE_TEST_ANTHROPIC_KEY",
                        "models": ["claude/custom"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    codex = tmp_path / "config.toml"
    codex.write_text(
        """
[model_providers.work]
base_url = "https://openai.example/v1/"
env_key = "CLADE_TEST_OPENAI_KEY"
models = ["gpt/custom"]
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLADE_CLAUDE_PROVIDERS_FILE", str(claude))
    monkeypatch.setenv("CLADE_CODEX_CONFIG_FILE", str(codex))
    monkeypatch.setenv("CLADE_TEST_ANTHROPIC_KEY", "anthropic-secret")
    monkeypatch.setenv("CLADE_TEST_OPENAI_KEY", "openai-secret")
    resolver = NativeProfileResolver(home=tmp_path)

    claude_profile = resolver.resolve(
        {"store": "claude-providers", "profile": "work", "adapter": "anthropic"}
    )
    codex_profile = resolver.resolve(
        {"store": "codex-config", "profile": "work", "adapter": "openai"}
    )

    assert claude_profile.base_url == "https://anthropic.example/v1"
    assert claude_profile.api_key == "anthropic-secret"
    assert claude_profile.models == ("claude/custom",)
    assert codex_profile.base_url == "https://openai.example/v1"
    assert codex_profile.api_key == "openai-secret"
    assert codex_profile.models == ("gpt/custom",)


def test_catalog_transport_rejects_insecure_endpoints_and_redirects():
    with pytest.raises(DiscoveryFailure, match="insecure_or_invalid_endpoint"):
        _models_url("http://models.example.test")
    assert _NoRedirect().redirect_request(
        None, None, 302, "redirect", {}, "https://attacker.example"
    ) is None


@pytest.mark.asyncio
async def test_registry_routes_return_only_safe_projection(monkeypatch):
    settings = {"connections": {"work": _connection()}}
    calls = []

    class FakeRegistry:
        def inspect(self, received, *, force_refresh=False):
            calls.append((received, force_refresh))
            return {"schema_version": "clade.provider_registry/v1", "connections": []}

    monkeypatch.setattr(providers_route, "GLOBAL_SETTINGS", settings)
    monkeypatch.setattr(providers_route, "DEFAULT_REGISTRY", FakeRegistry())

    assert (await providers_route.inspect_provider_registry())["connections"] == []
    assert (await providers_route.refresh_provider_registry())["connections"] == []
    assert calls == [(settings, False), (settings, True)]
