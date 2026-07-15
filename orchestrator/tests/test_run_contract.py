"""Offline tests for the optional repository run contract."""

import subprocess

from run_contract import (
    contract_fingerprint,
    effective_settings,
    load_run_contract,
    validate_run_contract,
)


def test_absent_contract_returns_none(tmp_path):
    assert load_run_contract(tmp_path) is None
    assert contract_fingerprint(tmp_path) is None


def test_effective_settings_overlay_and_preserve_defaults():
    defaults = {
        "max_workers": 2,
        "loop_convergence_k": 2,
        "loop_convergence_n": 3,
        "loop_max_iterations": 20,
        "auto_merge": True,
        "unrelated": "preserved",
    }
    contract = {
        "version": 1,
        "max_concurrency": 6,
        "convergence_k": 1,
        "max_iterations": 12,
        "auto_merge": False,
    }

    result = effective_settings(contract, defaults)

    assert result["max_workers"] == 6
    assert result["loop_convergence_k"] == 1
    assert result["loop_convergence_n"] == 3
    assert result["loop_max_iterations"] == 12
    assert result["auto_merge"] is False
    assert result["unrelated"] == "preserved"
    assert defaults["max_workers"] == 2


def test_validate_flags_unknown_bad_types_and_ranges():
    warnings = validate_run_contract({
        "version": "1",
        "max_concurrency": 0,
        "retry": {"enabled": "yes", "mystery": 1},
        "verify_commands": "pytest",
        "oracle_posture": "sometimes",
        "unknown": True,
    })

    assert "unknown key: unknown" in warnings
    assert "version must be an integer" in warnings
    assert "max_concurrency must be an integer >= 1" in warnings
    assert "unknown retry key: mystery" in warnings
    assert "retry.enabled must be a boolean" in warnings
    assert "verify_commands must be a list of non-empty strings" in warnings
    assert "oracle_posture must be required, advisory, or disabled" in warnings


def test_load_known_good_frontmatter(tmp_path):
    (tmp_path / "CLADE_WORKFLOW.md").write_text(
        """---
version: 1
max_concurrency: 4
retry:
  enabled: true
  max_attempts: 3
backoff:
  initial_seconds: 1.5
  max_seconds: 20
  multiplier: 2
convergence_k: 1
convergence_n: 2
max_iterations: 10
verify_commands:
  - python3 -m pytest -q
oracle_posture: required
auto_merge: false
---
# Workflow
""",
        encoding="utf-8",
    )

    contract = load_run_contract(tmp_path)

    assert contract == {
        "version": 1,
        "max_concurrency": 4,
        "retry": {"enabled": True, "max_attempts": 3},
        "backoff": {"initial_seconds": 1.5, "max_seconds": 20, "multiplier": 2},
        "convergence_k": 1,
        "convergence_n": 2,
        "max_iterations": 10,
        "verify_commands": ["python3 -m pytest -q"],
        "oracle_posture": "required",
        "auto_merge": False,
    }
    assert validate_run_contract(contract) == []


def test_fingerprint_is_current_git_blob_sha(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    workflow = tmp_path / "CLADE_WORKFLOW.md"
    workflow.write_text("---\nversion: 1\n---\n", encoding="utf-8")
    expected = subprocess.run(
        ["git", "hash-object", "CLADE_WORKFLOW.md"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert contract_fingerprint(tmp_path) == expected
