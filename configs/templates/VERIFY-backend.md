# VERIFY — [Project Name]
<!-- Managed by /review skill. Edit checkpoint descriptions freely; statuses are updated by the agent. -->
<!-- Legend: ✅ pass  ❌ fail  ⚠ known limitation  ⬜ not yet tested -->

**Project type:** backend
**Last full pass:** never
**Coverage:** 0 ✅, 0 ❌, 0 ⚠, 0 ⬜ untested

---

## API Endpoints
<!-- Every route must return the correct status code and response schema.
     Fill in actual routes from your project. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| A1 | GET /[resource] → 200 with array, correct schema, empty = [] not 404 | ⬜ | — | |
| A2 | GET /[resource]/:id → 200 with object; unknown id → 404 with message | ⬜ | — | |
| A3 | POST /[resource] → 201, record persisted in DB, response includes new id | ⬜ | — | |
| A4 | PUT/PATCH /[resource]/:id → 200, changes persisted, response reflects update | ⬜ | — | |
| A5 | DELETE /[resource]/:id → 204, record removed from DB | ⬜ | — | |

## Authentication & Authorization
<!-- Every protected route must enforce auth correctly. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| AU1 | Unauthenticated request to protected endpoint → 401 | ⬜ | — | |
| AU2 | Authenticated but insufficient permissions → 403 | ⬜ | — | |
| AU3 | Valid token → request proceeds, user context available | ⬜ | — | |
| AU4 | Expired token → 401 with clear message (not 500, not silent) | ⬜ | — | |
| AU5 | Tampered / invalid token → 401, no internal error leaked | ⬜ | — | |

## Input Validation
<!-- All inputs validated at the boundary — bad data rejected before touching DB. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| V1 | Missing required fields → 400 with list of missing field names | ⬜ | — | |
| V2 | Wrong type (string where int expected) → 400 with description | ⬜ | — | |
| V3 | Oversized payload → 413 or 400, not timeout or 500 | ⬜ | — | |
| V4 | SQL injection in string params → rejected, no DB error leaked | ⬜ | — | |
| V5 | XSS payloads in text fields → stored as literal text, escaped on output | ⬜ | — | |

## Error Responses
<!-- Error shape must be consistent and never leak internals. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| ER1 | All 4xx responses return JSON `{"error": "..."}` (not HTML, not empty body) | ⬜ | — | |
| ER2 | 500 responses return generic message — no stack traces, DB errors, or file paths | ⬜ | — | |
| ER3 | Errors logged server-side with request context (method, path, user id) | ⬜ | — | |

## Database Operations
<!-- Data integrity must hold under normal and concurrent conditions. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| DB1 | Multi-table writes use transactions — partial write on failure leaves no orphans | ⬜ | — | |
| DB2 | Foreign key constraints enforced — no orphan records created | ⬜ | — | |
| DB3 | Concurrent writes to same record → no data corruption or lost updates | ⬜ | — | |
| DB4 | Soft delete (if used) → deleted records excluded from list endpoints | ⬜ | — | |
| DB5 | Long-running queries do not block API response for other requests | ⬜ | — | |

## Edge Cases
<!-- Boundary conditions that commonly cause regressions. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| EC1 | Empty result set → 200 `[]`, not 404 | ⬜ | — | |
| EC2 | Duplicate creation → 409 conflict or idempotent (documented behavior) | ⬜ | — | |
| EC3 | Update non-existent resource → 404, not 500 | ⬜ | — | |
| EC4 | Concurrent delete + update same resource → both return gracefully | ⬜ | — | |
| EC5 | Extremely large list query (no pagination) → bounded or pagination enforced | ⬜ | — | |

## Performance & Resilience
<!-- Baseline performance contracts. Set targets before first run. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| PR1 | P95 response time for core endpoints < [target] ms (measure baseline, then alert at 150% of baseline) | ⬜ | — | set target |
| PR2 | Server handles [N] concurrent requests without 5xx (N = expected peak hourly active users) | ⬜ | — | set N |
| PR3 | DB connection pool not exhausted under expected load | ⬜ | — | |
| PR4 | Graceful shutdown: in-flight requests complete before process exits | ⬜ | — | |
| PR5 | Health check endpoint exists: `GET /health` returns 200 with DB connectivity status | ⬜ | — | |

## Security
<!-- OWASP API Security Top-10 baseline. -->

| ID | Checkpoint | Status | Verified | Notes |
|----|-----------|--------|----------|-------|
| SEC1 | Passwords hashed with bcrypt/argon2 before storage — never stored in plaintext | ⬜ | — | |
| SEC2 | Rate limiting on auth endpoints (login, password reset) → 429 after N failed attempts | ⬜ | — | |
| SEC3 | No secrets (API keys, DB passwords) in logs, error responses, or version control | ⬜ | — | |
| SEC4 | CORS: allowed origins explicitly listed — not `*` on authenticated endpoints | ⬜ | — | |
| SEC5 | SQL queries use parameterized statements / ORM — no string interpolation | ⬜ | — | |

---
<!-- Add new checkpoints above this line. /review appends discovered scenarios here automatically. -->
