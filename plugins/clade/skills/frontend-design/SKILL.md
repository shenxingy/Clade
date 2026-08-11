---
name: frontend-design
description: "Create distinctive, production-grade frontend interfaces and presentation surfaces with high design quality. Detects and enforces the project's design system (.design-system.md, design-system skill repo, or DESIGN.md) — hard-rule grep checks, rendered-output validators, review checklist, decisions log; can also author a new design system (SKILL.md + DESIGN.md + assets)."
---

# Clade for Codex

This workflow runs **directly in Codex**. Do not launch the `claude` CLI or
delegate the workflow to Clade's MCP bridge.

Codex compatibility rules:

- Plugin skills are namespaced. Invoke this workflow explicitly as
  `$clade:frontend-design`; a bare `$name` does not select the installed Clade plugin.
- Read the nearest `AGENTS.md` files for repository instructions. If a project
  has only `CLAUDE.md`, treat it as legacy project guidance and read it too.
- Store new Clade working state under `.clade/` (or `~/.clade/` for personal
  state). Existing legacy Claude state may be read for migration, but do not
  create new vendor-specific state.
- A `/skill-name` reference means the corresponding Codex
  `$clade:skill-name` plugin skill, or the same workflow invoked naturally when
  explicit skill invocation is not available.
- Use Codex web, file, shell, image, and subagent capabilities when the source
  workflow names a vendor-specific tool. If a capability is unavailable, use
  the documented fallback instead of spawning another agent CLI.
- Paths such as `<plugin-root>/...` are relative to the installed Clade plugin
  containing this `SKILL.md`; resolve that root before invoking a helper.

## Canonical Clade workflow

This skill guides creation of distinctive, production-grade frontend interfaces that avoid generic "AI slop" aesthetics. Implement real working code with exceptional attention to aesthetic details and creative choices.

The user provides frontend requirements: a component, page, application, or interface to build. They may include context about the purpose, audience, or technical constraints.

---

## Design System Integration

**Before making ANY visual choices**, look for a project design system — first hit wins:

```bash
# Detection cascade
test -f .design-system.md && echo "FOUND: .design-system.md (token sheet)"
test -f design-system/SKILL.md && echo "FOUND: design-system skill repo"
test -f DESIGN.md && echo "FOUND: DESIGN.md (full spec)"
```

1. **`.design-system.md`** — token-sheet convention (this skill's original format).
2. **`design-system/SKILL.md`** — a design system packaged as a skill and dropped into the project: agent-facing rules + paste-ready assets (tokens.css, components/, brand/). Read SKILL.md fully; open the deep spec it links (usually `DESIGN.md`) only when a rule needs rationale. Use the shipped components/assets directly — never re-implement them.
3. **`DESIGN.md`** at project root — a full design spec without the skill wrapper.

**If a design system is found:**
- Read it fully before proceeding.
- ALL color, typography, spacing, and component choices MUST use tokens from it. Do NOT invent new values.
- Treat `[placeholder]` values as undefined — skip those tokens and apply creative freedom for those dimensions only. If ALL tokens are still `[placeholder]`, note "design system template not filled in" and proceed with full creative freedom.
- If the design system contradicts general aesthetic guidelines below, **the design system wins**.
- If only partial tokens are defined (e.g., colors but no typography), use tokens where available and apply creative freedom to the undefined dimensions.
- The "Differentiation" step changes: instead of picking any aesthetic freely, **create distinction WITHIN the system constraints** — like a chef creating a signature dish from a fixed pantry. Find the most expressive combination of the given tokens.

**If no design system exists:**
- Proceed with full creative freedom (existing behavior below).

### Obligations when working under a design system

- **Hard rules are law.** If the system declares HARD RULES — typically grep-able patterns ("never `rounded-*`", "no `border-*`") — grep every file you wrote for the banned patterns before finishing. Run the system's review checklist if it ships one.
- **Verify at every declared viewport.** If the system names breakpoints (e.g. 375px and 1280px), check both before claiming done — a rule that holds at desktop and breaks at mobile is a broken rule.
- **Record decisions, especially rejections.** If the spec has a Decisions Log, append significant choices with date + rationale — including experiments you tried and reverted. Record what *measurably* failed and the constraint that replaced it ("7–12pt supporting text unreadable at presentation distance → 13pt floor, 18pt median"), not just the verdict ("dark version rejected"). A measured failure becomes a reusable rule; a bare verdict only prevents one repeat.
- **Match the enforcement tier to the rule.** Grep catches banned tokens in source. Rules about *rendered output* — type size, how much of the canvas a surface covers, word count, contrast — need a validator that opens the built artifact; rules that must never regress belong in the build or CI. When a rule cannot be grepped, say so rather than letting a clean grep imply it was checked.
- **A gate that crashes is worse than no gate** — it reports nothing and reads as clean. After writing or changing a validator, run it against a known violation and confirm it actually fails.
- **Offer enforcement once.** When hard rules are grep-able and you saw (or made) a violation, suggest `/generate-hook` to turn them into a PostToolUse warn hook — checkable patterns are one command away from mechanical enforcement.

### Authoring a design system (when asked to create one)

Structure it as two layers plus assets, so it works both as agent context and human reference:

- **`SKILL.md`** (agent-facing, ≤100 lines): aesthetic in one sentence; HARD RULES stated as grep-able patterns; token summary; component pointers; a short review checklist.
- **`DESIGN.md`** (deep spec): full tokens/typography/components with rationale; adopted heuristics written as "**Principle** — statement → *how we apply it here*" (not bare principle names); a **Decisions Log** table (date | decision | rationale) that also records rejected experiments; note the biggest live tension between principles and the current design honestly.
- **Paste-ready assets** beside the docs (tokens.css, components) — ship code, don't describe it in prose.
- **A validator** whenever a hard rule targets rendered output rather than source text: a script that opens the built artifact (rendered page, PDF, slide images) and fails loudly with the offending number. Wire it into the build so the rule is enforced, not merely documented.

---

## Component Library Awareness

If the design system specifies or ships a component library:
- **Design-system skill repo with components/** → import its shipped components (Button, icons, Logo…) — never rebuild or re-render what it ships (brand marks especially: use the SVG assets, never re-render from a font)
- **shadcn/ui** → use shadcn components (`Button`, `Card`, `Input`, etc.) instead of building from scratch
- **MUI / Material UI** → use MUI components with `sx` prop or `styled()`
- **Ant Design** → use antd components with `theme` token overrides
- **Radix UI** → use Radix primitives with custom CSS
- **Other** → import from the specified library; do not rebuild what already exists

If no component library is specified in the design system, fall back to raw HTML/CSS using the design system's tokens.

If no design system exists at all, build from scratch with full creative freedom.

---

## Design Thinking

Before coding, understand the context and commit to a BOLD aesthetic direction:
- **Purpose**: What problem does this interface solve? Who uses it?
- **Tone**: Pick an extreme: brutally minimal, maximalist chaos, retro-futuristic, organic/natural, luxury/refined, playful/toy-like, editorial/magazine, brutalist/raw, art deco/geometric, soft/pastel, industrial/utilitarian, etc. There are so many flavors to choose from. Use these for inspiration but design one that is true to the aesthetic direction.
- **Constraints**: Technical requirements (framework, performance, accessibility).
- **Differentiation**: What makes this UNFORGETTABLE? What's the one thing someone will remember? *(If a design system exists, create distinction WITHIN its constraints.)*
- **Usability check**: before finalizing a layout, run it against the high-leverage usability laws — Hick's (fewer, clearer choices), Miller's (~7±2 items per group), Fitts's (large, close targets), Jakob's (innovate in look, not in where things live), Von Restorff (exactly one element stands out), Serial Position (most important items first and last). Full set: https://lawsofux.com/. Where the design knowingly violates one, name which and how you mitigate it — an acknowledged tension beats a silent one.

**CRITICAL**: Choose a clear conceptual direction and execute it with precision. Bold maximalism and refined minimalism both work - the key is intentionality, not intensity.

**Build on constrained scales, and prove the hierarchy in grayscale.** Consistency comes
from a small fixed set of spacing, type, and elevation steps, not from judging each value
by eye. Compose in grayscale first — if the layout's reading order only appears once color
arrives, the hierarchy is being carried by color alone and will collapse for a colorblind
user, in dark mode, or in print. Fix it with size, weight, and space, then add color.

Then implement working code (HTML/CSS/JS, React, Vue, etc.) that is:
- Production-grade and functional
- Visually striking and memorable
- Cohesive with a clear aesthetic point-of-view
- Meticulously refined in every detail

---

## Accessibility & Legibility Floors

These apply to **every** interface, with or without a design system. They are floors, not
targets: clear them first, then spend all the creative freedom below. A design system may
raise a floor; nothing lowers one. If a requested look cannot clear a floor, say so and
propose the nearest version that does — do not ship it silently.

- **Contrast (WCAG 2.2 AA)**: body text ≥4.5:1 against its backdrop; large text (≥24px, or ≥18.66px bold) ≥3:1; icons, input borders, and focus rings ≥3:1. *Backdrop* means the real one — text over a gradient, photo, noise texture, or blur must clear the ratio at its **worst** pixel, not its average. `design-lint html` measures statically-declared colour+background pairs; `design-lint render` heuristically estimates rendered-pixel contrast (capped at WARN, never authoritative). Gradient/photo/blur backdrops, and icon/input-border/focus-ring contrast specifically, are **[human-verified-only]**.
- **Focus is always visible**: never `outline: none` without a replacement. Focus indicators need ≥3:1 against both the component and its surroundings, with at least a 2px perimeter, and the focused element must not be obscured. `design-lint html` catches a bare `outline: none` with no `:focus`/`:focus-visible` replacement rule declared. The ≥3:1 ratio, ≥2px perimeter, and not-obscured requirements are **[human-verified-only]**.
- **Target size**: interactive targets ≥24×24 CSS px (WCAG 2.2 AA, 2.5.8); aim for ~44px on primary touch actions. **[human-verified-only]** — design-lint has no rendered hit-target-size check.
- **Motion respects preference**: wrap every animation, scroll effect, and transition in `@media (prefers-reduced-motion: no-preference)`, or neutralize them under `(reduce)`. Parallax, large-scale movement, and autoplaying loops are vestibular triggers — they need this most, and they are exactly what "surprising motion" tends to produce. `design-lint html` checks that declared animation/transition is guarded by a `prefers-reduced-motion` media query. Whether the `(reduce)` branch actually neutralizes the motion (versus just existing) is **[human-verified-only]**.
- **Body type**: ≥16px body copy, line-height ≈1.5, and a measure of 45–75 characters (~66 optimal; push line-height to 1.6–1.7 past 75). Oversized measure and 14px body are the two most common legibility failures in generated UI. `design-lint html` checks declared `font-size` against the 16px floor. Line-height and measure (characters per line) are **[human-verified-only]**.
- **Semantics before styling**: headings in real order (one `h1`, no skipped levels), `alt` on meaningful images (`alt=""` on decorative ones), labels bound to inputs, actual `<button>` elements. Screen-reader structure is part of the design, not a cleanup pass. `design-lint html` checks heading order and presence of an `alt` attribute on every `<img>` (not whether the alt text is correct, or correctly empty on decorative images). Label-to-input binding and real-`<button>`-vs-styled-`<div>` are **[human-verified-only]**.

Contrast, target size, and measure are **rendered-output** rules — a clean grep proves
nothing about them. See the enforcement tiers above.

---

## Frontend Aesthetics Guidelines

Focus on:
- **Typography**: Choose fonts that are beautiful, unique, and interesting. Avoid generic fonts like Arial and Inter; opt instead for distinctive choices that elevate the frontend's aesthetics; unexpected, characterful font choices. Pair a distinctive display font with a refined body font. *(Exception: if the project's design system explicitly specifies font families, use them — the design system overrides general aesthetic rules.)*
- **Color & Theme**: Commit to a cohesive aesthetic. Use CSS variables for consistency. Dominant colors with sharp accents outperform timid, evenly-distributed palettes. *(Exception: if the project's design system defines a color palette, use those tokens exactly.)*
- **Motion**: Use animations for effects and micro-interactions. Prioritize CSS-only solutions for HTML. Use Motion library for React when available. Focus on high-impact moments: one well-orchestrated page load with staggered reveals (animation-delay) creates more delight than scattered micro-interactions. Use scroll-triggering and hover states that surprise — **inside a `prefers-reduced-motion` guard**, always.
- **Spatial Composition**: Unexpected layouts. Asymmetry. Overlap. Diagonal flow. Grid-breaking elements. Generous negative space OR controlled density. Break the grid deliberately, from a **constrained spacing scale** — arbitrary one-off pixel values read as sloppy, not as daring.
- **Backgrounds & Visual Details**: Create atmosphere and depth rather than defaulting to solid colors. Add contextual effects and textures that match the overall aesthetic. Apply creative forms like gradient meshes, noise textures, geometric patterns, layered transparencies, dramatic shadows, decorative borders, custom cursors, and grain overlays. Every one of these sits *behind text* — check the contrast floor at the busiest pixel, and add a scrim, solid plate, or text shadow when it fails rather than dropping the effect.

NEVER use generic AI-generated aesthetics like overused font families (Inter, Roboto, Arial, system fonts), cliched color schemes (particularly purple gradients on white backgrounds), predictable layouts and component patterns, and cookie-cutter design that lacks context-specific character.

**Exception**: if the project's design system explicitly specifies these fonts/colors/patterns, use them — the design system overrides general aesthetic rules.

Interpret creatively and make unexpected choices that feel genuinely designed for the context. No design should be the same. Vary between light and dark themes, different fonts, different aesthetics. NEVER converge on common choices (Space Grotesk, for example) across generations.

**IMPORTANT**: Match implementation complexity to the aesthetic vision. Maximalist designs need elaborate code with extensive animations and effects. Minimalist or refined designs need restraint, precision, and careful attention to spacing, typography, and subtle details. Elegance comes from executing the vision well.

Remember: Codex is capable of extraordinary creative work. Don't hold back, show what can truly be created when thinking outside the box and committing fully to a distinctive vision.

---

## Presentation & Deck Surfaces

Slides, pitch decks, and anything read from across a room **invert** several rules above —
"atmosphere and depth" is precisely how a slide becomes unreadable. When the output is
presented rather than browsed:

- **One thesis per slide.** Give one claim, metric, or step the dominant visual weight; supporting proof is secondary and metadata tertiary (roughly 60/30/10). Three or more equal cards make every fact look equally important and destroy the reading order — use asymmetry, scale, and whitespace instead.
- **Highlight the decisive beat.** In a sequence, emphasize the decision/result step rather than styling every step equally. In metrics and roadmaps, enlarge the current or decisive fact and dim the rest.
- **Legibility floors outrank taste.** Audience-facing body copy ≥18pt where possible, with a hard floor around 13pt below which text is metadata only and must never carry the point. Cap words per slide (~70): a slide that has to be *read* is a slide nobody hears.
- **Heavy full-bleed surfaces are focal, not atmospheric.** A dominant dark or saturated field should mark the one thing that matters on that slide, not set the mood of the whole deck. Cap its share of the canvas (~45% outside deliberate interstitials) — past that it stops being emphasis and becomes the background.
- **Review at presentation distance**, not at 100% zoom on your own monitor: a viewer should identify the slide's point in about two seconds without reading the body copy.
- **Generate from a single content model** where possible (one source → PPTX/PDF/images/viewer) so the numeric rules above can be checked mechanically instead of eyeballed. Those checks are rendered-output rules — see the enforcement tiers above; a word count or a coverage ratio cannot be grepped out of source.

---

## SEO Requirements

Every page or layout component generated **must include** the following by default (omit only if user explicitly says "no SEO"):

```html
<!-- Required in <head> -->
<title>[Page title — unique, ≤60 chars]</title>
<meta name="description" content="[Page description — ≤160 chars]">
<meta property="og:title" content="[Same as title]">
<meta property="og:description" content="[Same as description]">
<meta property="og:image" content="[Absolute URL to OG image]">
<meta property="og:url" content="[Canonical URL]">
<link rel="canonical" href="[Canonical URL]">

<!-- For homepage/landing pages — add Organization or WebSite schema -->
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"WebSite","name":"[Site name]","url":"[URL]"}
</script>
```

- For React/Next.js: use `<Head>` or `metadata` export
- For Vue: use `useHead()` / vue-meta
- For raw HTML: inline in `<head>`
- For components that aren't full pages: skip, but note "add to parent layout"

After implementation, note: `Run /seo page <url> to audit, /seo geo <url> for AI search readiness`

---

## Output Requirements

**Start every response with a `## Design Decisions` section** before any code:

```markdown
## Design Decisions

- **Design system**: [Found <source: .design-system.md / design-system/SKILL.md / DESIGN.md> — using tokens: <list key tokens used>] OR [No design system found — full creative freedom applied]
- **Hard-rule check**: [Grepped output for banned patterns: <patterns> — clean] OR [N/A — no hard rules declared]
- **Rendered-output rules**: [Ran <validator> against the built artifact — <what it measured>] OR [Declared but unchecked: <rule> needs a rendered-artifact validator] OR [N/A — all hard rules are grep-able]
- **Measured worst contrast ratio**: [`design-lint <lane> <artifact>` worst pair: <X.XX>:1 — <PASS/WARN/FAIL/SKIP + reason>] OR [Not run: <why — e.g. no rendered artifact yet>]
- **Accessibility floors**: [Contrast <worst measured ratio> / focus visible / targets ≥24px / reduced-motion guarded / body ≥16px at 45–75ch — all clear] OR [Cleared except <floor>: <why, and the nearest conforming alternative offered>]
- **Component library**: [Using <library> as specified in design system] OR [No library specified — building from raw HTML/CSS] OR [N/A — no design system]
- **Aesthetic direction**: [1-sentence description of the chosen aesthetic]
- **Differentiation**: [What makes this memorable — the one thing users will remember]
- **Key token overrides**: [If design system existed: list any dimensions where partial tokens meant creative freedom was applied]
```

This section makes design reasoning transparent and verifiable.


---

## Completion Status

**Completion checklist — run before reporting done:**
- If the artifact is HTML/web output: run `design-lint html <artifact>` and read every finding. A `SKIP` means that check could not verify the rule statically — it is not a pass, and does not license claiming the floor is clear.
- If the artifact is a deck/PPTX: run `design-lint deck <file.pptx>` (source metrics) and, once rendered, `design-lint render <slide-images>` (pixel metrics).
- Record the worst measured contrast ratio design-lint reported in the `## Design Decisions` block (see Output Requirements above) — do not report the contrast floor as clear from an eyeballed guess.

- ✅ **DONE** — task completed successfully
- ⚠ **DONE_WITH_CONCERNS** — completed but with caveats to note
- ❌ **BLOCKED** — cannot proceed; write details to `.clade/blockers.md`
- ❓ **NEEDS_CONTEXT** — missing information; use AskUserQuestion

**3-strike rule:** If the same approach fails 3 times, switch to BLOCKED — do not retry indefinitely.

## Additional skill reference

# Frontend Design

Guides creation of distinctive, production-grade frontend interfaces that avoid generic AI aesthetics. Generates real working code with exceptional attention to design details.

## Usage

```
/frontend-design        # Start with interactive requirements gathering
```

Respects the project's design system if present — `.design-system.md` (token
sheet), `design-system/SKILL.md` (design system packaged as a skill, with
tokens/components/brand assets), or `DESIGN.md` (full spec). Enforces its hard
rules, runs its review checklist, and records decisions (including rejected
experiments) in its Decisions Log. Can also author a new design system in the
two-layer SKILL.md + DESIGN.md + assets structure.

Covers presentation surfaces (slides, decks) as well as web UI — these invert
several web aesthetic rules, so they carry their own legibility floors, one-thesis
hierarchy, and focal-surface caps, checked on the rendered artifact rather than
by grepping source.

## Delivery completion

If this workflow changes files or external state:

- Inspect the real final state before responding, including `git status` for a
  repository task.
- Never report `DONE` while task-owned changes are uncommitted. Use or continue
  `$clade:delivery` and create a repository-compliant checkpoint or preserve
  the work when committing is unavailable.
- When the user request or trusted repository policy makes publication,
  deployment, or live verification part of the task, do not silently downgrade
  the result to local-only work.
- If a required delivery transition lacks authority, credentials, a destination,
  or reachable external state, report `BLOCKED` or `NEEDS_CONTEXT` rather than
  appending a "not committed/pushed/deployed" caveat after `DONE`.
