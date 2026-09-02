# Design Direction Profiles

Load this reference for Standard and Full interface work, whenever the user asks
for a theme, style, preset, or alternate version, and whenever the visual
direction is materially undecided. For a Micro change under an established
design system, reuse the existing direction and mark the profile step `N/A`.

A profile is a compact design hypothesis, not a theme package. It makes a
direction reusable and tunable without allowing aesthetics to replace product,
platform, or verification evidence.

## 1. Write the Design Read

Before benchmarking, write one provisional sentence:

> Reading this as a [surface] for [audience], optimizing [tasks/outcome], with a
> [direction family] language because [evidence].

Confirm or revise that sentence after the benchmark. If two plausible reads
would lead to materially different products, ask exactly one clarifying
question. Otherwise state the inference and continue.

## 2. Record the profile

Use this schema in working notes and substantial handoffs:

```yaml
schema: clade.design-direction/v1
variant: V1
mode: greenfield
preset: product-quiet
family: project-design-system
composition: 2
motion: 2
density: 3
appearance: system
signature: none
source: local
overrides: []
```

- `variant` identifies the design alternative or iteration. Keep it separate
  from the schema version.
- `mode` is `greenfield`, `preserve`, `evolve`, or `reframe`.
- `preset` is a named starting point below or `custom`.
- `family` names the project design system, platform system, visual school, or
  custom direction that supplies the actual visual language.
- `appearance` is `light`, `dark`, `system`, or a justified single-mode choice.
- `signature` names at most one product-specific visual or interaction moment.
- `source` records local evidence or a pinned external source.
- `overrides` lists user-requested departures from the preset.

Keep safety, accessibility, user-data integrity, platform behavior, and the
project's design system above the profile. A profile never changes those
contracts.

## 3. Tune three axes

Treat the values as ordinal anchors, not percentages or quality scores.

| Value | Composition | Motion | Density |
|---|---|---|---|
| 1 | Conventional/native flow | Essential feedback only | Gallery-like and sparse |
| 2 | Stable grid with one focal break | Feedback plus short transitions | Relaxed product surface |
| 3 | Selective asymmetry and mixed modules | Spatial continuity and staged reveal | Typical application density |
| 4 | Narrative composition with strong variation | One signature kinetic sequence | Compact expert workflow |
| 5 | Experimental composition justified by the brief | Motion-led experience, never input-blocking | Cockpit-level information density |

Start from the closest preset. Move one step at a time unless the user asks for
a deliberate break. Do not hide an arbitrary default behind the numbers.

## 4. Choose a named starting point

| Preset | Best fit | Composition | Motion | Density | Direction cue |
|---|---|---:|---:|---:|---|
| `system-native` | Native or platform-constrained utility | 1 | 1 | 3 | Let platform components, type, navigation, and input behavior lead |
| `product-quiet` | Focused SaaS, tools, settings, and everyday product work | 2 | 2 | 3 | Crisp hierarchy, restrained elevation, one intentional accent; never a default Linear imitation |
| `editorial-story` | Portfolios, publishing, reports, and narrative pages | 4 | 2 | 2 | Let type, imagery, and reading rhythm carry the composition |
| `soft-premium` | Considered consumer, hospitality, wellness, and service brands | 3 | 2 | 2 | Quiet contrast and material detail; do not default to beige, brass, or serif |
| `industrial` | Developer tools, studios, events, and high-contrast brands | 4 | 2 | 3 | Expose structure, use hard geometry, and keep ornament functional |
| `playful` | Education, community, family, and social products | 4 | 3 | 2 | Use illustration, shape, and responsive feedback with semantic restraint |
| `kinetic-campaign` | Launches and expressive brand campaigns | 5 | 4 | 2 | Make type or imagery the subject; never block scrolling or core actions |
| `civic-trust` | Public, regulated, safety-critical, and accessibility-first work | 1 | 1 | 3 | Prefer predictability, plain language, visible state, and calm hierarchy |
| `dense-operations` | Dashboards, admin, analytics, and expert control surfaces | 2 | 1 | 5 | Optimize scanning, comparison, tables, shortcuts, and state clarity |

Use `custom` when none fits. Record all three axes explicitly and explain the
family instead of inventing a new preset name for one task.

For a brand-owned surface, choose the `family` from
`brand-differentiation.md`; use this profile only to control intensity and
density. For native work, default to `system-native` unless brand or product
evidence justifies another preset.

## 5. Adapt the studied Taste Skill directions

The aliases below are local, platform-aware adaptations of
[Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) inspected at
commit `ccbc15639c97057cbfcf32ecebc38ef716e4bb37`. They preserve provenance but
do not execute or silently synchronize the upstream prompt.

| Requested alias | Clade adaptation |
|---|---|
| `taste:minimalist-ui` | Start with `product-quiet`; lower composition or density only when the task benefits |
| `taste:high-end-visual-design` | Start with `soft-premium`; derive palette and type from the actual brand |
| `taste:industrial-brutalist-ui` | Start with `industrial`; preserve platform semantics and legibility floors |
| `taste:design-taste-frontend` | Infer a `custom` profile from the Design Read; it is a general workflow, not one theme |
| `taste:gpt-taste` | Use the chosen profile plus the strict anti-default audit below; it is a ruleset, not one theme |

Treat `image-to-code` as a checkpoint strategy rather than a theme: generate or
collect reference frames only when they reduce visual uncertainty, then verify
the implementation in the real surface.

Do not import upstream defaults for framework, animation library, font, icon
family, punctuation, or layout as universal rules. Clade deliberately keeps
those choices subordinate to the repository, target platform, brief, and
measured outcome. Audit a newer upstream commit before changing these aliases.

## 6. Handle redesign modes and variants

- `preserve`: keep information architecture, brand tokens, component language,
  and interaction model; correct defects without restyling the product.
- `evolve`: keep the recognizable system and change one axis by one step or
  introduce one new signature moment.
- `reframe`: choose a new family or move multiple axes only when the user asks
  for a redesign or evidence shows the current direction blocks the outcome.
- `greenfield`: choose from the brief and benchmark without pretending an
  existing convention must be preserved.

Never silently change URLs, navigation labels, field names, data meaning,
brand marks, or legal copy as part of a visual reframe.

When comparing variants, keep content, tasks, and platform behavior constant.
Change one family decision or at most two axes, state the hypothesis each
variant tests, and recommend one. Define `V2` as an explicit delta from `V1`,
not as an unrelated second mockup.

## 7. Run the contextual anti-default audit

Flag these patterns when they appear without a brief-backed reason:

- a centered hero followed by interchangeable cards and a generic CTA;
- decorative glass, pills, status dots, gradients, or dashboard chrome;
- fake product UI that replaces a truthful screenshot or working prototype;
- one section layout repeated until the page loses rhythm;
- a palette or type choice inferred only from an industry stereotype;
- motion that cannot name its feedback, spatial, continuity, attention, or
  progress job.

For every flag, remove it or record the product-specific reason it remains.
These are diagnostic tells, not global bans. If `composition` or `motion` is 4
or 5, require a rendered visual checkpoint before committing to the direction.

## 8. Verify the profile

Check that the implementation:

- can be traced back to the Design Read and profile without hand-waving;
- uses the named family and project tokens consistently;
- implements the requested variant delta and no accidental extra redesign;
- retains complete states, platform behavior, accessibility, and reduced
  motion;
- passes the source, rendered/interactive, and outcome evidence tiers defined
  by the main workflow.
