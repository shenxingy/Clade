---
name: sync
description: End-of-session documentation sync — updates TODO.md, PROGRESS.md, and commits by default
argument-hint: '[--no-commit]'
---

# Sync Skill

End-of-session ritual automation. Reviews what was done, updates project documentation, and optionally commits.

## What it does

1. Reviews recent git history to understand what was accomplished
2. Auto-updates TODO.md (checks off completed items)
3. Appends a session summary to PROGRESS.md
4. Optionally commits the doc changes

## Usage

```
/sync                              # Review + update docs + commit (default)
/sync --no-commit                  # Review + update docs only (skip commit)
```
