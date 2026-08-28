# Windows Interface Adapter

Load this reference for Windows App SDK, WinUI, WPF, and Windows desktop apps.

## Platform contract

- Use [Fluent 2](https://fluent2.microsoft.design/), Windows App SDK guidance,
  and the target framework's controls as primary implementation sources.
- Preserve windowing, title bar, menus, command surfaces, keyboard accelerators,
  focus, right-click/context menus, text selection, drag/drop, and system
  navigation conventions.
- Prefer WinUI/WPF controls and documented states before recreating them. Use
  the WinUI Gallery as a runnable behavior reference rather than copying a
  screenshot.
- Support mouse, precision touchpad, keyboard, touch, pen, and controller only
  where the product and device class require them. Never rely on hover alone.

## States and adaptation

- Design for resizable windows, DPI scaling, text scaling, light/dark themes,
  high contrast, and keyboard focus. Decide and document minimum supported
  window size.
- Keep focus indicators visible and preserve logical tab order and access keys.
- Cover loading, empty, error, offline, permission, destructive confirmation,
  undo, cancellation, and interrupted work.
- Use motion to connect, transition, give feedback, guide, or express progress.
  Fluent timing examples are starting points, not a reason to animate every
  control.

## Visual checkpoint

- Prefer a WinUI/XAML preview, sample page, or focused native test host for
  behavior-bearing decisions.
- An HTML study may explore layout, density, color, type, or product workflow,
  but it cannot validate Windows windowing, focus, input, scaling, Narrator,
  high contrast, or native control behavior.

## Verification

- Build and run the actual Windows target and its test suite.
- Inspect supported window sizes, DPI/text scaling, light/dark/high-contrast
  modes, keyboard-only use, pointer/touch behavior, and reduced animation.
- Exercise Narrator or the relevant accessibility inspection tooling for
  important flows; verify names, roles, states, relationships, focus order, and
  live updates.
- Compare against runnable controls in
  [Windows samples](https://learn.microsoft.com/en-us/windows/apps/dev-tools/samples)
  and check [mouse interactions](https://learn.microsoft.com/en-us/windows/apps/develop/input/mouse-interactions)
  and [motion guidance](https://learn.microsoft.com/en-us/windows/apps/design/signature-experiences/motion)
  when those decisions are in scope.
