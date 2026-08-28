# Apple Interface Adapter

Load this reference for iOS, iPadOS, macOS, UIKit, SwiftUI, and AppKit.

## Platform contract

- Use [Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/)
  and the target OS SDK as the primary sources.
- Prefer SwiftUI/UIKit/AppKit controls and behaviors for navigation, windows,
  menus, toolbars, commands, text editing, selection, drag/drop, permissions,
  sharing, and system integrations.
- Preserve each device family's input model. iPhone touch, iPad touch/pointer,
  and macOS pointer/keyboard/windowing are related but not interchangeable.
- A normal macOS action button may retain the arrow cursor. Do not apply a web
  hand cursor to every native control. Use platform pointer effects and custom
  pointers only when the task warrants them.
- Use system typography for platform controls by default. Apply brand type and
  color to expressive/product layers without weakening Dynamic Type, legibility,
  or expected control hierarchy.

## States and adaptation

- Test compact and regular size classes or the app's supported window sizes;
  support resizing and multitasking where the product target requires them.
- Support Dynamic Type, increased contrast, dark appearance, Reduce Motion,
  VoiceOver, Full Keyboard Access, and platform focus behavior.
- Make touch targets comfortably operable and keep destructive actions,
  permissions, undo, cancellation, loading, empty, and error recovery explicit.
- Use haptics and sound only for meaningful feedback; never make either the sole
  indication of state.

## Visual checkpoint

- Prefer SwiftUI Preview, a focused UIKit/AppKit host, simulator, or a small
  native sample target for behavior-bearing decisions.
- An HTML study is acceptable only for composition, typography, color, density,
  or product-flow discussion. Label it as a visual hypothesis and rebuild in
  native controls after approval.
- Validate menus, toolbars, window chrome, keyboard shortcuts, focus, pointer,
  text selection, drag/drop, haptics, and accessibility only in the native
  surface.

## Verification

- Run the repository's `xcodebuild`/Swift tests and build the relevant scheme.
- Inspect SwiftUI previews or the running app across supported devices, window
  sizes, appearances, text sizes, orientations, and input modes.
- Exercise VoiceOver and keyboard navigation for important flows; inspect
  accessibility labels, values, traits, actions, order, and grouping.
- Enable Reduce Motion and increased contrast; check permission denial, offline,
  slow, empty, error, interruption, cancellation, and resume behavior.
- Do not claim App Store quality, native fidelity, or device coverage from an
  HTML prototype or a single simulator screenshot.

Primary references:
[HIG](https://developer.apple.com/design/human-interface-guidelines/),
[Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility),
[Motion](https://developer.apple.com/design/human-interface-guidelines/motion),
and [Pointing devices](https://developer.apple.com/design/human-interface-guidelines/pointing-devices).
