"""Secret-safe runtime persistence primitives.

All runtime-controlled text passes through this stdlib-only leaf before it is
written to JSONL, SQLite, traces, or provider logs. Metadata contains only
counts, categories, and logical field names; it never retains matched text.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "clade.redaction/v1"

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "authorization",
    "client_secret",
    "cookie",
    "credentials",
    "credential",
    "password",
    "passwd",
    "private_key",
    "refresh_token",
    "secret",
    "secret_key",
    "session_cookie",
    "webhook_secret",
}

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{40,}\b")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe_key", re.compile(r"\b(?:sk|rk|pk)_live_[A-Za-z0-9]{20,}\b")),
    (
        "jwt",
        re.compile(
            r"\beyJ[A-Za-z0-9_=-]{10,}\.eyJ[A-Za-z0-9_=-]{10,}"
            r"\.[A-Za-z0-9_=-]{10,}\b"
        ),
    ),
    (
        "bearer_token",
        re.compile(r"(?i)\b(?:authorization\s*:\s*)?bearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    ),
    (
        "env_secret",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|password|passwd|auth[_-]?token)"
            r"[\s:=]+['\"]?[^'\"\s]{12,}['\"]?"
        ),
    ),
    (
        "url_credentials",
        re.compile(r"(?i)(?P<scheme>\b[a-z][a-z0-9+.-]*://)[^/@\s:]+:[^/@\s]+@"),
    ),
    ("home_path", re.compile(r"(?<![A-Za-z0-9_])/(?:home|Users)/[^/\s]+")),
    ("windows_user_path", re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+")),
)

_PRIVATE_KEY_BEGIN = re.compile(
    r"-----BEGIN (?:RSA |OPENSSH |DSA |EC |PGP )?PRIVATE KEY-----"
)
_PRIVATE_KEY_END = re.compile(
    r"-----END (?:RSA |OPENSSH |DSA |EC |PGP )?PRIVATE KEY-----"
)


@dataclass(frozen=True)
class RedactionMetadata:
    schema_version: str = SCHEMA_VERSION
    count: int = 0
    kinds: dict[str, int] = field(default_factory=dict)
    fields: tuple[str, ...] = ()

    @property
    def redacted(self) -> bool:
        return self.count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "count": self.count,
            "kinds": dict(sorted(self.kinds.items())),
            "fields": list(self.fields),
        }


@dataclass(frozen=True)
class RedactionResult:
    value: Any
    metadata: RedactionMetadata


def _normalise_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")


def _is_sensitive_key(key: Any) -> bool:
    normalised = _normalise_key(key)
    return (
        normalised in _SENSITIVE_KEYS
        or normalised.endswith("_api_key")
        or normalised.endswith("_access_token")
        or normalised.endswith("_refresh_token")
        or normalised.endswith("_client_secret")
        or normalised.endswith("_password")
        or normalised.endswith("_private_key")
    )


def _redact_text(text: str) -> tuple[str, Counter[str]]:
    if not text:
        return text, Counter()
    counts: Counter[str] = Counter()
    redacted = text

    def replace(kind: str, match: re.Match[str]) -> str:
        counts[kind] += 1
        if kind == "url_credentials":
            return f"{match.group('scheme')}<redacted:credentials>@"
        if kind == "home_path":
            prefix = "/Users" if match.group(0).startswith("/Users/") else "/home"
            return f"{prefix}/<redacted:user>"
        if kind == "windows_user_path":
            drive = match.group(0)[:2]
            return f"{drive}\\Users\\<redacted:user>"
        return f"<redacted:{kind}>"

    for kind, pattern in _PATTERNS:
        redacted = pattern.sub(lambda match, k=kind: replace(k, match), redacted)
    return redacted, counts


def redact_runtime(value: Any, *, field_path: str = "$") -> RedactionResult:
    """Recursively redact a JSON-like runtime value."""
    counts: Counter[str] = Counter()
    fields: set[str] = set()

    def walk(item: Any, path: str) -> Any:
        if isinstance(item, dict):
            out: dict[Any, Any] = {}
            for key, nested in item.items():
                child_path = f"{path}.{key}"
                if _is_sensitive_key(key) and nested not in (None, "", [], {}):
                    out[key] = "<redacted:sensitive_key>"
                    counts["sensitive_key"] += 1
                    fields.add(child_path)
                else:
                    out[key] = walk(nested, child_path)
            return out
        if isinstance(item, list):
            return [walk(nested, f"{path}[{index}]") for index, nested in enumerate(item)]
        if isinstance(item, tuple):
            return tuple(
                walk(nested, f"{path}[{index}]") for index, nested in enumerate(item)
            )
        if isinstance(item, str):
            masked, hits = _redact_text(item)
            if hits:
                counts.update(hits)
                fields.add(path)
            return masked
        return item

    redacted = walk(value, field_path)
    metadata = RedactionMetadata(
        count=sum(counts.values()),
        kinds=dict(counts),
        fields=tuple(sorted(fields)),
    )
    return RedactionResult(redacted, metadata)


def merge_metadata(*items: RedactionMetadata | dict[str, Any] | None) -> RedactionMetadata:
    counts: Counter[str] = Counter()
    fields: set[str] = set()
    for item in items:
        if not item:
            continue
        raw = item.to_dict() if isinstance(item, RedactionMetadata) else item
        counts.update({str(k): int(v) for k, v in (raw.get("kinds") or {}).items()})
        fields.update(str(field) for field in (raw.get("fields") or []))
    return RedactionMetadata(
        count=sum(counts.values()),
        kinds=dict(counts),
        fields=tuple(sorted(fields)),
    )


class RedactingStreamCapture:
    """Stream provider output to disk without ever persisting raw text."""

    def __init__(self) -> None:
        self._metadata = RedactionMetadata()
        self._inside_private_key = False

    @property
    def metadata(self) -> RedactionMetadata:
        return self._metadata

    def _process_line(self, line: str) -> str:
        if self._inside_private_key:
            if _PRIVATE_KEY_END.search(line):
                self._inside_private_key = False
            return ""
        if _PRIVATE_KEY_BEGIN.search(line):
            self._inside_private_key = not bool(_PRIVATE_KEY_END.search(line))
            self._metadata = merge_metadata(
                self._metadata,
                RedactionMetadata(count=1, kinds={"private_key": 1}, fields=("$",)),
            )
            return "<redacted:private_key>\n" if line.endswith("\n") else "<redacted:private_key>"
        result = redact_runtime(line)
        self._metadata = merge_metadata(self._metadata, result.metadata)
        return str(result.value)

    async def capture(
        self,
        reader: asyncio.StreamReader | None,
        output_path: Path,
        *,
        append: bool = False,
    ) -> RedactionMetadata:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        pending = ""
        mode = "a" if append else "w"
        with open(output_path, mode, encoding="utf-8") as output:
            if reader is not None:
                while True:
                    chunk = await reader.read(65536)
                    if not chunk:
                        break
                    pending += decoder.decode(chunk)
                    lines = pending.splitlines(keepends=True)
                    if lines and not lines[-1].endswith(("\n", "\r")):
                        pending = lines.pop()
                    else:
                        pending = ""
                    for line in lines:
                        output.write(self._process_line(line))
                    output.flush()
                pending += decoder.decode(b"", final=True)
            if pending:
                output.write(self._process_line(pending))
            output.flush()
        return self._metadata


def write_redaction_metadata(output_path: Path, metadata: RedactionMetadata) -> None:
    """Merge safe redaction counts into an adjacent JSON sidecar."""
    if not metadata.redacted:
        return
    sidecar = output_path.with_suffix(output_path.suffix + ".redaction.json")
    existing: dict[str, Any] | None = None
    if sidecar.is_file():
        try:
            existing = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = None
    merged = merge_metadata(existing, metadata)
    sidecar.write_text(json.dumps(merged.to_dict(), sort_keys=True) + "\n", encoding="utf-8")


async def capture_provider_output(
    reader: asyncio.StreamReader | None,
    output_path: Path,
    *,
    append: bool = False,
) -> RedactionMetadata:
    """Capture one provider stream and persist only its redacted form."""
    capture = RedactingStreamCapture()
    metadata = await capture.capture(reader, output_path, append=append)
    write_redaction_metadata(output_path, metadata)
    return metadata
