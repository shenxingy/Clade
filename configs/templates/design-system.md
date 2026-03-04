# Design System
# Copy this file to your project root as `.design-system.md` and fill in your project's tokens.
# Workers read this file to inject consistent visual decisions into every frontend task.
# Leave a section blank or keep `[placeholder]` values → that section will be skipped by orchestrator.

## Color Palette
# Define all colors as CSS custom properties. Use semantic naming (role, not hue).
# Example: --color-primary: #3B82F6;  --color-error: #EF4444;

:root {
  /* Brand */
  --color-primary: [placeholder];      /* main CTA, links, focused rings */
  --color-primary-hover: [placeholder]; /* darkened primary for hover states */
  --color-secondary: [placeholder];    /* secondary actions, badges */
  --color-accent: [placeholder];       /* highlights, tags, decorative pops */

  /* Neutrals (light mode base) */
  --color-background: [placeholder];   /* page background */
  --color-surface: [placeholder];      /* card / panel background */
  --color-border: [placeholder];       /* dividers, input borders */
  --color-text: [placeholder];         /* primary body text */
  --color-text-muted: [placeholder];   /* secondary / placeholder text */

  /* Semantic */
  --color-success: [placeholder];      /* e.g. #22C55E */
  --color-warning: [placeholder];      /* e.g. #F59E0B */
  --color-error: [placeholder];        /* e.g. #EF4444 */
  --color-info: [placeholder];         /* e.g. #3B82F6 */
}

## Typography
# List every font token workers should use. Do NOT leave workers to choose fonts ad-hoc.
# Example: --font-display: 'Geist', sans-serif;

:root {
  /* Font families */
  --font-display: [placeholder];  /* headings, hero text */
  --font-body: [placeholder];     /* paragraph, UI labels */
  --font-mono: [placeholder];     /* code blocks, terminal output */

  /* Size scale (rem, based on 16px root) */
  --text-xs:   [placeholder];  /* e.g. 0.75rem  — captions, tags */
  --text-sm:   [placeholder];  /* e.g. 0.875rem — secondary labels */
  --text-base: [placeholder];  /* e.g. 1rem     — body copy */
  --text-lg:   [placeholder];  /* e.g. 1.125rem — sub-headings */
  --text-xl:   [placeholder];  /* e.g. 1.25rem  */
  --text-2xl:  [placeholder];  /* e.g. 1.5rem   — section headings */
  --text-3xl:  [placeholder];  /* e.g. 1.875rem */
  --text-4xl:  [placeholder];  /* e.g. 2.25rem  — hero / display */

  /* Line height */
  --leading-tight:  [placeholder];  /* e.g. 1.25 — headings */
  --leading-normal: [placeholder];  /* e.g. 1.5  — body */
  --leading-loose:  [placeholder];  /* e.g. 1.75 — long-form prose */

  /* Font weight */
  --font-normal:   [placeholder];  /* e.g. 400 */
  --font-medium:   [placeholder];  /* e.g. 500 */
  --font-semibold: [placeholder];  /* e.g. 600 */
  --font-bold:     [placeholder];  /* e.g. 700 */
}

## Spacing & Layout
# 4px base grid. Workers must use these tokens — no raw px values in components.

:root {
  /* Spacing scale (4px base) */
  --space-1:  [placeholder];   /* 4px */
  --space-2:  [placeholder];   /* 8px */
  --space-3:  [placeholder];   /* 12px */
  --space-4:  [placeholder];   /* 16px */
  --space-6:  [placeholder];   /* 24px */
  --space-8:  [placeholder];   /* 32px */
  --space-12: [placeholder];   /* 48px */
  --space-16: [placeholder];   /* 64px */

  /* Layout */
  --max-width-content: [placeholder];  /* e.g. 1280px — main content area */
  --max-width-prose:   [placeholder];  /* e.g. 720px  — article / doc pages */
  --sidebar-width:     [placeholder];  /* e.g. 256px  — nav sidebar */
}

/* Breakpoints (use in media queries — not as CSS vars) */
/* sm:  640px  — large phones / small tablets */
/* md:  768px  — tablets */
/* lg:  1024px — small desktops */
/* xl:  1280px — standard desktops */
/* 2xl: 1536px — wide screens */

/* Grid system */
/* Columns: [placeholder]  — e.g. 12-column */
/* Gutter:  [placeholder]  — e.g. var(--space-6) */

## Component Library
# Specify which component library (if any) workers should use. Prevents mixing libraries.

# Library: [placeholder]
# Options: shadcn/ui | Radix UI | Material UI | Ant Design | Headless UI | custom | none

# Key components and their import paths:
# - Button:   [placeholder]  e.g. import { Button } from '@/components/ui/button'
# - Input:    [placeholder]
# - Dialog:   [placeholder]
# - Select:   [placeholder]
# - Toast:    [placeholder]
# - Table:    [placeholder]
# - Card:     [placeholder]

# Import convention: [placeholder]
# e.g. "Always import from @/components/ui/*, never from library directly"
# e.g. "All primitives live in src/components/ui — extend, don't re-implement"

## Theme
# Describe light/dark mode support and CSS variable naming conventions.

# Light/dark mode: [placeholder]
# Options: light-only | dark-only | system (prefers-color-scheme) | user-toggle

# Dark mode implementation: [placeholder]
# Options: CSS class (.dark on <html>) | data-theme attribute | media query only

# CSS variable naming convention: [placeholder]
# e.g. --color-* for colors, --text-* for typography, --space-* for spacing
# e.g. all tokens in :root, dark overrides in [data-theme="dark"] { ... }

# Dark mode token overrides (fill in if supporting dark mode):
# [data-theme="dark"] {
#   --color-background: [placeholder];
#   --color-surface: [placeholder];
#   --color-text: [placeholder];
#   --color-text-muted: [placeholder];
#   --color-border: [placeholder];
# }

## Constraints
# Hard rules workers MUST follow. Violations produce inconsistent UI.
# Be explicit: list banned choices and required alternatives.

# Banned fonts: [placeholder]
# e.g. "Never use Arial, Times New Roman, or Comic Sans — use --font-body / --font-display only"

# Banned colors: [placeholder]
# e.g. "Never hardcode hex values in component files — always reference CSS custom properties"

# Accessibility requirements:
# - Minimum contrast ratio: [placeholder]  e.g. 4.5:1 for text (WCAG AA)
# - Focus styles: [placeholder]  e.g. "All interactive elements must show a visible focus ring using --color-primary"
# - Motion: [placeholder]  e.g. "Respect prefers-reduced-motion — wrap animations in @media (prefers-reduced-motion: no-preference)"

# Other constraints:
# - [placeholder]  e.g. "No inline styles — use CSS modules or Tailwind utility classes only"
# - [placeholder]  e.g. "Icon library: lucide-react only — do not import from @heroicons or @radix-ui/icons directly"
# - [placeholder]  e.g. "Border radius: use rounded-md (6px) by default; rounded-full only for avatars/pills"
