"""A declared decision memo must reach the argued-page checks through the CLI."""
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "configs/scripts/artifact-lint.py"

_HEAD = '''<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width">
<meta name="artifact-type" content="decision"><title>Release decision</title>
</head><body><h1>Release decision</h1><p>As of 2026-09-24.</p>'''
_TAIL = '''<h2>Options</h2><p>Wait or ship.</p></body></html>'''
_LEAD = ('<section id="bottom-line"><p><strong>Bottom line:</strong> ship on Friday.</p>'
         '<p><strong>Needs you:</strong> approve the release by 2026-09-26.</p></section>')


def _lint(page: Path, *extra: str) -> tuple[int, dict]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(page), "--json", *extra],
        capture_output=True, text=True, check=False,
    )
    return result.returncode, json.loads(result.stdout)[0]


def test_decision_profile_reaches_the_cli_and_keeps_argument_checks(tmp_path):
    page = tmp_path / "decision.html"
    page.write_text(_HEAD + _LEAD + _TAIL)
    for override in ([], ["--type", "decision"]):
        code, report = _lint(page, *override)
        assert code == 0, report["findings"]
        assert report["stats"]["type"] == "decision"
        findings = {item["id"] for item in report["findings"]}
        assert not {"type-unknown", "type-undeclared"} & findings
        assert {"title-claim", "limits", "next", "why", "method"} <= findings
        assert not {"lead", "lead-ask"} & findings


def test_a_decision_without_its_lead_fails_the_cli(tmp_path):
    """`lead` is a FAIL like every other FAIL: it sets the exit code a publish step reads."""
    page = tmp_path / "decision.html"
    page.write_text(_HEAD + _TAIL)
    code, report = _lint(page)
    assert code == 1
    assert {"id": "lead", "level": "FAIL"}.items() <= next(
        f for f in report["findings"] if f["id"] == "lead").items()
