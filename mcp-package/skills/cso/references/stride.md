# STRIDE Threat Model — Reference
_Load on demand during Phase 5 of the security audit._

## STRIDE Analysis Table

For each major component (web server, database, auth service, background workers, message queues), evaluate:

| Threat | Definition | Attack questions | Common mitigations |
|--------|-----------|-----------------|-------------------|
| **S — Spoofing** | Impersonating a user or service | Can an attacker forge auth tokens? Bypass auth headers? Replay old sessions? Claim to be another service in inter-service comms? | Strong auth (MFA, short-lived tokens), mutual TLS for services |
| **T — Tampering** | Modifying data without authorization | Can data be modified in transit (HTTP without TLS)? At rest (unencrypted DB, world-writable files)? Can API inputs bypass server-side validation? | TLS everywhere, signed payloads, input validation, integrity checks |
| **R — Repudiation** | Denying an action was taken | Are critical actions (admin ops, data deletion, payment) logged with user identity + timestamp? Can users deny sending a message? | Immutable audit logs, signed transactions, non-repudiation architecture |
| **I — Information Disclosure** | Exposing data to unauthorized parties | Can an attacker enumerate user IDs? Read another user's data (IDOR)? Access debug endpoints? Infer data from error messages or timing? | Authorization at every read, error normalization, rate limiting on enumerable endpoints |
| **D — Denial of Service** | Making service unavailable | Are there unbounded loops on user input? Expensive operations (regex, crypto) callable without auth? Missing rate limits on costly endpoints? Algorithmic complexity attacks? | Rate limiting, resource quotas, input size limits, auth before expensive ops |
| **E — Elevation of Privilege** | Gaining higher permissions than authorized | Can a regular user invoke admin functions? Can a low-privilege API key access high-privilege operations? Privilege escalation via misconfigured roles? | Principle of least privilege, role validation on every endpoint, server-side authorization |

## Component-Based Analysis Template

For each component, fill:

```
Component: [e.g., "REST API server"]
Trust boundary: [what can callers control?]
Data in: [what inputs does it accept?]
Data out: [what data does it expose?]

S threat: [specific spoofing risk or "None identified"]
T threat: [specific tampering risk or "None identified"]
R threat: [specific repudiation risk or "None identified"]
I threat: [specific info disclosure risk or "None identified"]
D threat: [specific DoS risk or "None identified"]
E threat: [specific privilege escalation risk or "None identified"]
```

## Threat Priority Matrix

| Likelihood | Low Impact | Medium Impact | High Impact |
|-----------|-----------|--------------|------------|
| **High** | MEDIUM | HIGH | CRITICAL |
| **Medium** | LOW | MEDIUM | HIGH |
| **Low** | INFO | LOW | MEDIUM |

Apply the matrix per threat: estimate likelihood (how easily exploitable?) × impact (data exposure? service disruption? financial loss?).
