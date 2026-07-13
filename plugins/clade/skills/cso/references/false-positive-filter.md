# False Positive Filter — CSO Audit
_Load on demand during Phase 6 of the security audit._

## Auto-Discard Rules

Before reporting any finding, apply these exclusion rules. Findings matching any rule below are **discarded** (noted in the report as filtered, not silently dropped).

| # | Rule | Rationale |
|---|------|-----------|
| 1 | **DoS / resource exhaustion** — skip unless it's financial amplification (e.g., unauthenticated user can trigger unbounded LLM API calls) | DoS is nearly impossible to prevent fully; real mitigations are infra-level |
| 2 | **Missing rate limiting on non-auth, non-costly endpoints** — skip unless business logic is affected | Rate limiting on `GET /healthz` or static assets is not a meaningful security finding |
| 3 | **Log spoofing** — skip | Not security-critical for most applications |
| 4 | **SSRF where attacker controls only the path, not host or protocol** — skip | Path-only SSRF has very limited blast radius |
| 5 | **User content in the user-message position of an AI conversation** — skip | This is not prompt injection; it's the intended use case |
| 6 | **Regex complexity** in code that doesn't process untrusted input — skip | ReDoS is only a risk when regex operates on attacker-controlled input |
| 7 | **CVEs with CVSS < 4.0 and no public exploit** — skip | Low-severity CVEs with no known exploit path are noise |
| 8 | **Docker issues in `Dockerfile.dev` / `Dockerfile.local`** — skip unless referenced in prod configs | Dev-only containers don't affect production security |
| 9 | **Missing audit logs** — skip unless there's a compliance requirement (SOC2, HIPAA, PCI-DSS) | Audit logs are a compliance concern, not inherently a security vulnerability |
| 10 | **Insecure randomness** in non-security contexts (UI IDs, colors, display names) — skip | `Math.random()` is fine for UI; it's only an issue for tokens/secrets |
| 11 | **Test fixtures and mock files** — skip unless imported by non-test code | Hardcoded credentials in `tests/fixtures/` are not a production risk |
| 12 | **Missing security headers** (HSTS, CSP, X-Frame-Options) — flag as LOW only if data is sensitive | These are hardening best practices, not exploitable vulnerabilities unless data is high-value |

## Self-Check Before Reporting

For each surviving finding, verify:

1. **Attack path exists** — Can you describe a specific sequence of steps an attacker takes?
2. **Worst realistic outcome** — What's the actual impact? Data leak? Account takeover? Financial loss?
3. **Codebase-specific** — Is this a generic warning or specific to this code?
4. **False positive check** — Does a mitigation already exist that you might have missed?

If you can't concretely answer #1, downgrade or discard the finding.

## Confidence Levels

Every finding should have a confidence score:

| Confidence | Meaning | Action |
|-----------|---------|--------|
| **HIGH (8-10/10)** | Clearly exploitable, attack path verified in code | Report with full detail |
| **MEDIUM (5-7/10)** | Likely exploitable but depends on runtime behavior | Report with caveat "verify at runtime" |
| **LOW (2-4/10)** | Potential concern but unclear attack path | Report as informational only |
| **DISCARD (0-1/10)** | False positive or matches auto-discard rules | Mention in "Discarded" section of report |
