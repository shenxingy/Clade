---
name: frontend-design
description: Create, prototype, redesign, audit, or optimize production-grade interfaces and presentation surfaces across websites, responsive/mobile web, iOS/iPadOS/macOS, Android, Windows, Electron/Tauri, Flutter/React Native, and other local/native apps. Use for UI/UX design, visual polish, named or tunable themes and design variants, components, interaction states, cursor or motion decisions, design systems, decks, and requests such as 设计页面、优化网页/界面/UI、设计主题/视觉风格/界面版本、优化手机端 UI、原生 App 或桌面软件设计. Runs a platform-aware benchmark, reusable design-direction profiles, an optional HTML or native preview checkpoint, implementation, accessibility checks, and rendered/live verification.
when_to_use: "design UI, improve UI, optimize UI, redesign interface, UX audit, visual polish, interaction design, motion design, design theme, visual theme, named theme, style preset, tunable preset, design variant, theme version, create component, build page, website redesign, responsive web, mobile web, native app UI, desktop app UI, local app, iOS, iPadOS, macOS, Android, Windows, WinUI, SwiftUI, Jetpack Compose, Flutter, React Native, Electron, Tauri, design a slide deck, apply the design system, author a design system, 设计页面, 优化网页, 优化界面, 优化 UI, 设计主题, 视觉主题, 视觉风格, 界面版本, 可调预设, 工业粗野主义主题, 用工业粗野主义主题设计一个界面版本, 优化手机端 UI, UI 设计, UX 优化, 交互设计, 动效设计, 手机端 UI, 原生 App, 桌面软件, 本地软件, 苹果软件, Windows 软件, 做 PPT, 设计幻灯片, 按设计系统, 品牌规范"
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
```

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
