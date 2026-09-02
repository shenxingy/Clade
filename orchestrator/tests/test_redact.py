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

# Fake credentials, split so this file never carries a contiguous scannable
# literal — configs/scripts/checks.sh scans every staged diff and would block
# the commit that adds these tests. Same convention as tests/test-checks.sh.
FAKE_UNDERSCORE_KEY = "sk_" + "d69f1a2b3c4d5e6f7081920a1b2c3d4e5f60718293a4b5c6"
FAKE_STRIPE_LIVE = "sk_" + "live_51ABCdefGHIjklMNOpqrSTU12345"
FAKE_STRIPE_TEST = "sk_" + "test_51ABCdefGHIjklMNOpqrSTU12345"

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


def test_underscore_prefixed_key_detected() -> None:
    # The hyphen-form `sk-` pattern does not cover `sk_`, and env_secret needs
    # quotes — so this shape used to escape every pattern in the file.
    text = "the key is sk_" + "d69f1a2b3c4d5e6f7081920a1b2c3d4e5f60718293a4b5c6"
    masked, hits = redact_mod.redact(text)
    assert hits, "should detect underscore-prefixed vendor key"
    assert hits[0].kind == "generic_secret_key"
    assert "sk_d69" not in masked
    assert "<redacted:generic_secret_key>" in masked


def test_unquoted_underscore_key_in_env_assignment_detected() -> None:
    # `\bAPI_KEY` finds no word boundary inside SCAMAI_API_KEY, so env_secret
    # misses this even when quoted. The value pattern is what has to catch it.
    text = "SCAMAI_API_KEY=" + FAKE_UNDERSCORE_KEY
    masked, hits = redact_mod.redact(text)
    assert hits and hits[0].kind == "generic_secret_key"
    assert "sk_d69" not in masked


def test_stripe_live_key_keeps_specific_label() -> None:
    # Pins the ordering claim: a future reorder that let the generic pattern
    # shadow stripe_key would flip this label.
    _, hits = redact_mod.redact(FAKE_STRIPE_LIVE)
    assert hits and hits[0].kind == "stripe_key"


def test_stripe_test_key_detected() -> None:
    # Previously matched nothing: stripe_key demanded `_live_`, and the generic
    # pattern cannot span `test_` (4 alnum before the second underscore).
    masked, hits = redact_mod.redact(FAKE_STRIPE_TEST)
    assert hits and hits[0].kind == "stripe_key"
    assert "sk_test_51" not in masked


def test_no_false_positive_on_underscore_suffixed_identifier() -> None:
    # Regression guard for the \b. This is the exact shape that appears 14x in
    # the real correction corpus (task_count, task_live, task_progress, ...).
    _, hits = redact_mod.redact("task_abcdefghijklmnopqrstuvwxyz0123456789ABCD")
    assert hits == []


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


def test_cli_check_flags_underscore_key() -> None:
    proc = subprocess.run(
        [sys.executable, str(_REDACT_PATH), "--check"],
        input=FAKE_UNDERSCORE_KEY,
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 1
    assert "generic_secret_key" in proc.stderr


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

# ─── Non-ASCII context ────────────────────────────────────────────────────────
# Python's \w, and therefore \b, is Unicode-aware by default: 是 and к are word
# characters, so there is no boundary between them and the `s` of `sk-`. Every
# \b-anchored pattern in redact.py silently failed on a key pasted into Chinese
# or Cyrillic prose — which is the path that matters, because the main caller is
# correction-detector.sh and its own trigger list is 不要|别用|错了|改回|不对.


def test_key_in_chinese_prose_is_detected() -> None:
    """The case the redactor exists for, and the one that did not work."""

    text = "不对，改回原来的写法，key是" + "sk-ant-" + "api03-" + "A" * 45
    masked, hits = redact_mod.redact(text)
    assert hits, "a key adjacent to CJK text must still be detected"
    assert "sk-ant-" not in masked


def test_github_token_after_chinese_is_detected() -> None:
    text = "别用这个，token是" + "ghp_" + "a" * 36
    masked, hits = redact_mod.redact(text)
    assert hits
    assert "ghp_" not in masked


def test_aws_key_between_chinese_is_detected() -> None:
    text = "错了，密钥" + "AKIA" + "IOSFODNN7EXAMPLE" + "别提交"
    masked, hits = redact_mod.redact(text)
    assert hits
    assert "AKIA" not in masked


def test_key_after_cyrillic_is_detected() -> None:
    masked, hits = redact_mod.redact("ключ" + "sk_" + "b" * 40)
    assert hits
    assert "sk_" not in masked


def test_task_id_in_chinese_prose_is_still_not_a_secret() -> None:
    """The ASCII fix must not cost the false-positive guard."""

    _, hits = redact_mod.redact("这是一个" + "task_" + "c" * 32 + "的任务")
    assert not hits


def test_every_pattern_is_ascii_anchored() -> None:
    """A pattern added later without re.ASCII reopens the whole hole."""

    import re

    missing = [kind for kind, rx, _ in redact_mod._PATTERNS if not rx.flags & re.ASCII]
    assert not missing, f"patterns missing re.ASCII: {missing}"
