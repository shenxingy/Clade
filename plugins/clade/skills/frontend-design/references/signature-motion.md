# Signature motion — hero intros, scroll-driven product stories, and how to build them

Load this when the ask names a hero animation, a scroll-driven or "Apple-style"
product story, a 3D product showcase, kinetic typography, a motion identity —
眼前一亮 / 主视觉动效 / 标志性动效 / 滚动驱动动画 / 产品 3D 展示 — or whenever
the design-direction profile sets `motion` to 4 or 5 or names a `signature`.
The ordinary micro-interaction table stays in `design-rules.md` §6; this file
governs the one place on a page that is allowed to exceed it.

## Why this file exists

"给网站加一些酷炫动画" produces fade-in, floating blobs, gradient glow, card
tilt and a particle background — the library demo. The brief that works is the
opposite shape: **design one signature change that shows the product's
capability within two seconds, then go quiet.** And the Apple-style scroll
effect is not an animation name; its technical core is **scroll progress
driving a designed cinematic timeline**, not elements with animation attached.

Provenance: two owner-supplied essays, 2026-09-19. The timings and ranges below
are the essays' recommendations, not measured outcomes — treat them as the
starting budget and record any departure with its reason.

## 1. Name it before you build it

| What you see | What it is called |
|---|---|
| Animation progress bound to scroll position; scroll back and it reverses | **Scroll-driven / scroll-linked / scroll-scrubbed animation** |
| Scrolling tells a story chapter by chapter | **Scrollytelling** |
| The scene stays fixed on screen while the page scrolls | **Pinned / sticky scroll section** |
| A product turns, approaches, comes apart on scroll | **3D product showcase**, **360° spin / turntable**, **camera orbit**, **cinematic product reveal** |
| Plays once when the page opens | **Hero intro / cinematic reveal** |
| Breathes, drifts, turns slowly in place | **Ambient motion / idle animation** |
| Follows, tilts or scatters as the pointer approaches | **Reactive / pointer-driven motion** |
| Changes with clicks, input, or product state | **State-driven animation** |
| One shape becomes another | **Morphing** |
| Type splits, reassembles, stretches, interleaves | **Kinetic typography** |
| Liquid, particles, flow fields, light that keeps changing | **Generative / shader animation** |
| A product performs on its own: rotate, disassemble, recompose | **3D product choreography** |
| The motion is part of the brand | **Motion identity / brand motion system** |

The key word is **scrub**: at 30% of the chapter the animation sits at 30%;
scroll up and it plays backwards. Search with these when collecting
references: `signature hero animation`, `interactive hero motion`, `ambient
website animation`, `cinematic product animation`, `kinetic typography
website`, `generative shader website`, `3D product choreography`, `motion
identity design`, `scrollytelling`.

## 2. Two archetypes

### A. The scroll-scrubbed product story

- Pin a 100vh scene (`position: sticky` or ScrollTrigger `pin`); the chapter
  spans about **400–500vh** of scroll distance. Native scrolling is untouched.
- Progress-to-animation is a pure mapping: `ease: none` on the playhead tween,
  and `scrub` (0.5–0.6) is the only smoothing. Stop scrolling and it stops;
  scroll up and it reverses; fast scrolling skips through without resistance.
- Write the choreography as segments before touching code. An example chapter:

  ```text
  0–15%    product emerges from dark; opacity 0→1; slight scale up
  15–35%   turns left; camera moves in; copy A leaves
  35–55%   side profile; highlight sweeps the metal edge; copy B enters
  55–75%   back; camera closes on the camera module; copy C enters
  75–90%   module disassembles; lens and sensor spread out
  90–100%  everything recomposes; front view; CTA appears
  ```

- What reads as premium is not "the phone turned" but when it starts turning,
  how fast, whether the camera moves at the same time, whether the highlight
  travels, when the copy appears, whether text ever covers the product, and
  whether each move leads into the next.
- **Six layers move together**: the product (rotation, position, scale,
  disassembly), the camera (orbit, dolly, focal length, look-at), the light
  (position, intensity, HDRI rotation, roughness — a highlight that never
  moves reads as plastic), the copy timeline, mask and depth (emerge from
  dark, pass in front of text, blur the background, circular reveal), and page
  state (background colour, nav colour, progress, the CTA at the end). Rotating
  a model alone reads as a product viewer.
- Copy rhythm: product moves → composition clears a space → copy enters → the
  reader has time → copy leaves → next shot. Never everything flying at once;
  copy never competes with the product.

### B. The hero intro → idle → reactive

- **Intro**: plays once on load, no scroll dependency, **1.8–2.6 s** total,
  four beats that never overlap into "everything at once":

  ```text
  0–300 ms      stable — the reader sees the subject first
  300–600 ms    foreshadow — a small retreat that says something is coming
  600–1400 ms   the change — disassemble, morph, pass-through, flip, material shift
  1400–1900 ms  recompose — headline lands
  after         still, in the final composition
  ```

- **Signature moment**: one unexpected but logically continuous change. The
  magic is that the reader assumed two different things and finds they were one
  continuous object — or a familiar thing changes in a way nobody predicted and
  everybody accepts afterwards.
- **Idle**: at most **one** micro-motion every **8–12 s**; otherwise still.
  Stillness is part of the piece. Constant drifting, glowing and turning numbs
  the reader and blocks reading.
- **Reactive** (desktop only): pointer response of **4–12 px** and **2–5°**,
  depth layers under **30 px**, a soft but quick spring or inertia back to
  rest. Bigger reads as a game menu or a cheap 3D card. Mobile has no hover:
  the intro plays, and tap gives feedback.
- The formula behind all of it: **stable → foreshadow → surprise → climax →
  settle → quiet**.

## 3. Semantic motion — the story is the product

Do not put an unrelated phone, orb or gradient in the hero. The motion has to
show what the product does, so that with the copy removed a stranger could
still say what it is, and a competitor could not paste it onto their site.

Worked example for a detection / authenticity product:

```text
open      a document rises off the plane; a highlight sweeps its surface; the title starts
change    the document splits into four layers, offset a few millimetres in depth:
          raw pixels · text · compression traces · metadata
detect    a scan light passes; normal regions stay put, suspicious regions shift,
          tampered regions show hairline red cracks, related evidence links up with fine lines
resolve   the layers snap back together; the document shrinks; the risk score forms
          beside it; the CTA appears
idle      a scan line every so often; the grid breathes; one suspicious region blinks
          once; the pointer near a region gets a magnifier-style pixel refraction
```

It is cool, it explains the product in two seconds, it cannot be copied, and it
becomes the motion identity. Put it beside "a 3D sphere and a gradient halo"
and the difference is the whole argument.

## 4. Choose the route by the shot, not by the technology

Four ways to get "a phone that turns", from cheapest to most demanding:

| Route | What it really is | Fits | Does not fit |
|---|---|---|---|
| **CSS 3D transform** (2.5D tilt) | One transparent PNG under `perspective()` + `rotateX/Y/Z`, `scale`, `translate`, `opacity` | Slight tilt and zoom; small budget; a quick "Apple flavour" | Turning to the back, an orbiting camera, real reflections, disassembly |
| **Pre-rendered frame sequence + canvas** | 120–300 frames rendered offline (Blender / C4D / Maya), `drawImage` of frame `round(progress × (n−1))` | Fixed shots at studio quality: ray-traced light, metal, glass, depth of field, disassembly; identical on every device | Free rotation by the user; changing the shot means re-rendering |
| **Scrubbed video** | `video.currentTime = progress × duration` | Smooth long shots, autoplay | Precise frame control (seek latency, keyframe interval), alpha, mobile stutter under fast scrubbing |
| **Real-time WebGL** (Three.js / React Three Fiber, glTF) | The browser loads the model; scroll drives `rotation`, `position`, `camera`, `light`, `material` | A configurator: rotate, recolour, click parts, reuse the model | Anything where a slightly-off model, material or light would read as a game asset; hot, dropping phones |

| Need | Route |
|---|---|
| Slight tilt and zoom | CSS 3D |
| Fixed shot, maximum quality | frame sequence + canvas |
| Continuous cinematic shot, autoplay | video |
| Scroll-controlled fixed shot | frame sequence first, video second |
| The user rotates freely / changes colour or material | real-time 3D |
| Disassembly with parts flying | frame sequence or real-time 3D |
| No 3D specialist on hand | CSS, or a bought model rendered to frames |
| The safest route for a coding agent | frame sequence + GSAP |

**Default for a marketing site: frame sequence + canvas + GSAP ScrollTrigger,
about 80% of the time.** Choose real-time 3D only when the user genuinely has to
control the product. Do not use WebGL in order to have used WebGL; if DOM, SVG
and a mask can do it, the 3D layer is cost without value.

```text
Blender / Cinema 4D → WebP/AVIF frames → <canvas> → GSAP ScrollTrigger (scrub + pin + copy timeline)
```

Technology by goal, for everything that is not a rendered product:

| Goal | Use |
|---|---|
| Split text, card changes, masks, path animation | GSAP + SVG + CSS (MorphSVG, DrawSVG, MotionPath, SplitText, Flip) |
| React hover / tap / spring / layout change | Motion |
| Vector art that reacts to product state (idle → processing → success → error) | Rive state machine |
| Real 3D with camera and light | Three.js / React Three Fiber |
| Liquid, particles, refraction, flow fields | Three.js `ShaderMaterial` + GLSL; `EffectComposer` for one post effect |
| A fixed cinematic product shot | Blender pre-render (frames or WebM/MP4) |
| Page transitions and shared elements | GSAP Flip / View Transitions |
| Small looping vector illustration, icons, logo | Lottie |
| A quick simple 3D hero without writing Three.js | Spline |

Lottie, Rive and Spline are not the tools for a photographic metal product.
A shader hero uses **one** core effect — refraction *or* particles *or* fluid
*or* glow — never all of them.

Where the work goes: the front-end is often about a hundred lines; the model,
material, HDRI, focal length, edge aliasing, screen legibility and mobile
performance take the other ninety percent. An agent cannot conjure those from
"make it like Apple"; §6 lists what it needs handed to it.

## 5. Budgets and mechanics — the checkable part

**Frame sequence.** Desktop ~180 frames at ~1920 px, mobile ~90 frames at
~900 px with its own composition, WebP or AVIF. Load order: first frame →
the next ten → spaced keyframes → fill the gaps; never block on all of them.
Show the first frame or a designed poster before anything draws — never an
empty canvas. `drawImage` on a canvas sized for `devicePixelRatio` **capped at
2**; recompute on resize; no layout shift. Stop drawing when the section leaves
the viewport. Ship a static-image fallback. (lint: `source.motion.dpr`,
`source.motion.render-loop`)

**Scrubbed video.** The encoder's keyframe interval decides how scrubbing
feels; test fast back-and-forth on a phone before committing.

**Real-time 3D.** Never default to 4K textures, real-time soft shadows,
stacked transparent glass, depth of field, bloom, ambient occlusion and 2–3×
DPR at once — that stack is what drops frames. Compress the GLB and its
textures; render on demand, not every frame; pause off-screen. The picture is
driven by designed camera choreography, never by OrbitControls as the main
view.

**Never scroll-jack.** Do not intercept `wheel` or `touchmove` and decide the
page's scroll yourself, and do not pull in page-snapping libraries. The reader
scrolls at their own pace; pinning the scene is fine, hijacking the scroll is
not, and Apple's sense of control is the former. (lint:
`source.motion.scrolljack`)

**Reduced motion.** No pinned long chapter; show the designed static final
frame with the full copy; the CTA is never gated on the animation finishing.
(lint: `source.motion.reduced`)

**Always.** The intro never blocks clicks or input; stop the
`requestAnimationFrame` loop once the intro ends; low-end devices get the
simplified version; nothing shifts layout while assets load.

## 6. Storyboard before code — the handoff

Nothing is coded until this table exists. It is the deliverable the agent
produces first and the owner approves; the essay's rule is 先提供分镜和时间轴，
再开始写代码.

| Segment | Range (scroll % or ms) | Product | Camera | Light | Copy | Page state |
|---|---|---|---|---|---|---|
| 1 | | | | | | |

Inputs the agent needs handed to it, because it cannot invent them: the model
or rendered frames; the shot segments; each segment's progress range; the copy
and its order; separate desktop and mobile compositions; the performance
budget; the static fallback.

**When there are no assets yet**, say so and pick the route the situation
allows rather than faking one: a single product render or a transparent PNG
can carry the CSS 3D route; a purchased or CC0 GLB can be rendered to frames
without an artist in the loop (`blender -b scene.blend -o //frames/frame-####
-F WEBP -a` after the camera path and HDRI are set — the shot design is still
a human decision); still imagery and textures can come from the `/banana`
skill, labelled as generated; a product's own real screenshots beat any
fabricated UI. Never ship a fake product interface as if it were real, and
never substitute an unrelated object for a product the team has not modelled. The roles a real piece needs — product / creative
(what story), motion designer (shots, rhythm, transitions), 3D designer (model,
material, light, render), front-end (scroll ↔ timeline), visual designer
(type, composition, page joins). The agent fills the front-end column well:
ScrollTrigger, canvas, preloading, responsiveness, the Three.js scene, the
timeline from a storyboard, frame-drop and asset checks.

## 7. Acceptance

1. Understood at a glance.
2. With the copy removed, it still shows the product's capability.
3. There is one moment worth remembering.
4. The page is fully usable the moment the intro ends.
5. It reads as brand design, not a library demo.
6. Desktop and phone are recomposed separately.
7. Smooth on a mid- or low-end device.
8. Free of cheap glow, particle excess and purposeless floating.
9. Scrub stops with the finger and reverses on scroll-up; nothing hijacks the
   scroll.

Banned unless the school and the brief argue for it: purple-blue AI gradient
orbs; random particles; every card floating; constant glow; exaggerated 3D
tilt; random glitch; cosmos, robots and neural networks unrelated to the
product; a long-lived blur over text; an infinite strong main animation.

> 真正的新颖感，通常不是"动得更多"，而是一个熟悉的东西，以用户没预料到、
> 但事后觉得非常合理的方式发生变化。
>
> Novelty is rarely more motion. It is a familiar thing changing in a way the
> reader did not predict and, afterwards, finds entirely reasonable.
