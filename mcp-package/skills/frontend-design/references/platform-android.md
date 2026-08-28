# Android Interface Adapter

Load this reference for Android, Jetpack Compose, Views, and Material surfaces.

## Platform contract

- Use [Material 3](https://m3.material.io/) and current Android developer
  guidance as primary sources, then follow the product's declared design system.
- Prefer Compose/Views primitives for navigation, text input, selection, system
  bars/insets, dialogs, sheets, permissions, sharing, back behavior, and
  accessibility semantics.
- Preserve Android back/navigation expectations and account for system UI,
  keyboard/IME, orientation, foldables, large screens, and window resizing when
  supported.
- Treat touch as primary on phones while supporting keyboard, mouse, stylus, or
  D-pad on device classes that expose them. Never depend on hover.

## States and adaptation

- Cover loading, empty, error, offline, permission, destructive confirmation,
  undo, cancellation, background/resume, and interrupted work.
- Support font scaling, TalkBack, dark theme, high-contrast needs, animation
  scale/reduced motion, localization expansion, and comfortable touch targets.
- Use haptics and motion only for meaningful feedback, continuity, spatial
  explanation, attention, or progress.

## Visual checkpoint

- Prefer Compose Preview, an isolated Activity/Fragment, emulator, or device for
  behavior-bearing decisions.
- HTML may explore information hierarchy, layout, density, color, and typography
  but cannot validate navigation/back, insets, IME, touch, TalkBack, haptics, or
  native component behavior.

## Verification

- Run Gradle lint, unit/instrumented tests, and the relevant build variant.
- Inspect representative phone, tablet/large-screen, orientation, font-scale,
  theme, and input configurations supported by the product.
- Exercise TalkBack and keyboard/D-pad focus for important flows; verify
  semantics, labels, state descriptions, traversal order, live regions, and
  custom actions.
- Test permission denial, offline/slow data, background/resume, process
  recreation where relevant, reduced animation, and long localized content.
- Do not claim native quality from a static mock or a single emulator size.
