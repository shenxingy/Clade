"""Cross-layer provider/runtime/surface conformance fixture contracts."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys

from provider_registry import DiscoveryFailure
from evals import run_provider_conformance as conformance


def test_all_sanitized_provider_fixtures_match_real_runtime_contracts():
    cases, schema_errors = conformance.load_cases()
    results, drift_errors = conformance.run_offline()

    assert schema_errors == []
    assert len(cases) == len(results) == 6
    assert drift_errors == []
    assert {result["runtime"] for result in results} == {"claude", "codex"}
    assert {result["surface"] for result in results} == {
        "claude-code",
        "codex",
        "mcp",
        "generic",
    }
    assert all(result["profile_bound"] for result in results)
    assert all(not result["secret_exposed"] for result in results)


def test_fixture_schema_rejects_endpoints_paths_and_secret_material():
    cases, errors = conformance.load_cases()
    assert errors == []
    unsafe = deepcopy(cases[0])
    unsafe["base_url"] = "https://must-not-live-in-fixture.example"
    unsafe["api_key"] = "must-not-live-in-fixture"

    errors = conformance.validate_case(unsafe, "unsafe.json")

    assert any("endpoints" in error for error in errors)
    assert any("secret-bearing" in error for error in errors)


def test_live_smoke_is_credential_gated(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLADE_PROVIDER_SMOKE_BASE_URL", raising=False)

    result, error = conformance.live_smoke("anthropic")

    assert result is None
    assert error == "missing_anthropic_api_key"


def test_live_smoke_skip_needs_only_stdlib_dependencies():
    script = (
        Path(__file__).resolve().parents[1]
        / "evals"
        / "run_provider_conformance.py"
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"ANTHROPIC_API_KEY", "CLADE_PROVIDER_SMOKE_BASE_URL"}
    }

    result = subprocess.run(
        [sys.executable, "-S", str(script), "--live", "anthropic"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "SKIP provider live smoke" in result.stdout


def test_live_smoke_reports_only_safe_catalog_summary(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "live-canary-never-report")
    seen_headers = {}

    def transport(_url, headers, _timeout):
        seen_headers.update(headers)
        return {"data": [{"id": "provider/model-a"}, {"id": "provider/model-b"}]}

    result, error = conformance.live_smoke("openai", transport=transport)

    assert error is None
    assert result == {
        "adapter": "openai",
        "model_count": 2,
        "catalog_digest": result["catalog_digest"],
    }
    assert result["catalog_digest"].startswith("sha256:")
    assert seen_headers["Authorization"] == "Bearer live-canary-never-report"
    assert "live-canary-never-report" not in str(result)
    assert "provider/model-" not in str(result)


def test_live_smoke_failure_exposes_only_safe_category(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "failure-canary-never-report")

    def transport(*_args):
        raise DiscoveryFailure("auth")

    result, error = conformance.live_smoke("anthropic", transport=transport)

    assert result is None
    assert error == "auth"
    assert "failure-canary-never-report" not in str(error)
