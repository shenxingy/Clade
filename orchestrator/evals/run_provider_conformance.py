#!/usr/bin/env python3
"""Deterministic provider/runtime/surface fixtures plus credential-gated smoke.

Offline mode drives the real registry, execution resolver, runtime adapters,
native profile readers, and canonical surface guidance with sanitized fixtures.
Live mode performs one read-only model-catalog request and reports only a count,
digest, and safe error category. It never prints endpoints, headers, keys, or
model IDs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ORCHESTRATOR_ROOT.parent
if str(ORCHESTRATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_ROOT))

from provider_registry import (  # noqa: E402
    DiscoveryFailure,
    NativeProfile,
    NativeProfileResolver,
    ProviderRegistry,
    _catalog_digest,
    _default_transport,
    _discover,
)


CASES_DIR = Path(__file__).resolve().parent / "provider_cases"
SURFACES = {
    "claude-code": (
        REPO_ROOT / "configs/skills/provider/surfaces/claude-code.md",
        "# Claude Code connection adapter",
    ),
    "codex": (
        REPO_ROOT / "configs/skills/provider/surfaces/codex.md",
        "# Codex connection adapter",
    ),
    "mcp": (
        REPO_ROOT / "configs/skills/provider/surfaces/mcp.md",
        "# MCP connection adapter",
    ),
    "generic": (
        REPO_ROOT / "configs/skills/provider/surfaces/generic.md",
        "# Generic connection adapter",
    ),
}
REQUIRED_FIELDS = {
    "id",
    "surface",
    "runtime",
    "inference_provider",
    "wire_protocol",
    "adapter",
    "store",
    "wire_model",
    "catalog_capabilities",
    "expected",
}
_FORBIDDEN_KEY_MARKERS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)
_FAKE_KEY = "fixture-canary-never-serialize"


def _walk(value: Any, path: str = "fixture"):
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield f"{path}.{key}", key, nested
            yield from _walk(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _walk(nested, f"{path}[{index}]")


def validate_case(case: Any, source: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(case, dict):
        return [f"{source}: fixture must be an object"]
    missing = sorted(REQUIRED_FIELDS - set(case))
    if missing:
        errors.append(f"{source}: missing fields {missing}")
    if case.get("surface") not in SURFACES:
        errors.append(f"{source}: unsupported surface {case.get('surface')!r}")
    if case.get("runtime") not in {"claude", "codex"}:
        errors.append(f"{source}: unsupported runtime {case.get('runtime')!r}")
    expected_store = {
        "claude": "claude-providers",
        "codex": "codex-config",
    }.get(case.get("runtime"))
    if expected_store and case.get("store") != expected_store:
        errors.append(f"{source}: runtime requires store {expected_store!r}")
    for path, key, nested in _walk(case):
        lowered = str(key).lower()
        if (
            lowered != "secret_exposed"
            and any(marker in lowered for marker in _FORBIDDEN_KEY_MARKERS)
        ):
            errors.append(f"{path}: secret-bearing fixture key is forbidden")
        if isinstance(nested, str) and (
            "://" in nested
            or nested.startswith(("~", "/"))
            or "-----BEGIN " in nested
        ):
            errors.append(f"{path}: endpoints, paths, and key material are forbidden")
    return errors


def load_cases(path: Path = CASES_DIR) -> tuple[list[dict[str, Any]], list[str]]:
    cases: list[dict[str, Any]] = []
    errors: list[str] = []
    for fixture in sorted(path.glob("*.json")):
        try:
            case = json.loads(fixture.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{fixture.name}: unreadable JSON ({type(exc).__name__})")
            continue
        errors.extend(validate_case(case, fixture.name))
        if isinstance(case, dict) and case.get("id") != fixture.stem:
            errors.append(f"{fixture.name}: id must match filename stem")
        cases.append(case)
    if not cases:
        errors.append(f"no provider fixtures found in {path}")
    return cases, errors


def _write_native_profile(root: Path, case: Mapping[str, Any]) -> dict[str, str]:
    profile = "fixture-profile"
    model = case["wire_model"]
    adapter = case["adapter"]
    if case["store"] == "claude-providers":
        profile_path = root / "providers.json"
        provider: dict[str, Any] = {
            "runtime": "claude",
            "name": "Sanitized fixture",
            "models": [model],
        }
        if adapter != "native-static":
            provider.update(
                {
                    "base_url": "https://fixture.invalid",
                    "api_key_env": "CLADE_CONFORMANCE_FAKE_KEY",
                }
            )
        profile_path.write_text(
            json.dumps({"providers": {profile: provider}}),
            encoding="utf-8",
        )
        return {"CLADE_CLAUDE_PROVIDERS_FILE": str(profile_path)}

    profile_path = root / "config.toml"
    lines = [
        f"[model_providers.{profile}]",
        'name = "Sanitized fixture"',
        f'models = ["{model}"]',
    ]
    if adapter != "native-static":
        lines.extend(
            [
                'base_url = "https://fixture.invalid"',
                'env_key = "CLADE_CONFORMANCE_FAKE_KEY"',
            ]
        )
    profile_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"CLADE_CODEX_CONFIG_FILE": str(profile_path)}


def run_case(case: Mapping[str, Any]) -> dict[str, Any]:
    # Offline fixture replay needs the full orchestrator dependency set. Keep
    # these imports out of module scope so credential-gated live mode can SKIP
    # safely on a bare stdlib runner before optional dependencies are installed.
    from execution_resolver import resolve_execution
    from worker_provider import get_agent_runtime
    from worker_routing import WorkerRoute

    errors = validate_case(dict(case), str(case.get("id") or "fixture"))
    if errors:
        raise ValueError("; ".join(errors))
    with tempfile.TemporaryDirectory(prefix="clade-provider-conformance-") as raw:
        root = Path(raw)
        profile_env = _write_native_profile(root, case)
        profile_env["CLADE_CONFORMANCE_FAKE_KEY"] = _FAKE_KEY
        profile_env["ANTHROPIC_BASE_URL"] = "https://wrong.invalid"
        profile_env["ANTHROPIC_API_KEY"] = "wrong-canary"
        connection_id = f"{case['runtime']}-fixture"
        connection = {
            "agent_runtime": case["runtime"],
            "inference_provider": case["inference_provider"],
            "wire_protocol": case["wire_protocol"],
            "endpoint_identity": "sanitized-native-profile",
            "models": {"logical-strong": case["wire_model"]},
            "pinned_models": [case["wire_model"]],
            "capabilities": {},
            "discovery": {
                "adapter": case["adapter"],
                "store": case["store"],
                "profile": "fixture-profile",
                "ttl_seconds": 60,
            },
        }
        observed_headers: dict[str, str] = {}

        def transport(_url, headers, _timeout):
            observed_headers.update(headers)
            return {
                "data": [
                    {
                        "id": case["wire_model"],
                        "capabilities": case["catalog_capabilities"],
                    }
                ]
            }

        with patch.dict(os.environ, profile_env, clear=False):
            registry = ProviderRegistry(
                cache_path=root / "registry-cache.json",
                transport=transport,
                profile_resolver=NativeProfileResolver(home=root),
            )
            adapter = get_agent_runtime(case["runtime"])
            envelope = resolve_execution(
                task={
                    "model": "logical-strong",
                    "execution_profile": "implement",
                    "execution_requirements": {"repository_read": "required"},
                },
                settings={
                    "runtime_connections": {case["runtime"]: connection_id},
                    "connections": {connection_id: connection},
                },
                route=WorkerRoute(
                    case["runtime"],
                    "logical-strong",
                    "high",
                    "provider conformance fixture",
                ),
                adapter=adapter,
                registry=registry,
            )
            task_file = root / "task.md"
            task_file.write_text("sanitized fixture", encoding="utf-8")
            command = adapter.build_command(
                task_file=task_file,
                requested_model=envelope.resolved.model,
                task_type=None,
                mcp_config=None,
                effort=envelope.resolved.effort,
                connection=connection,
            )
            worker_env = {
                "ANTHROPIC_BASE_URL": "https://wrong.invalid",
                "ANTHROPIC_API_KEY": "wrong-canary",
            }
            adapter.apply_connection_env(connection, worker_env)

        cache_text = (root / "registry-cache.json").read_text(encoding="utf-8")
        capability_name = case["expected"]["capability"]["name"]
        capability = envelope.resolved.capabilities.to_dict()[capability_name]
        surface_path, surface_marker = SURFACES[case["surface"]]
        if case["runtime"] == "codex":
            profile_bound = 'model_provider="fixture-profile"' in command
        elif case["adapter"] == "native-static":
            profile_bound = not (
                worker_env.get("ANTHROPIC_BASE_URL")
                or worker_env.get("ANTHROPIC_API_KEY")
            )
        else:
            profile_bound = (
                worker_env.get("ANTHROPIC_BASE_URL") == "https://fixture.invalid"
                and worker_env.get("ANTHROPIC_API_KEY") == _FAKE_KEY
            )
        serialized = json.dumps(envelope.to_dict(), sort_keys=True) + command + cache_text
        return {
            "id": case["id"],
            "surface": case["surface"],
            "runtime": envelope.resolved.runtime_id,
            "inference_provider": envelope.resolved.inference_provider,
            "wire_protocol": envelope.resolved.wire_protocol,
            "model": envelope.resolved.model,
            "catalog_state": envelope.provenance["model_catalog_state"],
            "catalog_source": envelope.provenance["model_catalog_source"],
            "capability": {"name": capability_name, **capability},
            "profile_bound": profile_bound,
            "surface_marker_present": (
                surface_marker in surface_path.read_text(encoding="utf-8")
            ),
            "secret_exposed": any(
                secret in serialized
                for secret in (_FAKE_KEY, "wrong-canary")
            ),
            "auth_shape": (
                "x-api-key"
                if "x-api-key" in observed_headers
                else "bearer"
                if "Authorization" in observed_headers
                else "none"
            ),
        }


def run_offline(path: Path = CASES_DIR) -> tuple[list[dict[str, Any]], list[str]]:
    cases, errors = load_cases(path)
    if errors:
        return [], errors
    results: list[dict[str, Any]] = []
    for case in cases:
        result = run_case(case)
        if result != case["expected"]:
            errors.append(
                f"{case['id']}: result drift\n"
                f"expected={json.dumps(case['expected'], sort_keys=True)}\n"
                f"actual={json.dumps(result, sort_keys=True)}"
            )
        results.append(result)
    return results, errors


def live_smoke(
    adapter: str,
    *,
    transport=_default_transport,
) -> tuple[dict[str, Any] | None, str | None]:
    defaults = {
        "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com"),
        "openai": ("OPENAI_API_KEY", "https://api.openai.com"),
    }
    env_name, default_url = defaults.get(
        adapter,
        ("CLADE_PROVIDER_SMOKE_API_KEY", ""),
    )
    api_key = os.environ.get(env_name)
    base_url = os.environ.get("CLADE_PROVIDER_SMOKE_BASE_URL") or default_url
    if not api_key or not base_url:
        return None, f"missing_{env_name.lower()}"
    try:
        models, capabilities = _discover(
            NativeProfile(
                adapter=adapter,
                base_url=base_url,
                api_key=api_key,
                models=(),
            ),
            timeout=5.0,
            transport=transport,
        )
    except DiscoveryFailure as exc:
        return None, exc.category
    return {
        "adapter": adapter,
        "model_count": len(models),
        "catalog_digest": _catalog_digest(models, capabilities),
    }, None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live",
        choices=("anthropic", "openai", "minimax", "moonshot", "custom-openai"),
    )
    args = parser.parse_args()
    if args.live:
        result, error = live_smoke(args.live)
        if result is None and error and error.startswith("missing_"):
            print(f"SKIP provider live smoke: {args.live} credential is unavailable")
            return 0
        if result is None:
            print(f"FAIL provider live smoke: {args.live} category={error}")
            return 1
        print(
            "PASS provider live smoke: "
            f"adapter={result['adapter']} models={result['model_count']} "
            f"digest={result['catalog_digest']}"
        )
        return 0
    results, errors = run_offline()
    if errors:
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        return 1
    print(f"PASS provider conformance: {len(results)} sanitized fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
