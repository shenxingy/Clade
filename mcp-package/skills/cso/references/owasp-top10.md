# OWASP Top 10 — Audit Checklist
_Source: OWASP Top 10 2021 (current as of 2026-04)_

Load this file on demand during Phase 4 of the security audit.

## Checklist

| # | Category | What to check | Confidence signal |
|---|----------|--------------|-------------------|
| **A01** | **Broken Access Control** | Authorization checks on every protected route? IDOR: can user N access resource owned by user M? Verify direct object references use ownership checks, not just auth. | HIGH if you can find a route that reads resource by ID without ownership check |
| **A02** | **Cryptographic Failures** | Passwords hashed with bcrypt/argon2/scrypt (not MD5/SHA1/SHA256)? TLS enforced? Sensitive data encrypted at rest? Cookie flags (Secure, HttpOnly, SameSite)? | HIGH if you find `hashlib.sha1`, `MD5`, `bcrypt` missing |
| **A03** | **Injection** | SQL: parameterized queries or ORM? Shell: subprocess with list args (not string interpolation)? LDAP, XML, NoSQL injection? Path traversal in file ops? | HIGH if you find `cursor.execute(f"..."` or `subprocess.run(f"..."` or `os.system(` |
| **A04** | **Insecure Design** | Rate limiting on auth endpoints (/login, /register, /reset)? Account enumeration possible (different error for "user not found" vs "wrong password")? Password reset flow: token expiry, single-use? | MEDIUM — check response bodies for user enumeration |
| **A05** | **Security Misconfiguration** | Debug mode off in prod (`DEBUG=True` in Django, `debug: true` in Flask)? Error messages reveal stack traces to users? Default credentials changed? Unused features/endpoints disabled? CORS allowlist (not `*`)? | HIGH if `DEBUG=True` or `CORS_ALLOW_ALL_ORIGINS=True` in env |
| **A06** | **Vulnerable Components** | From dependency scan — critical/high CVEs with known exploits. Flag: unpinned major dependencies. | HIGH if pip-audit or npm audit reports critical CVEs |
| **A07** | **Auth & Session Failures** | JWT: `alg=none` accepted? Token signed with secret, not hardcoded? Session tokens regenerated after login (fixation)? Logout actually invalidates server-side session? Password reset tokens single-use? | HIGH if JWT library doesn't enforce algorithm, or if logout only clears client cookie |
| **A08** | **Software Integrity Failures** | Unpinned GitHub Actions (`uses: actions/checkout@v3` vs `@main`)? Unverified 3rd party scripts loaded (`<script src="untrusted.cdn.com">`)? Subresource Integrity (SRI) on CDN assets? | MEDIUM — check `.github/workflows/*.yml` for `@main` action pins |
| **A09** | **Logging Failures** | Auth events logged (login success/fail, logout, password change)? Sensitive data NOT in logs (passwords, tokens, PII)? Log injection possible (user input in log messages without sanitization)? | MEDIUM — grep for `log.*password\|log.*token` patterns |
| **A10** | **SSRF** | User-controlled URLs fetched by the server? Allowlist of permitted domains? Internal metadata endpoints accessible (`169.254.169.254`, `metadata.google.internal`)? DNS rebinding mitigations? | HIGH if you find `requests.get(user_input)` or `fetch(req.body.url)` without allowlist |

## Common High-Signal Grep Patterns

```bash
# A01 - IDOR
grep -rn "\.get(id)\|\.find(id)\|params\[.id.\]" --include="*.py" --include="*.ts" --include="*.js" .

# A02 - Weak hashing
grep -rn "hashlib.md5\|hashlib.sha1\|MD5(\|SHA1(" --include="*.py" .

# A03 - SQL injection
grep -rn 'execute(f"\|execute(.*%.*%\|execute(".*{' --include="*.py" .

# A03 - Shell injection
grep -rn 'os\.system\|subprocess\.run.*shell=True\|subprocess\.call.*shell=True' --include="*.py" .

# A05 - Debug mode
grep -rn 'DEBUG\s*=\s*True\|debug\s*=\s*True\|debug=True' --include="*.py" --include="*.env*" .

# A07 - JWT algorithm not enforced
grep -rn 'algorithms=None\|algorithm=None\|verify=False' --include="*.py" .

# A10 - SSRF
grep -rn 'requests\.get(\|requests\.post(\|fetch(\|urllib\.request' --include="*.py" . | grep -v 'test\|mock\|fixture'
```
