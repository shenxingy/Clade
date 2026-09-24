# Architecture and system diagrams — one legend, one level, one question

A diagram earns its place when it shows a mechanism the reader would otherwise
have to assemble from prose: where data flows, which parts talk, what changes
between two options, what is built and what is not. If a sentence says it
faster, write the sentence. Load the bundled `artifact-diagramming` skill for
the inline-SVG mechanics; this file is the notation and colour discipline.

## Which diagram for which question

| The reader is asking | Draw | Level | Max elements |
|---|---|---|---|
| What is this system and who or what touches it? | System context | C4 L1 | 8–12 |
| How is the whole estate arranged, who owns what? | System landscape | C4 landscape | 15–20 |
| What are the deployable pieces and what is each built with? | Container | C4 L2 | 12–20 |
| What is inside this one service? | Component — generate it, do not maintain it | C4 L3 | ≤ 15 |
| How does this one flow actually run? | Sequence / dynamic, numbered steps | any | 6–10 lifelines |
| Where does it run, in which environment? | Deployment | — | 12–20 |
| Where does data go and where are the trust boundaries? | Data-flow with boundary boxes | container | ≤ 15 |
| Which team owns which context and how do they integrate? | Context map | landscape | ≤ 12 |
| What is built, in progress, planned, dead? | Container diagram with status styling + an inventory table | C4 L2 | ≤ 20 |
| When does each thing land? | Now / next / later swimlane, not a Gantt | — | ≤ 12 |
| What are the exact numbers per part? | **A table**, beside the diagram | — | — |

A status page draws L1 and L2 and stops; component diagrams are for a part
under active change, and code diagrams are never drawn by hand.

## Notation rules (checkable)

1. Every diagram has a **title** naming its type and scope; nine in ten first
   drafts lack one. [Brown, C4 notation]
2. Every diagram has a **key on the drawing itself** — colours, shapes, line
   styles, arrowheads, border styles — even when obvious to the author.
   [Brown, C4 checklist]
3. Every element has a **name, a type** (person / system / container /
   component / data store) **and a one-line responsibility**. [Brown]
4. Containers and components state their **technology**; a context diagram
   deliberately does not. [Brown]
5. Every line is **one direction, one arrowhead**; two flows are two lines,
   or one line annotated request/response. [Brown; Microsoft WAF]
6. Every line is **labelled with intent**, consistent with its direction —
   never a bare "uses". Inter-container lines carry the protocol
   (HTTPS/JSON, gRPC, SQL). [Brown]
7. **One abstraction level per diagram**; a container never sits beside a
   component. [Brown]
8. **Under twenty elements**, fewer where possible; split by bounded context
   or by one service and its direct neighbours, not by squeezing. [Brown]
9. **Flow reads left to right** (or top to bottom), users where the flow
   starts, consistently across every diagram on the page. [Google Cloud
   Architecture Center]
10. **Boundaries first, icons second**: draw the group boxes (trust, deployment,
    ownership) before placing parts in them. [AWS Architecture Icons]
11. **Minimise crossings**; where unavoidable, cross near 90°. Crossings are
    the single strongest readability factor, bends second. [Purchase]
12. **Accurate over simple**: do not draw a service inside a subnet it is
    reached through a private endpoint from. [Microsoft WAF]
13. **Metadata on the figure**: last-updated date, author, version; retire a
    diagram that no longer answers an active question. [Microsoft WAF]
14. **Never rely on colour alone** — pair it with border style, shape or
    icon. [Microsoft WAF; Okabe & Ito]
15. **Hand-drawn style signals "draft"**; use it in a design review, never on
    a published status page. [Hohpe]
16. **Sequence diagrams number their interactions** and are used sparingly.
    [Brown, dynamic diagrams]

## Colour and legend discipline — the same six classes on every diagram

Five to six semantic classes is the working maximum for one document. Bind
each to a token, redefine only the token for dark mode, and pair each with a
redundant shape or border so the class survives greyscale.

| Class | Token | Light | Dark | Redundant channel |
|---|---|---|---|---|
| Our code / our service | `--dg-own` | `#0072B2` | `#56B4E9` | solid border, filled |
| External / third party | `--dg-ext` | `#6B6B6B` | `#A1A1A1` | grey fill |
| Data store | `--dg-data` | `#00745B` | `#3ECFA4` | cylinder |
| Human / actor | `--dg-actor` | `#B35A00` | `#E69F00` | pill or figure |
| Planned / not built | `--dg-plan` | `#8A6A00` | `#F0E442` | dashed border, no fill |
| Deprecated / dead | `--dg-dead` | `#9A9A9A` | `#6E6E6E` | dashed, 55% opacity, struck label |

Line semantics, declared once in the key: **solid = synchronous call**,
**dashed = asynchronous / event**, **dotted = dependency only**. Data flow and
control flow differ by arrowhead shape, never by a second hue alone. Numbers
(throughput, p99, counts) go on the line as a second label line or in the
inventory table — never floating.

Contrast (computed, not quoted): `#0072B2` on white ≈ 5.2:1; `#009E73` ≈ 3.4:1
and `#D55E00` ≈ 3.9:1 pass as fills and thick strokes but not as small text;
Okabe–Ito orange `#E69F00` ≈ 2.25:1 fails on white, which is why the light-mode
actor token above is darkened. Re-check every pair on the dark ground.

The legend lives **inside the SVG**, lists only the classes used on that
diagram, is set in the same size as element labels, and is identical from one
diagram to the next on the page. If the organisation's design system defines
these classes, use its tokens; the mapping above is the fallback, not an
override.

## Status and "where we are" drawings

- **Built vs planned vs dead** is a container diagram where every box carries
  owner, health and status styling from the table above, with the inventory
  table (part · job · runtime · repo/path · owner · status) beside it. The
  drawing shows relationships; the table carries the facts.
- **As-built vs as-designed** is a reflexion model: the intended drawing with
  three line styles — convergent (present in both), divergent (built but not
  designed), absent (designed but not built). Say which the code is.
- **Gap to goal across a portfolio** is a capability ladder in the text, or a
  Wardley map when evolution stage is the argument. Not a Gantt.
- **Options** are drawn as the difference: the one edge each option adds or
  removes, on the same drawing, not one boxed diagram per option.

## Mermaid or hand-drawn SVG

Mermaid earns its place for a sequence diagram or a flow under ten nodes:
cheap, diffable, and `accTitle` / `accDescr` emit real accessible names. It
loses on everything a report figure needs: no manual layout, crossing edges
and overlapping labels past 10–15 nodes, **no CSS-variable theming** (colours
are baked into the SVG at render time, so light/dark tokens cannot reach
them), and **no legends in C4 mode**. Hand-author the SVG for any figure in a
report: `viewBox` with no fixed width/height, `max-width:100%; height:auto`,
`vector-effect="non-scaling-stroke"`, real `<text>` at ≥ 12 px effective,
`role="img"` with a leading `<title>` and a `<desc>`, colours from tokens,
orthogonal edges routed by hand.

## The generator's checklist

1. Title names type and scope; a `<desc>` longer than the title.
2. `role="img"` + `aria-labelledby` (or `aria-label`) on the root `<svg>`.
   *(lint: `svg-aria`)*
3. A key group is present, lists every class used, and nothing unused.
4. Every node: name, type, technology (L2+), responsibility ≤ 12 words.
5. Every edge: verb-phrase label, one arrowhead, protocol on inter-container
   edges.
6. Node count ≤ 20 (warn at 15); one abstraction level.
7. `viewBox` present; no inline width/height; text is real `<text>`.
8. Every fill and stroke is a token with light and dark values. *(lint:
   `svg-theme`, `svg-palette`)*
9. Foreground/background ≥ 3:1 for marks, ≥ 4.5:1 for labels, both themes.
10. Planned and deprecated differ by border and opacity, not colour alone.
11. One flow axis, no back-edges across it; crossings minimised.
12. Date, author, version on the figure.

## Sources

- Brown, the C4 model — https://c4model.com/ · notation https://c4model.com/diagrams/notation · checklist https://c4model.com/diagrams/checklist · dynamic https://c4model.com/diagrams/dynamic
- Brown, "How to review a software architecture diagram" — https://dev.to/simonbrown/how-to-review-a-software-architecture-diagram-6p0
- Brown, "Diagramming distributed architectures with the C4 model" — https://dev.to/simonbrown/diagramming-distributed-architectures-with-the-c4-model-51cm
- Roos, "Misuses and mistakes of the C4 model" — https://www.workingsoftware.dev/misuses-and-mistakes-of-the-c4-model/
- arc42 sections 5–7 — https://docs.arc42.org/section-5/
- Hohpe, *The Software Architect Elevator*; "Architects zoom" — https://architectelevator.com/architecture/architects-zoom/
- Microsoft, "Create architecture design diagrams" (Well-Architected) — https://learn.microsoft.com/en-us/azure/well-architected/architect-role/design-diagrams
- AWS Architecture Icons — https://aws.amazon.com/architecture/icons/ · Google Cloud Architecture Center — https://docs.cloud.google.com/architecture
- Kubernetes, "Components of Kubernetes" (an exemplary L2 figure) — https://kubernetes.io/docs/concepts/overview/components/
- Mermaid accessibility, theming, C4 — https://mermaid.js.org/config/accessibility.html · https://mermaid.js.org/config/theming.html · https://mermaid.js.org/syntax/c4.html
- Purchase, "Validating graph drawing aesthetics" — https://link.springer.com/chapter/10.1007/bfb0021827
- Murphy & Notkin, software reflexion models — https://www.semanticscholar.org/paper/0f52fa7e6c48d0e747ce498d577b658793c49be3
- Wardley maps — https://en.wikipedia.org/wiki/Wardley_map
- W3C WCAG 2.2 SC 1.4.11 — https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html
