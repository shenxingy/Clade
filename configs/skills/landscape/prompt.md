# /landscape — the whole system, for someone who has to decide

## Why this skill exists

The owner had been hand-typing this brief every time, because nothing carried
it: *"我看这一个报告就能把整个系统了解得一清二楚，没有任何细节的遗漏… 把我当成一个
资深的 PhD 加 PM 加上 Software Engineer"*. A brief that has to be re-typed is one
the system failed to learn. This file is that brief, encoded once.

`/map` is not this. `/map` writes an `ARCHITECTURE.md` for one repository with a
single Mermaid graph. This is cross-repository, cross-team, goal-versus-gap, and
it digs up what was tried and abandoned.

## Non-negotiables

**One reader, three heads.** Every section names whose question it answers. A
view with no named concern is decoration (ISO/IEC/IEEE 42010's one useful idea).

**Measured over asserted.** Every number carries where it came from and when.
Where a fact cannot be recovered mechanically, say so in the report — a section
that guesses at progress is worse than one that asks. Preserve unknowns as
unknown, the way `/status` already does.

**Declared omissions.** "Nothing missing" is only honest if what is out of scope
is written down. §17 is not optional.

**Deployment is part of delivery.** The report is published, not left as a file.
If a first-party document connector is attached, it goes there; otherwise
publish an Artifact and hand back the link.

## Section spine — produce these, in this order

Front matter, so the reader may stop after it:

0. **Header stamp** — title, date, the exact commit or version described, and an
   "as of" per claim class. An undated system report is a lie within a week.
1. **Reader's map** — name each reader, the one question each arrives with, and
   which section answers it. This is what lets one document serve three
   audiences instead of becoming three documents.
2. **Answer first** — the whole system in 120 words or fewer, plus one number.
   If it cannot be written, the system is not yet understood.

Body:

3. **Ultimate goal as a testable target** — one sentence, its metric, its
   threshold. If it is not measurable, §12's gap degenerates into vibes.
4. **Constraints** — the non-negotiables that pre-decided the design, flat.
   A reader without these re-proposes what was already rejected.
5. **System context** — the system as one box, its users, every external system
   it touches (C4 level 1). The only diagram all three readers need; it fixes
   the boundary before anything inside it is argued about.
6. **Parts inventory** — one table: part | one-sentence job | runtime | repo and
   path | owner | status. This single table answers "what parts", "where is the
   code", "who is doing it" and "how far along" at once. A container diagram
   (C4 level 2) sits beside it, because relationships do not fit a table.
7. **Surfaces and ends** — every way a human or machine enters, with entry
   point, user, and **whether it is live or dormant**. Not a C4 concept and the
   most load-bearing section here: without it a dormant layer reads as
   production.
8. **Per-part architecture** — one subsection per part, identical shape every
   time: responsibility, key modules with real paths, dependencies in and out,
   the invariant it must not break, and a component diagram **only** for parts
   under active change. The fixed shape is what makes an omission visible.
9. **One real task traced end to end** — the actual command, the actual files
   touched, the actual output. This is how a senior engineer decides in thirty
   seconds whether the document is true or aspirational.
10. **Decisions that shaped it** — only the irreversible, surprising, or genuine
    trade-offs, each with the alternative that lost and the cost accepted.
    Without that gate this becomes a changelog.
11. **Failed attempts and abandoned directions** — what was tried, why it was
    dropped, and whether the door is closed or merely parked. Recovered
    mechanically; see below. Placed here because it is §10's object with a
    different outcome.
12. **Gap** — a capability ladder, never a two-column table. Per capability:
    five named levels, today's level, **the evidence for that level**, the
    target, and the specific blocker on the next rung.
13. **Next step, expanded** — exactly one action, with definition of done,
    verifier, owner, blast radius, and what it explicitly is not. One. A list of
    five is a backlog and defers the decision the report exists to force.
14. **Risks and known debt** — what could invalidate the plan and the signal
    that would show it happening, including honest unknowns.

Back matter:

15. **Glossary** — PhD, PM and SWE do not share a referent for "agent",
    "worker", "task" or "attempt".
16. **Evidence and provenance** — for every number: source, method, date.
17. **What this report does not cover** — the declared scope boundary.

**Deliberately excluded as ceremony**, so nobody adds them back: code-level
diagrams (C4's own guidance says no, IDEs generate them on demand); component
diagrams for parts nobody is changing; 4+1's logical/development split; and all
of 42010's viewpoint-declaration apparatus. Two of 42010's ideas earn their
place — stakeholder framing and mandatory rationale — and nothing else.

## Recovering the facts

### Failed and abandoned attempts

Ranked by measured yield on a real repository, not by intuition. The three
signals people reach for first — unmerged branches, closed-unmerged PRs,
won't-fix issues — yielded 0, 1 and 0 on this repo, because it squash-merges and
deletes branches. Run the top tier always:

1. **Deleted plan and goal files, and what they left unmet.** Highest yield by a
   wide margin: 14 files and 63 unfinished criteria on Clade. For each path ever
   deleted under `goals/`, `goal-*`, `loop-*`, or a tasks file, recover the last
   version and count its unchecked boxes. A goal file that died 11 open and 0
   done is a loop that delivered nothing, and that is the story.
2. **Items removed from a TODO while still unchecked**, in a commit that checked
   nothing off — deletion as a silent decision.
3. **Prose decision markers the owner already wrote** — won't-fix, superseded,
   rejected, `[~]`.
4. **Paths deleted and still absent from HEAD**, with a separate "killed then
   revived" list — a resurrection explains current state better than a deletion.
5. **Directories that exist only in history.** The cheapest command in the set
   and it names every abandoned subsystem in one line.
6. **Dead paths still referenced by live code** — these are current bugs, not
   history; report them as such.

Refactoring also deletes code. The discriminator: an abandoned experiment leaves
**unmet intent** behind — unchecked criteria, a plan with no successor, a
reference that now dangles. A refactor leaves a replacement. Say which you found.

### Who is working on what

Two mandatory steps, because either alone reports the wrong half — on a real org
sweep, 15 of 28 active repositories had **zero** open human PRs.

1. **Merged-PR census** over the window: the reliable throughput signal. If the
   total reaches the search cap, halve the window and re-run — the API truncates
   silently rather than erroring.
2. **Open-PR board** with review state, CI rollup and diff size. Split it into
   fresh (≤14 days) and parked (>14 days) and report the fresh ones as active
   work: on the sweep that calibrated this, 37 of 46 open PRs were stale. Do not
   report review state as progress; it was `none` on most recent PRs.
3. **Branch-level work in progress** for the most recently pushed repositories —
   the only view of work that has no PR yet. Flag recent branches with no PR as
   uncommunicated, not as invisible.
4. Use `gh api -X GET search/issues` and the GraphQL endpoint directly. The
   `gh search prs` wrapper is crippled where the raw API is not; do not
   "simplify" back to it.
5. If a company-memory MCP server is attached, use it for ownership and status
   that git cannot see, and cite its freshness.

**State the boundary.** Whether someone is blocked, whether a stale PR is
abandoned or merely waiting, and what an owner intends next are not recoverable
from git. List them as questions for a human rather than inventing an answer.

## Diagrams

Load the `artifact-diagramming` skill before drawing, and `artifact-design`
before writing the page.

- Colour carries meaning or it is not used. One hue per semantic class, and the
  page must be legible in both themes.
- Orthogonal edges, consistent line weight, a legend when more than three
  classes appear.
- Layered disclosure: context, then containers, then components only where
  something is changing.
- **Internal-network deployment means no CDN.** Inline the CSS and the SVG;
  assume external scripts and fonts will not load.

**Verify the render, do not assume it.** Screenshot the published page and look
at it — that is the owner's standing instruction ("截图确认，它的专业性是否完全
对齐了，颜色、字体") and it catches what code review cannot: an unreadable
contrast pair, a diagram clipped at a narrow width, a font that did not load.

## Finish

- Publish, then hand back the link.
- List what could not be recovered mechanically, as questions.
- If the report contradicts something written in the repo, fix the repo in the
  same pass or file it — a landscape report that leaves a known-false document
  standing has done half the job.
