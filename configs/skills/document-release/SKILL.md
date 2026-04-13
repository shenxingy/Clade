---
name: document-release
description: Post-ship documentation sync — updates README, CHANGELOG, CLAUDE.md, ARCHITECTURE, and TODOS after a release. Ensures docs never drift from code. Run after /commit or /ship before closing a PR.
when_to_use: "post-ship docs sync, update README after release, update CHANGELOG, CLAUDE.md sync after shipping a feature — NOT for session-end TODO/PROGRESS update (use /sync)"
argument-hint: '[--dry-run to preview without writing]'
user_invocable: true
---
