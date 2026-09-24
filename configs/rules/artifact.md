---
paths: "**/artifacts/**/*.html, **/artifact*/**/*.html, **/worklog*.html, **/report*/*.html, **/reports/**/*.html"
---
**Report page — a reader must get the problem, the certainty and the next step
from the first screen.** Full text: the `artifact` skill's `references/`
(`spines.md`, `figures.md`, `diagrams.md`, `review.md`); the mechanical half is
`python3 ~/.claude/scripts/artifact-lint.py <file>`.

- **Choose the reader question first:** use `spines.md` to select the type and
  container. A status page need not be an architecture diagram. Use only
  figures and numbers that answer the question; never fill a template with
  invented metrics. Define unfamiliar terms where first used.
- **Front matter for argued pages:** date stamp ("as of …") · headline that could be
  false · deck ≤ 120 words with key evidence · relevant numbers, each with its
  denominator and window · graded verdict (verified / inferred / speculation)
  · key & terms with one colour per entity, reused everywhere on the page.
- **Argued-page headings are claims; labels are eyebrows.** Reference/worklog
  headings follow their lookup/state structure. Mark applicable roles as data:
  `id="key"`, `id="why"`, `id="limits"`, `id="next"`, `id="method"`,
  `id="sources"`.
- **Why the numbers look like this** (mechanism, what was ruled out) before
  the body; **what I did to find out** (read, ran, compared, in order) before
  the sources — the two sections the owner asks for by name.
- **Back matter:** what did not work · limits and claims we do not make ·
  ONE next step with owner and date, then the backlog · what I did ·
  sources/reproduce · what this page does not cover. Every table gets a
  "Reading:" line.
- **Figures:** inline SVG, tokens or `currentColor`, ≤ 8 categorical hues from
  Okabe–Ito/Tol in fixed order, bars from zero, `n =` on rows, threshold lines
  labelled, caption = takeaway, `role="img"` + `aria-label`, legible in a
  screenshot of both themes.
- **Build:** `<!doctype html>` · `<meta charset>` · `<meta name=viewport>`
  first; `<meta name="artifact-type">`; `:root` tokens + `prefers-color-scheme`
  block; no CDN script, stylesheet or font; readable with JavaScript off.
- **Before ready/publishing:** execute `references/review.md`: lint, inspect
  light/dark × desktop/phone first screens and every figure at displayed size,
  then a fresh-reader review without the author's explanation. Fix wrong
  takeaways, invisible content, collisions and clipping; recapture after edits.
  Record the exact revision, screenshots, reader answers and verdict in
  `artifact-review.md`. Missing evidence is UNVERIFIED, never PASS. After
  authorized publishing, inspect the served URL in its actual wrapper.
