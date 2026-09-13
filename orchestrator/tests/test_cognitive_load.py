"""The analyzer `/blog analyze --cognitive-load` names.

`references/cognitive-load.md` specified this script — six metrics, a threshold
table, a composite rule and a report shape — for a full release line while the
file did not exist, so the flag failed on a missing path. These pin the
specification, and two of them pin defects the first real run exposed.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "configs" / "scripts" / "blog" / "cognitive_load.py"


def _load():
    spec = importlib.util.spec_from_file_location("cognitive_load", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["cognitive_load"] = module
    spec.loader.exec_module(module)
    return module


cl = _load()

_PROSE = (
    "A reader has finite attention. Keep one idea per paragraph. Say the thing "
    "plainly. Then say why it holds. A short sentence lands. Write the way you "
    "would explain it to someone standing beside you. Do not make them hold "
    "three unfinished thoughts at once. Finish one, then start the next.\n"
)
_DENSE = (
    "Acme Corp and Globex Systems joined Initech Labs and Umbrella Group to "
    "study crawl budget, index bloat, entity salience and query fan-out. As we "
    "will see, the SERP shifted. Later in this post we return to it, which "
    "matters, although the sample, which was small, drew on 12 sites.\n"
)


def _rows(text, jargon=None):
    return cl.measure(cl.split_sections(text), jargon or set(cl.DEFAULT_JARGON))


def test_the_script_the_reference_names_exists():
    assert _SCRIPT.is_file()


def test_self_test_passes():
    assert cl.self_test() == 0


def test_sections_split_on_h2():
    rows = _rows("## One\n\n" + _PROSE + "\n## Two\n\n" + _PROSE)
    assert [r["section"] for r in rows] == ["One", "Two"]


def test_text_before_the_first_h2_becomes_introduction():
    rows = _rows(_PROSE + "\n## Later\n\n" + _PROSE)
    assert rows[0]["section"] == "Introduction"


def test_plain_prose_scores_zero():
    assert _rows("## Clean\n\n" + _PROSE)[0]["load_score"] == 0


def test_dense_prose_outscores_plain_prose():
    dense = _rows("## Dense\n\n" + _DENSE)[0]["load_score"]
    plain = _rows("## Clean\n\n" + _PROSE)[0]["load_score"]
    assert dense > plain


def test_two_overloaded_signals_make_a_p1():
    row = _rows("## Dense\n\n" + _DENSE)[0]
    assert sum(1 for v in row["verdicts"].values() if v == "overloaded") >= 2
    assert cl.classify(row) == "P1"


def test_forward_references_are_counted():
    assert _rows("## S\n\n" + _DENSE)[0]["forward_reference_count"] >= 2


def test_jargon_counts_once_across_sections():
    doc = "## First\n\n" + _DENSE + "\n## Second\n\n" + _DENSE
    rows = _rows(doc)
    assert rows[0]["jargon_introduction_count"] >= 3
    assert rows[1]["jargon_introduction_count"] == 0


def test_a_custom_jargon_file_augments_rather_than_replaces(tmp_path):
    extra = tmp_path / "j.txt"
    extra.write_text("flux capacitor\n# a comment\n\n", encoding="utf-8")
    doc = tmp_path / "p.md"
    doc.write_text("## S\n\nThe flux capacitor drives crawl budget here.\n" + _PROSE,
                   encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(_SCRIPT), str(doc), "--format", "json", "--jargon", str(extra)],
        capture_output=True, text=True, check=False)
    found = json.loads(out.stdout)["sections"][0]["new_jargon"]
    assert "flux capacitor" in found, "the custom term was not picked up"
    assert "crawl budget" in found, "a default term was dropped — it replaced instead of augmenting"


def test_fenced_code_is_not_prose():
    assert _rows("## S\n\n```\n" + _DENSE + "\n```\n")[0]["load_score"] == 0


def test_a_markdown_table_is_not_prose():
    table = "## S\n\n| Acme Corp | Globex Systems |\n|---|---|\n| 42 | 99 |\n"
    assert _rows(table)[0]["words"] == 0


def test_a_short_section_is_listed_but_not_scored():
    # The bug this caught: 6 prose words with two names is "33.3 entities per
    # 100 words". Arithmetic, not a finding.
    row = _rows("## Tiny\n\nAcme Corp and Globex.\n")[0]
    assert row["scored"] is False
    assert row["load_score"] == 0
    assert cl.classify(row) == "unscored"


def test_an_unpunctuated_bullet_list_is_not_one_sentence():
    # Measured before the fix on a real reference doc: avg_clause_depth 27.0.
    bullets = "## Listy\n\n" + "- A point, with a clause, which extends, and more\n" * 12
    assert _rows(bullets)[0]["avg_clause_depth"] <= 6


def test_short_sections_do_not_drag_the_overall():
    doc = "## Tiny\n\nAcme Corp.\n\n## Real\n\n" + _PROSE
    out = cl.render(_rows(doc), "T", sum(r["words"] for r in _rows(doc)))
    assert "not scored" in out
    assert "Overall load: 0" in out


def test_json_output_is_valid_and_carries_priorities(tmp_path):
    doc = tmp_path / "p.md"
    doc.write_text("# T\n\n## Dense\n\n" + _DENSE + "\n## Clean\n\n" + _PROSE, encoding="utf-8")
    out = subprocess.run([sys.executable, str(_SCRIPT), str(doc), "--format", "json"],
                         capture_output=True, text=True, check=False)
    data = json.loads(out.stdout)
    assert data["title"] == "T"
    assert {s["priority"] for s in data["sections"]} <= {"P1", "P2", "healthy", "unscored"}


def test_exit_code_is_1_when_a_p1_exists(tmp_path):
    doc = tmp_path / "p.md"
    doc.write_text("## Dense\n\n" + _DENSE, encoding="utf-8")
    assert subprocess.run([sys.executable, str(_SCRIPT), str(doc)],
                          capture_output=True).returncode == 1


def test_exit_code_is_0_on_healthy_prose(tmp_path):
    doc = tmp_path / "p.md"
    doc.write_text("## Clean\n\n" + _PROSE, encoding="utf-8")
    assert subprocess.run([sys.executable, str(_SCRIPT), str(doc)],
                          capture_output=True).returncode == 0


def test_a_missing_file_is_an_error_not_a_traceback(tmp_path):
    out = subprocess.run([sys.executable, str(_SCRIPT), str(tmp_path / "nope.md")],
                         capture_output=True, text=True, check=False)
    assert out.returncode == 1
    assert "Traceback" not in out.stderr


def test_the_report_shape_matches_the_reference(tmp_path):
    doc = tmp_path / "p.md"
    doc.write_text("# T\n\n## Dense\n\n" + _DENSE + "\n## Clean\n\n" + _PROSE, encoding="utf-8")
    out = subprocess.run([sys.executable, str(_SCRIPT), str(doc)],
                         capture_output=True, text=True, check=False).stdout
    for anchor in ("## Cognitive Load Heatmap:", "Overall load:",
                   "| Section (H2) | Words | Load |", "### Overloaded sections (P1)",
                   "### Borderline sections (P2)", "### Healthy sections"):
        assert anchor in out, f"report is missing {anchor!r}"
