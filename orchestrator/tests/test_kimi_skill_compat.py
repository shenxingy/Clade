"""Real-tree Kimi skill compatibility scan tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNER = REPO_ROOT / "configs" / "scripts" / "kimi-skill-compat.py"
SKILLS = REPO_ROOT / "configs" / "skills"


def test_real_scan_classifies_every_skill_directory_without_dropping_one() -> None:
    expected = sorted(path.parent.name for path in SKILLS.glob("*/SKILL.md"))
    assert expected, "the completeness control needs a non-empty real skill tree"
    result = subprocess.run(
        [sys.executable, str(SCANNER), "--root", str(SKILLS), "--json"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    report = json.loads(result.stdout)
    rows = report["skills"]
    assert len(rows) == len(expected)
    assert sorted(row["name"] for row in rows) == expected
    assert report["totals"]["skills"] == len(expected)
    assert sum(report["totals"][name] for name in
               ("native", "adapted", "degraded", "claude-only")) == len(expected)
    for row in rows:
        assert row["classification"] in {"native", "adapted", "degraded", "claude-only"}
        assert row["scanned_files"], f"{row['name']}: no files scanned"
        if row["classification"] != "native":
            assert row["evidence"], f"{row['name']}: classification has no evidence"
        for item in row["evidence"]:
            assert item["line"] >= 1
            assert item["path"] in row["scanned_files"]
            assert item["text"]
            assert item["fact"]
