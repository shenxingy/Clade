"""The /handoff ↔ /pickup contract, read from every surface that ships it.

/handoff writes a file and /pickup reads it back, so the two prompts are a
producer/consumer pair with no code between them: a section one writes and the
other never reads is lost at every reset, and a section the reader expects that
the writer never emits is parsed as empty.

The property pinned here is the context-inertia fix (TODO.md, 2026-11-05 sweep;
Breunig, *Context Inertia*, 2026-10-14). /pickup used to say "Immediately start
executing Next Steps #1", which carried the last session's hypothesis across
the reset as orders. A Hypotheses section ALONE would carry the same inertia
(the skeptic's warning), so the producer change and the consumer re-check are
asserted together: the handoff records each hypothesis with evidence, status
and a drop condition plus stop conditions; pickup parses both, re-checks the
current hypothesis before it acts, keeps its no-"shall I proceed" autonomy, and
re-plans when the check contradicts the hypothesis.

Each assertion reads the text a runtime hands the model — the canonical
Claude Code skill (prompt.md + SKILL.md), the clade-mcp package copy, and the
generated Codex plugin SKILL.md — not a helper that builds it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# ─── Surfaces ────────────────────────────────────────────────────────────────

SURFACES = {
    "claude": REPO_ROOT / "configs" / "skills",
    "mcp": REPO_ROOT / "mcp-package" / "skills",
    "codex": REPO_ROOT / "plugins" / "clade" / "skills",
}

HYPOTHESES = "Hypotheses"
STOP = "Stop conditions & out of scope"
STATUSES = ("current", "UNCONFIRMED", "ruled-out")


def _skill_text(surface: str, skill: str) -> str:
    """Everything the runtime hands the model for one skill on one surface."""
    skill_dir = SURFACES[surface] / skill
    parts = [
        (skill_dir / name).read_text(encoding="utf-8")
        for name in ("prompt.md", "SKILL.md")
        if (skill_dir / name).is_file()
    ]
    assert parts, f"{skill} ships nothing on the {surface} surface ({skill_dir})"
    return "\n".join(parts)


def _handoff_templates(text: str) -> list[str]:
    """Every fenced markdown block that is a handoff template."""
    blocks = re.findall(r"```markdown\n(.*?)```", text, flags=re.DOTALL)
    return [b for b in blocks if b.lstrip().startswith("# Handoff:")]


def _headings(template: str) -> list[str]:
    """`##`/`###` headings of a template, without the hashes."""
    return [
        m.group(1).strip()
        for m in re.finditer(r"^#{2,3} (.+)$", template, flags=re.MULTILINE)
    ]


def _section(text: str, heading_re: str) -> str:
    """Body under the first heading matching heading_re, up to the next heading
    at the same or a higher level."""
    m = re.search(rf"^(#+) {heading_re}.*$", text, flags=re.MULTILINE)
    assert m, f"no heading matching {heading_re!r}"
    level = len(m.group(1))
    rest = text[m.end():]
    nxt = re.search(rf"^#{{1,{level}}} ", rest, flags=re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _pickup_parse_list(pickup: str) -> list[str]:
    """Section names pickup's Step 2 says it parses (`- **Name**:` bullets)."""
    body = _section(pickup, r"Step 2: Read \+ Parse")
    return re.findall(r"^- \*\*(.+?)\*\*:", body, flags=re.MULTILINE)


# ─── Producer: what /handoff writes ──────────────────────────────────────────

@pytest.mark.parametrize("surface", sorted(SURFACES))
def test_handoff_template_records_hypotheses_and_stop_conditions(surface: str) -> None:
    templates = _handoff_templates(_skill_text(surface, "handoff"))
    # prompt.md carries the authoritative template, SKILL.md the summary copy;
    # both reach the model, so both must carry the new sections.
    assert len(templates) == 2, f"{surface}: expected 2 handoff templates, got {len(templates)}"
    for template in templates:
        heads = _headings(template)
        assert HYPOTHESES in heads, f"{surface}: no ## {HYPOTHESES} in {heads}"
        assert STOP in heads, f"{surface}: no ## {STOP} in {heads}"

        hyp = _section(template, HYPOTHESES)
        for status in STATUSES:
            assert f"[{status}]" in hyp, f"{surface}: Hypotheses has no [{status}] entry"
        assert "Evidence:" in hyp, f"{surface}: Hypotheses records no evidence"
        assert "Drop it if:" in hyp, f"{surface}: Hypotheses records no drop condition"

        stop = _section(template, re.escape(STOP))
        for field in ("Done when:", "Stop and re-plan if:", "Out of scope:"):
            assert field in stop, f"{surface}: {STOP} has no {field!r}"

        # The re-check needs to know what landed after the handoff.
        assert "- HEAD:" in _section(template, "Meta"), f"{surface}: Meta records no HEAD"


@pytest.mark.parametrize("surface", sorted(SURFACES))
def test_handoff_templates_agree_on_section_headers(surface: str) -> None:
    """SKILL.md says pickup parses 'these exact section headers' while prompt.md
    holds the authoritative template; one updated without the other is drift."""
    first, second = (_headings(t) for t in _handoff_templates(_skill_text(surface, "handoff")))
    assert first == second


# ─── Consumer: what /pickup reads and does ───────────────────────────────────

@pytest.mark.parametrize("surface", sorted(SURFACES))
def test_pickup_parses_every_section_the_resume_depends_on(surface: str) -> None:
    parsed = _pickup_parse_list(_skill_text(surface, "pickup"))
    assert HYPOTHESES in parsed, f"{surface}: pickup never reads {HYPOTHESES}: {parsed}"
    assert STOP in parsed, f"{surface}: pickup never reads {STOP}: {parsed}"

    # Every name pickup parses must be a heading the handoff actually writes;
    # a rename on one side silently empties that field on the other.
    for template in _handoff_templates(_skill_text(surface, "handoff")):
        heads = _headings(template)
        for name in parsed:
            assert any(h.startswith(name) for h in heads), (
                f"{surface}: pickup parses {name!r}, handoff writes only {heads}"
            )


@pytest.mark.parametrize("surface", sorted(SURFACES))
def test_pickup_rechecks_the_hypothesis_before_acting(surface: str) -> None:
    step5 = _section(_skill_text(surface, "pickup"), r"Step 5:")

    # The old order: execute the last session's plan on sight.
    assert "Immediately start executing" not in step5, (
        f"{surface}: pickup still executes Next Steps as orders"
    )

    recheck = step5.find("re-check first")
    assert recheck != -1, f"{surface}: Step 5 has no re-check before acting"
    start = step5.find("Do NOT ask")
    assert start != -1, f"{surface}: Step 5 lost its no-'shall I proceed' autonomy"
    assert recheck < start, f"{surface}: Step 5 acts before it re-checks"

    # The three outcomes: proceed, re-plan, or proceed flagged.
    for outcome in ("**Holds**", "**Contradicted**", "**Cannot be checked cheaply**"):
        assert outcome in step5, f"{surface}: Step 5 has no {outcome} branch"
    contradicted = _branch(step5, "**Contradicted**")
    assert "do not execute the old Next Steps" in contradicted
    assert "re-plan" in contradicted
    assert "without asking" in contradicted, (
        f"{surface}: a contradicted hypothesis must re-plan, not stall on a question"
    )

    # And the stop conditions the handoff now records are honoured.
    assert "Done when" in step5 and "Out of scope" in step5


@pytest.mark.parametrize("surface", sorted(SURFACES))
def test_pickup_treats_next_steps_as_proposals(surface: str) -> None:
    pickup = _skill_text(surface, "pickup")
    parse = _section(pickup, r"Step 2: Read \+ Parse")
    assert re.search(r"\*\*Next Steps\*\*:.*proposals, not orders", parse, flags=re.DOTALL)
    # A handoff written before v3 has no Hypotheses section; pickup must still
    # name an assumption to re-check rather than skip the re-check.
    assert "v2 handoff" in parse and "UNCONFIRMED" in parse


def _branch(step5: str, label: str) -> str:
    """One `- **Label**` bullet of Step 5, continuation lines included."""
    start = step5.index(label)
    nxt = step5.find("\n- **", start + 1)
    return step5[start: nxt if nxt != -1 else len(step5)]
