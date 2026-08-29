# Cross-platform Interface Adapter

Load this reference for Electron, Tauri, Flutter, React Native, shared design
systems, and products shipping the same workflow on several platforms.

## Separate what should be shared

Share:

- user/task model, domain language, content, data, and recovery rules;
- brand foundations and semantic design tokens;
- component intent and state names;
- measurement definitions and major accessibility outcomes.

Translate per platform:

- windows, menus, title bars, system navigation, back/history, shortcuts;
- focus, pointer, touch, selection, drag/drop, text input, and context menus;
- permissions, sharing, notifications, haptics, system appearance, and assistive
  technology;
- density, target size, typography metrics, motion, and control anatomy where
  platform expectations differ.

Do not force pixel equality across targets. Aim for behavioral and brand
coherence while preserving learned platform contracts.

## Runtime-specific guidance

- **Electron/Tauri:** the content surface is web and should obey semantic HTML,
  keyboard, focus, accessibility, and browser rendering rules. The shell still
  needs native menus, shortcuts, windows, file dialogs, drag/drop, permissions,
  updates, and OS integration. An HTML prototype is often representative of the
  content surface but not the desktop shell.
- **React Native:** use native navigation, controls, accessibility APIs, and
  per-platform input behavior. Share product components only where they remain
  genuinely native and accessible on both targets.
- **Flutter:** use platform-adaptive navigation and controls where expectations
  differ; test semantics, text scaling, focus, shortcuts, and every shipped
  platform rather than assuming one renderer guarantees parity.
- **PWA:** load the web adapter. Additionally test installability, offline,
  update, permissions, safe areas, and standalone navigation behavior.

## Visual checkpoint

- Prefer the real shared component sandbox when it exists.
- Use HTML for Electron/Tauri content or early brand/layout studies.
- Use Flutter/React Native previews, simulators, and devices for native
  interaction. Label any HTML version as a visual hypothesis only.
- If the user asks to review first, show the shared direction plus the most
  divergent target adaptation; do not make them approve a false single-platform
  representation of a multi-platform system.

## Verification

- Run shared tests and every target platform's build, lint, accessibility, and
  interaction checks that are in scope.
- Inspect at least the most constrained and most divergent targets. For example,
  a narrow touch phone and a resizable keyboard/pointer desktop surface.
- Verify platform navigation, window/menu behavior, focus, text scaling,
  reduced motion, offline/error recovery, and assistive technology separately.
- Report untested targets explicitly. Passing the shared unit tests is not proof
  that all platform surfaces behave correctly.
