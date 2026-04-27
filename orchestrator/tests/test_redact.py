"""Tests for configs/scripts/redact.py — secret detection lib + CLI."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

# Load redact.py as a module without polluting sys.path globally.
# Register in sys.modules BEFORE exec_module so @dataclass on Python 3.14
# can resolve the module via cls.__module__.
_REDACT_PATH = Path(__file__).resolve().parents[2] / "configs" / "scripts" / "redact.py"
_spec = importlib.util.spec_from_file_location("clade_redact", _REDACT_PATH)
assert _spec and _spec.loader
redact_mod = importlib.util.module_from_spec(_spec)
sys.modules["clade_redact"] = redact_mod
_spec.loader.exec_module(redact_mod)


# ─── Library tests ───────────────────────────────────────────────────────────

def test_anthropic_key_detected() -> None:
    text = "ANTHROPIC_API_KEY=sk-ant-api03-abcdefghij1234567890ABCDEFGHIJ1234567890XX"
    masked, hits = redact_mod.redact(text)
    assert hits, "should detect anthropic key"
    assert hits[0].kind == "anthropic_key"
    assert "sk-ant-" not in masked
    assert "<redacted:anthropic_key>" in masked


def test_github_token_detected() -> None:
    text = "token = ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    masked, hits = redact_mod.redact(text)
    assert hits and hits[0].kind == "github_token"
    assert "ghp_" not in masked


def test_aws_access_key_detected() -> None:
    masked, hits = redact_mod.redact("export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
    assert hits and hits[0].kind == "aws_access_key"


def test_jwt_detected() -> None:
    jwt = (
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    _, hits = redact_mod.redact(jwt)
    assert hits and hits[0].kind == "jwt"


def test_generic_env_secret() -> None:
    text = 'API_KEY="abc123def456ghi789"'
    _, hits = redact_mod.redact(text)
    assert hits and hits[0].kind == "env_secret"


def test_pem_private_key() -> None:
    text = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA1234\n"
        "-----END RSA PRIVATE KEY-----"
    )
    masked, hits = redact_mod.redact(text)
    assert hits and hits[0].kind == "private_key"
    assert "MIIEpAIBAAKCAQEA1234" not in masked


def test_no_false_positive_on_short_strings() -> None:
    # Short literals that look like prefixes shouldn't trip the detector.
    _, hits = redact_mod.redact("sk-ant-foo and ghp_short and sk-test")
    assert hits == []


def test_idempotent() -> None:
    text = "X-API-Key: ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    masked, _ = redact_mod.redact(text)
    masked_again, hits_again = redact_mod.redact(masked)
    assert masked == masked_again
    assert hits_again == []


def test_preview_truncates() -> None:
    text = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    _, hits = redact_mod.redact(text)
    assert hits[0].preview.startswith("ghp_ab")
    assert hits[0].preview.endswith("6789")
    assert "..." in hits[0].preview


def test_empty_input() -> None:
    masked, hits = redact_mod.redact("")
    assert masked == ""
    assert hits == []


def test_preserves_non_secret_text() -> None:
    text = "before sk-ant-api03-abcdefghij1234567890ABCDEFGHIJ1234567890XX after"
    masked, _ = redact_mod.redact(text)
    assert masked.startswith("before <redacted:")
    assert masked.endswith(" after")


# ─── CLI tests ──────────────────────────────────────────────────────────────

def test_cli_check_returns_1_on_hit() -> None:
    proc = subprocess.run(
        [sys.executable, str(_REDACT_PATH), "--check"],
        input="ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 1
    assert "github_token" in proc.stderr


def test_cli_check_returns_0_on_clean() -> None:
    proc = subprocess.run(
        [sys.executable, str(_REDACT_PATH), "--check"],
        input="hello world\nno secrets here",
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    assert proc.stderr == ""


def test_cli_default_prints_redacted() -> None:
    proc = subprocess.run(
        [sys.executable, str(_REDACT_PATH)],
        input="key=ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    assert "ghp_" not in proc.stdout
    assert "<redacted:github_token>" in proc.stdout


def test_cli_json_output_shape() -> None:
    proc = subprocess.run(
        [sys.executable, str(_REDACT_PATH), "--json"],
        input="key=ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert "redacted" in payload
    assert "hits" in payload
    assert payload["hits"][0]["kind"] == "github_token"
