---
name: sync
description: End-of-session documentation sync — updates TODO.md and PROGRESS.md only (run /commit after to commit everything)
argument-hint: ''
---

# Sync Skill

End-of-session documentation ritual. Reviews what was done and updates project docs — no commit. Run `/commit` after to commit everything (docs + code) split by module.

## What it does

1. Reviews recent git history to understand what was accomplished
2. Auto-updates TODO.md (checks off completed items)
3. Appends a session summary to PROGRESS.md

## Usage

```
/sync            # Update TODO.md + PROGRESS.md
/commit          # Commit all changes (code + docs) split by module + push
/commit --no-push  # Commit only, skip push
```
