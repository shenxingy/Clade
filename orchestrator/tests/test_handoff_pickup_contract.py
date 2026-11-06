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

Each check reads the text a runtime hands the model — the canonical Claude Code
skill (prompt.md + SKILL.md), the clade-mcp package copy, and the generated
Codex plugin SKILL.md — not a helper that builds it.

The checks are prose assertions, so their strength is a question of which
regressions they notice. ``MUTATIONS`` answers it and keeps answering it: each
entry removes or rewords one guard in the canonical text, and
``test_every_mutation_is_noticed`` requires at least one check to go red. A
mutation whose anchor no longer matches fails rather than skips. The checks are
coupled to wording on purpose and say so where it matters: a rewording that
keeps the meaning breaks an anchor (loudly), a rewording that loses it should
break a check.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

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


def _branch(step5: str, label: str) -> str:
    """One `- **Label**` bullet of Step 5, continuation lines included."""
    start = step5.index(label)
    nxt = step5.find("\n- **", start + 1)
    return step5[start: nxt if nxt != -1 else len(step5)]


def _recheck_body(step5: str) -> str:
    """The numbered checks pickup runs: from 're-check first' to the first
    verdict branch. Grepping all of Step 5 would pass on words the verdict
    bullets repeat ('Drop it if'), and Step 3 repeats 'Meta.HEAD'."""
    start = step5.find("re-check first")
    assert start != -1, "Step 5 has no re-check before acting"
    end = step5.find("**Holds**", start)
    assert end != -1, "Step 5 has no **Holds** branch after the re-check"
    return step5[start:end]


def _paragraph_with(text: str, needle: str) -> str:
    """The blank-line-delimited paragraph of text that contains needle."""
    for para in re.split(r"\n\s*\n", text):
        if needle in para:
            return para
    raise AssertionError(f"no paragraph contains {needle!r}")


# A start instruction that runs ahead of the re-check: a start verb in the same
# sentence as a numbered Next Step or an urgency adverb. Wording-coupled by
# nature: it catches main's "Immediately start executing Next Steps #1" and
# "Start Next Steps #1 right away"; a start instruction that names neither is
# not caught, and the ordering check below is the backstop for Step 5 itself.
EARLY_START = re.compile(
    r"\b(?:start|begin|execute|run|resume|proceed|do)\b[^.\n]*"
    r"(?:Next Steps?\s*#\s*\d|right away|immediately|at once)",
    flags=re.IGNORECASE,
)

# ─── Checks: what /handoff writes ────────────────────────────────────────────

Check = Callable[[str, str], None]
CHECKS: list[Check] = []


def _check(fn: Check) -> Check:
    CHECKS.append(fn)
    return fn


@_check
def handoff_template_records_hypotheses_and_stop_conditions(handoff: str, pickup: str) -> None:
    templates = _handoff_templates(handoff)
    # prompt.md carries the authoritative template, SKILL.md the summary copy;
    # both reach the model, so both must carry the new sections.
    assert len(templates) == 2, f"expected 2 handoff templates, got {len(templates)}"
    for template in templates:
        heads = _headings(template)
        assert HYPOTHESES in heads, f"no ## {HYPOTHESES} in {heads}"
        assert STOP in heads, f"no ## {STOP} in {heads}"

        hyp = _section(template, HYPOTHESES)
        for status in STATUSES:
            assert f"[{status}]" in hyp, f"Hypotheses has no [{status}] entry"
        assert "Evidence:" in hyp, "Hypotheses records no evidence"
        assert "Drop it if:" in hyp, "Hypotheses records no drop condition"

        stop = _section(template, re.escape(STOP))
        for field in ("Done when:", "Stop and re-plan if:", "Out of scope:"):
            assert field in stop, f"{STOP} has no {field!r}"

        # The re-check needs to know what landed after the handoff.
        assert "- HEAD:" in _section(template, "Meta"), "Meta records no HEAD"


@_check
def handoff_templates_agree_on_section_headers(handoff: str, pickup: str) -> None:
    """SKILL.md says pickup parses 'these exact section headers' while prompt.md
    holds the authoritative template; one updated without the other is drift."""
    first, second = (_headings(t) for t in _handoff_templates(handoff))
    assert first == second


@_check
def incremental_handoff_carries_hypotheses_forward(handoff: str, pickup: str) -> None:
    """Every second and later /handoff in a chain takes the incremental path, so
    that is where ruled-out entries would be lost."""
    step2 = _section(handoff, r"Step 2: Detect Iteration Number")
    carry = _paragraph_with(step2, "Carry Hypotheses forward")
    assert "keep every ruled-out entry" in carry, "the incremental update drops ruled-out entries"
    assert STOP in carry, f"the incremental update does not carry {STOP!r}"


# ─── Checks: what /pickup reads and does ─────────────────────────────────────

@_check
def pickup_parses_every_section_the_resume_depends_on(handoff: str, pickup: str) -> None:
    parsed = _pickup_parse_list(pickup)
    assert HYPOTHESES in parsed, f"pickup never reads {HYPOTHESES}: {parsed}"
    assert STOP in parsed, f"pickup never reads {STOP}: {parsed}"

    # Every name pickup parses must be a heading the handoff actually writes;
    # a rename on one side silently empties that field on the other.
    for template in _handoff_templates(handoff):
        heads = _headings(template)
        for name in parsed:
            assert any(h.startswith(name) for h in heads), (
                f"pickup parses {name!r}, handoff writes only {heads}"
            )


@_check
def pickup_treats_next_steps_as_proposals(handoff: str, pickup: str) -> None:
    parse = _section(pickup, r"Step 2: Read \+ Parse")
    assert re.search(r"\*\*Next Steps\*\*:.*proposals, not orders", parse, flags=re.DOTALL)
    # A handoff written before v3 has no Hypotheses section; pickup must still
    # name an assumption to re-check rather than skip the re-check.
    assert "v2 handoff" in parse and "UNCONFIRMED" in parse


@_check
def pickup_handles_the_handoffs_no_hypothesis_marker(handoff: str, pickup: str) -> None:
    """The handoff tells a mechanical session to write a fixed marker instead of
    a hypothesis; pickup must recognise that exact marker, or Step 5 re-checks
    'the current hypothesis' when there is none and fits no verdict."""
    m = re.search(r'Mechanical work with no hypothesis: write "([^"]+)"', handoff)
    assert m, "the handoff no longer names its no-hypothesis marker"
    marker = m.group(1)
    para = _paragraph_with(_section(pickup, r"Step 2: Read \+ Parse"), marker)
    for must in ("check 1", "check 3", "skips check 2", "**Holds**"):
        assert must in para, f"pickup's no-hypothesis case does not say {must!r}"


@_check
def pickup_lists_every_commit_since_the_handoff(handoff: str, pickup: str) -> None:
    """A fixed `git log -10` cannot answer 'what landed after Meta.HEAD' past
    ten commits, nor at all once Meta.HEAD left the history (rebase, squash
    merge, another branch) — the 'ground moved' case the re-check exists for."""
    step3 = _section(pickup, r"Step 3: Verify Git State")
    assert "git log --oneline <Meta.HEAD>..HEAD" in step3, "Step 3 lists no commits since Meta.HEAD"
    assert "git merge-base --is-ancestor <Meta.HEAD> HEAD" in step3, (
        "Step 3 cannot tell a moved history from an unchanged one"
    )
    moved = _paragraph_with(step3, "ancestor: 1")
    assert "repository moved" in moved and "Contradicted" in moved, (
        "a history without Meta.HEAD is not routed to Contradicted"
    )


@_check
def pickup_rechecks_the_hypothesis_before_acting(handoff: str, pickup: str) -> None:
    step5 = _section(pickup, r"Step 5:")

    # The old order: execute the last session's plan on sight.
    assert "Immediately start executing" not in step5, "pickup still executes Next Steps as orders"

    recheck = step5.find("re-check first")
    assert recheck != -1, "Step 5 has no re-check before acting"
    start = step5.find("Do NOT ask")
    assert start != -1, "Step 5 lost its no-'shall I proceed' autonomy"
    assert recheck < start, "Step 5 acts before it re-checks"

    # Nothing before the re-check — Steps 1-4 or Step 5's preamble — starts work.
    ahead = pickup[: pickup.index("re-check first")]
    early = EARLY_START.search(ahead)
    assert not early, f"a start instruction runs ahead of the re-check: {early.group(0)!r}"

    # The three outcomes: proceed, re-plan, or proceed flagged.
    for outcome in ("**Holds**", "**Contradicted**", "**Cannot be checked cheaply**"):
        assert outcome in step5, f"Step 5 has no {outcome} branch"
    contradicted = _branch(step5, "**Contradicted**")
    assert "do not execute the old Next Steps" in contradicted
    assert "re-plan" in contradicted
    assert "without asking" in contradicted, (
        "a contradicted hypothesis must re-plan, not stall on a question"
    )
    assert "repository moved" in contradicted, "a moved repository does not reach Contradicted"


@_check
def pickup_recheck_names_what_to_check(handoff: str, pickup: str) -> None:
    """The label 're-check first' with nothing under it re-checks nothing."""
    checks = _recheck_body(_section(pickup, r"Step 5:"))
    # 1. Repository: commits since the handoff, and a history that lost it.
    assert "commit after Meta.HEAD" in checks, "the re-check never looks at what landed since the handoff"
    assert "not an ancestor" in checks, "the re-check ignores a history that lost Meta.HEAD"
    # 2. Verified facts: run the hypothesis's own falsifier; inferred is not verified.
    assert "Drop it if" in checks, "the re-check never runs the hypothesis's drop condition"
    assert "inferred" in checks, "the re-check treats an inferred fact as verified"
    # 3. Stop conditions: a met goal stops; out-of-scope steps are dropped.
    assert "Done when" in checks and "report that and stop" in checks, (
        "a goal already met does not stop the resume"
    )
    assert "Out of scope" in checks, "out-of-scope steps are not dropped"


@pytest.mark.parametrize("check", CHECKS, ids=lambda fn: fn.__name__)
@pytest.mark.parametrize("surface", sorted(SURFACES))
def test_contract_holds(surface: str, check: Check) -> None:
    check(_skill_text(surface, "handoff"), _skill_text(surface, "pickup"))


# ─── Mutations: every guard above is observed ────────────────────────────────
# (label, skill, regex, replacement). Applied to the canonical claude surface
# with re.DOTALL; the regex must match, and the result must differ.

MUTATIONS: list[tuple[str, str, str, str]] = [
    # Step 5's re-check body (review of PR #179: M1, M2, M11).
    ("repository and verified-fact checks dropped", "pickup",
     r"1\. \*\*Repository\*\*.*?(?=3\. \*\*Stop conditions\*\*)", ""),
    ("repository check no longer asks what landed", "pickup",
     r"did any commit after Meta\.HEAD \(Step 3\) touch .*?what its Evidence says\?", "is the tree clean?"),
    ("verified-fact check no longer runs the falsifier", "pickup",
     r're-run the cheapest check its Evidence or "Drop it if" line\n   names', "skim the Evidence"),
    ("re-check body replaced by a stub", "pickup",
     r"(re-check first\.\*\*[^\n]*\n).*?(?=\nPrint one line)", r"\1Done when / Out of scope noted.\n"),
    ("a met goal no longer stops the resume", "pickup",
     r"report that and stop", "note it and continue with Next Steps anyway"),
    ("inferred facts count as verified", "pickup",
     r' A fact the handoff marks "inferred" is\n   not verified\.', ""),
    ("out-of-scope steps are kept", "pickup",
     r' Drop any proposed step that falls under "Out of scope"\.', ""),
    ("re-check ignores a moved history", "pickup",
     r" If Step 3\n   found Meta\.HEAD is not an ancestor of HEAD, the repository moved: Contradicted\.", ""),
    # Step 3 (M6, and the -10 window it replaced).
    ("Step 3 lists no commits", "pickup", r"git log --oneline <Meta\.HEAD>\.\.HEAD\n", ""),
    ("Step 3 back to a fixed window", "pickup",
     r"git log --oneline <Meta\.HEAD>\.\.HEAD\n", "git log --oneline -10\n"),
    ("ancestor check dropped", "pickup",
     r'git merge-base --is-ancestor <Meta\.HEAD> HEAD; echo "ancestor: \$\?"\n', ""),
    ("a moved history is not routed anywhere", "pickup",
     r" Step 5 takes the Contradicted path\.", ""),
    ("Contradicted no longer covers a moved repository", "pickup",
     r"or the\n  repository moved under it", "or a\n  later commit undid it"),
    # The no-hypothesis marker, on both sides.
    ("pickup ignores the no-hypothesis marker", "pickup",
     r"A v3 handoff whose Hypotheses section is .*?acts as \*\*Holds\*\*\.\n", ""),
    ("handoff renames its no-hypothesis marker", "handoff",
     r'write "- none — mechanical work"', 'write "- n/a"'),
    ("no-hypothesis case asks instead of acting", "pickup",
     r"Step 5 still runs check 1 .*?acts as \*\*Holds\*\*\.", "Step 5 asks the user what to do."),
    # Step 5's ordering and verdicts (the PR body's D, E, G; review M7).
    ("start instruction before the re-check", "pickup",
     r"So test the ground under them before the first edit\.",
     "Start Next Steps #1 right away; do not wait."),
    ("autonomy granted ahead of the re-check", "pickup",
     r"(\*\*If Blocked has items\*\*)", r"Do NOT ask before acting; begin the work.\n\n\1"),
    ("main's order restored in Step 4", "pickup",
     r"(### Step 5: Re-check)", r"Immediately start executing Next Steps #1.\n\n\1"),
    ("Holds asks before starting", "pickup",
     r'Do NOT ask "shall I proceed\?" — just start\.', 'Ask "shall I proceed?" first.'),
    ("Contradicted asks before starting", "pickup",
     r"start it — still without asking\.", "start it after asking the user."),
    ("Contradicted runs the old plan", "pickup",
     r"do not execute the old Next Steps\.", "finish the old Next Steps first."),
    # Step 2 parsing (the PR body's A).
    ("pickup stops parsing Hypotheses", "pickup", r"^- \*\*Hypotheses\*\*:", "- Hypotheses:"),
    ("pickup stops parsing stop conditions", "pickup",
     r"^- \*\*Stop conditions & out of scope\*\*:", "- Stop conditions:"),
    ("Next Steps become orders", "pickup", r"so they are proposals, not orders", "so run them in order"),
    ("v2 fallback dropped", "pickup", r"A v2 handoff \(`STRUCTURED HANDOFF v2`\).*?in Step 5\.\n", ""),
    # The producer (the PR body's B, C, F; review M5).
    ("incremental update stops carrying Hypotheses", "handoff",
     r"  - Carry Hypotheses forward:.*?add both\.\n", ""),
    ("incremental update drops ruled-out entries", "handoff", r"keep every ruled-out entry, ", ""),
    ("carry-forward made optional", "handoff",
     r"Carry Hypotheses forward:", "If time allows, revisit hypotheses:"),
    ("drop condition removed from the templates", "handoff", r"Drop it if:", "Note:"),
    ("Meta stops recording HEAD", "handoff", r"^- HEAD: ", "- Head commit: "),
    ("SKILL.md template drifts from prompt.md", "handoff",
     r"## Hypotheses\n(?=- \*\*H1 \[current\]\*\*: <)", "## Assumptions\n"),
]


def _failing_checks(handoff: str, pickup: str) -> list[str]:
    failed = []
    for check in CHECKS:
        try:
            check(handoff, pickup)
        except (AssertionError, ValueError):
            failed.append(check.__name__)
    return failed


def test_mutation_control_is_green() -> None:
    """The harness reads the same texts the mutations edit; unmutated, they pass."""
    assert _failing_checks(_skill_text("claude", "handoff"), _skill_text("claude", "pickup")) == []


@pytest.mark.parametrize("mutation", MUTATIONS, ids=lambda m: m[0])
def test_every_mutation_is_noticed(mutation: tuple[str, str, str, str]) -> None:
    label, skill, pattern, replacement = mutation
    texts = {name: _skill_text("claude", name) for name in ("handoff", "pickup")}
    mutated, count = re.subn(pattern, replacement, texts[skill], flags=re.DOTALL | re.MULTILINE)
    assert count, f"{label}: anchor no longer matches the {skill} text — update the mutation"
    assert mutated != texts[skill], f"{label}: the mutation is a no-op"
    texts[skill] = mutated
    assert _failing_checks(texts["handoff"], texts["pickup"]), (
        f"{label}: every check stayed green — that guard is claimed, not checked"
    )
