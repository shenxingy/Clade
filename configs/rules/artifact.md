---
paths: "**/artifacts/**/*.html, **/artifact/**/*.html, **/worklog*.html, **/report*/*.html, **/reports/**/*.html"
---
**Report page — a reader must get the problem, the certainty and the next step
from the first screen.** Full text: the `artifact` skill's `references/`
(`spines.md`, `figures.md`, `diagrams.md`); the mechanical half is
`python3 ~/.claude/scripts/artifact-lint.py <file>`.

- **Front matter, in order:** date stamp ("as of …") · headline that could be
  false · deck ≤ 120 words with the two numbers · number strip, each with its
  denominator and window · graded verdict (verified / inferred / speculation)
  · key & terms with one colour per entity, reused everywhere on the page.
- **Headings are claims; labels are eyebrows.** Mark roles as data:
  `id="key"`, `id="limits"`, `id="next"`, `id="sources"`.
- **Back matter:** what did not work · limits and claims we do not make ·
  ONE next step with owner and date, then the backlog · sources/reproduce ·
  what this page does not cover. Every table gets a "Reading:" line.
- **Figures:** inline SVG, tokens or `currentColor`, ≤ 8 categorical hues from
  Okabe–Ito/Tol in fixed order, bars from zero, `n =` on rows, threshold lines
  labelled, caption = takeaway, `role="img"` + `aria-label`, legible in a
  screenshot of both themes.
- **Build:** `<!doctype html>` · `<meta charset>` · `<meta name=viewport>`
  first; `<meta name="artifact-type">`; `:root` tokens + `prefers-color-scheme`
  block; no CDN script, stylesheet or font; readable with JavaScript off.
- **Before publishing:** lint clean (or each WARN's reason on the page), then
  look at a light and a dark screenshot.
