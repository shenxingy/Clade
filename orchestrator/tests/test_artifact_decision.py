"""A declared decision memo must reach the argued-page checks through the CLI."""
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "configs/scripts/artifact-lint.py"


def test_decision_profile_reaches_the_cli_and_keeps_argument_checks(tmp_path):
    page = tmp_path / "decision.html"
    page.write_text('''<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width">
<meta name="artifact-type" content="decision"><title>Release decision</title>
</head><body><h1>Release decision</h1><p>As of 2026-09-24.</p>
<h2>Options</h2><p>Wait or ship.</p></body></html>''')
    for override in ([], ["--type", "decision"]):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(page), "--json", *override],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)[0]
        assert report["stats"]["type"] == "decision"
        findings = {item["id"] for item in report["findings"]}
        assert not {"type-unknown", "type-undeclared"} & findings
        assert {"title-claim", "limits", "next", "why", "method"} <= findings
