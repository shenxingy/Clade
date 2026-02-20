---
name: commit
description: Analyze uncommitted changes, split into logical commits by module, commit and push by default
argument-hint: '[--no-push] [--dry-run]'
---

# Commit Skill

Analyzes all uncommitted changes, groups them by logical module/feature, and creates well-organized commits — following the convention of splitting by feature rather than one big commit.

## What it does

1. Analyzes all staged and unstaged changes
2. Groups files into logical commits (schema, API, frontend, config, docs, etc.)
3. Generates appropriate commit messages for each group
4. Shows the plan for confirmation
5. Executes commits in sequence
6. Pushes by default

## Usage

```
/commit                   # Analyze + plan + confirm + commit + push (default)
/commit --no-push         # Commit only, skip push
/commit --dry-run         # Show plan only, don't commit
```
