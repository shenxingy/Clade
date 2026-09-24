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
  a "what to do, in order" close. The hub as a whole does not: 72% of its
  926 report pages have no next-step section, 69% no limits section, 60% no
  sources section, 53% no key, 35% a topic label for a headline, and 32%
  carry any figure. The gap is the missing standard, not any one author.
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

## The universal front matter — every argued page, in this order

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
2. **Deck.** ≤ 120 words directly under the headline: what was measured, on
   what population, the two numbers that matter, and what the reader should
   do. This is the BLUF; a reader who stops here must leave with the right
   belief. `/internal-deploy` calls the same paragraph the **Bottom line** —
   one contract, two names: the conclusion the reader acts on comes before
   any rounds, dates or timeline. *(lint: `deck`.)*
3. **Number strip.** Three to five numbers, each with its **denominator and
   window** on the same line: *"0 / 24 held-out frauds flagged at τ"*,
   *"33.4% recall of 12,152 forgeries at 1% real-clean FPR (n = 1,921)"*. A
   rate without its population is a mood. *(lint: `denominators`.)*
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

## The body — one spine per type

Declare the type in the page head: `<meta name="artifact-type"
content="finding">`. The lint relaxes claim-heading, limits and next-step
checks for `reference` and `worklog`; an undeclared page is linted as a
`finding`, the strictest shape.

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
9. **Sources and reproduction.** For every number: where it came from, the
   method, the date; the command that rebuilds the page's figures; the
   commit. *(lint: `sources`.)*
10. **What this page does not cover.** The declared scope boundary — "nothing
    missing" is only honest if what is out of scope is written down.

## Writing rules that make the spine legible

- **Headings are claims; labels are eyebrows.** The pages worth imitating put
  the label in a small eyebrow (`01 · the models`) and the claim in the
  heading (*"What exists, and what each one is"*, *"Why recall is stuck at
  about a quarter"*). Test: can the heading be false? *(lint:
  `headings-claim` — WARN below one claim in three.)*
- **Mark section roles as data.** `id="key"`, `id="limits"`, `id="next"`,
  `id="sources"` on the heading or section, and an in-page nav that links to
  them. Claim headings hide the role words; the id is what a tool — and the
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
  room reads in twenty minutes, appendix unbounded. The hub's median page is
  ~2,000 words; pages above 20,000 words exist and are unread. Split by
  sub-problem, never by length, and keep the answer page short. Above ~2,500
  words, add an in-page nav. *(lint: `toc`, `length`.)*
- **Both languages, same rules.** A Chinese page has the same spine; the lint
  reads 不 / 是 / 为什么 / 边界 / 下一步 as it reads their English
  counterparts.

## Devices worth copying — decoded from the hub's sixteen strongest pages

Read in full on 2026-09-23 (twelve rendered and inspected), chosen by lint
cleanliness, figure count and being forwarded. Each device below is one
concrete thing a page did that made it legible; use them as parts.

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
