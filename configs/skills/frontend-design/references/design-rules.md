# Design rules — "design sense" decomposed into checks

Load this for every interface lane. A Micro change applies the sections the
touched component reaches; Standard and Full apply all of them.

## Why this file exists

> 不要只告诉 AI"做得高级、好看、有设计感"。要把"设计感"拆成可以执行、可以检查、
> 可以验收的规则。
>
> Do not tell the model to make it "premium, polished, designed". Decompose
> design sense into rules that can be executed, checked, and accepted.

An agent asked for 高级感 produces the AI-template site: a gradient headline,
a rounded card for every block, shadows placed at random, too many colours, and
spacing that is *almost* aligned. It executes an explicit system well and
guesses "taste" badly. So every rule below is phrased so that something can
check it — `design-lint source` (**lint**), a screenshot at the review widths
(**shot**), or a grep (**grep**). A rule none of the three could check did not
make the list; the process that turns these into a page (Style DNA, three
directions, the component lab, one representative page, the P0–P3 review) is
in the main workflow and `design-review.md`.

Provenance: an owner-supplied essay, 2026-09-19, folded in here so the next
invocation carries it instead of the owner re-typing it.

## 1. Hierarchy — one thing wins per viewport

- Within a few seconds the reader can answer: what is this, what problem does it
  solve, what matters most on this page, what do I click next. (shot)
- One viewport holds **one** primary visual focus, **one** primary action, and
  one or two secondary actions; everything else steps back. Two primary buttons
  in one viewport is a defect, not emphasis. When everything is prominent,
  nothing is. (shot)
- Three tiers, and every element belongs to exactly one:

  ```text
  tier 1   title / current task / the core number
  tier 2   explanation / filters / supporting data
  tier 3   metadata / timestamps / tags / secondary actions
  ```

- Adjacent tiers differ on at least two of size, weight, colour and spacing.
  Weight alone is not hierarchy: `font-medium text-gray-700` on every line with
  the size nudged is the failure. (shot; lint counts the weights)
- Accent colour goes only on what needs attention — the primary action, a
  state, a key figure. Never on decoration. (shot)

## 2. Skeleton — invisible lines that repeat

- One page container; every major region shares it. (grep: one max-width token)
- Elements of the same tier share the **same** left edge. `64 / 72 / 60 / 76 px`
  is the amateur tell — each is nearly right and the whole page reads loose.
  (shot: overlay a ruler on the desktop capture)
- Card padding is one value per card tier; control height is one value per
  control type — button, input and select at the same height. (lint; shot)
- Align text baselines, not only box centres; optically align icons and marks,
  not mathematically. (shot)
- Layout comes from `gap` and the grid, never from a margin invented per
  element. (lint reports the margin-to-gap ratio; it does not judge it)
- Body copy has a measure of 45–75 characters; it never spans the viewport.
  (grep: a max-width on prose containers)
- No card inside a card inside a card, and borders do not stand in for
  whitespace as the grouping device. (shot)

## 3. Spacing — rhythm from one scale

Default scale when the project declares none:

```text
4    nudge
8    tight pairs
12   inside controls
16   ordinary elements
24   small groups
32   modules
48   large modules
64   page sections
96   marketing sections
```

- Every spacing value sits on the 4-px grid, 8-px above 16. `13 / 18 / 22 / 27 /
  35 / 41` are each fine alone and together have no rhythm. (lint:
  `source.spacing.grid`)
- A value off the grid needs a written visual reason beside it; otherwise it is
  a defect. The lint names the sites, the reviewer decides. Tailwind arbitrary
  spacing (`p-[13px]`) counts as off-grid.
- Hairlines and optical nudges of 1–2 px are lines, not space; the lint
  ignores them.

## 4. Type — few sizes, real contrast between them

- One body sans; at most one more family — display, serif or mono — with real
  contrast to it. (lint: at most 2 families)
- 4–6 sizes and 3–4 weights across the whole product. (lint:
  `source.type.scale`)
- Default scale when the project declares none (size / line height, px):

  ```text
  display   56 / 60
  page      40 / 44
  section   28 / 34
  card      18 / 24
  body      16 / 25
  meta      13 / 18
  ```

- Body line height is looser than display line height, and unitless so it grows
  with the reader's text size (WCAG 2.2 SC 1.4.12). (grep)
- Labels, helper text and metadata are visibly quieter than body — never the
  same weight *and* colour. (shot)
- Headings and body differ in size, weight, colour and spacing together, not
  bold alone. (shot)

## 5. Colour, geometry, elevation

- Neutrals carry the surface; one accent with a meaning. Status colours
  (success, warning, error, info) are tokens and are used only for status.
  Literal colours belong in the token file, not in components. (lint:
  `source.color.literal`)
- Radius has at most three or four values, each with a role — for example
  container 8, button 6, tag 999. Not everything is a pill. (lint:
  `source.geometry.radius`)
- Shadow only on what actually floats: menus, modals, drag. Ordinary cards
  separate by border, background and spacing. Two or three shadow tokens. (lint:
  `source.geometry.shadow`)
- Distinction comes from one or two repeated signature features (a condensed
  headline face, mono for data, a visible hairline grid, one action colour, one
  panel motion), not from personality on all five axes at once. Borrow split:
  A's density, B's type register, C's motion speed — never one product's page
  structure. (shot: the "logo removed" test in `design-review.md`)

## 6. Motion — a job, and a duration from the table

Motion does one of four jobs: confirm an action, explain a state change, keep
spatial continuity, guide attention. A motion that names none is removed.

| Kind | Duration |
|---|---:|
| Press feedback | 80–120 ms |
| Hover / focus | 120–180 ms |
| Small state change | 160–220 ms |
| Dropdown, popover, tooltip | 150–220 ms |
| Panel expand, tab switch | 200–300 ms |
| Modal, local page transition | 240–360 ms |
| Narrative / signature sequence | 400 ms and up — sparingly, never input-blocking |

- Frequent actions are fast, large moves may be slower, exits are never slower
  than entrances, hover is never delayed, and one product uses one rhythm. (lint
  flags any duration over 400 ms; shot)
- Displacement 4–16 px. List stagger 30–60 ms per sibling, up to 80 ms on an
  expressive brand surface, and the chain stops around eight siblings. Not a
  dozen elements arriving one by one; not every scroll region animating in;
  no background drifting to no purpose. (lint: keyframe translate over 16 px,
  ambient infinite animation; shot)
- Animate `transform` and `opacity`; `filter` and `clip-path` sparingly; never
  `width`, `height`, `top`, `left`, `margin`, `padding` — they relayout — and
  never `transition: all`. (lint: `source.motion.property`)
- `prefers-reduced-motion` is honoured wherever motion exists. (lint: FAIL)
- Loading reserves its space so nothing shifts; animation never blocks input;
  focus and scroll position survive a route change. (shot)
- A signature piece — a hero intro, a scroll-driven product story, a 3D
  showcase — is the one place on a page allowed past this table. Its own
  budgets (intro 1.8–2.6 s in four beats, idle at most one micro-motion per
  8–12 s, pointer 4–12 px / 2–5°, a pinned 100vh scene over 400–500vh of
  native scroll, DPR capped at 2, no scroll-jacking) and the storyboard that
  precedes it are in `signature-motion.md`.

## 7. States — a component is not done at "default"

Every interactive component ships: default, hover, focus, pressed, selected,
disabled, loading, success, warning, error, empty. A text field additionally:
label, placeholder, helper text, error message, required mark, disabled, focus,
autofill, and long-value overflow. At flow level: empty, skeleton, error with a
recovery path, permission denied, no results, first use, long content, very
large data, very small screen. (shot: one capture per state, or the state is
unshipped)

## 8. Responsive — decisions, not scaling

Review widths when the project declares none: **390, 768, 1280, 1440**. At
each width decide explicitly what wraps, what collapses, what hides, which
actions move into a menu, how the table degrades (stacked cards, or horizontal
scroll with a pinned first column), sidebar to drawer, modal to bottom sheet,
and how image, title and body wrap. Never a desktop layout shrunk. Forbidden at
every width: horizontal overflow, clipped text, a button outside its container,
an unreachable control. (shot ×4)

## 9. Copy is design

Specific beats grand.

```text
Upload a document and receive a tampering report in under 30 seconds.   ← design
Revolutionize document security with next-generation AI.               ← noise
```

Banned unless quoting someone: revolutionize, unlock the power, transform your
business, get started today, next-generation, supercharge, seamlessly,
cutting-edge, game-changing, unleash, 赋能, 重新定义, 颠覆. (lint:
`source.copy.slop`)

## 10. Tool UI is not a marketing site, and neither is a native app

- **Marketing site**: brand register, first-screen message, scroll rhythm, one
  CTA, proof. It may be dramatic, loose and visual.
- **Tool UI**: information architecture, efficiency, visible state,
  discoverability, data density, tables / filters / search, shortcuts, undo,
  loading / error / empty, protected destructive actions, feedback speed. The
  dashboard that screenshots well and fails in use has these tells: cannot tell
  what is clickable, key actions only on hover, table too airy, filters eat the
  screen, no bulk actions, layout jumps while loading, no recovery after an
  error, delete without undo, state lost on refresh. (shot: the usage pass in
  `design-review.md`, not the static capture)
- **Native app**: title bar and window behaviour, menu bar, shortcuts, context
  menu, drag and drop, focus, full screen and multi-window, system fonts and
  controls, light / dark, reduce-motion. Never a web dashboard forced into a
  native frame — the platform references carry the detail.

## 11. Performance floors

Images sized and lazy; few font files; no first-paint jump; animation that
never stalls scroll or input; long lists virtualised; no heavy dependency for
a small effect; no above-the-fold video or 3D by default. Measured targets live
in `brand-differentiation.md` ("Baseline that never varies").
