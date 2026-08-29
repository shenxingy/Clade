# Web Interface Adapter

Load this reference for websites, responsive/mobile web, browser extensions,
and PWAs.

## Platform contract

- Start with semantic HTML and browser behavior. Links navigate; buttons act;
  forms submit; history, selection, copy/paste, scrolling, zoom, and back/forward
  must continue to work.
- Prefer native elements before ARIA. Bind labels, preserve heading order, name
  controls, provide meaningful image alternatives, and manage focus only when
  the native order is insufficient.
- Treat keyboard and touch as first-class inputs. Never make hover the only
  route to content or action.
- Preserve expected cursor meanings: pointer for links/navigation where the
  browser convention applies, text cursor for selectable/editable text, grab
  for genuine drag, and resize cursors only for working resize affordances.
- Do not imitate macOS or Windows chrome unless the product is intentionally a
  remote/virtual representation and the imitation is necessary to the task.

## Layout and states

- Inspect every declared breakpoint and at least one narrow touch viewport and
  one wide desktop viewport. Use content-driven breakpoints when no design
  system exists.
- Support zoom, long localized text, dynamic content, empty/loading/error
  states, and realistic data density without clipping or horizontal traps.
- Keep controls at least 24 by 24 CSS pixels or satisfy the WCAG spacing
  exception; aim near 44 pixels for primary touch actions.
- Use responsive re-composition, not uniform shrinking. Preserve reading order
  between visual layout and DOM order.

## Visual checkpoint

- Prefer the existing app's dev route, Storybook/story, component explorer, or
  test fixture because it exercises real tokens and components.
- Use standalone HTML/CSS/JS when no runnable surface exists or the question is
  primarily composition, typography, density, or interaction direction.
- Make prototypes keyboard reachable, responsive, reduced-motion aware, and
  populated with realistic content. Label mocked data and nonfunctional paths.

## Verification

- Run repository types, lint, tests, and build.
- Run `design-lint html <artifact>` and read PASS, WARN, FAIL, and SKIP
  truthfully.
- Inspect the live page at every declared viewport, both appearance modes where
  supported, keyboard-only, reduced motion, zoom/text enlargement, slow/loading,
  empty, and error states.
- Check the actual accessibility tree or a screen reader for important flows;
  static markup checks are not a substitute.
- For performance-sensitive public surfaces, measure Core Web Vitals at the
  75th percentile when field data exists; use lab results only as diagnostics.
- Add title, description, canonical, Open Graph, and structured data only when
  the surface is public and crawlable.

Primary references: [HTML](https://html.spec.whatwg.org/),
[WCAG 2.2](https://www.w3.org/TR/WCAG22/),
[ARIA APG](https://www.w3.org/WAI/ARIA/apg/),
[Using ARIA](https://www.w3.org/TR/using-aria/), and
[CSS UI cursor](https://www.w3.org/TR/css-ui-4/).
