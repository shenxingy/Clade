This skill guides creation of distinctive, production-grade frontend interfaces that avoid generic "AI slop" aesthetics. Implement real working code with exceptional attention to aesthetic details and creative choices.

The user provides frontend requirements: a component, page, application, or interface to build. They may include context about the purpose, audience, or technical constraints.

---

## Design System Integration

**Before making ANY visual choices**, check if `.design-system.md` exists in the project root:

```bash
# Check for design system
test -f .design-system.md && echo "FOUND" || echo "NOT FOUND"
```

**If `.design-system.md` exists:**
- Read it fully before proceeding.
- ALL color, typography, spacing, and component choices MUST use tokens from this file. Do NOT invent new values.
- Treat `[placeholder]` values as undefined — skip those tokens and apply creative freedom for those dimensions only. If ALL tokens are still `[placeholder]`, note "design system template not filled in" and proceed with full creative freedom.
- If the design system contradicts general aesthetic guidelines below, **the design system wins**.
- If only partial tokens are defined (e.g., colors but no typography), use tokens where available and apply creative freedom to the undefined dimensions.
- The "Differentiation" step changes: instead of picking any aesthetic freely, **create distinction WITHIN the system constraints** — like a chef creating a signature dish from a fixed pantry. Find the most expressive combination of the given tokens.

**If `.design-system.md` does not exist:**
- Proceed with full creative freedom (existing behavior below).

---

## Component Library Awareness

If the design system (`.design-system.md`) specifies a component library:
- **shadcn/ui** → use shadcn components (`Button`, `Card`, `Input`, etc.) instead of building from scratch
- **MUI / Material UI** → use MUI components with `sx` prop or `styled()`
- **Ant Design** → use antd components with `theme` token overrides
- **Radix UI** → use Radix primitives with custom CSS
- **Other** → import from the specified library; do not rebuild what already exists

If no component library is specified in the design system, fall back to raw HTML/CSS using the design tokens from `.design-system.md`.

If no design system exists at all, build from scratch with full creative freedom.

---

## Design Thinking

Before coding, understand the context and commit to a BOLD aesthetic direction:
- **Purpose**: What problem does this interface solve? Who uses it?
- **Tone**: Pick an extreme: brutally minimal, maximalist chaos, retro-futuristic, organic/natural, luxury/refined, playful/toy-like, editorial/magazine, brutalist/raw, art deco/geometric, soft/pastel, industrial/utilitarian, etc. There are so many flavors to choose from. Use these for inspiration but design one that is true to the aesthetic direction.
- **Constraints**: Technical requirements (framework, performance, accessibility).
- **Differentiation**: What makes this UNFORGETTABLE? What's the one thing someone will remember? *(If a design system exists, create distinction WITHIN its constraints.)*

**CRITICAL**: Choose a clear conceptual direction and execute it with precision. Bold maximalism and refined minimalism both work - the key is intentionality, not intensity.

Then implement working code (HTML/CSS/JS, React, Vue, etc.) that is:
- Production-grade and functional
- Visually striking and memorable
- Cohesive with a clear aesthetic point-of-view
- Meticulously refined in every detail

---

## Frontend Aesthetics Guidelines

Focus on:
- **Typography**: Choose fonts that are beautiful, unique, and interesting. Avoid generic fonts like Arial and Inter; opt instead for distinctive choices that elevate the frontend's aesthetics; unexpected, characterful font choices. Pair a distinctive display font with a refined body font. *(Exception: if the project's design system explicitly specifies font families, use them — the design system overrides general aesthetic rules.)*
- **Color & Theme**: Commit to a cohesive aesthetic. Use CSS variables for consistency. Dominant colors with sharp accents outperform timid, evenly-distributed palettes. *(Exception: if the project's design system defines a color palette, use those tokens exactly.)*
- **Motion**: Use animations for effects and micro-interactions. Prioritize CSS-only solutions for HTML. Use Motion library for React when available. Focus on high-impact moments: one well-orchestrated page load with staggered reveals (animation-delay) creates more delight than scattered micro-interactions. Use scroll-triggering and hover states that surprise.
- **Spatial Composition**: Unexpected layouts. Asymmetry. Overlap. Diagonal flow. Grid-breaking elements. Generous negative space OR controlled density.
- **Backgrounds & Visual Details**: Create atmosphere and depth rather than defaulting to solid colors. Add contextual effects and textures that match the overall aesthetic. Apply creative forms like gradient meshes, noise textures, geometric patterns, layered transparencies, dramatic shadows, decorative borders, custom cursors, and grain overlays.

NEVER use generic AI-generated aesthetics like overused font families (Inter, Roboto, Arial, system fonts), cliched color schemes (particularly purple gradients on white backgrounds), predictable layouts and component patterns, and cookie-cutter design that lacks context-specific character.

**Exception**: if the project's design system explicitly specifies these fonts/colors/patterns, use them — the design system overrides general aesthetic rules.

Interpret creatively and make unexpected choices that feel genuinely designed for the context. No design should be the same. Vary between light and dark themes, different fonts, different aesthetics. NEVER converge on common choices (Space Grotesk, for example) across generations.

**IMPORTANT**: Match implementation complexity to the aesthetic vision. Maximalist designs need elaborate code with extensive animations and effects. Minimalist or refined designs need restraint, precision, and careful attention to spacing, typography, and subtle details. Elegance comes from executing the vision well.

Remember: Claude is capable of extraordinary creative work. Don't hold back, show what can truly be created when thinking outside the box and committing fully to a distinctive vision.

---

## Output Requirements

**Start every response with a `## Design Decisions` section** before any code:

```markdown
## Design Decisions

- **Design system**: [Found `.design-system.md` — using tokens: <list key tokens used>] OR [No `.design-system.md` found — full creative freedom applied]
- **Component library**: [Using <library> as specified in design system] OR [No library specified — building from raw HTML/CSS] OR [N/A — no design system]
- **Aesthetic direction**: [1-sentence description of the chosen aesthetic]
- **Differentiation**: [What makes this memorable — the one thing users will remember]
- **Key token overrides**: [If design system existed: list any dimensions where partial tokens meant creative freedom was applied]
```

This section makes design reasoning transparent and verifiable.
