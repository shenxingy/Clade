"""The retrospective half of the redaction fix.

The prospective fix (redact before writing) cannot touch what is already on
disk, and the scrub that removes it has one non-obvious failure mode worth
pinning: a JSONL file stores a newline as the two characters `\\` and `n`, so a
credential that began a line inside a captured prompt sits on disk immediately
after the letter `n`. That is a word character, `\\b` does not match, and a raw
scan of the encoded line walks straight past it.

This was not hypothetical. On the real correction log the same 44-character key
appeared twice on one line and a raw scan reported one of them, which would
have left a live credential in a file the report called clean.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRUB = REPO / "configs" / "scripts" / "scrub-corrections.py"
sys.path.insert(0, str(REPO / "configs" / "scripts"))

from redact import scan  # noqa: E402

# Assembled so the literal never appears in the source and trips the secret gate.
FAKE_KEY = "sk-" + "proj" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v2"


def _run(directory: Path | None, *args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRUB)]
    if directory is not None:
        cmd += ["--dir", str(directory)]
    return subprocess.run(cmd + list(args), capture_output=True, text=True, check=False)


def _seed(tmp_path: Path) -> Path:
    """One record whose prompt puts the key at the start of a line, and again inline."""
    record = {
        "timestamp": "2026-08-11T19:14:26Z",
        "project": "/tmp/example",
        "type": "explicit",
        "prompt": f"here is the dashboard output\n{FAKE_KEY}\n\nexport X={FAKE_KEY}\n",
    }
    log = tmp_path / "history.jsonl"
    log.write_text(json.dumps(record) + "\n", encoding="utf-8")
    return log


def test_raw_scan_alone_misses_the_line_initial_occurrence(tmp_path: Path) -> None:
    """The gap this script exists to close, demonstrated rather than asserted."""
    log = _seed(tmp_path)
    encoded = log.read_text(encoding="utf-8")

    assert encoded.count(FAKE_KEY) == 2, "both occurrences should be on disk"
    # A raw scan of the ENCODED line sees only the one preceded by '='.
    assert len(scan(encoded)) == 1
    # Decoded, both are plainly visible — which is why the scrub decodes.
    assert len(scan(json.loads(encoded)["prompt"])) == 2


def test_dry_run_reports_every_occurrence_and_writes_nothing(tmp_path: Path) -> None:
    log = _seed(tmp_path)
    before = log.read_bytes()

    result = _run(tmp_path)

    assert result.returncode == 0
    assert "×2 on this line" in result.stdout
    assert "2 credential(s) found" in result.stdout
    assert "Nothing was written" in result.stdout
    assert log.read_bytes() == before, "a dry run must not touch the file"
    # The report identifies the key without reprinting it.
    assert FAKE_KEY not in result.stdout


def test_apply_masks_both_occurrences(tmp_path: Path) -> None:
    log = _seed(tmp_path)

    result = _run(tmp_path, "--apply")

    assert result.returncode == 0
    scrubbed = log.read_text(encoding="utf-8")
    assert FAKE_KEY not in scrubbed, "the credential must be gone from disk"
    assert scrubbed.count("<redacted:openai_key>") == 2
    assert "ROTATE THESE KEYS" in result.stdout

    # The record must survive as a record — a scrub that corrupts the history
    # the correction system reasons from has traded one defect for another.
    record = json.loads(scrubbed)
    assert record["timestamp"] == "2026-08-11T19:14:26Z"
    assert record["project"] == "/tmp/example"
    assert "here is the dashboard output" in record["prompt"]


def test_rerun_is_clean_and_idempotent(tmp_path: Path) -> None:
    log = _seed(tmp_path)
    _run(tmp_path, "--apply")
    after_first = log.read_bytes()

    result = _run(tmp_path, "--apply")

    assert "clean: no credentials found" in result.stdout
    assert log.read_bytes() == after_first


def test_clean_directory_reports_clean(tmp_path: Path) -> None:
    (tmp_path / "rules.md").write_text("- [2026-09-02] a (edge-case): b\n", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 0
    assert "clean: no credentials found" in result.stdout


def test_missing_directory_exits_nonzero(tmp_path: Path) -> None:
    result = _run(tmp_path / "absent")
    assert result.returncode == 1
    assert "no such directory" in result.stdout


def test_named_files_scrub_only_those_files(tmp_path: Path) -> None:
    """The same credential turned up outside the directory this was written for,
    and not every file it turned up in should be rewritten by this tool."""
    target = _seed(tmp_path)
    bystander = tmp_path / "untouched.jsonl"
    bystander.write_text(json.dumps({"prompt": f"key={FAKE_KEY}"}) + "\n", encoding="utf-8")
    bystander_before = bystander.read_bytes()

    result = _run(None, str(target), "--apply")

    assert result.returncode == 0
    assert FAKE_KEY not in target.read_text(encoding="utf-8")
    assert bystander.read_bytes() == bystander_before, "an unnamed file must not be touched"


def test_named_file_and_dir_together_is_refused(tmp_path: Path) -> None:
    log = _seed(tmp_path)
    result = _run(tmp_path, str(log), "--apply")
    assert result.returncode == 2
    assert FAKE_KEY in log.read_text(encoding="utf-8"), "a refused run writes nothing"


def test_missing_named_file_exits_nonzero(tmp_path: Path) -> None:
    result = _run(None, str(tmp_path / "absent.jsonl"))
    assert result.returncode == 1
    assert "no such file" in result.stdout


def test_apply_preserves_the_file_mode(tmp_path: Path) -> None:
    """The atomic replace writes a new inode; an owner-only log must not come
    back group-readable."""
    log = _seed(tmp_path)
    log.chmod(0o600)

    _run(tmp_path, "--apply")

    assert log.stat().st_mode & 0o777 == 0o600
