# Section spines — what an artifact page must answer, in order

Read this before writing any page. The reader is one person with three heads —
PhD, PM, engineer — and one question: *what is the state of this thing, and
what do I do about it?* A page passes when, from the first screen, that reader
can say what the problem is **now**, how sure we are, and what the **next
step** is. Everything below the first screen is the evidence for those three
sentences.

## Where this comes from

- **A measured hub.** 1,037 pages of one company's internal artifact hub,
  scanned on 2026-09-23 with `artifact-lint.py --survey` (the study is
  `docs/research/2026-09-23-artifact-standard.md`). The pages people actually
  forward share one shape — a headline that is a finding, a number strip, a
  graded verdict, a key-and-terms section, sections whose headings are claims,
  a "what to do, in order" close. The hub as a whole does not: of its 936
  report pages, 72% never explain why the numbers look like this and 88%
  never say what was done to find out; no page passes every check. The full
  table, per author, is in the study — this file states the rules, the study
  holds the numbers. The gap is the missing standard, not any one author.
- **Answer-first writing.** BLUF (US Army AR 25-50), Minto's pyramid and SCQA,
  Amazon's six-page narrative, Alley's assertion–evidence headings.
- **Engineering documents.** Google design docs (Ubl: goals, non-goals,
  alternatives), the Google SRE postmortem template, Rust RFC "Drawbacks" and
  "Unresolved questions", Oxide RFD document states, Uber RFC cross-cutting
  checklist.
- **Research reporting.** Heilmeier's catechism, the NeurIPS checklist,
  Lipton & Steinhardt on explanation vs speculation, Karpathy on silent
  failure.
- **Architecture views.** C4 levels and arc42 sections — used in
  `diagrams.md`; here only for what an architecture page must list.

Full citations are at the end of this file.

## Route the reader's question before choosing the spine

The topic supplies the facts; the reader's task chooses the artifact. The same
model evaluation can support a finding, a ship/no-ship decision, or a status
update. Name one primary question before drafting.

| Reader question | Type | First-screen answer | Useful visual, only if needed |
|---|---|---|---|
| What did we learn, and does the evidence support it? | `finding` | Result, baseline, population, uncertainty | Comparison or distribution with the decision threshold |
| Where are we now, and what is stopping progress? | `status` | Goal vs current state, dated change, blocker, owner/next action | Progress/gap table; trend if comparable observations exist |
| How does this system work? | `architecture` | Purpose, boundary, live vs planned, entry point | Context then containers; one real task traced through them |
| What broke, why, and is it fixed? | `rca` | Impact, present recovery state, confirmed cause vs hypothesis | Incident timeline or evidenced causal chain |
| What should we choose, and why? | `decision` | Recommendation, decisive trade-off, decision owner/deadline | Options matrix with consistent criteria; sensitivity if measured |
| How can I take over and continue? | `handoff` | Current state, first executable step, traps and open work | Task/dependency flow when it prevents a mistake |
| Where do I find or learn this specific thing? | `reference` | Scope, lookup route, definitions and a worked example | Indexed table or annotated example |
| What is this branch doing right now? | `worklog` | Goal, now, human action, blockers, freshness | Compact state list; timeline below it |

Use a table for lookup, prose for a short argument, a chart for a pattern,
and a diagram for relationships. A concept explanation fits a reference with
a worked example unless there is a new finding to argue. For a mixed brief,
choose the primary question and link supporting views; split pages only when
readers have independent tasks.

Choose the **container separately**: HTML for a linked/asynchronous report;
slides for a presented sequence; an editable document for collaboration;
interactive controls when changing a parameter/filter answers a real question.
An exported image/PDF needs its own visible labels, background and source/date;
it cannot depend on the HTML page's hover, CSS or surrounding explanation.

The spines below are question coverage, not a mandatory count of sections.
Combine short answers and mark genuine unknowns. Never fabricate numbers,
causes, failed experiments or a diagram to satisfy a template. A compact
answer should not grow an empty research-report shell. Apply `review.md` to
test whether this choice actually works for a newcomer.

## The shared front matter — answer first, details after

An *argued* page is a finding, status report, architecture page, RCA, handoff
or decision memo. A reference register and a work-log have their own shape
(below) and skip items 1–4.

0. **Header stamp.** One line: what this page is · the date it describes
   ("as of 2026-09-23", "compiled 2026-09-03 from 255 threads") · the exact
   commit, model version or dataset version · author · where the sources
   live. An undated report is wrong within a week and nobody can tell.
   *(lint: `as-of` — FAIL when the first screen carries no date.)*
1. **Headline = the finding.** A sentence that could be false: *"v9 learned
   the pipeline, not the tampering."* not *"v9 evaluation"*. If the page has
   no finding yet, the headline is the question, ending in `?`. A noun phrase
   is a label; a label makes the reader read the body to learn the point.
   *(lint: `title-claim`.)*
2. **Deck.** ≤ 120 words directly under the headline: the subject, conclusion,
   key evidence (with population for measurements), and what the reader should
   do. This is the BLUF; a reader who stops here must leave with the right
   belief. Whatever a skill calls this paragraph — deck, bottom line, BLUF —
   it is one contract: the conclusion the reader acts on comes before any
   rounds, dates or timeline. *(lint: `deck`.)*
3. **Key evidence.** For quantitative questions, a compact number strip, each
   with its **denominator and window** on the same line: *"0 / 24 held-out frauds flagged at τ"*,
   *"33.4% recall of 12,152 forgeries at 1% real-clean FPR (n = 1,921)"*. A
   rate without its population is a mood. For a qualitative page, state the
   decisive evidence or trade-off instead; do not manufacture metrics. *(lint: `denominators`.)*
4. **Verdict, graded.** For each headline claim: **Reproduced / Confirmed /
   Not supported / Not measured**, with a visible confidence mark (●●●○) and
   one line of why. Verified fact, inference and speculation are separated
   typographically, never interleaved — the first of Lipton & Steinhardt's
   troubling trends is exactly that interleaving.
5. **Key & terms.** Every named entity (model, dataset, cohort, service) and
   every metric, defined once with its denominator; one colour per entity,
   used identically in every chip, table and chart on the page. The pages on
   the hub that readers found legible all carry this section; 53% of pages
   have none. *(lint: `key-terms` — fires when there are figures or tables
   and no key.)* Mark the section `id="key"` so tools find it.

## The two sections the owner keeps asking for by name

Every argued page answers these two questions, combining brief answers with
existing sections where helpful,
because they are the questions the reader asks after the summary and
they were re-typed as a brief three times before being written down here:

- **Why the numbers look like this.** The mechanism behind the headline
  number, the alternative explanations that were ruled out and how, and how
  sure that leaves us. Not "the recall is 33%" but "the recall is 33% because
  the model learned the generators' fingerprint, and here is the ablation
  that says so". A number without its cause is a rumour with a decimal
  point. *(lint: `why` — WARN on finding, status, rca and decision pages.)*
  If a cause has not been established, say so and separate candidate explanations
  from evidence; a required why section is not permission to invent causality.
  Mark it `id="why"`.
- **What I did to find this out.** The research log, in order: what was read,
  what was run, what was compared against what, what was tried and dropped
  (link the failed-attempts section), with dates. It sits near the end, just
  before the sources, and it is what lets a reader weigh the result and a
  successor repeat it. *(lint: `method` — WARN on every argued page.)* Mark it
  `id="method"`.

## An index that follows the reader, once the page is longer than one sitting

Past about **6,000 words** — the top 9% of one company hub, 97 of 1,065 pages
measured 2026-09-24 — a reader loses the shape of the page. A list of links at
the top is not enough; by the time it has scrolled away the reader cannot say
where they are, what is left, or how much of the argument they have already
had. Two obligations, and they are cheap:

- **Pin it** (`position: sticky`), so the map is reachable from anywhere.
- **Mark where the reader is** — `IntersectionObserver` sets `aria-current` on
  the entry for the section in view. This is the half people skip, and it is
  the half that answers "where am I".

On wide screens put it in a **left rail**, where the whole map is visible at
once and the current entry is a bookmark in it; collapse to a pinned bar below
about 1024px, and hide it in print. *(lint: `nav-position`.)*

The usual better answer is to **split**: one answer page that holds the finding
and the decision, linking sub-pages for the atlas, the catalogue and the raw
inventory. Splitting by sub-problem keeps each page's reader question intact;
splitting by length does not. The hub's strongest teardown page is the
counter-example that made this rule — 25,159 words, 18th longest of 1,065,
with a pinned 15-link bar that never says which of the 15 you are in.

## The body — one spine per type

Declare the type in the page head: `<meta name="artifact-type"
content="finding">`. The lint relaxes claim-heading, next-step and why
checks for `reference` and `worklog`. **Limits does not relax**: a register is
exactly where a reader turns "not listed" into "does not exist", so it owes a
line on what it does not cover. An undeclared page is linted as a `finding`,
the strictest shape.

### `finding` — a research result

| # | Section (as a claim heading) | What it answers |
|---|---|---|
| 1 | Objective, no jargon | Heilmeier Q1: what are you trying to do, in words a PM repeats correctly |
| 2 | How it is done today and where that stops | The baseline and its limit, with the number |
| 3 | What is new and why it should work | Hypothesis; the mechanism, not the name |
| 4 | Evidence, verified | Each measurement with population, split, date; the money figure lives here |
| 5 | Where the gain comes from | Ablation: answer *what worked* before *why* |
| 6 | Speculation, fenced | Clearly marked; never in §4 |
| 7 | What did not move | Negative results — a component that "silently works a bit worse" is a result |
| 8 | What would change our mind | The falsifier: the measurement that would retract the headline |

### `status` — where a project stands

| # | Section | What it answers |
|---|---|---|
| 1 | Where we are, dated | Situation: two or three numbers with their windows |
| 2 | What changed / what is wrong | Complication: the disruption that makes the page necessary |
| 3 | The question on the table | One sentence; the decision the page exists to force |
| 4 | Analysis | MECE arguments under the governing thought, evidence at the base |
| 5 | What is working, measured | Strengths with the number that says so |
| 6 | What is not, and what we tried | Weaknesses and the failed attempts, each with why it was dropped |
| 7 | Alternatives considered | The trade-off that led to rejection, not a list of names |
| 8 | Open questions and who owns them | Split three ways: resolve now / resolve during the work / out of scope |

### `architecture` — what the system is, as built

| # | Section | What it answers |
|---|---|---|
| 1 | Goal as a testable target and the constraints | What pre-decided the design |
| 2 | Context diagram (C4 L1) | The system as one box, its users, every external system |
| 3 | Parts inventory | One table: part · one-sentence job · runtime · repo and path · owner · status (live / dormant / planned) |
| 4 | Container diagram (C4 L2) with a legend | Relationships that do not fit the table |
| 5 | Surfaces and ends | Every way a human or machine enters, and whether it is live |
| 6 | Per-part architecture, identical shape each time | Responsibility · key modules with real paths · dependencies in/out · the invariant it must not break |
| 7 | One real task traced end to end | The actual command, files, output — how an engineer decides in thirty seconds whether the page is true |
| 8 | As-built vs as-designed drift | What diverged and whether the doc or the code is wrong |
| 9 | Decisions that shaped it | Only the irreversible, surprising or genuine trade-offs, each with the alternative that lost |
| 10 | Gap ladder | Per capability: five named levels, today's level with evidence, the target, the blocker on the next rung |

`/landscape` is this spine at whole-system scale, with the failed-attempt
archaeology; use it when the scope is more than one repository.

### `rca` — a post-mortem

Google SRE's template field order, verbatim, because every reader has seen it:
title with incident id · date · authors · **status** ("complete, action items
in progress") · summary · **impact, quantified with the null statement** ("1.21
B queries lost, no revenue impact") · root causes · trigger · resolution ·
detection · **action items table: item · type · owner · link** · lessons
learned in three fixed parts: *what went well / what went wrong / where we
got lucky* · timeline · supporting information. "Human error" as a root cause
ends the investigation instead of starting it; write the constraint the human
was under.

### `handoff` — for the next person

Read this first · what the work claims · where everything lives (paths,
hosts, buckets, credentials and who grants them) · what is done and what is
open · **open, unverified and known-wrong** as three separate lists · how to
rebuild the artefact from scratch · conventions and hard rules · who knows
what. Number the sections; a handoff is read in order, once.

### `decision` — a memo that asks for a ruling

The recommendation first, then the options with the trade-off that loses for
each, the evidence, what it costs to be wrong, and the exact decision wanted
by whom by when. One page; the analysis goes in an appendix.

### `reference` — a register, manual or catalogue

Label headings are correct here (the reader looks things up), so the lint does
not ask for claims. It still asks for the header stamp, a key, a limits
section ("what this register does not cover") and a "working with it"
section that names the file and the command.

### `worklog` — the living page for one branch

Header rewritten every publish — **Goal · Now · Human TODO · Blockers** — over
an append-only, newest-first timeline of `HH:MM — what happened`. One item
per job in Human TODO; a row that bundles three jobs never leaves the list.
Publish to a stable slug so the page versions in place. *(lint:
`worklog-header`, `worklog-timeline`.)*

## The universal back matter — every argued page

6. **What did not work.** Each attempt: what it was, why it was dropped,
   whether the door is closed or parked. A reader without this re-proposes
   it. *(lint: `failed-attempts`, INFO.)*
7. **Limits, and claims we do not make.** What was not measured, not covered,
   or not claimed — in those words. NeurIPS accepts "not applicable" with a
   reason; it does not accept silence, and neither does a reader. Include
   "what I could not establish from code and docs". *(lint: `limits`.)*
8. **Next step — one, then the backlog.** Exactly one action with its
   definition of done, verifier, owner and date; a list of five is a backlog
   and defers the decision the page exists to force. The backlog follows,
   ranked, each item with an owner. *(lint: `next`.)*
9. **What I did to find this out.** The research log described above: what
   was read, run and compared, in order, with dates. *(lint: `method`.)*
10. **Sources and reproduction.** For every number: where it came from, the
    date; the command that rebuilds the page's figures; the commit. *(lint:
    `sources`.)*
11. **What this page does not cover.** The declared scope boundary — "nothing
    missing" is only honest if what is out of scope is written down.

## Writing rules that make the spine legible

- **Headings are claims; labels are eyebrows.** The pages worth imitating put
  the label in a small eyebrow (`01 · the models`) and the claim in the
  heading (*"What exists, and what each one is"*, *"Why recall is stuck at
  about a quarter"*). Test: can the heading be false? *(lint:
  `headings-claim` — WARN below one claim in three.)*
- **Mark section roles as data.** `id="key"`, `id="why"`, `id="limits"`,
  `id="next"`, `id="method"`, `id="sources"` on the heading or section, and an
  in-page nav that links to them. Claim headings hide the role words; the id is what a tool — and the
  next agent — keys on. The same lesson that put the work-log header into
  the manifest as data: seven markup shapes for four labels, and a scraper
  that mistook a blocker paragraph for three tasks.
- **Every table gets a reading line.** Under the table: *"Reading the column:
  the same model flags 0.00% of pristine documents, 0.99% of independent
  issuer documents…"* and *"Highlighted: yellow = the recall comparison,
  green = unchanged"*. A table without one is data, not evidence.
- **Every rate carries its denominator and window on the same line**, and the
  denominator names a population, not a number: *"of 1,921 held-out real
  issuer PDFs from 82 issuers"*. Four things get called "clean"; say which.
- **Corrections stay on the page.** *"An earlier version of this page reported
  1.72×; that compared two different quantities."* A silent fix teaches the
  reader nothing and hides that the page moves.
- **Verified / inferred / speculation are marked**, per claim, with a
  consistent device (●●●○ dots, a chip, a fenced block) — never by tone.
- **Length.** Amazon's calibration: six narrative pages (~3,000 words) that a
  room reads in twenty minutes, appendix unbounded. One company hub's median
  page is **1,223 words** (n = 1,065, measured 2026-09-24) and 21 pages run
  past 20,000. Whether anyone finishes those is not known — the hub records no
  reading data — so the rule is not "long is unread": split by sub-problem,
  never by length, and keep the answer page short. Above ~2,500 words add an
  in-page nav; past ~6,000 that nav must follow the reader (see the index
  section above). *(lint: `toc`, `length`, `nav-position`.)*
- **Both languages, same rules.** A Chinese page has the same spine; the lint
  reads 不 / 是 / 为什么 / 边界 / 下一步 as it reads their English
  counterparts.

## Devices worth copying — decoded from the hub's sixteen strongest pages

Read in full on 2026-09-23 (twelve rendered and inspected), chosen by lint
cleanliness, figure count and being forwarded. Each device below is one
concrete thing a page did that made it legible; use them as parts.

One more page was read end to end on 2026-09-24 — the doc-fraud teardown of
eleven vendors (25,159 words, 28 figures, 23 tables, 13 of 13 section headings
stating a finding). Its comparison devices were not in this list and are
grouped under **Comparison tables** below; its failure is the one that produced
the index rule above.

**Front matter**
- **Evidence-grade chips as a legend at the top** — "Measured / published ·
  vendor's own claim · our inference" — and every number on the page wears
  one. The reader never has to ask how sure.
- **A boxed TL;DR with three labelled lines**: *Who it's for · Why now ·
  Status*. Fits a demo brief in eight lines.
- **"Read this first: six things that will otherwise cost you a day"** at
  the top of a handoff — numbered traps, each with what to do instead.
- **Reading paths by reader and time budget**: "Only five minutes: §… → §… ·
  To review the architecture: §… · To manage progress: §…", plus
  "reading time ~40 min" in the stamp.
- **A state strip** (round 1 analysed · round 2 live · prevalence still
  open) beside the stamp, so the document's own status is a field.

**Numbers**
- **A reproduction table with a `match` column** — eleven metrics, ours vs
  theirs, every row "match" — before any new claim is made.
- **"Why I trust this evaluation"** as a heading, with the leakage checks
  listed (overlap = 0 on cluster / case id / hash / loan id).
- **A matched-control paragraph**: 20/20 failing documents show the
  property, 0/30 controls do, 100% separation — three tiles.
- **A funnel with a status pill per stage** (52,573 → 16,493 → 15,332 →
  ~18,700, each DONE), and "removed, never deleted — every removal logged".
- **A matrix with a state legend** (RUN · WARM · — · DL) for what runs when.
- **A "gap" column** on a dot plot, with the axis labelled "← toward genuine
  · toward forged →" so the direction needs no legend.

**Comparison tables** *(from the 2026-09-24 teardown)*
- **An evidence-class chip on every cell**, not a source line under the
  table: `API` documented · `DEMO` seen in a tour or video · `MKT`/`TAPE`
  claimed in marketing or on tape · `INF.` our inference — all 77 cells of an
  11 × 7 matrix wear one. A shipped API and a claim made on a podcast stop
  reading alike, which is the whole risk of a competitor table.
- **Say what a blank means**, under the table: *"A dot means no public
  evidence, not proof of absence."* Without that line every hole is read as a
  measured zero, and a comparison table is mostly holes.
- **A negative-space tile** when the finding is what nobody does: `0 / 11`
  *publish a trusted share, or show a re-typeset fake flagged*. The hole is
  the result, so it gets a tile like any other number.
- **A depth scale defined once, then counted per subject**: L0 verdict · L1
  score · L2 reason list · L3 located evidence · L4 forensic detail · L5
  cross-document · L6 action, counted per vendor and heat-mapped. It answers
  *how deep does each one go*, which a has-the-feature tick cannot.
- **A verdict on every row of a catalogue** — `COPY` / `AVOID` on each
  rebuilt screen, each carrying the file path and timecode it came from. A
  neutral catalogue defers the decision it was gathered to make.
- **Provenance in the method section, not the footer**: commit, branch, the
  directory on the host, and one line saying whose numbers these are —
  *"vendor numbers are their own claims, not verified by us."*

**Argument**
- **A "Falsification" section**: the claim, the test that would kill it,
  and the result — followed by "What would be required (not generated
  here)".
- **"Established / Not established"** as the closing pair, one list each.
- **"Read the *forged max* column, not the AUC"** — a reading instruction
  as a heading, when the obvious number misleads.
- **A causal chain with a verified link per step** ("1 · The first bands
  were invented … 2 · The replacement asked the wrong question … 4 ·
  Deepest, and still open") — each link measured, not inferred.
- **"Signals we do not lean on"** and **"Results that were cut, and must
  stay cut"** — the negative space stated.
- **"What the marketing leaves out"** in a vendor brief.
- **A "Delivered capability and boundary" column** in the PR table, so every
  merged change states what it does not claim.
- **Per-chapter fixed skeleton in a long chronicle**: the problem entering →
  the mechanism (with the real constants) → why this over the alternatives
  → measured → what broke → what it taught; plus "seven terms carry the
  whole story" and "the clock of the system — constants that recur".
- **"It happens"**: one real, cited case per item in a manual (a DOJ
  prosecution beside each forgery type), then "what it leaves behind".
- **A before → after pair with the entire pixel diff boxed in red**.
- **A live progress line for a running job** ("2250/2000 cells · 112.5% ·
  1,186 min elapsed · $417.91 of the $250 cap") on a page that reports it.

**Close**
- **"The gap, in one sentence"**, then **"Next steps, ranked against the
  North Star"**, then **"Provenance of every number here"**.
- **"Other people tell parts of this better. Read them first."** — a
  curated source strip with one line on why each is worth the click.
- **"The shape it should have been"** as the last section of a post-mortem.

## Anti-patterns the sources name, seen on the hub

1. A topic for a headline ("Model Update", "PDF 检测评估") — 35% of pages.
2. No date in the first screen — 22%.
3. A page with no `<h1>` at all, because the title is a styled `div` — 6%;
   it cannot be skimmed, linked or summarised.
4. Walls of tables with no figure (13%) and figures with no caption.
5. Percentages with no population, or "1% FPR" with no statement of which of
   the four "clean" populations it counts.
6. Next steps that are vague, unowned, or a list of five.
7. Non-goals and limits omitted, so scope arguments never resolve.
8. Speculation written in the same register as measurement.
9. Metrics that credit an architecture change for a hyper-parameter's work —
   no ablation.
10. A page that renders nothing without JavaScript: no text for search, for
    a summariser, or for a slow client.
11. Bullet lists in place of argument — the reason Amazon banned slides.
12. "Human error" as a root cause.

## Sources

- US Army AR 25-50, "Preparing and Managing Correspondence" (BLUF) —
  https://armypubs.army.mil/epubs/DR_pubs/DR_a/ARN42124-AR_25-50-007-WEB-13.pdf
- Minto, *The Pyramid Principle*; SCQA — https://modelthinkers.com/mental-model/minto-pyramid-scqa
- Bryar & Carr, *Working Backwards* (six-pagers) — https://commoncog.com/working-backwards/
- Alley, the assertion–evidence approach — https://www.assertion-evidence.com/
- Ubl, "Design Docs at Google" — https://www.industrialempathy.com/posts/design-docs-at-google/
- Google SRE, "Postmortem Culture" and the example postmortem —
  https://sre.google/sre-book/postmortem-culture/ · https://sre.google/sre-book/example-postmortem/
- Google SRE Workbook, "Implementing SLOs" (a rate is good events over valid events) — https://sre.google/workbook/implementing-slos/
- Rust RFC template (Drawbacks, Unresolved questions) — https://github.com/rust-lang/rfcs/blob/master/0000-template.md
- Oxide, RFD 1 (document states) — https://rfd.shared.oxide.computer/rfd/0001
- Orosz, "Scaling engineering teams via RFCs" — https://blog.pragmaticengineer.com/scaling-engineering-teams-via-writing-things-down-rfcs/
- DARPA, the Heilmeier catechism — https://www.darpa.mil/about/heilmeier-catechism
- NeurIPS paper checklist — https://neurips.cc/public/guides/PaperChecklist
- Lipton & Steinhardt, "Troubling Trends in Machine Learning Scholarship" — https://arxiv.org/abs/1807.03341
- Karpathy, "A Recipe for Training Neural Networks" — https://karpathy.github.io/2019/04/25/recipe/
- arc42 template — https://arc42.org/overview · C4 model — https://c4model.com/
- PagerDuty, the Howie post-incident guide — https://howie-guide.pagerduty.com/
