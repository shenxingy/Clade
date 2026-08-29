# UI/UX Benchmark Contract

Read this reference for every interface task. Use it to decide what evidence is
relevant; do not turn awards, popularity, or personal taste into a universal
ranking.

## Contents

1. Evidence ladder
2. Reference set
3. Native versus custom
4. Interaction state contract
5. Cursor and pointer semantics
6. Motion contract
7. Outcome comparison

## 1. Evidence ladder

Ask these questions in order:

1. **Does it improve the product's real outcome?** Prefer task success,
   completion time, error/recovery, abandonment, support burden, retention,
   conversion, and performance percentiles.
2. **Can representative users complete the task?** Observe complete flows and
   failure recovery; do not ask only whether users like the look.
3. **Does it honor the platform contract?** Platform guidance defines learned
   behavior for navigation, input, semantics, focus, windows, motion, and
   accessibility.
4. **Does it clear engineering and inclusion floors?** Test semantics,
   contrast, focus, target size, text scaling, reduced motion, assistive
   technology, responsiveness, and performance.
5. **Does it offer a useful expressive idea?** Awards and curated showcases are
   valuable for visual language, storytelling, and interaction possibilities,
   not proof of usability or product fit.

There is no context-free "world number one" interface. Define the target user,
platform, task, and success measure before comparing candidates.

## 2. Reference set

For a full benchmark collect:

- one official target-platform source;
- two direct competitors performing the same task;
- one awarded or editorially curated product for expressive range;
- one mature design system for component/state discipline;
- one counterexample or observed failure pattern.

Capture the full task, not just a hero screen. Include loading, empty, error,
permission, offline, destructive, undo, keyboard, touch, and accessibility
states where applicable. Record observations separately from inferences.

Useful discovery sources:

- Expression and awards: [Awwwards](https://www.awwwards.com/),
  [FWA](https://thefwa.com/),
  [Webby judging criteria](https://www.webbyawards.com/judging-criteria/),
  [UX Design Awards](https://ux-design-awards.com/jury/judging-criteria),
  [Apple Design Awards](https://developer.apple.com/design/awards/), and
  Microsoft Store Awards.
- Product flows: [Mobbin](https://mobbin.com/),
  [Pageflows](https://pageflows.com/),
  [Baymard research](https://baymard.com/research/methodology), and
  [Nielsen Norman heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/).
- Mature systems: [Adobe Spectrum](https://spectrum.adobe.com/),
  [IBM Carbon](https://carbondesignsystem.com/), and
  [GitHub Primer](https://primer.style/).
- Web quality: [WCAG 2.2](https://www.w3.org/TR/WCAG22/),
  [ARIA APG](https://www.w3.org/WAI/ARIA/apg/), and
  [Core Web Vitals](https://web.dev/articles/defining-core-web-vitals-thresholds).

Prefer primary platform documentation for implementation decisions. Use flow
libraries and award galleries to form hypotheses, then verify those hypotheses
against this product.

## 3. Native versus custom

Divide the interface into three layers:

### Platform skeleton — keep native

- input semantics and expected pointer/touch behavior;
- focus, keyboard navigation, shortcuts, and assistive technology;
- window, menu, system navigation, selection, drag/drop, and history behavior;
- system permissions, text scaling, reduced motion, and platform appearance.

### Product brain — invent deliberately

- information architecture and the core task model;
- progressive disclosure and complexity management;
- loading, empty, error, undo, batch, offline, and uncertain/AI states;
- product-specific commands, shortcuts, and recovery.

### Brand expression — make memorable

- color, typography, layout density, imagery, illustration, data expression,
  sound, haptics, and a few signature motion moments;
- never use brand styling to erase the platform skeleton or product clarity.

Rule of thumb: the closer a decision is to input, accessibility, windows, and
system behavior, the more native it should remain. The closer it is to the
product's unique task and value, the more room there is to invent.

## 4. Interaction state contract

For every interactive component evaluate:

- rest;
- hover only where a hover-capable input exists;
- focus;
- pressed/active;
- selected or checked when state persists;
- disabled only when necessary and with an explanation where useful;
- loading without layout shift or duplicate submission;
- success and error result.

At the flow level evaluate first use, populated, empty, slow, offline,
permission denied, partial failure, destructive confirmation, undo, and resumed
work. Do not encode a state only through color or animation.

## 5. Cursor and pointer semantics

- A cursor supplements affordance; shape, copy, placement, semantics, focus,
  and feedback must make the action discoverable without it.
- Touch has no hover. Never hide required information behind hover.
- Use the platform's standard pointer for ordinary controls. A native macOS
  action button retaining the arrow cursor is normal; it is not evidence that
  the control is inactive.
- On the web, preserve browser conventions for links, text, drag, and resize.
  Do not force one cursor onto every clickable element.
- Use custom cursors only for a task-specific tool whose interaction cannot be
  communicated by a standard cursor, and retain accessible alternatives.

## 6. Motion contract

Motion must do at least one job:

1. confirm feedback;
2. explain spatial relationship;
3. preserve object continuity;
4. guide attention;
5. express progress.

Start with no animation and add the smallest motion that improves
comprehension. Keep high-frequency actions restrained, make exits no slower
than entrances, avoid layout movement on hover, and obey reduced-motion
preferences. Platform timings are reference points, not universal tokens.

## 7. Outcome comparison

For optimization, compare the same task before and after. At minimum record:

- the hypothesis;
- changed and intentionally unchanged behavior;
- observed usability/accessibility/performance evidence;
- risks and reversible fallback;
- the production or user-test signal that would confirm the change.

Automated scans are evidence, not completion. If user tests, device tests, or
production data are unavailable, name the missing gate and do not invent a
positive result.
