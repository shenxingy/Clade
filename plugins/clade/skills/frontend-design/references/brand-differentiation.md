# Brand differentiation — designing against the default

Load this when the surface is a brand's own site or landing page, when several
sibling products must not look related, or whenever "make it look distinctive"
is part of the ask.

## Why it exists

This methodology was written by the owner and hand-typed into prompts fifteen
times over five months, most of it in a single 9,181-character brief, while the
skill it explicitly told Claude to call — this one — contained none of it. Every
constraint below was previously being supplied by hand on each run.

**The most useful thing here is that it has two versions and they disagree.**
The first said: follow Linear, Vercel, Stripe and Anthropic's restrained
palettes — dark grey ground, one low-saturation accent, or warm off-white with
dark text. That produced three sibling sites that looked like each other. The
second version therefore *forbids* exactly what the first recommended. Restraint
copied from a shared reference set is not restraint; it is homogeneity with good
taste. Read the ban list below as the correction to an earlier version of this
same document, not as arbitrary prohibition.

## The default you are fighting

The most-seen pattern in training data is **Modern SaaS Minimal**: near-black or
dark-grey ground, a low-saturation blue-violet accent, Inter, a bento grid, soft
shadows, subtle gradients. It is competent, it is safe, and it is why unrelated
products look like one company.

The second-most-seen is the **warm editorial default**: warm off-white ground,
ochre or terracotta accent, a serif display face, generous margins.

Neither is forbidden. Choosing either **by default, without an argument** is.
Every choice below has to be written down with its reason.

## Step 1 — Positioning before pixels

Write `BRAND.md` first. Do not open a stylesheet until it exists.

- Name, one-line positioning, and slogan
- User picture: occupation, age, situation of use, emotional state
- Differentiation: why would someone choose this over its nearest sibling?
- Brand personality in 5–8 adjectives (*serious / restrained / academic / cold*
  reads nothing like *playful / bold / rebellious / extremely online*)
- The visual school, chosen from the pool below, **with the reason**

If the user supplies none of this, infer it from the domain, the existing
content and the product, and write down what the inference rests on. "A general
AI tool" is not a positioning; it is a refusal to choose one.

## Step 2 — Choose a visual school deliberately

Twenty schools. Pick one, or mix two **with intent** — "editorial typography
with a 3D-first hero" is a mix; stacking references is not.

| School | Register |
|---|---|
| Modern SaaS Minimal | Cool, precise, technical. **The default trap** — pick only on a real argument |
| Editorial / Magazine | Large imagery, serif headlines, magazine measure |
| Brutalist Web | Coarse, high contrast, system fonts, deliberately anti-designed |
| Neo-Brutalist | Thick strokes, hard shadows, saturated clashes, geometric blocks |
| Glassmorphism / Aurora | Frosted glass, aurora gradients, bloom |
| Y2K / Cyber | Chrome, metal, pixels, glitch |
| Maximalist / Memphis | Clashing colour, stacked geometry, playful illustration |
| Swiss / International | Strict grid, neo-grotesque, heavy whitespace, red and black |
| Japanese Minimalism | Extreme whitespace, light weights, natural colour, asymmetry |
| Retro-Futurism / Synthwave | Neon, grid horizon, sunset gradient, CRT |
| Dark Luxury | True black, fine serif, gold or silver accent |
| Sci-Fi / Terminal | Monospace, scanlines, HUD, phosphor |
| Scientific / Academic | White ground, black text, figure-led, citation register |
| Playful Illustration | Hand-drawn illustration as the subject, warm, rounded |
| Documentary / Photojournalism | Full-bleed photography, minimal interface |
| Fashion Editorial | Irregular layout, unusual display faces, monochrome plus one accent |
| Gradient Mesh / Liquid | Large liquid gradients, organic form. Easy to do badly |
| 3D-First | A 3D object is the subject, not decoration |
| Typography-as-Hero | Enormous type fills the viewport; type *is* the image |
| Analog / Handmade | Paper grain, collage, handwriting, film |

Hard rule: do not repeat the school of a sibling product. When the siblings are
unknown, assume Modern SaaS Minimal is taken.

## Step 3 — Build the palette from four decisions

Choose each dimension explicitly and record the reason in `BRAND.md`.

- **A. Lightness** — dark ground (L\* < 20) / light ground (L\* > 94) / mid-tone
  (harder; needs real skill to hold together)
- **B. Temperature** — warm / cool / neutral / split (warm ground with cool
  accents or the reverse; high difficulty, high payoff)
- **C. Primary hue** — cobalt 220 · electric blue 210 · indigo 240 ·
  blue-violet-grey 250 · emerald 160 · deep green 150 · teal 180 · amber 40 ·
  terracotta 20 · crimson 0 · magenta 330. A school may justify going outside
  this: brutalist black-and-white with fluorescent green or yellow; Y2K chrome
  with electric pink; dark luxury black with gold or champagne; analog kraft
  paper with ink blue.
- **D. Accent strategy** — monochrome / complementary clash / analogous /
  triadic (hardest)

Banned as defaults, each because it was actually produced and looked derivative:

- Dark grey ground + low-saturation blue-violet + off-white text — the Linear
  knockoff
- Warm off-white + ochre + dark brown serif — the Anthropic knockoff
- Gradients with no reason
- Three or more primaries at equal weight

Deliver a full 11-step tonal scale per role colour, a semantic mapping table,
and verified contrast.

## Step 4 — Type has to differentiate too

Not everything is Inter. Choose from the register that matches the school and
say why.

- **Sans** — Inter, Geist, Söhne, GT America, Neue Haas Grotesk, ABC Diatype,
  Basis Grotesque, Founders Grotesk, Neue Montreal, Aeonik, Suisse Int'l,
  Archivo, Space Grotesk, General Sans, Satoshi, Work Sans, DM Sans
- **Serif display** — Tiempos, Instrument Serif, Fraunces, Editorial New,
  PP Editorial Old, Reckless, GT Sectra, Playfair Display, Canela, Migra,
  Signifier, Domaine Display
- **Mono** — JetBrains Mono, Geist Mono, Berkeley Mono, IBM Plex Mono,
  Space Mono, DM Mono, Commit Mono
- **Display / experimental** — Monument Extended, Druk, PP Neue Machina,
  PP Hatton, PP Right Serif, Tusker Grotesk, Clash Display
- **Handwritten / analog** — Caveat, Homemade Apple, or a drawn SVG wordmark

**Banned**: Poppins, Montserrat, Lato, Roboto, Open Sans, Nunito, Raleway,
Quicksand.

Two families at most, and only with real contrast between them.

## Step 5 — One signature interaction, matched to the school

It must serve this brand's subject, and it must belong to the chosen school. A
brutalist site does not get a glassmorphic animation; an editorial site does not
get a cyberpunk HUD. A generic particle field is not a signature.

Match the medium to the school — ASCII and character jitter for brutalist,
a black-and-white reveal mask for editorial, a wireframe mesh that orbits for
technical, single-stroke ink redrawn slowly for Japanese minimal, CRT scanlines
and VHS glitch for retro-futurism, gold leaf flaking for dark luxury, landmark
plots with readable values for scientific, torn-paper collage for analog.

Any technology is fine — SVG, Canvas 2D, Lottie, Rive, CSS, Three.js, React
Three Fiber, Babylon, OGL, raw GLSL, video with WebGL post-processing, WebGPU,
a physics engine. The earlier restriction to Framer Motion or GSAP was dropped;
those remain fine for ordinary micro-interaction, 200–400 ms, restrained.

Hard constraints, none negotiable:

- **No scroll-jacking.** The reader scrolls at their own pace; the animation
  happens alongside. No pin-and-scrub sequences.
- **Must answer the pointer** — hover, cursor position, or viewport entry. An
  autonomous loop is wallpaper.
- **Related to the subject**, not a generic demo.
- Honour `prefers-reduced-motion`.
- No first-paint cost: lazy-load, never block LCP.
- Degrade on mobile; provide a WebGL fallback.
- 60 fps desktop, 30 fps mobile.
- Never a full-bleed background animation that pushes content aside.

## Step 6 — Layout, and the template to avoid

Do not reach for hero → bento → features → testimonials → CTA → footer every
time. The school dictates the layout: editorial opens on a full image and runs
long prose with footnotes; brutalist exaggerates browser defaults; Swiss uses a
strict twelve-column grid with asymmetric whitespace; typography-as-hero gives
the first screen to one sentence; Japanese minimal gives it to one small centred
element; 3D-first hands the whole viewport to the scene with the interface
floating over it; documentary lets a photograph dominate.

Component shape follows too. A brutalist button has no rounded corners and no
gradient shadow. A Japanese-minimal surface has no aggressive hover.

## Step 7 — Voice differs as much as the visuals

Define at least five do/don't rules in `BRAND.md`. An academic brand writes in
the third person and cites; a social brand writes short first-person lines; a
professional tool writes in parameters; a luxury brand writes little and leaves
space.

## Baseline that never varies

Whatever the school:

- **Accessibility** — WCAG AA contrast verified, keyboard reachable, focus
  visible, images with alt text, decorative animation `aria-hidden`, reduced
  motion honoured
- **Performance** — Lighthouse ≥ 90 desktop and ≥ 80 mobile, LCP < 2.5 s,
  CLS < 0.1, INP < 200 ms, responsive `srcset` with AVIF or WebP, critical CSS
  inline, fonts preloaded with `font-display: swap`
- **Responsive** — mobile-first, tested at all five breakpoints, touch targets
  at least 44×44 px, motion degraded on mobile
- **Colour scheme** — light and dark where the school allows; where it does not
  (dark luxury, some brutalist variants), say so in `BRAND.md`

## Before submitting — the anti-laziness check

- [ ] Was `BRAND.md` written *before* any code?
- [ ] Is the school something other than Modern SaaS Minimal — or is there a
      real argument for it?
- [ ] Did the palette avoid dark-grey-plus-low-saturation-blue-violet?
- [ ] Did it avoid warm-off-white-plus-ochre-plus-serif?
- [ ] Is the body face something other than Inter, or is Inter argued for?
- [ ] Does the signature interaction belong to the chosen school, and to the
      subject?
- [ ] Does the layout leave the SaaS template behind?
- [ ] Does the copy's voice match the school?
- [ ] Are the accessibility and performance floors met and measured?
- [ ] **Final test**: put this beside a typical Linear or Vercel site. Can you
      tell at a glance they are two different companies? If not, start again.
