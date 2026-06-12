---
name: review-pr
description: AI checks out a PR into a worktree, runs the project's CI commands, and posts a structured review with execution evidence — parallel to OpenClaw's /review-pr
when_to_use: "review PR, code review pull request, PR feedback"
argument-hint: '[PR_NUMBER_OR_URL]'
user_invocable: true
---

# Review PR Skill

Checks out the PR into a worktree, discovers and runs the project's CI commands, writes a structured review (summary, evidence, risks, suggestions), and posts it as a PR comment via `gh`. The verdict is grounded in the Evidence section — tests that fail force ❌, and a review that couldn't execute the change never posts ✅.

## Usage

```
/review-pr          # Review the PR for the current branch
/review-pr 42       # Review PR #42
/review-pr https://github.com/owner/repo/pull/42
```
