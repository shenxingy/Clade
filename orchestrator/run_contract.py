"""Repository-owned autonomous-run policy contract.

This is a stdlib-only leaf module.  ``CLADE_WORKFLOW.md`` is deliberately
optional: callers can distinguish an absent contract from an empty/invalid one
and preserve the historical settings path when it is not present.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, TypedDict


RUN_CONTRACT_VERSION = 1
_CONTRACT_FILE = "CLADE_WORKFLOW.md"


class RetryPolicy(TypedDict, total=False):
    enabled: bool
    max_attempts: int


class BackoffPolicy(TypedDict, total=False):
    initial_seconds: float
    max_seconds: float
    multiplier: float


class RunContract(TypedDict, total=False):
    version: int
    max_concurrency: int
    retry: RetryPolicy
    backoff: BackoffPolicy
    convergence_k: int
    convergence_n: int
    max_iterations: int
    verify_commands: list[str]
    oracle_posture: str
    auto_merge: bool


_TOP_LEVEL_KEYS = frozenset(RunContract.__annotations__)
_RETRY_KEYS = frozenset(RetryPolicy.__annotations__)
_BACKOFF_KEYS = frozenset(BackoffPolicy.__annotations__)
_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$")


def _scalar(raw: str) -> Any:
    """Parse the small scalar subset used by the contract."""
    value = raw.strip()
    if not value:
        return None
    if value[0:1] == value[-1:] and value[0:1] in ("'", '"'):
        return value[1:-1]
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "none", "~"):
        return None
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            pass
    if value.startswith("[") and value.endswith("]"):
        inside = value[1:-1].strip()
        return [] if not inside else [_scalar(part) for part in inside.split(",")]
    return value


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse scalars, one-level mappings, and string lists from front matter."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}

    result: dict[str, Any] = {}
    parent: str | None = None
    for raw_line in lines[1:end]:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent == 0:
            match = _KEY_RE.match(raw_line)
            if not match:
                parent = None
                continue
            key, raw_value = match.group(1), (match.group(2) or "")
            if raw_value.strip():
                result[key] = _scalar(raw_value)
                parent = None
            else:
                result[key] = [] if key == "verify_commands" else {}
                parent = key
            continue

        if parent is None:
            continue
        if stripped.startswith("-") and isinstance(result[parent], list):
            item = stripped[1:].strip()
            if item:
                result[parent].append(_scalar(item))
            continue
        match = _KEY_RE.match(stripped)
        if match and isinstance(result[parent], dict):
            result[parent][match.group(1)] = _scalar(match.group(2) or "")
    return result


def load_run_contract(repo_dir: str | Path) -> dict | None:
    """Load ``CLADE_WORKFLOW.md`` front matter, or ``None`` when absent."""
    path = Path(repo_dir) / _CONTRACT_FILE
    if not path.is_file():
        return None
    try:
        return _parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return {}


def contract_fingerprint(repo_dir: str | Path) -> str | None:
    """Return the Git blob SHA for the current contract contents."""
    repo = Path(repo_dir)
    path = repo / _CONTRACT_FILE
    if not path.is_file():
        return None
    try:
        completed = subprocess.run(
            ["git", "hash-object", _CONTRACT_FILE],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    fingerprint = completed.stdout.strip()
    return fingerprint or None


def validate_run_contract(contract: dict) -> list[str]:
    """Return human-readable schema warnings without mutating the contract."""
    if not isinstance(contract, dict):
        return ["contract must be a mapping"]
    warnings: list[str] = []
    for key in sorted(set(contract) - _TOP_LEVEL_KEYS):
        warnings.append(f"unknown key: {key}")

    version = contract.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        warnings.append("version must be an integer")
    elif version != RUN_CONTRACT_VERSION:
        warnings.append(
            f"version must be {RUN_CONTRACT_VERSION} (got {version})"
        )

    def positive_int(key: str) -> None:
        value = contract.get(key)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 1
        ):
            warnings.append(f"{key} must be an integer >= 1")

    for key in ("max_concurrency", "convergence_n", "max_iterations"):
        positive_int(key)
    value = contract.get("convergence_k")
    if value is not None and (
        not isinstance(value, int) or isinstance(value, bool) or value < 0
    ):
        warnings.append("convergence_k must be an integer >= 0")

    retry = contract.get("retry")
    if retry is not None:
        if not isinstance(retry, dict):
            warnings.append("retry must be a mapping")
        else:
            for key in sorted(set(retry) - _RETRY_KEYS):
                warnings.append(f"unknown retry key: {key}")
            if "enabled" in retry and not isinstance(retry["enabled"], bool):
                warnings.append("retry.enabled must be a boolean")
            attempts = retry.get("max_attempts")
            if attempts is not None and (
                not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1
            ):
                warnings.append("retry.max_attempts must be an integer >= 1")

    backoff = contract.get("backoff")
    if backoff is not None:
        if not isinstance(backoff, dict):
            warnings.append("backoff must be a mapping")
        else:
            for key in sorted(set(backoff) - _BACKOFF_KEYS):
                warnings.append(f"unknown backoff key: {key}")
            for key in _BACKOFF_KEYS:
                value = backoff.get(key)
                minimum = 1 if key == "multiplier" else 0
                if value is not None and (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or value < minimum
                ):
                    warnings.append(f"backoff.{key} must be a number >= {minimum}")
            initial = backoff.get("initial_seconds")
            maximum = backoff.get("max_seconds")
            if isinstance(initial, (int, float)) and isinstance(maximum, (int, float)) and initial > maximum:
                warnings.append("backoff.initial_seconds must not exceed backoff.max_seconds")

    commands = contract.get("verify_commands")
    if commands is not None and (
        not isinstance(commands, list)
        or any(not isinstance(command, str) or not command.strip() for command in commands)
    ):
        warnings.append("verify_commands must be a list of non-empty strings")
    posture = contract.get("oracle_posture")
    if posture is not None and posture not in ("required", "advisory", "disabled"):
        warnings.append("oracle_posture must be required, advisory, or disabled")
    if "auto_merge" in contract and not isinstance(contract["auto_merge"], bool):
        warnings.append("auto_merge must be a boolean")
    return warnings


def effective_settings(contract: dict, defaults: dict) -> dict:
    """Return a settings copy with valid, declared contract policy overlaid."""
    settings = dict(defaults)
    if not isinstance(contract, dict):
        return settings

    aliases = {
        "max_concurrency": "max_workers",
        "convergence_k": "loop_convergence_k",
        "convergence_n": "loop_convergence_n",
        "max_iterations": "loop_max_iterations",
        "auto_merge": "auto_merge",
        "verify_commands": "verify_commands",
        "backoff": "retry_backoff",
    }
    invalid_messages = validate_run_contract(contract)
    for source, target in aliases.items():
        if source in contract and not any(
            message.startswith(source + " ") or message.startswith(source + ".")
            for message in invalid_messages
        ):
            settings[target] = contract[source]

    retry = contract.get("retry")
    if isinstance(retry, dict):
        if isinstance(retry.get("enabled"), bool):
            settings["auto_classify_retry"] = retry["enabled"]
        attempts = retry.get("max_attempts")
        if isinstance(attempts, int) and not isinstance(attempts, bool) and attempts >= 1:
            settings["auto_classify_retry_max"] = attempts

    posture = contract.get("oracle_posture")
    if posture in ("required", "advisory", "disabled"):
        settings["auto_oracle"] = posture == "required"
        settings["auto_review"] = posture != "disabled"
    return settings
