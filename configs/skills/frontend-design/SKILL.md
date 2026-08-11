---
name: frontend-design
description: Create distinctive, production-grade frontend interfaces and presentation surfaces with high design quality. Detects and enforces the project's design system (.design-system.md, design-system skill repo, or DESIGN.md) — hard-rule grep checks, rendered-output validators, review checklist, decisions log; can also author a new design system (SKILL.md + DESIGN.md + assets).
when_to_use: "design UI, create component, frontend design, build page, design a slide deck, presentation slides, apply the design system, follow brand guidelines, author a design system, 设计页面, 做 PPT, 设计幻灯片, 按设计系统, 品牌规范"
user_invocable: true
---

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
