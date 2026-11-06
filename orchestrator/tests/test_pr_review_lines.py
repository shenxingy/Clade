"""The two PR-body review lines, read the way their consumer reads them.

Every surface that writes a PR body (the repository's PR template, /create-pr §4,
/delivery §6, /ship) states `Review depth:` and `Could not verify:`, and /retro
rolls them up through configs/scripts/pr-verification-gaps.py. These tests feed
what each producer writes to that parser, so a vocabulary that drifts on one side
goes red here rather than reading as "unparsed" in a retro nobody checks:

- the template, left unedited as a PR body, is UNFILLED, not missing or a value;
- every depth a surface offers parses to that depth;
- /create-pr's worked example parses to the items it names;
- the command /retro tells the agent to run works, end to end, on a PR body made
  by filling in the template.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "configs" / "scripts" / "pr-verification-gaps.py"
TEMPLATE = REPO / ".github" / "PULL_REQUEST_TEMPLATE.md"
EMITTERS = [
    ".github/PULL_REQUEST_TEMPLATE.md",
    "configs/skills/create-pr/prompt.md",
    "configs/skills/delivery/prompt.md",
    "configs/skills/ship/prompt.md",
]
_DEPTH_FORMAT = re.compile(r"Review depth: <?((?:[a-z-]+ \| )+[a-z-]+)>?")


def _rollup() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pr_verification_gaps", SCRIPT)
    assert spec and spec.loader, f"{SCRIPT} is missing"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_unedited_template_reads_as_unfilled_not_missing():
    """A PR opened from the template without touching the two lines is counted as unfilled, honestly."""
    parsed = _rollup().parse_body(TEMPLATE.read_text(encoding="utf-8"))
    assert parsed["review_depth"]["state"] == "unfilled", parsed
    assert parsed["could_not_verify"]["state"] == "unfilled", parsed


@pytest.mark.parametrize("emitter", EMITTERS)
def test_every_depth_a_surface_offers_parses_to_that_depth(emitter):
    text = (REPO / emitter).read_text(encoding="utf-8")
    offered = _DEPTH_FORMAT.findall(text)
    assert offered, f"{emitter} states no `Review depth: a | b | c` line"
    assert "Could not verify: " in text, f"{emitter} states no `Could not verify:` line"
    rollup = _rollup()
    for alternatives in offered:
        values = alternatives.split(" | ")
        assert values == list(rollup.DEPTHS), f"{emitter} offers {values}, the rollup reads {rollup.DEPTHS}"
        for value in values:
            depth = rollup.parse_body(f"Review depth: {value}\n")["review_depth"]
            assert depth == {"state": "stated", "depth": value, "by": ""}, (emitter, value, depth)


def test_the_create_pr_example_parses_to_what_it_names():
    text = (REPO / "configs/skills/create-pr/prompt.md").read_text(encoding="utf-8")
    example = [line for line in text.splitlines()
               if re.match(r"(Review depth|Could not verify): ", line) and "|" not in line]
    assert len(example) == 2, f"/create-pr §4 should carry one worked example of both lines, found {example}"
    parsed = _rollup().parse_body("\n".join(example))
    assert parsed["review_depth"] == {"state": "stated", "depth": "skimmed", "by": "(by @reviewer)"}
    items = parsed["could_not_verify"]["items"]
    assert [(i["label"], i["reason"]) for i in items] == [
        ("macOS run", "no Mac reachable"), ("live hook firing", "needs an interactive session")]


def test_the_command_retro_runs_rolls_up_bodies_written_from_the_template(tmp_path):
    """/retro's own command line, on PR bodies made by filling in the template, prints the candidate TODO entry."""
    retro = (REPO / "configs/skills/retro/prompt.md").read_text(encoding="utf-8")
    match = re.search(r"^python3 ~/\.claude/scripts/pr-verification-gaps\.py (.+)$", retro, re.M)
    assert match, "/retro names no pr-verification-gaps.py command"
    args = match.group(1).replace("<days>", "7").split()

    rollup = _rollup()
    template = TEMPLATE.read_text(encoding="utf-8")

    def filled(depth: str, gaps: str) -> str:
        body = template.replace("Review depth: <none | skimmed | read-in-full>", f"Review depth: {depth}")
        return body.replace("Could not verify: <none | item (why); item (why)>", f"Could not verify: {gaps}")

    prs = [rollup._pr(1, filled("none", "macOS run (no Mac reachable); hosted CI (receipt pending)"), 3),
           rollup._pr(2, filled("skimmed (by @reviewer)", "macOS run (Touch ID not pressed)"), 2),
           rollup._pr(3, template, 1)]
    fixture = rollup._write_fixture(tmp_path / "fixture", prs)
    out = subprocess.run([sys.executable, str(SCRIPT), *args, "--fixture", str(fixture)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "- [ ] Verify macOS run — unverified in 2 merged PRs (#1, #2)" in out.stdout, out.stdout
    assert "stated in 2 of 3 PRs (0 said none, 1 left it unfilled, 0 carry no line)" in out.stdout, out.stdout
    assert "claim a reading that no submitted review by anyone but the author backs (#2)" in out.stdout, out.stdout
