"""Keep the distributable MCP skill docs aligned with the shipped manifest."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_ROOT = REPO_ROOT / "mcp-package"


def _manifest_skills() -> set[str]:
    return {
        line.strip()
        for line in (MCP_ROOT / "skills.list").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


@pytest.mark.parametrize(
    ("readme_name", "heading"),
    [
        ("README.md", "Available Skills"),
        ("README.zh-CN.md", "内置 Skills"),
    ],
)
def test_mcp_readme_skill_table_matches_manifest(readme_name: str, heading: str):
    manifest = _manifest_skills()
    text = (MCP_ROOT / readme_name).read_text(encoding="utf-8")
    heading_match = re.search(
        rf"^## {re.escape(heading)}\s*[\(（](\d+)[\)）]$", text, re.MULTILINE
    )

    assert heading_match is not None
    section = text[heading_match.end() :].split("\n## ", 1)[0]
    documented = set(
        re.findall(r"^\| \*\*([^*]+)\*\* \|", section, re.MULTILINE)
    )

    assert int(heading_match.group(1)) == len(manifest)
    assert documented == manifest
