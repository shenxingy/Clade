# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest (main) | ✅ |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

If you discover a security issue in Clade, please report it privately:

**Email:** alex@get-reality.com

Include in your report:
- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested mitigation (optional)

You will receive a response within **72 hours**. If the vulnerability is confirmed, a patch will be released as soon as possible.

## Scope

This project consists of shell scripts and a Python web server deployed locally. Key areas of security concern:

- **Shell injection** in hooks that process user/git data
- **Path traversal** in scripts that read/write files
- **Privilege escalation** via hooks that execute as the current user
- **Orchestrator web server** (FastAPI on localhost) — not intended to be exposed externally

Out of scope: issues in Claude Code itself, Anthropic's API, or third-party dependencies.

## Disclosure Policy

Once a fix is available, we will:
1. Release a patched version
2. Credit the reporter in the release notes (unless anonymity is requested)
3. Publish details of the vulnerability after users have had time to update
