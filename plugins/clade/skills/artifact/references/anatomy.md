# Anatomy — the parts a report page, a slide and a deck are built from

`spines.md` says in what order a page answers its reader; this file is the
parts list: the elements the strongest published pages and decks are
actually built from, observed on the pages themselves, so a generator picks
from a known inventory instead of inventing sections. Two read-only research
passes on 2026-09-23 opened five families of documents — consulting reports
(BCG, McKinsey Global Institute), data journalism and annual reports (Our
World in Data, Pew, Stanford AI Index, State of AI, a16z, Stripe, Cloudflare
Radar), research and engineering write-ups (Distill, Anthropic, Google
Research, Cloudflare and GitHub incident reports, Google SRE), government and
standards documents (ONS statistical bulletins, GOV.UK, NIST), and product /
decision documents (Amazon PR/FAQ, Google design docs, Shape Up, Linear,
Kubernetes release posts) — and the two verbatim-transcribable slide checklists
(Doumont; Alley's assertion–evidence). Paywalled outlets (NYT, FT, Bloomberg,
The Economist, Gartner) were unreachable and are not asserted from memory.

The company hub's twenty strongest pages, read the same day, use the same
parts; those are listed as devices in `spines.md`.

## Report page — element inventory

Grouped by where the element sits. "When" is the rule for whether it earns
its place; sizes are what the observed pages actually spend.

**Front**

| Element | Observed as | When | Size |
|---|---|---|---|
| Headline claim | a16z "This is the year the world came onchain"; Increment "Everything is broken, and it's okay" | Always — a topic title forfeits the most-read line | 6–12 words |
| Dek / standfirst | One sentence under the title giving the mechanism | When the headline needs a why | 15–30 words |
| Author · date · version stamp, plus **next release date** | ONS prints "Release date" and "Next release" — a falsifiable commitment | Always | 1–3 lines |
| Reading time | BCG "12 MIN read" | > 1,500 words | 1 line |
| Key-findings box | BCG "Key Takeaways" (3); AI Index "Top Takeaways" (12, one figure each) | > 800 words | 3–12 bullets |
| Executive summary / "In brief" page | MGI ships it as its own PDF | > 10 pages | 1–8 pages |
| Table of contents / sidebar nav | ONS 12-item TOC; Pew 15–19-chapter sidebar | > 5 sections | list |
| Accreditation / status badge | ONS "accredited official statistics" + reviewer + date; Oxide RFD state | When a body or a process certifies it | 1 line |

**Evidence**

| Element | Observed as | When | Size |
|---|---|---|---|
| Key-insight block: sentence headline + paragraph + "What you should know about this data" + chart | Our World in Data — the densest unit observed; use it as the page's repeating spine | Every main finding | ~5 per page |
| KPI / stat tiles with unit and scope | Cloudflare Radar "Global Internet traffic grew 19% in 2025" | Numbers a reader will quote | 3–6 tiles |
| Numbered exhibit with an action title | BCG "Exhibit 2: From 2024 to 2026, AI's Grasp of Software Engineer Skills Has Evolved Dramatically" | Every chart; numbering enables cross-reference | 1 line |
| Source line under the exhibit | Pew stamps "Note: / Source: / PEW RESEARCH CENTER" on the chart itself, so a screenshot carries its provenance | Every chart | 1–3 lines |
| "How to read this chart" note | OWID per-chart subtitle and note | Non-standard chart forms | 1–2 lines |
| Annotated chart | Labels on the plot marking the moment argued (Cloudflare error-rate graphs) | When the reader must find one region | in-figure |
| Figure caption that says what to look at | Google Research "Spotting the invisible — compares…" | Every figure | 1–2 sentences |
| Interactive figure with an explicit instruction | Distill "Hover over a node…"; the instruction is what makes the affordance discoverable | When the claim is a mechanism with parameters | per figure |
| System-context / architecture diagram | Cloudflare's reverse-proxy diagram inside the postmortem; a required element of Google design docs | Any causal-chain argument | 1 per doc |
| Timeline table | Cloudflare: UTC-stamped rows, status + description | Incidents, launches, anything time-ordered | 6–20 rows |
| Impact table | Affected surface × observed impact | Multi-surface consequences | 5–10 rows |
| Comparison / decision matrix | Options × criteria | 3+ options × 3+ criteria | 1 table |
| Sidebar / callout | MGI "Sidebar:"; GOV.UK inset text | A tangent a subset of readers needs | 100–250 words |
| Pull quote | A lifted sentence at display size | Long prose runs (inference: a navigation aid) | 1 sentence |

**Method and limits**

| Element | Observed as | When | Size |
|---|---|---|---|
| Methodology box, **before** the findings | Pew "How we did this"; Cloudflare Radar states its baseline window inline | Always — placement up front is what separates the best | 100–300 words |
| "Things you need to know about this release" | ONS caveat block before the numbers | Revisions, series breaks, coverage gaps | 3–6 bullets |
| Limitations / strengths and limitations | Anthropic "our method only captures a fraction of the total computation"; ONS | Every empirical claim | 1–5 bullets |
| "Measuring the data" / quality and methods | ONS deep method section, distinct from the front box | When the method is itself contested | 1–3 pages |
| Definitions / glossary | ONS numbered "Glossary" and "Definitions"; NIST acronym appendix | Any term the audience defines differently | 5–20 entries |
| Goals and non-goals / no-gos · alternatives considered · appetite · rabbit holes | Google design docs; Shape Up (appetite = "how much time we want to spend and how that constrains the solution") | Proposals and irreversible decisions | 3–8 bullets each |

**Close**

| Element | Observed as | When | Size |
|---|---|---|---|
| Action items: item · type · owner · bug | Google SRE postmortem table; type = mitigate / prevent / process; the bug id makes it checkable | Anything with follow-through | 5–15 rows |
| Lessons-learned triad | SRE: what went well / what went wrong / **where we got lucky** — the third is the one nobody writes | Retrospectives | 3 lists |
| Health / status enum | Linear: On track / At risk / Off track + 150 words | Recurring updates | 1 enum |
| Scorecard vs prior predictions | State of AI grades every forecast since 2018 with hit rates | Recurring annual reports | 1 table |
| Changelog / "what changed since last time" | AI Index ships a separate "Report Revisions" document; GOV.UK change notes | Living documents | 1 line per change |
| FAQ, external and internal split | Amazon PR/FAQ: customer questions vs internal ones (TAM, unit economics, top reasons for failure) | Decision docs | 5–15 questions |
| Endnotes vs sources; citation block; reuse licence; data download; contributors and reviewers; contact; related links | OWID separates "Endnotes" from per-chart sources and gives MLA + BibTeX, CC-BY and the GitHub data repo; ONS names a team with email and phone; Distill names its reviewers with issue links | Anything meant to be cited, forwarded or challenged | 1 block each |

## Section orders that recur

1. **Claim-first analytical** (BCG, MGI): headline claim → key takeaways (3) → numbered exhibits with action titles → implications → authors → related. The exhibit numbering is the skeleton; prose is connective tissue.
2. **Insight-spine explanatory** (Our World in Data): intro → related topics → n × [sentence-headline insight + "what you should know about this data" + chart] → key charts → endnotes → cite → reuse.
3. **Statistical bulletin** (ONS): badge + release / next-release dates → main points → thematic sections → data → glossary and definitions → quality, methods and data sources → related links → cite → contact.
4. **Incident / postmortem** (Cloudflare, GitHub, Google SRE): apology + one-sentence what-and-when → impact table → architecture primer → causal chain → timeline table → other impact → remediation and follow-up → action items with owner and type.
5. **Standards / technical report** (NIST SP): cover → authority → abstract → keywords → acknowledgments → audience → TOC + list of figures and tables → numbered sections → references → appendices.
6. **Proposal / decision** (Shape Up, Google design docs, Amazon PR/FAQ): problem → appetite → solution with a diagram → rabbit holes → no-gos / goals and non-goals → alternatives considered → cross-cutting concerns (security, privacy, observability) → FAQ.

## What the best do that the average does not

1. Every exhibit title is a sentence with a verb, never the axes.
2. Sources sit under the exhibit, not at the end.
3. The method box comes before the findings.
4. Caveats travel with the specific claim, beside the chart they qualify.
5. The next publication date is stated.
6. Prior predictions are graded in public.
7. Corrections are a first-class artifact, not a silent edit.
8. Follow-ups carry an owner, a type and a tracking id.
9. The retrospective asks the uncomfortable third question: where did we get lucky.
10. The data is downloadable in the same click as the claim.

## Anti-patterns observed

Topic titles on exhibits · method as a terminal appendix · structure without content (a guidance hub whose child pages 404) · a gated PDF as the real report with a teaser page · a landing page as the deliverable (one number, two PDFs) · findings without a denominator or window · numbered sections that hide the claim (impeccable structure, no executive summary) · unlabelled interactivity.

## Slide — element inventory

Sources: Doumont's slide checklist (*Trees, maps, and theorems*) and Alley's
assertion–evidence checklist, both transcribable verbatim; consulting page
standards (Deckary, Slideworks, Minto's SCR); Duarte's glance test and
Slidedocs; Reynolds; Kawasaki; Tufte's critique and Amazon's ban.

| Element | Purpose | Placement | Rule / limit |
|---|---|---|---|
| Action title (assertion headline) | The so-what as a claim, not a topic | Top, same position on every slide | A complete sentence with subject and verb; ≤ 12 words (Doumont) / ≤ 15 (MBB); never more than two lines; left-justified; states a conclusion, not a process |
| Subtitle / kicker | Scope, unit, period of what is below | Under the title, smaller | Shorter than the title; never restates it; never smaller than body |
| The one exhibit | The evidence that proves the title | Body, single dominant object | Exactly one message per slide; readable "in an instant, globally rather than sequentially" |
| Unit / axis / label line | Makes the number interpretable | On or above the chart | Every quantity carries a unit and a period; data prominent, the rest recessive |
| Source line | Provenance and date of every data point | Footer left | "Source: origin (years); firm analysis"; 8–9 pt |
| Footnote | Definitions, exclusions, method caveats | Above the source line | Numbered to the mark in the body |
| Tracker / breadcrumb | Where this slide sits in the storyline | Header or top-left band | Visually segregated from content |
| Takeaway box | Restates the implication when the exhibit is dense | Right rail or below | Optional; never contradicts or duplicates the title |
| Page number | Reference in discussion | Bottom right, always | Every slide |
| Footer / logo | Deck identity | Bottom | Noise on a talk slide — Doumont says omit decoration |
| Body text, when unavoidable | Words that only work as words | Body | 18–24 pt; an audience reads ≤ 20 words a minute; lists of 2–4 items |
| Speaker notes | What the slide does not say | Off-slide | The delivered deck and the leave-behind are two artefacts, never one "slideument" |

## Deck — element inventory and the orders that recur

| Element | Purpose | When needed |
|---|---|---|
| Title slide | Title, author, date, venue, version | Always |
| Executive summary (Situation – Complication – Resolution) | The answer up front, on slide two; the resolution is 60–70% of it | Any decision deck |
| Agenda / structure | Preview of the argument | > ~15 slides; ≤ 5 main points, ideally exactly 3; one level; never titled "Outline" |
| Tracker | Persistent navigation | Multi-section decks |
| Section dividers | Chapter breaks | Recognisable at a glance as structure, not content |
| Evidence slides | One claim + one exhibit, repeated; MECE within a section | The bulk |
| The money slide | The one exhibit the deck exists for | One per deck; it may take 90 seconds |
| Limitations / risks | The boundary of the claim | Research talks, launch pages, decision decks |
| Asks / next steps / decisions | What the audience must do | Any review deck; decisions stated ("Approve $80K…") |
| Appendix / backup | Anticipated questions | Consulting, QBR, pitch |
| Sources slide | Consolidated provenance | Academic and data-heavy decks; 12–14 pt, not bold |

**Orders.** *Consulting storyline* (Minto): ghost deck first — one line per slide, the action title; then title → executive summary → structure → situation → complication → question → MECE sections (divider → evidence → takeaway) → recommendation → roadmap → risks → next steps and asks → appendix. Gate: reading only the titles must give a coherent argument (horizontal logic); each body proves only its own title (vertical logic). *Assertion–evidence talk* (Alley): title → why anyone cares → gap → approach → method ×2 → results, one assertion + one figure each ×5 → money slide → limitations → implications → acknowledgements → backup; about one slide a minute. *Pitch* (Sequoia): company purpose in one sentence → problem → solution → why now → market → competition → product → business model → team → financials → five-year vision; Kawasaki 10/20/30. *Launch page* (observed across Anthropic, Google, NVIDIA): hero claim → benchmark chart against named baselines → availability and pricing early → capability by capability → demo → customer quotes → secondary benchmark table → safety / limitations → developer access → footnotes and methodology → related links. *Status / QBR*: 10–20 slides; summary (on track? wins? decisions owed) → KPI dashboard (5–10 metrics, the same chart every quarter) → wins → misses and root cause → risks → decisions requested → next-quarter plan → appendix.

## Checkable slide rules

1. The title is a complete sentence with a subject and a verb.
2. ≤ 12–15 words, never more than two lines, same size and position on every slide.
3. One message per slide; nothing competes with it.
4. No bullet lists as evidence; if unavoidable, 2–4 items.
5. Body text ≤ 20 words per minute of talk (Tufte's measured median is 40 words a slide, ~8 seconds).
6. Type: headline 28 pt, body 18–24 pt, references 12–14 pt (Alley); Kawasaki says nothing under 30 pt.
7. Bold sans; no all-caps, italics or underline for emphasis.
8. At most two typefaces and 3–4 colours; colour carries meaning, never decoration.
9. Contrast ≥ 4.5:1 for text (≥ 3:1 at ≥ 18 pt or 14 pt bold).
10. Glance test: comprehensible in about three seconds.
11. The slide makes reasonable sense without the speaker.
12. Every data slide carries source and period; every quantity a unit.
13. Page number on every slide, same corner.
14. Tracker and navigation visually segregated from content.
15. Background art, logos and decoration deleted from content slides.
16. Reading order is set by the layout, not by stacked text boxes.
17. Structure ≤ 5 main points, ideally 3; ≤ 5 sub-points.
18. Prefer figures to tables — tables are hard to see on a screen.
19. Read only the titles: they must tell the whole story.
20. About 60 seconds per consulting slide, one minute per academic slide.

## Presentation, slidedoc or report page

Duarte's two questions: does the audience need you to deliver it → a
**presentation** (road-sign slides: few words, one image, giant type; the
notes carry the rest). Do they need substantial detail read alone → a
**slidedoc** (built in slide software, read not narrated: 100 words a page
baseline, 250 ceiling, 50–70 characters a line, columns, a table of contents,
dividers, page numbers, sequential titles that form an argument — which is
what a consulting deck actually is). Beyond ~250 words a page → a
**document**: Tufte's high-resolution handout, Amazon's six-page narrative
read silently at the start of the meeting. Write the deck and the leave-behind
as two artefacts; a deck that tries to be both fails at both.

## Claude Code artifact types — which container

`Artifact` `action: "list_types"` lists the types this account can start a
new artifact from; on 2026-09-23 the core set was four, each shipping a
`SKILL.md` that the create result returns:

- **Slides** — 16:9 decks to present, page through and download; ships
  references for craft, deck files, diagrams and diagram recipes, fonts,
  format, images, layout, questions, styles. The slide and deck rules above
  are the content rules; this is the container.
- **Docs** — living documents (plans, memos, briefs) people and Claude read
  and edit together; content lives in the Claude Docs service, the artifact is
  the shared viewer. For documents that will keep changing, not for a
  published report.
- **Design** — a canvas of live artboards for pages, screens, mock-ups,
  wireframes, posters and social visuals; the right container for "three
  directions side by side".
- **Design System** — a brand's README, tokens across themes, type scale,
  spacing, components with live previews, assets, as one browsable reference
  agents build on.

A single-page report is none of these: it is a plain HTML artifact, and this
skill's spine, figure and colour rules are what give it structure. Load the
bundled `artifact-design` (layout, type, two-theme tokens), `dataviz` (form,
colour formula, the palette validator) and `artifact-diagramming` (inline SVG
mechanics) skills before writing; `artifact-capabilities` when the page needs
shared state, comments, assets or downloads.

## Sources

Report side: Our World in Data (life expectancy, energy, CO₂ pages; ETL metadata reference) · ONS consumer price inflation and mid-year population bulletins · Cloudflare 18 Nov 2025 outage, 12 Sep dashboard/API outage, Radar 2025 year in review · GitHub availability report June 2025 · Google SRE example postmortem and postmortem culture · Distill "A gentle introduction to graph neural networks" · Anthropic "Tracing thoughts" · Google Research methane-mapping post · BCG "AGI timeline: what CEOs need to know" · McKinsey Global Institute discussion papers · Stanford AI Index 2025 · State of AI · a16z State of Crypto 2025 · Stripe annual update 2024 · Pew "How the global religious landscape changed" · NIST SP 800-207 · GOV.UK service manual and writing guidelines · Shape Up chapter 6 · Ubl, "Design Docs at Google" · Working Backwards PR/FAQ · Linear initiative and project updates · Kubernetes v1.33 release post · Increment "Reliability" · The Pudding.
Slide side: Doumont checklist (principiae.be) · Alley assertion–evidence checklist and the ASEE comprehension study · Tufte, *The Cognitive Style of PowerPoint* · Bezos on six-page memos · Sequoia "Writing a business plan" · YC "How to design a better pitch deck" · Kawasaki 10/20/30 · Slideworks and Deckary consulting-slide standards · Minto SCQA · Duarte glance test (HBR) and Slidedocs · Reynolds design tips · Healy "Making slides" · Gelman's presentations page · WCAG 2.2 contrast · Anthropic, Google DeepMind and NVIDIA launch pages.
