"""The second-order pass `ai-slop-detection.md` specified and nothing ran.

The reference is explicit that a phrase blocklist is necessary and not
sufficient — replace the obvious vocabulary and the model reaches for structural
patterns a word swap cannot touch. It then specifies ten structural tics and
three rhythmic signals with numeric thresholds, names `lint_prose.py` as their
implementation, and that file did not exist, so "AI-detection passed" has meant
the first-order pass alone.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "configs" / "scripts" / "blog" / "lint_prose.py"


def _load():
    spec = importlib.util.spec_from_file_location("lint_prose", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["lint_prose"] = module
    spec.loader.exec_module(module)
    return module


lp = _load()

_HUMAN = (
    "## The cost nobody budgets\n\n"
    "Migrations fail on the boring parts. Not the schema. The seventeen scripts "
    "nobody remembered, each pointing at a column that moved.\n\n"
    "## What we changed\n\n"
    "We froze writes for four hours on a Sunday, which everyone hated and which "
    "turned out to be the only thing that worked. The alternative was a "
    "dual-write window, and dual writes mean reconciliation, and reconciliation "
    "means a second bug surface at exactly the moment you can least afford one. "
    "So: four hours, one Sunday, done.\n\nIt held.\n"
)


def _fired(text, key="fired"):
    return set(lp.analyze(text, include_first=False)[key])


def test_the_script_the_reference_names_exists():
    assert _SCRIPT.is_file()


def test_self_test_passes():
    assert lp.self_test() == 0


def test_human_prose_trips_no_blocking_signal():
    assert _fired(_HUMAN) == set()


def test_question_cadence_headings_fire():
    doc = "".join(f"## Is this number {i}?\n\nSome prose here about it.\n\n" for i in range(4))
    assert "question_cadence_h2" in _fired(doc)


def test_mixed_heading_forms_do_not_fire():
    doc = ("## What broke\n\nA thing.\n\n## Is it fixed?\n\nYes.\n\n"
           "## The rollout\n\nSlow.\n\n## Costs\n\nHigh.\n")
    assert "question_cadence_h2" not in _fired(doc)


def test_here_openers_fire():
    doc = "\n\n".join(["Here's the thing about it.", "Here are the reasons why.",
                       "Here is the answer to that.", "Here's another one entirely."])
    assert "here_openers" in _fired(doc)


def test_the_key_insight_tell_fires():
    assert "key_insight_tell" in _fired("A sentence. The key insight is that it works.")


def test_wrapup_questions_fire_at_three():
    doc = ("Why does this matter? A line. What does this mean for teams? Another. "
           "What does this mean for buyers? Done.")
    assert "wrapup_question" in _fired(doc)


def test_hedge_stacking_fires():
    doc = ("It may often be typically the case that this generally usually holds "
           "for most teams in most situations across most quarters.")
    assert "hedge_stacking" in _fired(doc)


def test_hedge_counting_uses_word_boundaries():
    # "maybe" contains "may"; "unlikely" contains "likely". Substring counting
    # scored ordinary prose as hedging.
    doc = ("Maybe the unlikely maybe unlikely maybe unlikely case is maybe the "
           "unlikely one that maybe seems unlikely to maybe hold unlikely.")
    assert "hedge_stacking" not in _fired(doc)


def test_false_balance_fires():
    doc = " ".join(["While speed matters, it also costs."] * 5)
    assert "false_balance" in _fired(doc)


def test_a_structural_signal_survives_a_vocabulary_swap():
    # The entire premise of a second-order pass.
    doc = "".join(f"## Is this thing {i}?\n\nProse.\n\n" for i in range(4))
    swapped = doc.replace("thing", "widget").replace("Prose", "Copy")
    assert "question_cadence_h2" in _fired(swapped)


def test_fenced_code_is_not_linted():
    doc = "## Real heading\n\nSome prose.\n\n```\n## Is this a heading?\nHere's a thing.\n```\n"
    assert _fired(doc) == set()


def test_a_heading_inside_a_fence_is_not_a_heading():
    # Reading the raw text counted fenced `##` lines as post headings.
    doc = "## One\n\nProse.\n\n```\n" + "## Is it?\n" * 8 + "```\n"
    assert "question_cadence_h2" not in _fired(doc)


def test_short_paragraphs_of_short_sentences_are_not_called_flat():
    # 6/3/12 words is four-fold variation and SD 3.7; an absolute floor alone
    # calls that machinery.
    para = ("Migrations fail on the boring parts. Not the schema. The seventeen "
            "scripts nobody remembered, each pointing at a column that moved.")
    assert "paragraph_sentence_flatness" not in set(
        lp.analyze(para, include_first=False)["advisory"])


def test_the_measured_noisy_signals_are_advisory_not_blocking():
    for signal in ("paragraph_shape_flatness", "paragraph_sentence_flatness",
                   "opening_word_repetition", "symmetric_list_bloat"):
        assert signal in lp.ADVISORY


def test_advisory_signals_never_leak_into_the_blocking_set():
    doc = "## S\n\n" + "- Item of a fixed length here\n" * 8
    result = lp.analyze(doc, include_first=False)
    assert not set(result["fired"]) & lp.ADVISORY


def test_phrase_tables_are_borrowed_not_restated():
    # Two copies of one list is how they diverge.
    assert lp.AI_PHRASES, "AI_PHRASES did not load from analyze_blog.py"
    source = (_SCRIPT.parent / "analyze_blog.py").read_text(encoding="utf-8")
    body = _SCRIPT.read_text(encoding="utf-8")
    for phrase in lp.AI_PHRASES[:5]:
        assert phrase in source
        assert f'"{phrase}"' not in body, f"{phrase!r} is hard-coded in lint_prose.py"


def test_first_order_is_opt_in(tmp_path):
    doc = tmp_path / "p.md"
    doc.write_text(_HUMAN, encoding="utf-8")
    plain = subprocess.run([sys.executable, str(_SCRIPT), str(doc), "--format", "json"],
                           capture_output=True, text=True, check=False)
    assert "first_order" not in json.loads(plain.stdout)
    withfo = subprocess.run(
        [sys.executable, str(_SCRIPT), str(doc), "--format", "json", "--first-order"],
        capture_output=True, text=True, check=False)
    assert "first_order" in json.loads(withfo.stdout)


def test_strict_makes_advisory_signals_fail(tmp_path):
    doc = tmp_path / "p.md"
    doc.write_text("## S\n\n" + "- Item of a fixed length here\n" * 8, encoding="utf-8")
    loose = subprocess.run([sys.executable, str(_SCRIPT), str(doc)], capture_output=True)
    strict = subprocess.run([sys.executable, str(_SCRIPT), str(doc), "--strict"],
                            capture_output=True)
    assert loose.returncode == 0
    assert strict.returncode == 1


def test_exit_code_is_1_on_a_blocking_signal(tmp_path):
    doc = tmp_path / "p.md"
    doc.write_text("A line. The key insight is that it works.\n", encoding="utf-8")
    assert subprocess.run([sys.executable, str(_SCRIPT), str(doc)],
                          capture_output=True).returncode == 1


def test_a_missing_file_is_an_error_not_a_traceback(tmp_path):
    out = subprocess.run([sys.executable, str(_SCRIPT), str(tmp_path / "nope.md")],
                         capture_output=True, text=True, check=False)
    assert out.returncode == 1 and "Traceback" not in out.stderr


def test_the_report_names_the_advisory_caveat(tmp_path):
    doc = tmp_path / "p.md"
    doc.write_text("## S\n\n" + "- Item of a fixed length here\n" * 8, encoding="utf-8")
    out = subprocess.run([sys.executable, str(_SCRIPT), str(doc)],
                         capture_output=True, text=True, check=False).stdout
    assert "advisory" in out.lower()
    assert "43-70%" in out
