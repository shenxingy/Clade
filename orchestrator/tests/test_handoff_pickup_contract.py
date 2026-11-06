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
mutation whose anchor no longer matches fails rather than skips. The claim is
exactly that table: every mutation in it must turn the suite red. An edit the
table does not list is not shown to be caught. The checks are coupled to
wording on purpose: a rewording that keeps the meaning breaks an anchor
(loudly); a rewording that loses it is caught when a listed mutation covers it.

Verdict branches are pinned by their TRIGGER (the parenthetical after the
label) and their BODY, not by the label alone: a label with its condition cut
routes nothing.
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


def _flat(text: str) -> str:
    """Whitespace collapsed, so an assertion survives a re-wrap of the prose."""
    return re.sub(r"\s+", " ", text)


def _bullet(text: str, label: str) -> str:
    """One `- **Label**` bullet, continuation lines included, flattened. It ends
    at the next top-level bullet or a blank line. Raises ValueError when the
    bullet is gone, which the mutation harness counts as red."""
    start = text.index(label)
    ends = [i for i in (text.find("\n- ", start + 1), text.find("\n\n", start + 1)) if i != -1]
    return _flat(text[start: min(ends) if ends else len(text)])


def _trigger(bullet: str) -> str:
    """The condition of a verdict bullet: the parenthetical after its label.
    Pinning the label alone lets the condition be cut while the branch stays."""
    m = re.match(r"- \*\*[^*]+\*\* \((.*?)\):", bullet)
    assert m, f"verdict bullet states no trigger: {bullet[:80]!r}"
    return m.group(1)


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
# sentence as a numbered Next Step, "the first/next (proposed) step", or an
# urgency adverb. Wording-coupled by nature: it catches main's "Immediately start
# executing Next Steps #1", "Start Next Steps #1 right away" and "start working on
# the first proposed step"; a start instruction that names none of them is not
# caught, and the ordering check below is the backstop for Step 5 itself.
EARLY_START = re.compile(
    r"\b(?:start|begin|execute|run|resume|proceed|do)\b[^.\n]*"
    r"(?:Next Steps?\s*#\s*\d|right away|immediately|at once"
    r"|\b(?:first|next) (?:proposed )?(?:Next )?step\b)",
    flags=re.IGNORECASE,
)

# A qualifier that makes the re-check optional. The one sanctioned skip is the
# no-hypothesis case's "skips check 2" (Step 2), which still runs checks 1 and 3.
OPTIONAL = re.compile(
    r"\bskip(?!s check 2\b)\w*|\bif time allows\b|\boptional(?:ly)?\b",
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

        # Each step names the hypothesis it rests on, so the steps that fall
        # with a contradicted hypothesis are visible to the re-plan.
        assert "(rests on H1)" in _section(template, "Next Steps"), (
            "Next Steps no longer name the hypothesis they rest on"
        )

        # The re-check needs to know what landed after the handoff.
        assert "- HEAD:" in _section(template, "Meta"), "Meta records no HEAD"

    # pickup re-checks "the current one", which presumes there is one at most.
    assert "At most one is current" in handoff, "the template allows several current hypotheses"


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
    carry = _flat(_paragraph_with(step2, "Carry Hypotheses forward"))
    assert "keep every ruled-out entry" in carry, "the incremental update drops ruled-out entries"
    assert STOP in carry, f"the incremental update does not carry {STOP!r}"
    # Kept, but bounded: a session start auto-loads only the head of the file,
    # and Hypotheses sits above Next Steps and Meta.
    assert "shrinks to one line" in carry, "carried ruled-out entries grow without bound"


@_check
def handoff_report_names_the_current_hypothesis(handoff: str, pickup: str) -> None:
    report = _section(handoff, r"Step 4: Report")
    assert "Current hypothesis:" in report, "the handoff report hides the hypothesis Next rests on"


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

    # What each status means to the reader: the current one carries its
    # falsifier, UNCONFIRMED is not fact, ruled-out is not re-tried.
    hyp = _bullet(_section(pickup, r"Step 2: Read \+ Parse"), "- **Hypotheses**")
    assert '"Drop it if"' in hyp, "pickup does not read the current hypothesis's drop condition"
    assert "(not facts)" in hyp, "pickup reads UNCONFIRMED hypotheses as facts"
    assert "do not re-try them" in hyp, "pickup re-tries ruled-out hypotheses"


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
    ten commits. And `--is-ancestor` has three answers that need three routes:
    0 (log is complete), 1 (object here, history moved — a rebase or a squash
    merge, which is how this repository lands every PR, so content decides, not
    history), 128 (object absent — nothing can say, so not re-checked)."""
    step3 = _section(pickup, r"Step 3: Verify Git State")
    assert "git log --oneline <Meta.HEAD>..HEAD" in step3, "Step 3 lists no commits since Meta.HEAD"
    assert "git merge-base --is-ancestor <Meta.HEAD> HEAD" in step3, (
        "Step 3 cannot tell a moved history from an unchanged one"
    )

    moved = _bullet(step3, "- **ancestor: 1**")
    assert "squash-merged" in moved and "check 1 diffs the cited files" in moved, (
        "a rebased or squash-merged history is not compared by content"
    )
    assert "not evidence against the hypothesis" in moved, "a changed history alone counts as evidence"
    assert "Contradicted" not in moved, "a rebase or squash merge alone discards the old Next Steps"

    absent = _bullet(step3, "- **ancestor: 128**")
    assert "does not have the commit" in absent, "exit 128 is not classified"
    assert "check 1 cannot run" in absent and "Cannot-be-checked path" in absent, (
        "a clone without Meta.HEAD is not routed to Cannot be checked"
    )

    # Without this fallback every v2 handoff runs --is-ancestor on a HEAD it
    # never recorded and exits 128.
    v2 = _paragraph_with(step3, "A v2 handoff has no Meta.HEAD")
    assert "git log --oneline -10" in v2 and "Done list" in v2, "a v2 handoff has no Step 3 fallback"


@_check
def pickup_briefing_shows_the_hypothesis_and_proposals(handoff: str, pickup: str) -> None:
    briefing = _section(pickup, r"Step 4: Display Briefing")
    assert "Hypothesis: {current hypothesis" in briefing, "the briefing hides the hypothesis"
    assert "Proposed next (re-checked in Step 5):" in briefing, "the briefing presents Next Steps as the plan"


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

    # Nothing anywhere in the steps makes the re-check optional.
    optional = OPTIONAL.search(_section(pickup, r"Execution Steps"))
    assert not optional, f"a qualifier makes the re-check optional: {optional.group(0)!r}"

    flat5 = _flat(step5)
    assert "Print one line — `Re-check: {H} holds | contradicted | not re-checked" in flat5, (
        "the verdict is never stated, so nobody can see which branch ran"
    )
    assert "Contradicted wins" in flat5, "a check that could not run can outvote one that contradicts"

    # The three outcomes, each by trigger and body, not by label.
    holds = _bullet(step5, "- **Holds**")
    holds_when = _trigger(holds)
    assert "the check supports it, finds nothing against it" in holds_when, (
        "Holds no longer requires a check that ran"
    )
    assert not re.search(r"not run|\bskip|unchecked", holds_when), f"Holds admits an un-run check: {holds_when!r}"
    assert "first Next Step that still follows from it" in holds, (
        "Holds runs Next Steps #1 even when the stop conditions dropped it"
    )

    contradicted = _bullet(step5, "- **Contradicted**")
    contradicted_when = _trigger(contradicted)
    for cond in ('"Drop it if"', '"Stop and re-plan if"', "no longer says what its Evidence says"):
        assert cond in contradicted_when, f"Contradicted does not fire when {cond} is met"
    assert "do not execute the old Next Steps" in contradicted
    assert "Re-plan from the Goal" in contradicted, "a contradicted hypothesis is not re-planned"
    assert "without asking" in contradicted, (
        "a contradicted hypothesis must re-plan, not stall on a question"
    )
    assert "so the next /handoff carries it" in contradicted, "the contradicted hypothesis is not recorded"

    cannot = _bullet(step5, "- **Cannot be checked cheaply**")
    assert "128" in _trigger(cannot), "a clone without Meta.HEAD is not a cannot-check case"
    for must in ("UNCONFIRMED", "not re-checked", "tests it"):
        assert must in cannot, f"Cannot be checked cheaply is an unconditioned bypass: no {must!r}"


@_check
def pickup_recheck_names_what_to_check(handoff: str, pickup: str) -> None:
    """The label 're-check first' with nothing under it re-checks nothing."""
    checks = _flat(_recheck_body(_section(pickup, r"Step 5:")))
    # 1. Repository: the cited files, by content, whatever the history did.
    assert "still say what its Evidence says" in checks, "the re-check never compares the Evidence"
    assert "git diff --stat <Meta.HEAD> HEAD -- <cited paths>" in checks and "by content" in checks, (
        "the re-check does not compare the cited files by content"
    )
    assert "not in its Done list" in checks, "a v2 handoff has no repository check"
    assert "128, this check cannot run: say so" in checks, "a check that cannot run is silent"
    # 2. Verified facts: run the hypothesis's own falsifier; inferred is not verified.
    assert '"Drop it if"' in checks, "the re-check never runs the hypothesis's drop condition"
    assert 'A fact the handoff marks "inferred" is not verified' in checks, (
        "the re-check treats an inferred fact as verified"
    )
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
# with re.DOTALL | re.MULTILINE; the regex must match, and the result must
# differ. R<n> labels are the reviewer mutations from the second review of
# PR #179 that stayed green against the previous head.

MUTATIONS: list[tuple[str, str, str, str]] = [
    # Step 5's re-check body (first review of PR #179: M1, M2, M11; second: R2).
    ("repository and verified-fact checks dropped", "pickup",
     r"1\. \*\*Repository\*\*.*?(?=3\. \*\*Stop conditions\*\*)", ""),
    ("repository check no longer compares the Evidence", "pickup",
     r"do the files the current hypothesis cites still say what its\n   Evidence says\?",
     "did anything land since the handoff?"),
    ("repository check diffs nothing", "pickup",
     r"`git diff --stat <Meta\.HEAD> HEAD -- <cited paths>`", "`git log --oneline -3`"),
    ("v2 handoff has no repository check", "pickup",
     r"\n   A v2 handoff: look at the commits from Step 3 that are not in its Done list\.", ""),
    ("a check that cannot run stays silent", "pickup",
     r"\n   If Step 3 still got 128, this check cannot run: say so\.", ""),
    ("verified-fact check no longer runs the falsifier", "pickup",
     r're-run the cheapest check its Evidence or "Drop it if" line\n   names', "skim the Evidence"),
    ("re-check body replaced by a stub", "pickup",
     r"(re-check first\.\*\*[^\n]*\n).*?(?=\nPrint one line)", r"\1Done when / Out of scope noted.\n"),
    ("a met goal no longer stops the resume", "pickup",
     r"report that and stop", "note it and continue with Next Steps anyway"),
    ("inferred facts count as verified (sentence cut)", "pickup",
     r' A fact the handoff marks "inferred" is\n   not verified\.', ""),
    ("R2 inferred facts count as verified (reworded)", "pickup",
     r'marks "inferred" is\n   not verified\.', 'marks "inferred" counts as\n   verified.'),
    ("out-of-scope steps are kept", "pickup",
     r' Drop any proposed step that falls under "Out of scope"\.', ""),
    ("R14 re-check made skippable", "pickup",
     r"(re-check first\.\*\*)", r"\1 Skip it entirely when the handoff is under 2 hours old."),
    # Step 3 (M6, the -10 window it replaced, and the second review's R6/R7 and
    # its exit-1 finding).
    ("Step 3 lists no commits", "pickup", r"git log --oneline <Meta\.HEAD>\.\.HEAD\n", ""),
    ("Step 3 back to a fixed window", "pickup",
     r"git log --oneline <Meta\.HEAD>\.\.HEAD\n", "git log --oneline -10\n"),
    ("ancestor check dropped", "pickup",
     r'git merge-base --is-ancestor <Meta\.HEAD> HEAD; echo "ancestor: \$\?"\n', ""),
    ("exit 1 routed to Contradicted again", "pickup",
     r"Content still compares: Step 5's check 1 diffs .*?not evidence against the hypothesis\.",
     "The repository moved: Step 5 takes the Contradicted path."),
    ("exit 1 counts a changed history as evidence", "pickup",
     r"A changed history alone is not evidence against the hypothesis\.",
     "A changed history counts against the hypothesis."),
    ("exit 1 compares nothing", "pickup",
     r"Content still compares: Step 5's check 1 diffs the cited files from Meta\.HEAD to\n  HEAD, and ",
     "Then "),
    ("R7 exit 128 not classified", "pickup",
     r"- \*\*ancestor: 128\*\*.*?contradicts the hypothesis\.\n", ""),
    ("exit 128 routed to Contradicted", "pickup", r"Cannot-be-checked path", "Contradicted path"),
    ("exit 1 still routed to Contradicted on top", "pickup",
     r"(A changed history alone is not evidence against the hypothesis\.)",
     r"\1 Step 5 still takes the Contradicted path."),
    ("exit 128 misclassified", "pickup", r"this clone does not have the commit", "git printed an error"),
    ("v2 Step 3 fallback runs the v3 command", "pickup",
     r"(A v2 handoff has no Meta\.HEAD: run )`git log --oneline -10`",
     r"\1`git merge-base --is-ancestor <Meta.HEAD> HEAD`"),
    ("R6 v2 Step 3 fallback dropped", "pickup",
     r"A v2 handoff has no Meta\.HEAD: run `git log --oneline -10` instead and compare it\n"
     r"with the handoff's Done list\.\n", ""),
    # The no-hypothesis marker, on both sides.
    ("pickup ignores the no-hypothesis marker", "pickup",
     r"A v3 handoff whose Hypotheses section is .*?acts as \*\*Holds\*\*\.\n", ""),
    ("handoff renames its no-hypothesis marker", "handoff",
     r'write "- none — mechanical work"', 'write "- n/a"'),
    ("no-hypothesis case asks instead of acting", "pickup",
     r"Step 5 still runs check 1 .*?acts as \*\*Holds\*\*\.", "Step 5 asks the user what to do."),
    # Step 5's ordering and verdict routing (the first PR body's D, E, G;
    # review M7; second review R1, R5, R15, R16, R17).
    ("start instruction before the re-check", "pickup",
     r"So test the ground under them before the first edit\.",
     "Start Next Steps #1 right away; do not wait."),
    ("R1 plain start instruction in Step 4", "pickup",
     r"(### Step 5: Re-check)", r"After the briefing, start working on the first proposed step.\n\n\1"),
    ("autonomy granted ahead of the re-check", "pickup",
     r"(\*\*If Blocked has items\*\*)", r"Do NOT ask before acting; begin the work.\n\n\1"),
    ("main's order restored in Step 4", "pickup",
     r"(### Step 5: Re-check)", r"Immediately start executing Next Steps #1.\n\n\1"),
    ("R15 verdict line dropped", "pickup",
     r"Print one line — `Re-check: .*? — and act on it\.", "Act on the result."),
    ("Contradicted no longer wins", "pickup",
     r"\nContradicted wins: one check that contradicts decides, even when another could not run\.", ""),
    ("R17 Holds admits an un-run check", "pickup", r"finds nothing against it", "was not run"),
    ("Holds accepts the handoff's word", "pickup",
     r"the check supports it, finds nothing against it, or", "the handoff says it holds, or"),
    ("Holds admits a check that was not run", "pickup",
     r"(finds nothing against it), or", r"\1, or the check was not run, or"),
    ("Holds starts Next Steps #1 regardless", "pickup",
     r"start the first\n  Next Step that still follows from it", "start Next Steps #1"),
    ("main's order restored after the re-check", "pickup",
     r"(Print one line)", r"Immediately start executing Next Steps #1.\n\n\1"),
    ("Holds asks before starting", "pickup",
     r'Do NOT ask "shall I proceed\?" — just start\.', 'Ask "shall I proceed?" first.'),
    ("R16 Contradicted ignores a met drop condition", "pickup",
     r'a "Drop it if" or "Stop and re-plan if" condition is met, or a\n  cited file', "a\n  cited file"),
    ("Contradicted no longer covers a changed cited file", "pickup",
     r"or a\n  cited file no longer says what its Evidence says", "or a\n  later commit undid it"),
    ("Contradicted keeps the old plan", "pickup",
     r"Re-plan from the\n  Goal, the verified facts and the remaining hypotheses, state the new first step in\n  one line and",
     "Take the next old step and"),
    ("Contradicted asks before starting", "pickup",
     r"start it — still without asking\.", "start it after asking the user."),
    ("Contradicted runs the old plan", "pickup",
     r"do not execute the old Next Steps\.", "finish the old Next Steps first."),
    ("contradicted hypothesis is not recorded", "pickup", r" — so the next /handoff carries it", ""),
    ("R5 Cannot-be-checked is an unconditioned bypass", "pickup",
     r'proceed with it UNCONFIRMED, say "not re-checked: \{why\}", and\n  prefer a first step that tests it\.',
     "just start Next Step one."),
    ("Cannot-be-checked drops the missing-HEAD case", "pickup", r", or Step 3\n  still got 128\)", ")"),
    # Step 2 parsing (the first PR body's A; second review R13).
    ("pickup stops parsing Hypotheses", "pickup", r"^- \*\*Hypotheses\*\*:", "- Hypotheses:"),
    ("R13 ruled-out hypotheses re-tried", "pickup", r"do not re-try them", "re-try them first"),
    ("UNCONFIRMED read as fact", "pickup", r" \(not facts\)", ""),
    ("pickup reads no drop condition", "pickup",
     r'the `current` one with its Evidence and "Drop it if" line', "the `current` one"),
    ("pickup parses a heading the handoff never writes", "pickup", r"^- \*\*Goal\*\*:", "- **Objective**:"),
    ("pickup stops parsing stop conditions", "pickup",
     r"^- \*\*Stop conditions & out of scope\*\*:", "- Stop conditions:"),
    ("Next Steps become orders", "pickup", r"so they are proposals, not orders", "so run them in order"),
    ("v2 fallback dropped", "pickup", r"A v2 handoff \(`STRUCTURED HANDOFF v2`\).*?in Step 5\.\n", ""),
    # Step 4 briefing (second review R12).
    ("R12 briefing drops the hypothesis", "pickup",
     r"Hypothesis: \{current hypothesis, one line\} \[\{status in the handoff\}\]\n", ""),
    ("briefing presents Next Steps as the plan", "pickup", r"Proposed next \(re-checked in Step 5\):", "Next:"),
    # The producer (the first PR body's B, C, F; review M5; second review R8,
    # R9, R10 and the bounded carry-forward).
    ("incremental update stops carrying Hypotheses", "handoff",
     r"  - Carry Hypotheses forward:.*?add both\.\n", ""),
    ("incremental update drops ruled-out entries", "handoff", r"keep every ruled-out entry, ", ""),
    ("carry-forward made optional", "handoff",
     r"Carry Hypotheses forward:", "If time allows, revisit hypotheses:"),
    ("carried ruled-out entries grow without bound", "handoff",
     r" A ruled-out entry carried over from an earlier handoff\n    shrinks to one line .*?down the file\.", ""),
    ("incremental update drops the stop conditions", "handoff",
     r" Keep Stop conditions & out of\n    scope unless the user changed the scope\.", ""),
    ("drop condition removed from the templates", "handoff", r"Drop it if:", "Note:"),
    ("UNCONFIRMED status removed from the templates", "handoff", r"\*\*H3 \[UNCONFIRMED\]\*\*", "**H3**"),
    ("evidence removed from the templates", "handoff", r"^  - Evidence: ", "  - Notes: "),
    ("re-plan condition removed from the templates", "handoff", r"^- Stop and re-plan if: [^\n]*\n", ""),
    ("handoff no longer names its no-hypothesis marker", "handoff",
     r'\n     Mechanical work with no hypothesis: write "- none — mechanical work"\.', ""),
    ("R8 several current hypotheses allowed", "handoff", r" At most one is current\.", ""),
    ("R9 Next Steps stop naming their hypothesis", "handoff", r" \(rests on H1\)", ""),
    ("R10 handoff report drops the hypothesis", "handoff",
     r"Current hypothesis: \{H-current, one line — or \"none\"\}\n", ""),
    ("Meta stops recording HEAD", "handoff", r"^- HEAD: ", "- Head commit: "),
    ("SKILL.md template drifts from prompt.md", "handoff",
     r"## Hypotheses\n(?=- \*\*H1 \[current\]\*\*: <)", "## Assumptions\n"),
    ("SKILL.md template no longer a markdown block", "handoff",
     r"```markdown\n(?=# Handoff: \{YYYY-MM-DD HH:MM\}\n<!--[^\n]*\n\n## Goal\nOne sentence)", "```text\n"),
    ("SKILL.md template renames an unpinned section", "handoff",
     r"## Critical Context\n(?=- <non-obvious)", "## Context\n"),
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
