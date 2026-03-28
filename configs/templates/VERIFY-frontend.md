# VERIFY — [Project Name]
<!-- Managed by /review skill. Edit checkpoint descriptions freely; statuses are updated by the agent. -->
<!-- Legend: ✅ pass  ❌ fail  ⚠ known limitation  ⬜ not yet tested -->

**Project type:** frontend
**Last full pass:** never
**Coverage:** 0 ✅, 0 ❌, 0 ⚠, 0 ⬜ untested

---

## User Journeys
<!-- Complete end-to-end flows a real user would take. Fill in app-specific journeys. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| J1 | Landing page loads: content visible, no JS errors, CTA buttons functional | ⬜ | — | |
| J2 | Sign-up flow: fill form → submit → confirmation → land on dashboard | ⬜ | — | |
| J3 | Login flow: valid credentials → dashboard; invalid → inline error, no crash | ⬜ | — | |
| J4 | [Core feature flow — describe the primary user action this app enables] | ⬜ | — | app-specific |
| J5 | Settings / profile: page accessible, changes saved and reflected on reload | ⬜ | — | |
| J6 | Logout: session cleared, redirect to login, protected routes inaccessible | ⬜ | — | |

## Navigation
<!-- All routes reachable and behave correctly. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| N1 | All nav links navigate to correct pages (no 404s, no blank screens) | ⬜ | — | |
| N2 | Browser back/forward works without state corruption or blank page | ⬜ | — | |
| N3 | Direct URL access to protected route → redirect to login if unauthenticated | ⬜ | — | |
| N4 | Unknown route → custom 404 page, not blank or crash | ⬜ | — | |

## UI States
<!-- Every meaningful application state must render correctly. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| S1 | Empty state (no data) → dedicated empty-state UI shown, not blank or null | ⬜ | — | |
| S2 | Loading state → spinner or skeleton visible during data fetch | ⬜ | — | |
| S3 | Error state (API failure) → user-facing error message, not raw error or crash | ⬜ | — | |
| S4 | Full data state → renders without overflow, text clipping, or layout breaks | ⬜ | — | |

## Form Behavior
<!-- Every form must validate, submit safely, and provide feedback. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| F1 | Required field validation → inline error messages shown on submit | ⬜ | — | |
| F2 | Format validation (email, phone, URL) → validates before API call | ⬜ | — | |
| F3 | Submit button disabled while request in-flight → no duplicate submissions | ⬜ | — | |
| F4 | Success feedback after submission → confirmation message or redirect | ⬜ | — | |
| F5 | Form resets correctly after successful submission | ⬜ | — | |

## Error Paths
<!-- What happens when things go wrong — the user should never see a crash or white screen. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| E1 | API 500 / timeout → error message shown, retry available, no crash | ⬜ | — | |
| E2 | Network offline → graceful degradation, not white screen | ⬜ | — | |
| E3 | 400 invalid input → API error surfaced as user-readable message | ⬜ | — | |
| E4 | 401 unauthorized → redirect to login (not silent failure) | ⬜ | — | |
| E5 | 403 forbidden → error page with explanation, not crash or blank | ⬜ | — | |

## Edge Cases
<!-- Boundary conditions that commonly cause regressions. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| EC1 | Very long text content → truncated or wrapped, no layout breaks | ⬜ | — | |
| EC2 | Rapid repeated clicks (double-submit, fast nav) → no duplicate requests | ⬜ | — | |
| EC3 | Page refresh mid-flow → state handled (redirect to start or restore) | ⬜ | — | |
| EC4 | Mobile viewport 375px → no horizontal scroll, touch targets ≥ 44px | ⬜ | — | |
| EC5 | Special characters in inputs (emoji, Unicode, `<script>`) → rendered safely | ⬜ | — | |

## Integration Contracts
<!-- The API↔DB↔UI pipeline must be internally consistent. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| I1 | Data from API matches what's rendered (no missing fields, no type mismatches) | ⬜ | — | |
| I2 | Write operations reflected on next page load (DB writes reach UI) | ⬜ | — | |
| I3 | Auth token expiry handled transparently (auto-refresh or re-login prompt) | ⬜ | — | |
| I4 | Pagination / infinite scroll: correct data range, no duplicates or gaps | ⬜ | — | |

## Design Consistency
<!-- UI should look intentional and coherent across pages. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| D1 | Button, input, and card styles match design system across all pages (no rogue styles) | ⬜ | — | |
| D2 | Interactive elements have visible hover, focus, and active states | ⬜ | — | |
| D3 | Error and success states use appropriate visual treatment (color, icon, message) | ⬜ | — | |
| D4 | No layout shift after data loads (content does not jump around) | ⬜ | — | |

## Security
<!-- Frontend security baseline — OWASP top-10 surface. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| SEC1 | User-supplied text rendered in DOM is HTML-escaped (no XSS via dangerouslySetInnerHTML or v-html without sanitization) | ⬜ | — | |
| SEC2 | State-changing requests include CSRF protection (SameSite cookie, CSRF token, or same-origin check) | ⬜ | — | |
| SEC3 | Auth tokens stored in httpOnly cookies or memory — not localStorage (XSS-accessible) | ⬜ | — | |
| SEC4 | `npm audit` / `pnpm audit` shows zero high/critical vulnerabilities | ⬜ | — | |

## Accessibility
<!-- WCAG 2.1 AA baseline. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| A11Y1 | All interactive elements reachable and operable via keyboard (Tab / Enter / Space / Escape) | ⬜ | — | |
| A11Y2 | Images have descriptive `alt` text; decorative images use `alt=""` | ⬜ | — | |
| A11Y3 | Page has logical heading hierarchy (h1 → h2 → h3, no skips) | ⬜ | — | |
| A11Y4 | Focus indicator visible on all interactive elements (not just outline: none) | ⬜ | — | |

---
<!-- Add new checkpoints above this line. /review appends discovered scenarios here automatically. -->
