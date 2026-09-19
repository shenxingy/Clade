---
paths: "**/*.css, **/*.scss, **/*.less, **/*.tsx, **/*.jsx, **/*.vue, **/*.svelte, **/*.astro, **/*.html"
---
**UI file — "design sense" here is a set of checkable rules, not adjectives.**
Full text: the `frontend-design` skill's `references/design-rules.md`; the
review loop and Definition of Done in `references/design-review.md` beside it.

- **Spacing from the 4-px grid** (8 above 16). `13 / 18 / 22 / 27 px` is the
  random-spacing tell; Tailwind `p-[13px]` counts; 1–2 px hairlines are lines,
  not space. Layout comes from `gap` and the grid, not a margin per element.
- **Type: at most 2 families, 4–6 sizes, 3–4 weights** across the product.
  Adjacent tiers differ on two of size / weight / colour / space — weight alone
  is not hierarchy.
- **Radius: ≤ 4 values with roles. Shadow only on what floats** (2–3 tokens);
  cards separate by border, background and space. Colours live in the token
  file, never as literals in a component.
- **Motion table**: press 80–120 · hover 120–180 · state 160–220 · popover
  150–220 · panel/tab 200–300 · modal 240–360 ms; 400+ only for one signature
  sequence. Move 4–16 px, stagger 30–60 ms, animate `transform`/`opacity` only,
  never `transition: all` or a layout property, nothing infinite outside
  loaders, and guard with `prefers-reduced-motion`.
- **One primary action per viewport.** Accent only on action, state, key data.
- **Every state ships**: hover, focus, pressed, selected, disabled, loading,
  error, empty; a field also has label, helper, error, required, autofill and
  overflow. Never remove `outline` without a `:focus-visible` replacement.
- **Copy is design**: no revolutionize / unlock the power / transform your
  business / get started today / next-generation / seamlessly / 赋能 — say what
  happens, with a number.
- Before reporting: `design-lint source <dir>` (every WARN gets a fix or a
  written reason), then captures at 390 / 768 / 1280 / 1440 and the P0–P3
  review — "modern, clean, professional" is not a finding.
