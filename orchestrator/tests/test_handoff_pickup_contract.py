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
pinned together: the handoff's instructions to record each hypothesis with
evidence (inferences marked "inferred"), status and a drop condition plus stop
conditions; pickup's instructions to parse both, re-check the current
hypothesis before it acts, keep its no-"shall I proceed" autonomy, and re-plan
when the check contradicts the hypothesis. These are instructions to a model;
nothing here measures whether a model follows them.

Each check reads the text a runtime hands the model — the canonical Claude Code
skill (prompt.md + SKILL.md), the clade-mcp package copy, and the generated
Codex plugin SKILL.md — not a helper that builds it.

The checks are prose assertions, so their strength is a question of which
regressions they notice. ``MUTATIONS`` answers it and keeps answering it: each
entry removes or rewords one guard in the canonical text, and
``test_every_mutation_is_noticed`` requires at least one check to go red. A
mutation whose anchor no longer matches fails rather than skips. The claim is
exactly that table: every mutation in it must turn the suite red. An edit the
table does not list is not shown to be caught.

What one assertion checks: that a phrase is present in (or absent from) one
section or bullet of the prose, after whitespace is collapsed. Not what the
sentence around the phrase now means. Each assertion message says which phrase
went missing, not which behaviour broke. The known limit follows from that: a
substring pin cannot see an added disjunct or qualifier. "A changed history
alone is not evidence against the hypothesis, unless the log is long" keeps
every pinned phrase and passes. A rewording that drops a pinned phrase fails,
whatever it means; one that keeps every pinned phrase passes, whatever it means.

Verdict branches are pinned by phrases in their TRIGGER (the parenthetical
after the label) and their BODY, not by the label alone: a label with its
condition cut routes nothing.
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
    assert start != -1, "Step 5 has no 're-check first'"
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
            assert f"[{status}]" in hyp, f"the Hypotheses template has no [{status}] entry"
        assert "Drop it if:" in hyp, "the Hypotheses template has no 'Drop it if:' field"

        # The current hypothesis's Evidence line, and on it the producer half of
        # pickup's 'A fact the handoff marks "inferred" is not verified': the
        # writer is asked to label what it did not observe. Without the ask the
        # label never appears and pickup reads every inference as observed.
        # This checks that the line holds the word "inferred" in quotes, not
        # how the sentence around it uses the word.
        current = re.search(r"\[current\]\*\*[^\n]*\n {2}- Evidence: ([^\n]*)", hyp)
        assert current and '"inferred"' in current.group(1), (
            "the template's current hypothesis has no '- Evidence:' line, or that line no "
            "longer contains '\"inferred\"'"
        )

        stop = _section(template, re.escape(STOP))
        for field in ("Done when:", "Stop and re-plan if:", "Out of scope:"):
            assert field in stop, f"{STOP} has no {field!r}"

        # Each step names the hypothesis it rests on, so the steps that fall
        # with a contradicted hypothesis are visible to the re-plan.
        assert "(rests on H1)" in _section(template, "Next Steps"), (
            "the Next Steps template no longer shows a step marked '(rests on H1)'"
        )

        # The re-check needs to know what landed after the handoff.
        assert "- HEAD:" in _section(template, "Meta"), "the Meta template has no '- HEAD:' line"

    # pickup re-checks "the current one", which presumes there is one at most.
    assert "At most one is current" in handoff, "the handoff no longer says 'At most one is current'"


@_check
def handoff_templates_agree_on_section_headers(handoff: str, pickup: str) -> None:
    """SKILL.md says pickup parses 'these exact section headers' while prompt.md
    holds the authoritative template; one updated without the other is drift."""
    first, second = (_headings(t) for t in _handoff_templates(handoff))
    assert first == second, f"the two handoff templates' headings differ: {first} vs {second}"


@_check
def incremental_handoff_carries_hypotheses_forward(handoff: str, pickup: str) -> None:
    """Every second and later /handoff in a chain takes the incremental path, so
    that is where ruled-out entries would be lost."""
    step2 = _section(handoff, r"Step 2: Detect Iteration Number")
    carry = _flat(_paragraph_with(step2, "Carry Hypotheses forward"))
    assert "keep every ruled-out entry" in carry, (
        "the carry-forward paragraph no longer says 'keep every ruled-out entry'"
    )
    assert STOP in carry, f"the carry-forward paragraph never names {STOP!r}"
    # Kept, but bounded: a session start auto-loads only the head of the file,
    # and Hypotheses sits above Next Steps and Meta.
    assert "shrinks to one line" in carry, (
        "the carry-forward paragraph no longer says a carried ruled-out entry 'shrinks to one line'"
    )


@_check
def handoff_report_names_the_current_hypothesis(handoff: str, pickup: str) -> None:
    report = _section(handoff, r"Step 4: Report")
    assert "Current hypothesis:" in report, "Step 4's report has no 'Current hypothesis:' line"


# ─── Checks: what /pickup reads and does ─────────────────────────────────────

@_check
def pickup_parses_every_section_the_resume_depends_on(handoff: str, pickup: str) -> None:
    parsed = _pickup_parse_list(pickup)
    assert HYPOTHESES in parsed, f"Step 2's parse list has no **{HYPOTHESES}** bullet: {parsed}"
    assert STOP in parsed, f"Step 2's parse list has no **{STOP}** bullet: {parsed}"

    # Every name pickup parses must be a heading the handoff actually writes;
    # a rename on one side silently empties that field on the other.
    for template in _handoff_templates(handoff):
        heads = _headings(template)
        for name in parsed:
            assert any(h.startswith(name) for h in heads), (
                f"pickup parses {name!r}, handoff writes only {heads}"
            )

    # One phrase per status in Step 2's Hypotheses bullet: the current one's
    # falsifier, UNCONFIRMED as not fact, ruled-out as not re-tried. Presence
    # only — a qualifier added beside a phrase keeps it.
    hyp = _bullet(_section(pickup, r"Step 2: Read \+ Parse"), "- **Hypotheses**")
    assert '"Drop it if"' in hyp, "Step 2's Hypotheses bullet no longer mentions '\"Drop it if\"'"
    assert "(not facts)" in hyp, "Step 2's Hypotheses bullet lost '(not facts)'"
    assert "do not re-try them" in hyp, "Step 2's Hypotheses bullet lost 'do not re-try them'"


@_check
def pickup_treats_next_steps_as_proposals(handoff: str, pickup: str) -> None:
    parse = _section(pickup, r"Step 2: Read \+ Parse")
    assert re.search(r"\*\*Next Steps\*\*:.*proposals, not orders", parse, flags=re.DOTALL), (
        "Step 2 no longer has 'proposals, not orders' after its **Next Steps** bullet"
    )
    # A handoff written before v3 has no Hypotheses section. This checks only
    # that Step 2 still mentions a v2 handoff and UNCONFIRMED: removing the v2
    # paragraph is caught ("v2 fallback dropped"), rewording what it tells
    # pickup to do while keeping both words is not.
    assert "v2 handoff" in parse and "UNCONFIRMED" in parse, (
        "Step 2 no longer mentions both 'v2 handoff' and 'UNCONFIRMED'"
    )


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
    assert "git log --oneline <Meta.HEAD>..HEAD" in step3, (
        "Step 3 lacks `git log --oneline <Meta.HEAD>..HEAD`"
    )
    assert "git merge-base --is-ancestor <Meta.HEAD> HEAD" in step3, (
        "Step 3 lacks `git merge-base --is-ancestor <Meta.HEAD> HEAD`"
    )

    moved = _bullet(step3, "- **ancestor: 1**")
    assert "squash-merged" in moved and "check 1 diffs the cited files" in moved, (
        "the ancestor: 1 bullet lacks 'squash-merged' or 'check 1 diffs the cited files'"
    )
    assert "not evidence against the hypothesis" in moved, (
        "the ancestor: 1 bullet lost 'not evidence against the hypothesis'"
    )
    assert "Contradicted" not in moved, "the ancestor: 1 bullet names Contradicted"

    absent = _bullet(step3, "- **ancestor: 128**")
    assert "does not have the commit" in absent, "the ancestor: 128 bullet lost 'does not have the commit'"
    assert "check 1 cannot run" in absent and "Cannot-be-checked path" in absent, (
        "the ancestor: 128 bullet lacks 'check 1 cannot run' or 'Cannot-be-checked path'"
    )

    # Without this fallback every v2 handoff runs --is-ancestor on a HEAD it
    # never recorded and exits 128.
    v2 = _paragraph_with(step3, "A v2 handoff has no Meta.HEAD")
    assert "git log --oneline -10" in v2 and "Done list" in v2, (
        "Step 3's v2 paragraph lacks `git log --oneline -10` or 'Done list'"
    )


@_check
def pickup_briefing_shows_the_hypothesis_and_proposals(handoff: str, pickup: str) -> None:
    briefing = _section(pickup, r"Step 4: Display Briefing")
    assert "Hypothesis: {current hypothesis" in briefing, (
        "the briefing has no 'Hypothesis: {current hypothesis' line"
    )
    assert "Proposed next (re-checked in Step 5):" in briefing, (
        "the briefing lost 'Proposed next (re-checked in Step 5):'"
    )


@_check
def pickup_rechecks_the_hypothesis_before_acting(handoff: str, pickup: str) -> None:
    step5 = _section(pickup, r"Step 5:")

    # The old order: execute the last session's plan on sight.
    assert "Immediately start executing" not in step5, "Step 5 still says 'Immediately start executing'"

    recheck = step5.find("re-check first")
    assert recheck != -1, "Step 5 has no 're-check first'"
    start = step5.find("Do NOT ask")
    assert start != -1, "Step 5 has no 'Do NOT ask'"
    assert recheck < start, "Step 5's 'Do NOT ask' comes before its 're-check first'"

    # No text ahead of 're-check first' (Steps 1-4 and Step 5's preamble)
    # matches EARLY_START. It sees only the start phrasings that regex names.
    ahead = pickup[: pickup.index("re-check first")]
    early = EARLY_START.search(ahead)
    assert not early, f"text ahead of 're-check first' matches EARLY_START: {early.group(0)!r}"

    # No word OPTIONAL names (skip*, "if time allows", optional/optionally)
    # appears in Execution Steps, except Step 2's "skips check 2". A qualifier
    # phrased any other way ("only when the handoff is old") is not seen.
    optional = OPTIONAL.search(_section(pickup, r"Execution Steps"))
    assert not optional, f"Execution Steps contains an OPTIONAL word: {optional.group(0)!r}"

    flat5 = _flat(step5)
    assert "Print one line — `Re-check: {H} holds | contradicted | not re-checked" in flat5, (
        "Step 5 lost its 'Print one line — `Re-check: {H} holds | contradicted | not re-checked' instruction"
    )
    assert "Contradicted wins" in flat5, "Step 5 lost 'Contradicted wins'"

    # The three outcomes, each by phrases in its trigger and body, not by label.
    holds = _bullet(step5, "- **Holds**")
    holds_when = _trigger(holds)
    assert "the check supports it, finds nothing against it" in holds_when, (
        "Holds' trigger lost 'the check supports it, finds nothing against it'"
    )
    assert not re.search(r"not run|\bskip|unchecked", holds_when), (
        f"Holds' trigger contains 'not run', 'skip' or 'unchecked': {holds_when!r}"
    )
    assert "first Next Step that still follows from it" in holds, (
        "Holds' body lost 'first Next Step that still follows from it'"
    )

    contradicted = _bullet(step5, "- **Contradicted**")
    contradicted_when = _trigger(contradicted)
    for cond in (
        '"Drop it if"',
        '"Stop and re-plan if"',
        "no longer says what its Evidence says",
        # Check 2's mismatch: a re-run whose output differs from the recorded
        # Evidence while the drop condition is not literally met.
        "re-run no longer matches what its Evidence records",
    ):
        assert cond in contradicted_when, f"Contradicted's trigger lacks {cond!r}"
    assert "do not execute the old Next Steps" in contradicted, (
        "Contradicted's body lost 'do not execute the old Next Steps'"
    )
    assert "Re-plan from the Goal" in contradicted, "Contradicted's body lost 'Re-plan from the Goal'"
    assert "without asking" in contradicted, "Contradicted's body lost 'without asking'"
    assert "so the next /handoff carries it" in contradicted, (
        "Contradicted's body lost 'so the next /handoff carries it'"
    )

    cannot = _bullet(step5, "- **Cannot be checked cheaply**")
    assert "128" in _trigger(cannot), "Cannot be checked's trigger does not mention 128"
    for must in ("UNCONFIRMED", "not re-checked", "tests it"):
        assert must in cannot, f"Cannot be checked's body lacks {must!r}"


@_check
def pickup_recheck_names_what_to_check(handoff: str, pickup: str) -> None:
    """The label 're-check first' with nothing under it re-checks nothing."""
    checks = _flat(_recheck_body(_section(pickup, r"Step 5:")))
    # 1. Repository: the cited files, by content, whatever the history did.
    assert "still say what its Evidence says" in checks, "the re-check lost 'still say what its Evidence says'"
    assert "git diff --stat <Meta.HEAD> HEAD -- <cited paths>" in checks and "by content" in checks, (
        "the re-check lacks `git diff --stat <Meta.HEAD> HEAD -- <cited paths>` or 'by content'"
    )
    assert "not in its Done list" in checks, "the re-check lost 'not in its Done list' (the v2 case)"
    assert "128, this check cannot run: say so" in checks, (
        "the re-check lost '128, this check cannot run: say so'"
    )
    # 2. Verified facts: the hypothesis's own falsifier; inferred is not
    # verified; a re-run that no longer matches the Evidence is routed.
    assert 're-run the cheapest check its Evidence or "Drop it if" line names' in checks, (
        "check 2 lost 're-run the cheapest check its Evidence or \"Drop it if\" line names'"
    )
    assert 'A fact the handoff marks "inferred" is not verified' in checks, (
        "check 2 lost 'A fact the handoff marks \"inferred\" is not verified'"
    )
    # Without a route, a mismatch whose drop condition is not met fits no
    # verdict: not Holds (something is against it), not Contradicted (no
    # trigger named it), not Cannot be checked (the check ran).
    assert (
        "re-run whose output no longer matches what its Evidence records takes the Contradicted branch"
        in checks
    ), "check 2 lost 're-run whose output no longer matches what its Evidence records takes the Contradicted branch'"
    # 3. Stop conditions: a met goal stops; out-of-scope steps are dropped.
    assert "Done when" in checks and "report that and stop" in checks, (
        "the re-check lacks 'Done when' or 'report that and stop'"
    )
    assert "Out of scope" in checks, "the re-check never mentions 'Out of scope'"


@pytest.mark.parametrize("check", CHECKS, ids=lambda fn: fn.__name__)
@pytest.mark.parametrize("surface", sorted(SURFACES))
def test_contract_holds(surface: str, check: Check) -> None:
    check(_skill_text(surface, "handoff"), _skill_text(surface, "pickup"))


# ─── Mutations: each listed edit must turn a check red ───────────────────────
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
     r'a "Drop it if" or "Stop and re-plan if" condition is met, a\n  cited file', "a\n  cited file"),
    ("Contradicted no longer covers a changed cited file", "pickup",
     r"a\n  cited file no longer says what its Evidence says,", "a\n  later commit undid it,"),
    # Third review of PR #179: a check 2 re-run that no longer matches its
    # Evidence, while the drop condition is not met, fitted no verdict.
    ("check 2 mismatch dropped from the Contradicted trigger", "pickup",
     r", or check 2's re-run no longer\n  matches what its Evidence records\)", ")"),
    ("check 2 mismatch fits no verdict (routing sentence cut)", "pickup",
     r" A re-run whose output no longer matches what its Evidence\n   records takes the Contradicted branch,"
     r" even when its drop condition is not met\.", ""),
    ("check 2 mismatch routed to Holds", "pickup",
     r"records takes the Contradicted branch", "records still Holds"),
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
    # Third review: the producer half of 'A fact the handoff marks "inferred"
    # is not verified' was unpinned. One mutation per template.
    ("prompt.md template stops asking for \"inferred\"", "handoff",
     r' Mark anything you did not observe "inferred"\.', ""),
    ("SKILL.md template stops asking for \"inferred\"", "handoff",
     r'; "inferred" when you did not', ""),
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
