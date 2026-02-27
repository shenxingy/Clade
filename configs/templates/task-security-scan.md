===TASK===
model: haiku
TYPE: HORIZONTAL
---
# Security Scan Bot — Fix Security Findings

## Goal

Run security analysis tools on the codebase and fix detected vulnerabilities and bad practices to maintain secure, production-ready code.

## Context

**Scope:** Full codebase (or `[SPECIFIC_DIRS]`)
**Tools to run:**
- Python: `bandit` (code security) + `semgrep` (pattern-based analysis)
- Node.js: `npm audit`, `snyk`, or `semgrep`
- General: `semgrep` with community ruleset

**Severity filter:** Fix all HIGH + CRITICAL findings; document LOW + MEDIUM for triage

Example issues to look for:
- Hardcoded secrets or credentials
- SQL injection or unsafe query construction
- Unsafe deserialization
- Missing input validation
- Weak cryptography
- Insecure dependency versions
- Missing authentication/authorization checks

## Acceptance Criteria

- [ ] Ran security scan tool successfully (captured output)
- [ ] All CRITICAL findings are fixed or documented with justification
- [ ] All HIGH findings are fixed or documented with justification
- [ ] No new security findings introduced by fixes
- [ ] All existing tests still pass
- [ ] Fixes don't degrade functionality

### Verification of Fixes
- [ ] Code change addresses the root cause, not a symptom
- [ ] Input validation is added where needed (at system boundaries)
- [ ] Secrets not committed to git (use environment variables)
- [ ] Error messages don't leak sensitive information
- [ ] Dependencies with vulnerabilities are upgraded (if possible)

---

## Verification Checklist

### Auto-Verifiable (you must complete before committing)

- [ ] Ran security scan and saved output: `[tool] > security-scan-results.txt`
- [ ] All CRITICAL/HIGH findings resolved or documented
- [ ] Documentation explains why any unresolved findings are acceptable
- [ ] Build passes (no compilation errors)
- [ ] All existing tests still pass
- [ ] `git diff` shows only security-related changes (no refactoring creep)
- [ ] Code review: Secrets not hardcoded (check for `password`, `token`, `key` in code)
- [ ] Code review: Input validation added at boundaries (not internal functions)
- [ ] Code review: Fixes don't silently swallow errors — they handle or report them

### Human-Verifiable (flag if unsure)

- [ ] Security fix is the minimal correct solution (not over-engineered)
- [ ] Documentation explains the vulnerability and how it was fixed

---

## How to Use This Template

1. Copy to task queue: `cat configs/templates/task-security-scan.md >> tasks.txt`
2. Optionally specify scope in `[SPECIFIC_DIRS]` or leave as full codebase
3. Run with batch-tasks: `bash batch-tasks tasks.txt`
4. Worker will scan, identify issues, and fix

## Tips for the Worker

### For Python Projects

```bash
pip install bandit semgrep
bandit -r src/
semgrep --config=p/security-audit src/
```

### For Node.js Projects

```bash
npm audit
npm install -g snyk
snyk test
semgrep --config=p/security-audit src/
```

### Fix Strategy

1. **For dependency vulnerabilities:** Upgrade to patched version
   - Check changelog for breaking changes
   - Run tests after upgrade
   - Commit: `committer "chore: upgrade {pkg} to patch security vulnerability"`

2. **For code issues:**
   - Hardcoded secrets → move to environment variables
   - Unsafe inputs → add validation
   - Missing auth → add permission checks
   - Weak crypto → use modern algorithms
   - Commit: `committer "fix: resolve {SEVERITY} security finding in {location}"`

3. **For acceptable findings:**
   - Create `SECURITY-FINDINGS.md` documenting reason for accepting
   - Example: "This hardcoded string is a service health check constant, not a credential"

### Testing Security Fixes

- Run existing tests to confirm no functionality broken
- If fixing auth/permission issues, manually test that unauthorized access is blocked
- If fixing input validation, test with malicious inputs
- Commit security tests: `committer "test: add security test for {area}"`

---

## Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/) — common vulnerabilities
- [Bandit docs](https://bandit.readthedocs.io/) — Python security
- [Semgrep docs](https://semgrep.dev/) — multi-language pattern detection
- [NPM audit docs](https://docs.npmjs.com/cli/v8/commands/npm-audit) — Node.js dependencies
