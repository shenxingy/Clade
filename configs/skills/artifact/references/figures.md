# Figures that would pass review — and survive a dark theme

A figure on a report page is held to the standard of a figure in a paper: one
message, read at first glance, colours that mean something, text that is real
text. This file is the procedure and the checkable rules; the bundled
`dataviz` skill (load it too) carries the palette validator and mark specs,
and `diagrams.md` beside this file covers architecture drawings.

## The procedure — colour comes last

1. **Write the message first.** One sentence the figure must make true at a
   glance. That sentence becomes the caption's first line and, usually, the
   figure title. If you cannot write it, you do not yet have a figure.
2. **Pick the form from the data's job.** Magnitude → bars (zero baseline).
   Change over time → lines, banked near 45°. Distribution → dots, ranges,
   histograms. Comparison of a few arms across many rows → dot-range rows
   (mean ─┤ max) with the threshold as a labelled vertical line. A single
   headline number → a stat tile, not a chart. Individual values to look up
   → a table, not a chart.
3. **Assign colour by job.** Categorical (identity) → a fixed-order palette,
   ≤ 8 hues, never cycled. Sequential (magnitude) → one hue, light to dark,
   monotonic in luminance. Diverging (polarity around a real midpoint) → two
   hues and a neutral grey middle. Status (good / warning / critical) →
   reserved tokens that are never reused for a series.
4. **Fix the colour → entity mapping for the whole document**, in the key &
   terms section, and reuse it in every chip, table cell and chart. A model
   that is purple in figure 2 is purple in figure 5.
5. **Validate, do not eyeball.** `node <dataviz>/scripts/validate_palette.js
   "<hex,hex,…>" --mode light` and again with `--mode dark` against the dark
   surface. Fix FAILs before drawing.
6. **Draw with marks that read**: thin bars with a 2 px gap, 2 px lines, ≥ 8 px
   markers, direct labels on the arms that matter, the threshold drawn and
   labelled, `n =` in every row label, grey for context and one accent for
   the point.
7. **Caption = the takeaway**, one sentence, plus how to read the marks. Exactly
   one title per figure: in the drawing *or* as the caption's first sentence.
8. **Look at it in both themes** before publishing — a screenshot each — and
   check label collisions, clipped text, contrast at the least-contrasting
   spot.

## Rules (checkable) — with the source that states them

**Message and framing**
1. Decide the single message before drawing; the reader should grasp it at
   first glance. [Rougier, rule 2]
2. Every figure has a caption that says how to read it and adds the precise
   values that matter. [Rougier, rule 4]
3. The title states the conclusion, not the topic; one title per figure, in
   the graphic or leading the caption, never both. [Wilke ch. 22]
4. Never ship a library default unedited — defaults fit any plot and optimise
   none. [Rougier, rule 5]
5. Figure 1 is the summary: input, output, what the work enables. Three to six
   figures per document; start near the raw data. [Huang; Wilke ch. 29]

**Colour**
6. Match scheme to data: qualitative for categories, sequential for ordered
   magnitude, diverging only where a meaningful midpoint exists. [Tol §1;
   ColorBrewer]
7. Hue is the least accurate quantitative channel of all — use position and
   length for anything the reader must compare. [Cleveland & McGill, in
   Wong]
8. No rainbow, no jet: spectral order carries no magnitude, the hue bands read
   as jumps, and several hues collapse under colour-vision deficiency.
   [Rougier rule 6; Wilke ch. 19; Tol §4]
9. Sequential maps are monotonic in luminance (viridis, cividis, Tol
   iridescent); test by converting to greyscale. [Wilke ch. 19; Tol §4]
10. Six to eight categorical hues is the ceiling; past that, label directly or
    facet. [Wong, *Color coding*; Wilke ch. 19]
11. Never encode with colour alone — add shape, dash, position or a direct
    label. [Okabe & Ito; Wong, *Color blindness*]
12. Vary lightness as well as hue so the set survives greyscale and print.
    [Wong, *Color coding*]
13. Small marks and thin lines need larger colour differences. [Wong]
14. Grey for the context series, one strong accent for the point; baseline
    colours must not compete. [Wilke ch. 4]
15. Red/green pairs become magenta/green or red/turquoise; ~8% of men cannot
    separate the original. [Wong, *Color blindness*]
16. If two diverging scales appear in one document, they run the same
    direction. [Tol §3]
17. Missing data gets its own grey, distinct from every scale endpoint.
    [Tol §§3–4]
18. Keep one colour→meaning mapping across every figure in the document.
    (inference — follows from 16 and from Wilke's legend-order rule; no
    primary source states it as a document-wide rule.)

**Contrast, both themes**
19. Graphical marks needed to read the figure: ≥ 3:1 against their *adjacent
    background*. Series do **not** need 3:1 against each other — a validator
    that demands it rejects Okabe–Ito. [WCAG 2.2 SC 1.4.11]
20. Figure text: ≥ 4.5:1, or ≥ 3:1 at ≥ 24 px (18.5 px bold). No rounding —
    4.499 fails. [WCAG 2.2 SC 1.4.3]
21. Re-check 19 and 20 on the **dark** surface; a palette tuned on white
    routinely fails on black. Okabe–Ito orange `#E69F00` is 2.25:1 on white —
    fine as a fill, not as text or a thin line; darken to `#B35A00` for
    those in light mode. (inference: contrast computed, not quoted)

**Alignment and layout**
22. Bars and areas start at zero on a linear axis (length encodes value); at
    one on a log axis. Lines and points need no zero. [Wilke ch. 17]
23. Panels the reader is meant to compare share axis range, scale type and
    tick positions; the same operating point is the same open circle in every
    panel. (inference from small-multiples practice)
24. Aspect ratio changes the perceived trend; bank average slopes toward 45°
    for time series. [Healy ch. 1; Heer & Agrawala]
25. Direct-label whenever possible; a legend, when unavoidable, is ordered to
    match the visual order of the data. [Wilke ch. 20]
26. Quantitative axes carry units; categorical axes need no title. [Wilke
    ch. 22]
27. Axis labels, ticks and titles always; no pie, no 3-D. [Rougier rule 7;
    Cleveland & McGill]
28. Solid filled shapes, not outlines. [Wilke ch. 25]
29. Small multiples beat one chart that carries three encodings at once.
    [Wong, *Salience*]
30. Erase non-data ink — as a direction, not a maximand: fully stripped charts
    tested harder to read. [Tufte; Healy ch. 1]
31. Print targets, when the figure will also go into a paper: 89 mm single /
    183 mm double column, sans-serif, panel labels 8 pt bold, other text 5–7
    pt, lines 0.25–1 pt at final size, vector output. [Nature artwork guide]
32. Talks and screens need larger text, thicker lines, bigger points; adapt
    to the medium. [Rougier rule 3; Doumont]

## Palettes (hex) — pick from these, in this order

**Okabe–Ito** (8, colour-vision-deficiency safe; the scientific default)
`#000000` black · `#E69F00` orange · `#56B4E9` sky blue · `#009E73` bluish
green · `#F0E442` yellow · `#0072B2` blue · `#D55E00` vermillion ·
`#CC79A7` reddish purple. Two-arm comparisons on the hub's best pages use
blue `#0072B2` against a dark grey — not two saturated hues.

**Paul Tol** (all CVD-safe; take the first *n*)
- bright (lines, labels): `#4477AA #EE6677 #228833 #CCBB44 #66CCEE #AA3377 #BBBBBB`
- high-contrast (survives greyscale): `#004488 #DDAA33 #BB5566` (+ black, white)
- muted (nine, no clear red): `#CC6677 #332288 #DDCC77 #117733 #88CCEE #882255 #44AA99 #999933 #AA4499`, bad data `#DDDDDD`
- light (filled cells with black labels): `#77AADD #EE8866 #EEDD88 #FFAABB #99DDFF #44BB99 #BBCC33 #AAAA00 #DDDDDD`

**Sequential**: viridis `#440154 → #FDE725`; cividis `#00224E → #FDE725`
(CVD-optimised); Tol YlOrBr `#FFFFE5 #FFF7BC #FEE391 #FEC44F #FB9A29 #EC7014
#CC4C02 #993404 #662506`, bad data `#888888`.

**Diverging**: Tol BuRd `#2166AC … #F7F7F7 … #B2182B`; PRGn `#762A83 … #F7F7F7
… #1B7837`; sunset `#364B9A … #EAECCC … #A50026`.

**Status** is not a series colour. If the organisation's design system defines
verdict or status tokens, those are the status palette, scoped to status
chips; the categorical hues above still carry identity. Resolve the design
system first (`prompt.md`, step 0) — never invent a page's own status colours.

## The token pattern — every colour survives the theme

```css
:root {                       /* complete light palette, always first */
  --bg:#ffffff; --ink:#0a0a0a; --muted:#55555e; --line:#d5d5dc; --surface:#f3f3f5;
  --c1:#0072b2; --c2:#d55e00; --c3:#009e73; --c4:#cc79a7;   /* categorical, fixed order */
  --grid:#e2e2e6; --highlight:#fff3c4;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg:#0f1115; --ink:#e8e8ec; --muted:#a3a3ad; --line:#2a2d35; --surface:#171a21;
    --c1:#56b4e9; --c2:#f28e4c; --c3:#3ecfa4; --c4:#e29ccb;   /* re-stepped, re-validated */
    --grid:#262932; --highlight:#3b3410;
  }
}
:root[data-theme="dark"] { /* same block again, so an explicit toggle wins */ }
body { background: var(--bg); color: var(--ink); }
```

In the SVG: `fill="currentColor"` and `stroke="currentColor"` for text, axes
and ticks; `fill="var(--c1)"` for series; `stroke="var(--grid)"` for grid
lines. The one figure allowed to carry many literal hexes is a palette swatch
whose job is to show them; mark it `data-artifact-lint="ignore-palette"` on
the `<svg>` and say so in its caption — the lint then leaves that figure out
of the palette and theme counts and nothing else. A literal hex inside a chart is the one colour that carries meaning
and has been checked on both grounds — and even that is better as a token.
Inline the SVG; an `<img src="chart.svg">` cannot see the page's tokens, so
`currentColor` resolves to nothing across that boundary. *(lint:
`svg-theme`, `svg-palette`, `color-literals`.)*

## Chart anatomy that reads — the conventions worth copying

From the pages on the hub readers found clearest:

- **Threshold lines are drawn and labelled** on the data axis ("v8 τ 0.838",
  "v9 τ 0.859"), and the region past them is tinted so "flagged" is a shape,
  not a number.
- **Row labels carry the population**: `tamper · fraud · n = 24`; the rows
  that matter are bold, context rows are muted.
- **Two arms, two marks**: a square for one model, a circle for the other,
  each with its own hue, so the pair survives greyscale and a legend is
  unnecessary — the key section already fixed the colours.
- **Tooltips as `<title>` children** on marks: the exact mean and max are one
  hover away without cluttering the drawing. (Note: an SVG `<title>` is not
  the page title; the lint keeps them apart.)
- **The same operating point is the same symbol in every panel**, so a
  precision–recall point traces to the threshold that produced it.
- **Tables under the chart**, not instead of it, with a "Reading the column"
  line and a "Highlighted: yellow = …" line.

## Table or chart

| Reader wants to… | Use |
|---|---|
| Look up individual precise values | Table (with a reading line) |
| See a pattern, trend, exception, gap | Chart |
| Compare two arms across many rows | Dot-range rows, shared axis, threshold line |
| Compare one measure across ≤ 8 categories | Sorted horizontal bars from zero |
| Read a distribution | Histogram or dots, never a bar of the mean alone |
| Both look up and compare | Chart, then the table beneath it |

## The generator's checklist

Marked *(lint)* where `artifact-lint.py` checks it; the rest is the
screenshot review.

1. Caption states the takeaway, one sentence. *(lint: `figcaption`)*
2. Exactly one title per figure.
3. Every quantitative axis carries a unit; every axis has ticks and labels.
4. Categorical palette ≤ 8 hues, fixed order, from a named CVD-safe set.
   *(lint: `svg-palette`)*
5. Every series is redundantly encoded (colour + shape/dash/label) and has a
   label reachable without the legend.
6. Legend, if any, matches the visual order.
7. Sequential data on a monotonic-luminance map; diverging only with a real
   midpoint; all diverging scales run one direction.
8. A dedicated grey for missing data.
9. Bars/areas start at 0 (linear) or 1 (log).
10. Comparable panels share range, scale and ticks.
11. Marks ≥ 3:1 and text ≥ 4.5:1 against the adjacent ground, in both themes.
12. Smallest chart text ≥ 10 px at drawn scale; ticks legible in a 1280 px
    screenshot. *(lint: `svg-text-size`)*
13. Output is inline SVG with real `<text>`, `viewBox`, no fixed width/height.
14. `role="img"` and an `aria-label` (or a leading `<title>`) on every chart.
    *(lint: `svg-aria`)*
15. Colours are tokens or `currentColor`; no hex that only works on one
    ground. *(lint: `svg-theme`)*
16. `n =` on every row or arm; the threshold drawn and labelled.
17. No more than three salience channels at once.
18. The palette survives greyscale.

## Sources

- Rougier, Droettboom & Bourne, "Ten Simple Rules for Better Figures", PLOS Comp Bio 2014 — https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1003833
- Wong, "Points of View" columns, Nature Methods 2010–2011 (Color coding; Design of data figures; Salience; Gestalt; Color blindness; Avoiding color) — collection: https://static1.squarespace.com/static/587e7412be6594f2dc02480f/t/63e0d7f70f60c8044b65b900/1675679747977/Bang_Wong_Point-of-view_collection.pdf
- Okabe & Ito, Color Universal Design — https://jfly.uni-koeln.de/color/
- Tol, "Colour Schemes", SRON/EPS/TN/09-002 v3.2 — https://sronpersonalpages.nl/~pault/data/colourschemes.pdf
- Wilke, *Fundamentals of Data Visualization* — https://clauswilke.com/dataviz/
- Healy, *Data Visualization: A Practical Introduction*, ch. 1 — https://socviz.co/01-look-at-data.html
- Cleveland & McGill, Science 229 (1985), 828–833
- Heer & Agrawala, "Multi-Scale Banking to 45 Degrees", IEEE TVCG 2006 — http://vis.stanford.edu/papers/banking
- Nuñez, Anderton & Renslow, cividis, PLOS ONE 2018 — https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0199239
- Brewer, ColorBrewer — https://colorbrewer2.org/
- Nature, Guide to Preparing Final Artwork — https://www.nature.com/documents/nature-final-artwork.pdf
- W3C WCAG 2.2, SC 1.4.11 and SC 1.4.3 — https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html · https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html
- Few, "Selecting the Right Graph for Your Message" — https://www.perceptualedge.com/articles/ie/the_right_graph.pdf
- Doumont, *Trees, Maps, and Theorems* — https://principiae.be/X0100.php
- Huang, awesome-tips (figure 1 as teaser) — https://github.com/jbhuang0604/awesome-tips
- Tufte, *The Visual Display of Quantitative Information* (1983)
