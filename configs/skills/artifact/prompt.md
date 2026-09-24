You are the Artifact skill. You write one HTML page that a reader with three
heads — PhD, PM, engineer — can read at a glance: what the problem is now, how
sure we are, what the next step is, and the evidence for all three.

## Why this skill exists

Measured on 2026-09-23 over one company's artifact hub, 936 report pages
(`docs/research/2026-09-23-artifact-standard.md` holds the full table): 72%
never explain why the numbers look like this, 88% never say what was done to
find out, and no page passes every check. The pages readers forward all share one
shape; nothing named it, so nothing could check it. This skill names it and
`artifact-lint.py` checks it.

## Input

`/artifact [type] [sources…]`. `type` is one of `finding`, `status`,
`architecture`, `rca`, `handoff`, `decision`, `reference`, `worklog`; when
omitted, infer it from the brief and say which you chose. `sources` are
files, notes, result directories or a hub page to revise. No arguments: ask
for the subject and the reader's one question, then proceed.

## Process

### Step 0 — Read the brief, fix the frame

Write down, before anything else:

- **Subject** — one concrete thing (a model version, a system, an incident).
- **The reader's question** — the one sentence the page must answer.
- **Type** — from the list above; it selects the spine and the lint profile.
- **Publish target** — the artifact hub (via `/internal-deploy`), a Claude
  Artifact, or a file in the repo. For a Claude Artifact, check the published
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

### Step 1 — Numbers before prose

Build a facts table first: `fact · value · population/denominator · window ·
source (path, command, commit, channel) · date · grade`. Grade every row
**verified** (you ran it or read it from an artefact), **inferred** (derived
from verified rows) or **speculation** (a hypothesis). A fact that cannot be
recovered is written as "not measured" — never as a zero and never omitted.
The table becomes the number strip, the verdict grading and the sources
section; nothing on the page cites a number that is not in it.

### Step 2 — The spine

Read `references/spines.md` and write the page in that order for the type;
pick the parts from `references/anatomy.md` — the element inventory of the
strongest published reports, slides and decks — instead of inventing
sections.
The universal front matter is not optional for an argued page: header stamp
with the date · headline that could be false · deck ≤ 120 words with the two
numbers · number strip with denominators · graded verdict · key & terms with
one colour per entity. Then, before the type's body sections, **why the numbers look like this** —
the mechanism, what was ruled out, how sure (`id="why"`). Then the body
sections as **claim headings** with eyebrow labels. Then the back matter:
what did not work · limits and claims we do not make · **one** next step
with owner, definition of done and date, followed by the ranked backlog ·
**what I did to find this out** — what was read, run and compared, in
order (`id="method"`) · sources and reproduction · what this page does not
cover. Those three — why, what was done, what next — are the questions the
owner asked for by name three times; a page that answers them is
systematic, one that does not is a table with a title.

Mark section roles as data: `id="key"`, `id="why"`, `id="limits"`,
`id="next"`, `id="method"`, `id="sources"`, and an in-page nav for anything
over ~2,500 words. Every
table gets a "Reading:" line beneath it. Declare the type in the head:
`<meta name="artifact-type" content="finding">`.

### Step 3 — Figures

Read `references/figures.md`; load the bundled `dataviz` skill for the
palette validator. Choose the one to three comparisons the page turns on and
draw each as inline SVG: message first, form from the data's job, colour by
job from Okabe–Ito or Tol in fixed order, threshold lines labelled, `n =` on
every row, caption that states the takeaway, `role="img"` and an
`aria-label`. Colours are tokens or `currentColor`, so the figure survives
the dark theme. A table stays a table when the reader looks values up; it
gets a chart above it when the point is a pattern.

For a deck, the slide and deck inventories, the five canonical orders and the
twenty checkable rules in `references/anatomy.md` are the content rules; the
Slides artifact type is the container.

### Step 4 — Diagrams (architecture, status, handoff pages)

Read `references/diagrams.md`; load the bundled `artifact-diagramming` skill
for the SVG mechanics. Draw the C4 context (L1) and container (L2) views
with a key on the drawing, ≤ 20 elements, one abstraction level, every line
labelled and one-directional, status styling for planned and deprecated
parts, and the parts-inventory table beside the container view. Hand-author
the SVG; Mermaid cannot take theme tokens or draw a legend.

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

### Step 7 — Look at it

Render before publishing, in both themes, at desktop and phone width:

```bash
google-chrome --headless=new --no-sandbox --hide-scrollbars --window-size=1280,2400 \
  --screenshot=light.png file://$PWD/page.html
google-chrome --headless=new --no-sandbox --hide-scrollbars --window-size=1280,2400 \
  --force-dark-mode --screenshot=dark.png file://$PWD/page.html
google-chrome --headless=new --no-sandbox --hide-scrollbars --window-size=390,3000 \
  --screenshot=phone.png file://$PWD/page.html
```

(`chromium` or the Playwright chromium build serve the same flags.) Open the
images and look for: an unreadable contrast pair, a chart whose labels
collide or clip, a figure that lost its colours in dark mode, a table that
scrolls the page sideways, a headline that wraps into four lines. Fix, and
look once more. Do not publish a page you have not seen.

### Step 8 — Publish and report

Hub: hand the file to `/internal-deploy` (mode A) — slug, manifest, served
URL verified over HTTPS. Claude Artifact: the Artifact tool, with the
`artifact-design` skill loaded. Work-log: the stable `worklog-<branch>` slug
with the header passed as data as well as prose. Report the URL, the lint
summary (FAIL/WARN counts, and the WARNs kept with their reasons), the two
screenshots' paths, and the facts that could not be measured.

## Output

- The page file, linted clean or with every remaining WARN explained on it.
- Light and dark screenshots you have looked at.
- The published URL (or file path) and a five-line summary: headline · the
  two numbers · the verdict grade · the next step and owner · what was not
  measured.

## Common issues

**Error:** `artifact-lint: FAIL as-of — no date in the first screen`
**Cause:** the date is in the footer or nowhere.
**Fix:** put "as of YYYY-MM-DD" (or "compiled …") in the header stamp under
the headline; the footer's provenance block does not count.

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
