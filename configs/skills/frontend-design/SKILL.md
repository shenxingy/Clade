---
name: frontend-design
description: Create, prototype, redesign, audit, or optimize production-grade interfaces across websites, responsive/mobile web, iOS/iPadOS/macOS, Android, Windows, Electron/Tauri, Flutter/React Native, and other local/native apps — UI/UX, visual polish, named or tunable themes and design variants, components, interaction and motion, design systems, and decks, including requests such as 设计页面、优化网页/界面/UI、设计主题/视觉风格/界面版本. Runs a platform-aware benchmark, design-direction profiles, an optional preview checkpoint, implementation, accessibility checks, and rendered/live verification.
when_to_use: "design/improve/optimize UI, redesign interface, UX audit, visual polish, interaction or motion design, design/visual/named theme, style preset, design variant, theme version, create component, build page, website redesign, native/desktop app UI, slide deck, apply/author a design system, hero animation, signature motion, scroll-driven product story, 3D showcase, kinetic typography, 优化手机端 UI, 可调预设, 工业粗野主义主题, 用工业粗野主义主题设计一个界面版本, 主视觉动效, 标志性动效, 滚动驱动动画, 苹果式产品动画, 产品 3D 展示, 品牌动态语言, UI 设计, UX 优化, 交互设计, 动效设计, 原生 App, 桌面/本地/苹果/Windows 软件, 做 PPT, 设计幻灯片, 按设计系统, 品牌规范"
user_invocable: true
---

# Interface Design Pipeline

Guides interface work from evidence and platform choice through preview,
implementation, and verification. The historical `frontend-design` name stays
for compatibility; the workflow covers web, mobile, desktop, and native apps.

## Usage

```
/frontend-design        # Run the platform-aware interface pipeline
/frontend-design profile=soft-premium motion=1
/frontend-design review <path-or-url>   # P0–P3 review of an existing surface, fixes applied
```

"Design sense" is carried as checkable rules, not adjectives: the spacing
grid, type-scale caps, motion duration table, state list and review widths in
`references/design-rules.md`; the screenshot review loop, severity ladder and
Definition of Done in `references/design-review.md`; and `design-lint source
<dir>` for the half of those rules a static check can see. A hero intro or a
scroll-driven product story — the one place allowed past the motion table —
has its own archetypes, route choice, budgets and storyboard-first handoff in
`references/signature-motion.md`.

Every invocation classifies the target platform and task size, reads the shared
benchmark contract plus the relevant platform adapter, then runs all seven
pipeline phases at proportional depth. It respects the project's design system,
keeps platform contracts native, and makes product workflow and brand choices
deliberately.

For a theme, style, or alternate version, select a named design-direction
profile or infer a custom one, then tune composition, motion, and density. A
profile is a reusable hypothesis; repository and platform evidence still win.

When visual direction is materially uncertain, it creates a viewable checkpoint
before expensive implementation. HTML is preferred for browser UI and may be
used as a clearly labelled visual study for native apps; native behavior must be
validated in the real platform preview, simulator, or running app.
