# E2E User Interaction Matrix

This document defines the exhaustive interaction space for end-to-end testing.
Every time `/review` runs an E2E phase, it maps the project's features onto this matrix
and tests the highest-risk combinations.

---

## Dimensions

### Auth States
| ID | State |
|----|-------|
| S0 | Logged out / unauthenticated |
| S1 | Logged in, free tier |
| S2 | Logged in, paid / premium |
| S3 | Logged in, payment flow open (mid-purchase) |
| S4 | Account deletion in progress |

### Feature States
| ID | State |
|----|-------|
| F0 | Idle — no operation in progress |
| F1 | Operation in progress (upload, processing, generation, etc.) |
| F2 | Operation completed — result displayed |
| F3 | Operation failed / error state |

### Atomic User Actions
#### Account
| ID | Action |
|----|--------|
| A1 | Login (submit credentials) |
| A2 | Logout |
| A3 | Delete account (confirm) |
| A4 | Purchase / top-up credits |
| A5 | Change plan / subscription |

#### Navigation
| ID | Action |
|----|--------|
| N1 | Navigate to another page via menu or link |
| N2 | Close tab or browser window |
| N3 | Press back button |
| N4 | Navigate to home page |
| N5 | Open settings page / overlay |
| N6 | Close settings (return to previous context) |
| N7 | Refresh page (F5 / Cmd+R) |
| N8 | Duplicate tab / open in new tab |
| N9 | Switch to another browser tab and return |

---

## Interrupt Matrix — Operation × Action

Test what happens when a **long-running operation (F1) is interrupted** by each action.

| ID | Interrupt Action | Expected Outcome | Risk |
|----|-----------------|------------------|------|
| I-01 | N1: Navigate to another page | Operation continues server-side; returning shows progress or result | HIGH |
| I-02 | N2: Close tab/window | Server job completes or cleans up; credits not lost; no double-deduction | HIGH |
| I-03 | N3: Back button | Warning modal shown, or navigation blocked until done; no broken state | MEDIUM |
| I-04 | N4: Go to home | Same as I-01; banner/indicator shows in-progress job | HIGH |
| I-05 | N5: Open settings | Overlay opens without killing job; closing settings returns to live state | MEDIUM |
| I-06 | N6: Close settings | Returns to exact prior state; no lost progress | LOW |
| I-07 | N7: Refresh page | Result preserved if complete; loading state if still processing; no dup job | HIGH |
| I-08 | N8: Duplicate tab | No duplicate job created; one canonical job | MEDIUM |
| I-09 | N9: Switch tab and return | UI resumes correctly (websocket reconnect, polling resumes) | MEDIUM |
| I-10 | A2: Logout during operation | Job continues or cancels cleanly; result accessible on next login | HIGH |
| I-11 | A3: Delete account during operation | Job cancelled; credits refunded or usage not charged; no orphaned data | CRITICAL |
| I-12 | A4: Purchase during operation | Payment flow opens; ongoing operation unaffected | MEDIUM |

---

## Payment Flow Interrupts

| ID | State | Interrupt | Expected Outcome | Risk |
|----|-------|-----------|------------------|------|
| P-01 | Payment form open | N1: Navigate away | Intent cancelled; no charge; credits unchanged | HIGH |
| P-02 | Payment form open | N2: Close tab | Intent cancelled cleanly; idempotent | HIGH |
| P-03 | Payment processing (spinner) | N2: Close tab | No double-charge; webhook completes server-side | CRITICAL |
| P-04 | Payment success page | N2: Close tab immediately | Credits added via webhook; accessible on return | HIGH |
| P-05 | Payment form | N7: Refresh | Form state reset; no partial submission | MEDIUM |
| P-06 | Payment success | N3: Back button | Cannot resubmit; idempotent | HIGH |

---

## Auth State Transitions

| ID | From | Action | To | Test Concern |
|----|------|--------|-----|--------------|
| T-01 | S0 | A1: Login | S1/S2 | Session token set; no duplicate sessions |
| T-02 | S1 | A4: Purchase | S2 | Credits credited exactly once; no race condition |
| T-03 | S1/S2 | A2: Logout | S0 | Session destroyed; tokens cleared from storage |
| T-04 | S1/S2 | A3: Delete account | S0 | All user data removed; tokens revoked; no dangling refs |
| T-05 | S2 | F1 + A2: Logout mid-op | S0 | Job result linked to account; accessible after re-login |
| T-06 | S2 | F1 + A3: Delete mid-op | S0 | Job cancelled; no charge; clean teardown |
| T-07 | S0 | N3: Back after logout | S0 | Cannot access protected page; redirect to login |
| T-08 | S1 | Open in N8: new tab | S1 | Session shared; not duplicated; consistent state |

---

## Multi-Step Sequences

These test realistic user journeys that combine multiple actions.

| ID | Sequence | Expected Behavior |
|----|----------|-------------------|
| SEQ-01 | Start op → N5 Open settings → N6 Close settings → observe | Operation continues; settings close returns to live progress view |
| SEQ-02 | Start op → N4 Go home → return to feature page | Progress indicator shown on home; result visible on return |
| SEQ-03 | Start op → N4 Go home → A2 Logout → A1 Login → return | Result linked to account; accessible after re-login |
| SEQ-04 | Start op → N1 Navigate away → N3 Back → observe | Back returns to correct state; no dup job |
| SEQ-05 | Start op → N2 Close tab → reopen URL | Page loads with job status or completed result |
| SEQ-06 | Start op → A2 Logout → A1 Login immediately | Single session; no ghost sessions; result persists |
| SEQ-07 | Start op → A3 Delete account | Clean cancellation; user confirmed deleted; no dangling job |
| SEQ-08 | A4 Purchase → N5 Open settings → N6 Close → complete purchase | Settings did not break payment flow |
| SEQ-09 | A4 Purchase → N1 Navigate away → return to purchase page | Cart/intent restored; no double intent |
| SEQ-10 | Start op → N7 Refresh → N7 Refresh again | Job deduped; same job ID; not triggered twice |
| SEQ-11 | Login → start op → N9 Switch tab → return after 10 min | Session still valid; UI reconnects; result shown |
| SEQ-12 | Login → start op → let session expire → observe | Graceful expiry message; result accessible after re-login |

---

## How to Use This Matrix in E2E Testing

1. **Map features**: identify the project's long-running operations (F1 candidates) and auth flows
2. **Prioritize by risk**: CRITICAL and HIGH items must be tested; MEDIUM if time permits
3. **Test with Playwright**: for each scenario, write the interaction sequence and assert the expected outcome
4. **Check billing invariants**: for any monetized operation, verify credit/charge idempotency under interrupts
5. **Check auth invariants**: after any account action, verify no protected resources are accessible from prior state

When adding new features, map them to this matrix and add project-specific rows to VERIFY.md.
