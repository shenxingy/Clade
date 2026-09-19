# Design review — the screenshot loop, the severity ladder, and Definition of Done

Load this at phase 6 for Standard and Full work, and whenever the request is
to review, audit, or 挑毛病 an existing surface.

## Why this file exists

An agent that has just built a page grades it "modern, clean, professional,
user-friendly". That sentence carries no information. The first generated
version of any page is a **structural draft**; the quality comes from the
screenshot review, the item-by-item fixes and the unification pass that follow
it. This is that review, written against the checkable rules in
`design-rules.md` so it can be run rather than felt.

## Run it as a design director, not a cheerleader

- Treat the current page as a release candidate. No praise. The words *modern,
  clean, professional, user-friendly, polished, elegant, premium* are not
  findings and do not appear in the report.
- Capture the page at **390 / 768 / 1280 / 1440** (or the project's declared
  breakpoints) and in dark mode where supported. Overlay a ruler or a grid on
  the desktop capture before judging edges — "looks aligned" at a glance is how
  64 / 72 / 60 / 76 px ships.
- Run `design-lint source <dir>` on the source tree and `design-lint html
  <artifact>` on rendered pages. Read every WARN as a question the reviewer
  must answer with a fix or a written reason; a WARN is never noise.
- For a tool UI, also run the usage pass: click through the three most
  important tasks with realistic data, keyboard only once, and note what could
  not be found, could not be reached, or was lost on refresh.

## Severity

| Level | Meaning | Examples |
|---|---|---|
| **P0** | Blocks use | Overlapping content, broken responsive layout, horizontal overflow, an unreachable or non-functional control, body text under AA contrast |
| **P1** | Wrong hierarchy | Two primary actions in one viewport, the next step is unclear, visibly misaligned edges, a key state missing (error with no recovery, empty with no action) |
| **P2** | Inconsistency | Off-grid spacing, an extra font size or weight, radius / shadow / icon drift, an incomplete hover / focus / pressed / disabled set |
| **P3** | Polish | Micro spacing, motion tuning, copy tightening |

Not done until **zero P0 and zero P1**. P2 is listed with an owner and either
fixed or justified in writing; P3 is optional.

## The twenty checks

1. Is the page's primary visual focus unambiguous?
2. Does the reader know the next action immediately?
3. Do several elements compete for attention?
4. Do all major left and right edges truly align — not nearly?
5. Is padding identical across same-tier containers?
6. Does every spacing value come from the scale?
7. Do title, body, caption and metadata form distinct tiers?
8. Are there too many sizes, line heights or weights?
9. Are button, input and select heights equal?
10. Are icon size, stroke width and visual weight consistent?
11. Are radius and shadow used with roles rather than everywhere?
12. Is there card nesting?
13. Are groups made by whitespace, or by borders standing in for it?
14. Does it still read as the AI template — gradient hero, card grid, glass,
    floating orbs?
15. Are hover, focus, pressed, disabled, loading and error all present?
16. Is any motion too slow, too plentiful, or without a job?
17. Is there layout shift on load or on a state change?
18. Does it hold at 390 / 768 / 1280 / 1440?
19. Is the keyboard path complete and the focus ring visible?
20. Is there at least one recognisable, repeated brand feature?

## The loop

```text
capture at the four widths
    ↓
list findings by P0 → P3, each with the rule it breaks and the fix
    ↓
fix in code — a review that ends in advice has not reviewed
    ↓
re-capture and re-run design-lint
    ↓
repeat until no P0 or P1 remains; record the P2 / P3 that stay
```

Say what was fixed and what was left, with the counts at the start and at the
end. Do not report the loop as complete on the first pass; a page that had no
P0 or P1 on the first capture is the exception and is reported as such.

## Definition of Done — per page

- [ ] First glance: the most important information and the primary action are
      evident.
- [ ] No random spacing and no near-alignment; every edge sits on the grid.
- [ ] One shared container and grid across every page in scope.
- [ ] Type hierarchy is clear and body copy reads comfortably at its measure.
- [ ] Accent colour is rare and always means something.
- [ ] Same-type controls share one size.
- [ ] Radius, border and shadow follow the system's few values.
- [ ] Structure is not made of cards.
- [ ] Hover, focus, pressed, disabled, loading and error are complete.
- [ ] Empty, no-result, error and permission-denied states are designed.
- [ ] Desktop, tablet and phone are re-compositions, not scales of one layout.
- [ ] Motion explains a state change; none of it is decoration.
- [ ] No visible layout shift and no input lag.
- [ ] Keyboard operation and focus order are correct.
- [ ] Copy is concrete; none of the banned marketing phrases survive.
- [ ] One or two signature visual features repeat across the pages.
- [ ] The captures placed side by side read as one product.
- [ ] With the logo removed, it is still not the generic template.

> 设计感不是"添加更多视觉效果"，而是减少随机决定，建立一套清楚、克制、可重复的规则。
>
> Design sense is not more visual effect. It is fewer arbitrary decisions and
> one clear, restrained, repeatable set of rules.
