---
title: The artifact standard — what makes a report page legible at a glance, measured on 1,032 hub pages
date: 2026-09-23
review_date: 2026-09-23
status: reference
summary: >
  The owner asked why report pages on the company artifact hub so often "lack
  content or state things unclearly", what the most-published colleague does
  differently, how the best external practice structures a technical page and
  draws a publication-quality figure, and how to make the generator do it every
  time. Measured on all 1,032 live pages: the gap is hub-wide, not personal —
  72% of report pages have no next-step section, 69% no limits section, 53%
  no key or terms, 32% carry any figure, and 2 of 926 pass every check. The
  pages people forward share one shape; nothing named it, so nothing could
  check it. Result: the /artifact skill (section spines per page type, figure
  and colour rules, diagram notation), artifact-lint.py (22 mechanical checks,
  bilingual, with --survey), a path-scoped rule, and a published exemplar page.
---

# The artifact standard

**The question, verbatim (owner, 2026-09-23, translated):** look at how we
publish artifacts, content first. Go to the intranet hub and look at the many
pages the most-published colleague has put up: where does his thinking come
from, what is his architecture and overall structure, what is he trying to
express? My own pages are sometimes missing content or state things unclearly.
He is not perfect either — look at how the best people do it: how do you make
a page that someone understands at a glance (what the problem is now, the deep
analysis, the future TODO, strengths and weaknesses)? A research artifact
lives or dies by its figures — what are the requirements, alignment, colour,
how do you draw a figure that would get into a paper? A software page needs
the architecture thought through too. Handle how artifacts are generated and
how colour is handled, and loop on it.

Names of colleagues, internal URLs and page slugs are deliberately absent from
this public copy; the internal exemplar page carries them.

## 1. Method

- **Instrument.** `configs/scripts/artifact-lint.py`, stdlib-only, run as
  `--survey <hub root>` over every `<slug>/manifest.json` + `index.html`.
  Pages whose slug starts with `worklog-` are linted against the work-log
  protocol; the rest as a `finding`, the strictest shape. Groups are the
  manifest `owner` (fallback `publisher`) with prefixes stripped and two
  spellings aliased per person.
- **Population.** 1,032 live pages: 926 report pages and 106 work-logs.
  Snapshot taken 2026-09-23 on the serving host.
- **Reading.** Three of the most-forwarded pages read in full, plus the
  structural extraction (headings, figures, tables, tokens, fonts) of every
  page by the two most-published authors — 117 and 49 report pages.
- **Calibration loop.** The first heuristic draft mis-fired five ways on the
  strongest pages and each was fixed before the numbers below were taken:
  an SVG tooltip `<title>` was read as the page title; a percentage in a
  table cell was scored "no denominator" although the count sat in another
  cell; claim-style headings hid the section roles the regexes looked for
  (fixed by also reading `id`/`class` and in-page nav text); charset/viewport
  order was scored as a defect; an abstract placed in a `<div>` was scored
  missing. The self-test carries fixtures for each, and
  `orchestrator/tests/test_self_tests_can_fire.py` carries 17 mutations
  that must turn it red.

## 2. What the hub looks like

Share of the 926 report pages carrying each finding (WARN or FAIL):

| Finding | Share | What it means |
|---|---|---|
| no next-step section | 72% | the page forces no decision |
| no limits section | 69% | silence reads as "everything is fine" |
| no sources / reproduce section | 60% | numbers with nowhere to go |
| no key & terms section | 53% | entities and metrics never defined; colours never fixed |
| head standard failed (no doctype / charset / viewport) | 42% | 331 pages start with `<title>` — the publisher template, not the authors |
| headline is a topic label | 35% | the reader must read the body to learn the point |
| no date in the first screen | 22% | wrong within a week, undetectably |
| external script / stylesheet / font | 17% + 8% | renders the fallback on the intranet |
| wall of tables, no figure | 13% | |
| carries any figure at all | 32% | |
| passes every check | 2 of 926 | |

Work-logs: 93 of 106 lack the protocol header (Goal · Now · Human TODO ·
Blockers). Median report page is 1,351 words; the 90th percentile is 5,838;
15 pages exceed 20,000 words.

By author (share of pages **without** the finding, higher is better):

| group | n | any figure | title is a claim | deck | dated | claim headings | key & terms | limits | next | sources | no external refs |
|---|---|---|---|---|---|---|---|---|---|---|---|
| most-published author | 117 | 47% | 64% | 96% | 79% | 83% | 32% | 38% | 40% | 45% | 74% |
| this toolkit's owner | 49 | 39% | 59% | 92% | 90% | 86% | 43% | 49% | 29% | 49% | 80% |
| everyone else (≥ 20 pages each, 4 groups) | 27–48 | 7–52% | 56–91% | 96–100% | 53–100% | 58–96% | 11–62% | 21–48% | 6–33% | 26–50% | 56–78% |
| unattributed | 612 | 29% | 66% | 90% | 76% | 83% | 50% | 28% | 27% | 38% | 89% |

Reproduce: `python3 configs/scripts/artifact-lint.py --survey <hub root>
--alias <owner-id>=<name> …`. The table is the script's own output.

**Reading the table.** The owner's pages are at or above the most-published
author's on six of ten structural checks; of the four where they trail, two
are within a few points (headline as a claim 59% vs 64%, deck 92% vs 96%) and
two are substantive — the next-step section (29% vs 40%) and figures (39% vs
47%). "Missing content"
is, measured, three sections: key & terms, limits, next step. "Stated
unclearly" is, measured, the absence of a figure and of a denominator beside
the rate. Neither is an authoring-talent gap — no group clears 62% on any of
the three sections — it is the absence of a named standard.

## 3. What the strongest pages do — the shape, decoded

From the three most-forwarded pages read in full and the heading extraction
of all 117 by the same author. Every item below became a rule in
`configs/skills/artifact/references/spines.md`:

1. **The headline is the finding**, a sentence that could be false, with a
   full stop. The label ("v9 cross-check", "model improvement") moves to a
   small eyebrow above it.
2. **A four-sentence deck** with the numbers, then a **number strip** of 3–5
   tiles, each carrying its population on the same line ("0 / 24 held-out
   frauds flagged at τ").
3. **A graded verdict** — Reproduced / Not supported / Confirmed — with
   ●●●○ dots and one line of why, separating what was checked from what is
   inferred.
4. **"Colour key and terms"**: every named model, dataset and metric defined
   with its denominator, one colour per entity, and the sentence "the same
   colours are used in every table and in the chart".
5. **Section headings are claims** ("Ranking inside the set is not detection
   at the threshold", "Why recall is stuck at about a quarter"), numbered
   eyebrows carry the labels in long pages.
6. **Every table has a reading line** ("Reading the column: …",
   "Highlighted: yellow = …").
7. **Charts**: dot-range rows (mean ─┤ max) with the threshold drawn and
   labelled, the flagged region tinted, `n =` in every row label, two arms
   as square vs circle in two hues, tooltips as `<title>` children.
8. **Corrections stay on the page** ("an earlier version reported 1.72×;
   that compared two different quantities").
9. **The close is an instruction**: "What to do, in order", "Judge it where
   it ships", "What would make the claim hold".
10. **Work-logs** follow the memory system's protocol: Goal · Now · Human
    TODO · Blockers over a newest-first timeline.

Where it comes from (inference — the author was not interviewed): the shape
matches answer-first writing (BLUF, assertion–evidence headings), the SRE
rule that a rate names its population, the organisation's monochrome design
system (mono type, black/white, three verdict colours as the only accents),
and the work-log protocol documented in the memory system's own docs.

The same author's measured weaknesses: a remote font on 26% of pages (the
intranet renders the fallback), chart colours as literals that vanish in
dark mode, pages past 10,000 words with no in-page navigation, and a limits
section on only 38%.

## 4. What the best external practice says — and where it agrees

Three read-only research passes (structures; figures and colour; architecture
diagrams), every rule traced to a primary source. Full lists with citations
live in the skill's references; the convergence is the point:

- **Answer first** (AR 25-50 BLUF, Minto SCQA, Amazon's six-pager, Alley's
  assertion–evidence) = the decoded headline + deck + number strip.
- **Denominator and window on every rate** (Google SRE Workbook) = the number
  strip's population rule.
- **Non-goals, alternatives, drawbacks, unresolved questions** (Ubl's design
  docs, Rust RFC) = the limits and what-did-not-work sections.
- **Action items with owners; status as a first-class field** (Google SRE
  postmortem, Oxide RFD states) = one next step with owner and date.
- **Speculation fenced from measurement; ablation before attribution;
  limitations stated** (Lipton & Steinhardt, NeurIPS checklist, Karpathy) =
  the graded verdict.
- **Figures**: one message per figure, caption states the conclusion, ≤ 6–8
  categorical hues in fixed order, no rainbow, never colour alone, bars from
  zero, comparable panels share axes, 3:1 for marks and 4.5:1 for text against
  the adjacent ground in both themes (Rougier; Wong's *Points of View*; Wilke;
  Tol; Okabe–Ito; WCAG 2.2). One correction to a widely repeated rule: WCAG's
  3:1 is against the background, not between series — a validator demanding
  pairwise 3:1 rejects Okabe–Ito.
- **Diagrams**: C4 context + container with a key on the drawing, one
  abstraction level, ≤ 20 elements, every line labelled and one-directional;
  Mermaid cannot take theme tokens or draw a legend, so report figures are
  hand-authored SVG (Brown; Microsoft Well-Architected; arc42).

## 5. What was built

| Piece | Path | What it does |
|---|---|---|
| `/artifact` skill | `configs/skills/artifact/` | the process: frame → facts table → spine → figures → diagrams → build → lint → look → publish |
| spines | `…/references/spines.md` | universal front and back matter; one body spine per type (finding, status, architecture, rca, handoff, decision, reference, worklog) |
| figures | `…/references/figures.md` | procedure, 32 sourced rules, Okabe–Ito and Tol hexes, the two-theme token pattern, chart anatomy, checklist |
| diagrams | `…/references/diagrams.md` | which diagram for which question, C4 notation rules, six-class legend with light/dark tokens, Mermaid vs SVG |
| lint | `configs/scripts/artifact-lint.py` | 22 checks (FAIL/WARN/INFO), `<meta name="artifact-type">` profiles, `--survey`, `--self-test`; 17 mutations pinned |
| rule | `configs/rules/artifact.md` | injected when a `**/artifacts/**/*.html` (and siblings) is edited |
| `/landscape` | `configs/skills/landscape/prompt.md` | now points at the artifact references instead of carrying its own diagram rules |
| exemplar | internal hub, slug `artifact-standard` | the study as a page, written with the skill, linted clean, screenshot in both themes |

The lint is the enforcement; the prose is the explanation. A rule the script
cannot check is stated as a screenshot-review item, not left implicit.

## 6. The loop

| Round | Did | Found | Fixed |
|---|---|---|---|
| 1 | structural extraction of 66 + 63 pages; first heuristic survey | five mis-firing heuristics (§1) | all five; self-test fixtures |
| 2 | calibrated survey; the strongest pages re-linted | strongest page: 1 FAIL (remote font), 2 WARN (literal chart colours, 107 literal hex) — all real | thresholds; role detection via ids |
| 3 | the exemplar page written with the skill, linted with both lints, rendered light/dark/phone | a palette swatch figure legitimately carries 15 literal colours; `font-family: var(--stack)` was scored as a bare face (a lint defect); the page's own description of the placeholder check tripped it; the nav removed its focus outline; dark-mode chips had 2.3:1 text | lint: a per-figure `data-artifact-lint="ignore-palette"` opt-out and token-stack recognition, each with a fixture and a mutation; page: three wording/CSS fixes. No rule or threshold changed — converged |

Convergence criterion: a round that changes no rule and no threshold.

## 7. Not done, and open

- **Reading is not measured.** The hub has no read analytics, so "legible at a
  glance" is asserted from structure and external evidence, not from
  behaviour. Nginx access logs would give page-level reads; not built.
- **The publisher template** emits no doctype, charset or viewport — 331 of
  the 386 head-standard failures. That is one upstream fix in the memory
  system's publisher, not 331 page edits; opened as a PR on that repository
  the same day (a `_normalize_head()` step before the provenance footer,
  byte-preserving, idempotent, opt-out marker, eight tests). The four owner
  pages that had no `<h1>` were repaired and republished.
- **Heuristics are regexes**, bilingual but approximate; a Chinese heading
  under six characters is always a label to the lint, and a section role is
  found only through heading words, `id`/`class`, or nav text.
- **Figure quality beyond mechanics** (is the chosen form right, is the
  message true) remains the screenshot review.
- **The organisation's design system** is resolved at run time from the
  machine map, not shipped here — this repository is public.
