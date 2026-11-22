You are the Artifact skill. You write one HTML page that a reader with three
heads — PhD, PM, engineer — can read at a glance: what the problem is now, how
sure we are, what the next step is, what the page's owner must do or decide,
and the evidence for all of it.

## Why this skill exists

Measured on 2026-09-23 over one company's artifact hub, 936 report pages
(`docs/research/2026-09-23-artifact-standard.md` holds the full table): 72%
never explain why the numbers look like this, 88% never say what was done to
find out, and no page passes every check. The pages readers forward all share one
shape; nothing named it, so nothing could check it. This skill names it and
`artifact-lint.py` checks it.

A second measurement, on 2026-11-22: 54 recent pages on one internal artifact
hub, judged by two independent reviewers from phone and desktop screenshots.
Both passed 1 of 54. One reviewer found the owner's ask — what they must do or
decide — on the phone's first screen in 14 of 54 and below the fold or nowhere
in 27. Bylines, version notes, contents bars, goals and number tiles sat where
the ask belonged. So every argued page and work-log now leads with it, and the
lint's `lead` check holds the position.

## Input

`/artifact [type] [sources…]`. `type` is one of `finding`, `status`,
`architecture`, `rca`, `handoff`, `decision`, `reference`, `worklog`; when
omitted, infer it from the brief and say which you chose. `sources` are
files, notes, result directories or a hub page to revise. No arguments: ask
for the subject and the reader's one question, then proceed.

## Process

### Step 0 — Read the brief, fix the frame

Read the routing table in `references/spines.md` and the acceptance contract
in `references/review.md` before drafting. Subject alone does not select a
format: the same model can need a finding, decision or status page. State the
primary reader's assumed knowledge and the answers they must leave with.

Write down, before anything else:

- **Subject** — one concrete thing (a model version, a system, an incident).
- **The reader's question** — the one sentence the page must answer.
- **Type** — from the list above; it selects the spine and the lint profile.
- **Publish target** — the artifact hub (via `/internal-deploy`), a Claude
  Artifact, or a file in the repo. Use the following hosted Artifact types only
  if that tool is available in this runtime. For a Claude Artifact, check the published
  Artifact types first (`Artifact` tool, `action: "list_types"`): a deck goes
  to the **Slides** type (16:9, its own layout/diagram/font references) and a
  document people will edit together to the **Docs** type; a design mock-up
  to **Design**; only a single-page report is a hand-built HTML page. The
  spine, figure and colour rules below apply to all of them; what changes is
  the container.
- **Design system** — search before styling: the project's `DESIGN_SYSTEM.md`
  or tokens file, the organisation's design-system repository or hub page,
  the operator's private machine map. Apply it; never invent a per-page
  visual identity. If nothing resolves, use the token pattern in
  `references/figures.md` and say so on the page.

### Step 1 — Evidence before prose

Build an evidence table first: `claim · observation/value · population
(if quantitative) · window · source (path, command, commit, channel) · date
· grade`. Grade every row
**verified** (you ran it or read it from an artefact), **inferred** (derived
from verified rows) or **speculation** (a hypothesis). A fact that cannot be
recovered is written as "not measured" — never as a zero and never omitted.
The table supplies the verdict and sources, and a number strip only when the
reader's question is quantitative. Qualitative observations belong here too;
nothing on the page cites a number that is not in it.

### Step 2 — The spine

Read the selected spine in `references/spines.md`; use its questions to order
the page. Pick the parts from `references/anatomy.md` — the element inventory of the
strongest published reports, slides and decks — instead of inventing
sections.

An argued page opens with the **lead**. Above it sit only a one-line eyebrow,
the headline (which may carry the verdict and the ask itself) and one short
as-of line. The lead is the first block under them:

```html
<section id="bottom-line">
  <p><strong>Bottom line:</strong> the verdict or answer, one or two sentences.</p>
  <p><strong>Needs you:</strong> each action or decision the owner must take, by 2026-11-25.</p>
  <!-- or: <p><strong>Needs you:</strong> Nothing needed from you.</p> -->
</section>
```

Chinese pages use `结论：` and `需要你：` (or `不需要你做什么。`). Add a blocker
line only when the owner must know it now. Everything else goes below the
lead: bylines and provenance ("drafted by …", "prepared for …"), version notes
and corrections, contents bars, terms and keys, goals, methods, timelines and
number tiles; provenance and version history go to the foot of the page. Then
follow the front matter in `spines.md` (deck, key evidence, graded verdict,
key & terms), combining short sections where helpful. Quantitative claims
need denominators; a qualitative decision needs its trade-off, not a
manufactured number strip.
Define unfamiliar terms at first use, and keep colour meanings consistent.
Then answer **why this is the current state / why the numbers look like this** —
the mechanism, what was ruled out, how sure (`id="why"`). Then the body
sections as **claim headings** with eyebrow labels. Then the back matter:
what did not work · limits and claims we do not make · **one** next step
with owner, definition of done and date, followed by the ranked backlog ·
**what I did to find this out** — what was read, run and compared, in
order (`id="method"`) · sources and reproduction · what this page does not
cover. Those three — why, what was done, what next — are the questions the
owner asked for by name three times; a page that answers them is
systematic, one that does not is a table with a title.

Run the meaning edit in `references/review.md` before styling: the headline,
summary, captions and body must agree, and an unfamiliar reader must not need
the originating conversation to interpret them.

Mark section roles as data: `id="bottom-line"`, `id="key"`, `id="why"`,
`id="limits"`, `id="next"`, `id="method"`, `id="sources"`, and an in-page nav
for anything over ~2,500 words (below the lead, never above it). Every table
gets a "Reading:" line beneath it. Declare the type in the head:
`<meta name="artifact-type" content="finding">`.

### Step 3 — Figures

Read `references/figures.md`; if the bundled `dataviz` skill is available,
use its palette validator; otherwise measure the actual foreground/background
pairs with an available contrast tool and record the result. Choose only the
comparisons that clarify the reader's question;
zero figures is valid when prose or a lookup table answers it better — unless
the brief names a figure type ("flow chart", "structure diagram", "timeline"):
then draw that figure, and if you think another form reads better, argue it on
the page beside the figure instead of substituting a table. For
charts, prefer inline SVG: message first, form from the data's job, colour by
job from Okabe–Ito or Tol in fixed order, threshold lines labelled, `n =` on
every row, caption that states the takeaway, `role="img"` and an
`aria-label`. Colours are tokens or `currentColor`, so the figure survives
the dark theme. A table stays a table when the reader looks values up; it
gets a chart above it when the point is a pattern.

For a deck, the slide and deck inventories, the five canonical orders and the
twenty checkable rules in `references/anatomy.md` are the content rules; the
Slides artifact type is the container.

### Step 4 — Diagrams (when relationships explain the answer)

Read `references/diagrams.md`; load the bundled `artifact-diagramming` skill
for the SVG mechanics when available; otherwise use `references/diagrams.md`
directly. Architecture pages usually need C4 context (L1) and container (L2)
views. A status or handoff page needs them only when system relationships
answer the reader's question; a progress/gap table or task flow may fit better.
Use a key, one abstraction level and labelled directional relationships.
Prefer inline SVG for controlled layout and theme tokens. If another renderer
fits, inspect its exported output in the target container and both themes.

### Step 5 — Build

Head standard first: `<!doctype html>`, `<meta charset>`, `<meta
name="viewport">`, then `<title>` as a name (not a summary). Tokens in
`:root`, the dark redefinitions under `@media (prefers-color-scheme: dark)`
guarded with `:root:not([data-theme="light"])` and again under
`:root[data-theme="dark"]`. No CDN scripts, stylesheets or fonts — the
intranet has none; inline the CSS and the SVG, and give every font a local
fallback stack. `body` paints its own background. Everything readable is
visible at rest with JavaScript off. Wide tables scroll in their own
container.

### Step 6 — Lint

```bash
python3 ~/.claude/scripts/artifact-lint.py <page.html>            # inside this repo: configs/scripts/artifact-lint.py
python3 ~/.claude/scripts/artifact-lint.py <page.html> --strict   # WARN also fails
```

Every FAIL is fixed. Every WARN is fixed or its reason is written on the page
(in the sources or limits section) — a lint you silence in your head is a
rule nobody else can see. For a page that will be judged on its design, also
run `python3 ~/.claude/scripts/design-lint.py html <page.html>` for the
contrast pairs and type-size floors.

### Step 7 — Render, read, repair, repeat

Execute `references/review.md`: inspect the first screen, full page and every
figure in all four theme/viewport combinations. From the phone first screen
alone, answer *what must the owner do or decide?* — if that screen cannot
answer it, the page is NEEDS_REVISION whatever the lint says. Then check
relevant interaction, JavaScript-off and enlargement states. Verify actual
theme activation and computed paint when an image disappears. A captured
screenshot is not a pass.

Perform the fresh-reader review against the acceptance answers, without
supplying those answers to the reviewer. Fix misunderstandings and visual
failures on the page, then render and review the affected areas again. Save
`artifact-review.md` with the exact revision, evidence, defects, repairs and
PASS / NEEDS_REVISION / UNVERIFIED verdict. Required checks that cannot run
leave an unverified draft; they do not become silent skips.

### Step 8 — Publish and report

Use the available authorized publisher. The named skills/tools below are
conditional on installation; do not invent a tool or silently assume publishing
succeeded. If publishing is required but unavailable, preserve the reviewed
file and report the missing delivery capability.

Hub: hand the file to `/internal-deploy` (mode A) — slug, manifest, served
URL verified over HTTPS. Open the served page in its actual wrapper and repeat
the first-screen, figure, theme and essential-control checks; publishing may
change rendering even when the local file passed. Claude Artifact: the
Artifact tool, with the
`artifact-design` skill loaded. Work-log: the stable `worklog-<branch>` slug
with the header passed as data as well as prose, in the order Human TODO ·
Blockers · Now · Goal (same labels as the older Goal-first order, so readers
that find sections by label keep working). Report the URL, the lint
summary (FAIL/WARN counts and retained reasons), the review verdict and evidence
paths, and the facts or checks that could not be established.

## Output

- The page file, linted clean or with every remaining WARN explained on it.
- The complete applicable render matrix, inspected, and `artifact-review.md`.
- The published URL (or file path) and a six-line summary: headline · what
  the owner must do or decide (or "nothing needed") · the key evidence · the
  verdict grade · the next step and owner · what was not measured.

## Common issues

**Error:** `artifact-lint: FAIL as-of — no date in the first screen`
**Cause:** the date is in the footer or nowhere.
**Fix:** put "as of YYYY-MM-DD" (or "compiled …") in one short as-of line
under the headline; the footer's provenance block does not count as the date.

**Error:** `FAIL lead — the lead … is at: 150 units below the headline` (or `none`)
**Cause:** a byline, version note, contents bar, goal, method or row of number
tiles sits between the headline and the bottom line — or there is no lead.
**Fix:** put `<section id="bottom-line">` (Bottom line + Needs you) directly
under the headline and the as-of line; move the rest below it, and provenance
and version notes to the foot. The finding quotes what is in the way.

**Error:** `WARN lead-ask — the lead states no ask`
**Cause:** the bottom line is there, but it does not say what the owner must do.
**Fix:** add `Needs you: <action or decision> by <date>`, or the literal
"Nothing needed from you." / 「不需要你做什么。」 — never silence.

**Error:** `FAIL lead — work-log header puts Goal before Human TODO`
**Cause:** the header still runs in the old order, Goal · Now · Human TODO · Blockers.
**Fix:** reorder it to Human TODO · Blockers · Now · Goal; keep the labels.

**Error:** `WARN headings-claim — 2/9 section headings state a finding`
**Cause:** section headings are labels ("Results", "Evidence", "Timeline").
**Fix:** move the label into an eyebrow and write the finding as the heading;
if a section genuinely has no finding, that is the finding — write it.

**Error:** `WARN key-terms` on a page whose chips and colours are consistent
**Cause:** the mapping exists in the CSS but not on the page.
**Fix:** add the key & terms section (`id="key"`) that names each entity and
metric with its denominator and shows the chip; readers cannot see your CSS.

**Error:** figures look right in light mode and vanish in dark mode
**Cause:** literal hex text and axis colours inside the SVG.
**Fix:** `currentColor` for text/axes/ticks, `var(--c1)` for series, and the
dark redefinitions under the media query; re-run the palette validator with
`--mode dark`.

**Error:** `FAIL external-refs` for a Google Fonts link
**Cause:** the page was styled for the open web.
**Fix:** inline the face as a data: URI or use the local stack; the intranet
never fetches it, so the page was already rendering the fallback.
