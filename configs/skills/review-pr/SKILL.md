---
name: review-pr
description: AI reviews a PR diff and posts a structured review comment — parallel to OpenClaw's /review-pr
argument-hint: '[PR_NUMBER_OR_URL]'
---

# Review PR Skill

Reads the diff of a PR, writes a structured review (summary, risks, suggestions), and posts it as a PR comment via `gh`.

## Usage

```
/review-pr          # Review the PR for the current branch
/review-pr 42       # Review PR #42
/review-pr https://github.com/owner/repo/pull/42
```
