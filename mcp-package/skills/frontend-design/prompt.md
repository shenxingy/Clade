# Interface Design Pipeline

Create, prototype, redesign, audit, or optimize production-grade interfaces
across web, mobile, desktop, and native application surfaces. Preserve the
historical `frontend-design` entry point, but do not treat every interface as a
website.

Use evidence to decide what is best for this product. Awards reveal expressive
possibilities; platform guidance defines learned behavior; task tests and
production outcomes decide whether the result is actually better.

## Operating contract

Before making visual choices:

1. Read `references/ui-ux-benchmark.md` completely.
2. Classify the platform from the request and repository. If unclear, run
   `python3 <skill-root>/scripts/detect_interface_platform.py <project-root>`.
   Treat its result as evidence, not authority; user intent and shipped targets
   win. Ask only when the unresolved platform would materially change the work.
3. Read the matching platform reference completely:
   - browser, responsive web, or PWA: `references/platform-web.md`
   - iOS, iPadOS, macOS, UIKit, SwiftUI, or AppKit:
     `references/platform-apple.md`
   - Windows, WinUI, WPF, or Windows App SDK:
     `references/platform-windows.md`
   - Android, Material, Views, or Jetpack Compose:
     `references/platform-android.md`
   - Electron, Tauri, Flutter, React Native, or another shared-code shell:
     `references/platform-cross-platform.md`, plus every actual target platform
     reference that affects the requested work
   - slides, decks, or other projected/presented surfaces:
     `references/platform-presentation.md`
4. Detect the design system before choosing colors, type, spacing, components,
   or motion.
5. Read `references/design-direction-profiles.md` for Standard and Full work,
   whenever the user asks for a theme, preset, style, or alternate version, and
   whenever the visual direction is materially undecided. A Micro change under
   an established system may reuse the existing direction and mark this `N/A`.

For a mixed-platform product, share product logic, content, and brand tokens,
then translate platform contracts separately. Do not average incompatible
platform conventions into one lowest-common-denominator UI.

## Scope lane

Run every phase below for every UI task, but scale the evidence and artifacts to
the decision risk:

- **Micro** — a local, reversible component or style correction. Reuse existing
  product evidence; compare the platform rule and one relevant in-product or
  external pattern. Do not manufacture a research project.
- **Standard** — a component family, page, screen, or user flow. Use the official
  platform source, two direct-product flows where available, one mature design
  system, and one known failure/counterexample.
- **Full** — a new product, major redesign, unfamiliar interaction, or
  cross-platform system. Use the complete benchmark set: official platform,
  two direct competitors, an awarded reference, a mature design system, and a
  counterexample. Capture complete flows rather than hero screenshots.

State the lane and rationale. A skipped phase is not invisible: mark it `N/A`
with a concrete reason.

## Seven-phase pipeline

### 1. Lock the problem

Identify the target users, target platform(s), and three most important tasks.
Classify the request as greenfield design, optimization, or implementation of an
approved spec. Record technical constraints, input modes, accessibility needs,
locales, performance budget, and the desired outcome.

Draft the one-line `Design Read` and a `clade.design-direction/v1` profile from
`references/design-direction-profiles.md`. Treat both as hypotheses until the
benchmark confirms them. For redesigns, choose `preserve`, `evolve`, or
`reframe` explicitly; never smuggle a reframe into a request for polish.

For optimization, establish the baseline before editing: capture the current
rendered surface and important flows, list observed failures, and tie each
proposed change to task success, error recovery, comprehension, accessibility,
or a product metric. Do not translate personal taste into an unqualified
"improvement."

### 2. Build the benchmark

Use the evidence ladder and reference-set rules in
`references/ui-ux-benchmark.md`. Inspect complete states and flows: loading,
empty, error, permission, offline, undo, keyboard, touch, and destructive paths
where relevant. Separate observations from hypotheses.

Produce a compact benchmark brief containing:

- the reusable pattern and why it fits this task;
- the platform behavior that must remain native;
- the product behavior worth inventing;
- the brand expression worth making distinctive;
- rejected patterns and why they fail here.

Confirm or revise the Design Read and profile after reviewing the evidence.

### 3. Define behavior before decoration

Specify information hierarchy, navigation, content, and the shortest coherent
task path. For each interactive component, consider:

- rest, hover where available, keyboard focus, pressed, selected, disabled, and
  loading;
- success, empty, error, permission, offline, undo, and recovery states at the
  flow level;
- mouse/trackpad, keyboard, touch, stylus, assistive technology, and remote/game
  controller inputs only where the target platform supports them;
- localization expansion, dynamic type/font scaling, dark/high-contrast modes,
  and reduced motion.

Hover must never carry required information. Cursor changes must follow
platform and component semantics, not fashion. Motion must perform at least one
job: confirm feedback, explain spatial relationship, preserve continuity, guide
attention, or express progress. If removing an animation does not make the
change harder to understand, omit it.

### 4. Choose the visual checkpoint

**Brand surfaces first**: if this is a brand's own site or landing page, if
sibling products must not look related, or if "make it distinctive" is part of
the ask, load `references/brand-differentiation.md` and follow it before
choosing anything visual. It carries the standing constraints — the visual-school
pool, the four-dimension palette method, the banned default palettes and
typefaces, the signature-interaction rules, and the anti-laziness checklist.
Those constraints were being hand-typed into prompts for five months while this
skill did not contain them; the one thing not to do is design from taste and
then check the file afterwards.

Decide whether a preview reduces meaningful rework:

| Situation | Default checkpoint |
|---|---|
| Existing runnable web/app surface | Build in its real component preview, dev route, story, or sandbox |
| New browser UI or a purely visual concept | Create a small standalone HTML/CSS/JS prototype with realistic content |
| Native app with uncertain hierarchy, density, color, or type | HTML is allowed as a clearly labelled **visual hypothesis only** |
| Native interaction, window, menu, focus, touch, pointer, haptic, or accessibility behavior | Use SwiftUI/Compose/WinUI/XAML or the platform's real preview/simulator |
| Small reversible change under an established system | Implement directly and inspect the rendered result |

Prefer one recommended direction. Produce a second variant only when a real
tradeoff remains unresolved by evidence; do not generate decorative option
sprawl.

When `composition` or `motion` is 4 or 5, require a rendered checkpoint before
committing to the direction. When comparing versions, hold content, tasks, and
platform behavior constant and state the exact profile delta.

If the user asked to see the direction before implementation, make the preview
viewable, provide the local/live URL or rendered image, and stop at that
checkpoint for confirmation. Otherwise use the checkpoint as an internal
review step and continue. Never present an HTML mockup as proof of native
behavior.

### 5. Implement in the real surface

Use the existing framework, components, and repository conventions. Do not
replace a working stack merely to express an aesthetic. Match implementation
complexity to the value of the interaction.

Apply this precedence order when rules conflict:

1. safety, accessibility, and user data integrity;
2. platform input, semantic, window, and navigation contracts;
3. the project's explicit design system and shipped component library;
4. the product's task model and content;
5. brand expression and visual novelty;
6. general aesthetic guidance.

This is not a choice between native and custom. Keep the platform skeleton,
invent the product brain, and express the brand without breaking either.

### 6. Verify the implementation

Use three evidence tiers:

1. **Source/static** — types, lint, hard-rule grep, semantics, token usage.
2. **Rendered/interactive** — real viewports or native previews, screenshots,
   focus order, keyboard/touch/pointer behavior, state transitions, contrast,
   text scaling, reduced motion, overflow, and realistic data.
3. **Outcome** — representative users performing target tasks, then production
   success, completion time, errors, abandonment, support tickets, retention,
   conversion, and performance percentiles where applicable.

Run the repository's tests and the platform checks named in the selected
reference. For HTML/web output, run `design-lint html <artifact>` and inspect the
live result at every declared viewport. A clean static check does not prove a
rendered rule. For decks, run `design-lint deck` and, once rendered,
`design-lint render`.

Do not claim user testing, assistive-technology coverage, device coverage, or
production improvement unless it actually occurred. Report an unrun tier as a
named follow-up gate, not as a pass.

### 7. Compare and record

For optimization, compare before and after against the same tasks and
constraints. Record decisions, rejected experiments, remaining uncertainty,
and the next measurable signal. For a substantial or long-lived design, append
the decision to the project's design-system Decisions Log when one exists.

## Design system integration

Use the first design-system source found:

```bash
test -f .design-system.md && echo "FOUND: .design-system.md"
test -f design-system/SKILL.md && echo "FOUND: design-system/SKILL.md"
test -f DESIGN.md && echo "FOUND: DESIGN.md"
```

When one exists:

- Read it fully before visual implementation.
- Use its defined color, typography, spacing, motion, and component tokens.
  Treat `[placeholder]` as undefined and exercise freedom only there.
- Import its shipped components and brand assets; never redraw a supplied logo
  or rebuild a component primitive without a documented reason.
- Enforce grep-able hard rules against every task-owned file. Use a rendered
  validator for rules about contrast, size, coverage, hierarchy, or motion.
- Verify every declared viewport and appearance mode.
- Record significant choices and rejected experiments in its Decisions Log.

When no design system exists, define a small constrained token scale before
composing. Do not create a permanent design system unless the user asks for one
or the implementation clearly requires reusable governance.

If asked to author a design system, ship:

- `SKILL.md` no longer than 100 lines with grep-able hard rules, token summary,
  component pointers, and a review checklist;
- `DESIGN.md` with rationale, component/state specifications, principle-to-
  application statements, open tensions, and a Decisions Log;
- paste-ready tokens, components, and brand assets;
- a validator for every hard rule that targets rendered output.

## Component and aesthetic rules

- Prefer the project's component library. Use shadcn, MUI, Ant Design, Radix,
  SwiftUI/UIKit/AppKit, WinUI, Compose/Material, Flutter, or other declared
  primitives rather than rebuilding their contracts from scratch.
- Prove hierarchy in grayscale through size, weight, order, and space before
  relying on color.
- Use constrained type, spacing, radius, elevation, color, and motion scales.
- Choose a clear aesthetic direction appropriate to the product. Distinction
  should come from coherent hierarchy, content, composition, data expression,
  and a few signature moments, not effects on every control.
- A platform/system font is often the correct native choice. On expressive web
  and brand surfaces, choose typography deliberately; never reject a system
  font merely because it is common.
- Avoid generic AI styling: context-free purple gradients, interchangeable card
  grids, arbitrary glass, excessive pills, decorative dashboards, fake native
  chrome, and motion without a job.
- Do not add custom cursors, scroll hijacking, parallax, blur, grain, or texture
  unless they support the concept and survive platform, contrast, performance,
  and reduced-motion checks.

## Accessibility and legibility floors

These are floors, not aesthetic targets. A design system may raise but never
lower them.

- On web, meet WCAG 2.2 AA: body text at least 4.5:1; large text and meaningful
  non-text UI at least 3:1 against the real backdrop.
- Keep focus visible. Never remove an outline without an equally visible
  replacement, and ensure focused content is not obscured.
- Meet the target platform's minimum hit size; for web, never go below the WCAG
  24x24 CSS px minimum/spacing exception and aim near 44px for primary touch
  actions.
- Guard or neutralize animation under reduced-motion settings.
- On web, use real headings, links, buttons, labels, and image alternatives
  before ARIA. On native platforms, use real accessibility roles, names,
  values, actions, and focus order.
- Test text enlargement, localization expansion, high contrast, keyboard or
  switch access, and screen readers when relevant. Mark human/device-only checks
  truthfully.

## Presentation surfaces

For slides and decks, also follow `references/platform-presentation.md` and
invert browser assumptions:

- Give each slide one dominant thesis with roughly 60/30/10 visual hierarchy.
- Keep audience-facing body copy at least 18pt where possible, with about 13pt
  as a metadata-only floor; keep the main slide near 70 words or fewer.
- Use heavy full-bleed surfaces as focal beats, not ambient decoration.
- Review at presentation distance and validate the rendered artifact, not only
  the source.

## Public-web SEO only

Apply SEO metadata only to public, crawlable web pages. Do not add it to native
apps, internal tools, isolated components, or visual prototypes unless they are
also public pages. For an applicable page include a unique title, description,
canonical URL, Open Graph title/description/image/URL, and appropriate WebSite
or Organization structured data. Use the framework's native metadata API.

## Required handoff

Start the implementation handoff with:

```markdown
## Design Decisions

- **Scope lane**: [Micro / Standard / Full — rationale]
- **Platform**: [detected target(s), inputs, and platform reference loaded]
- **Design system**: [source and tokens/components used, or none]
- **Design direction**: [Design Read; `clade.design-direction/v1` preset,
  variant, mode, family, composition/motion/density, source, and overrides; or
  `N/A` for a Micro change that reuses an established direction]
- **Benchmark**: [reference set, reusable pattern, counterexample, rejected choice]
- **Brand differentiation** (brand surfaces only): [visual school and why; the
  four palette decisions; typeface and why; signature interaction and how it
  belongs to both school and subject; and the final test — beside a typical
  Linear or Vercel site, are these visibly two different companies?]
- **Native vs custom**: [platform skeleton / product brain / brand expression]
- **Visual checkpoint**: [real surface / HTML study / native preview / direct implementation — why]
- **State and motion**: [states covered; each motion's job or no-motion decision]
- **Verification**: [source, rendered/interactive, and outcome evidence; explicit unrun gates]
- **Measured worst contrast**: [ratio and tool/lane, or truthful reason it was not measurable]
```

Before reporting completion:

- confirm every pipeline phase is represented or marked `N/A` with a reason;
- run project tests, design-system checks, and selected platform verification;
- inspect the real rendered/native result rather than trusting source alone;
- preserve task-owned work through the repository delivery workflow;
- use `DONE_WITH_CONCERNS` when human/device/production evidence needed for the
  user's stated outcome remains unavailable.

Use `DONE`, `DONE_WITH_CONCERNS`, `BLOCKED`, or `NEEDS_CONTEXT` truthfully. After
three failures of the same approach, stop repeating it and report the blocking
condition.
