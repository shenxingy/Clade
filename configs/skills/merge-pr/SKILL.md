---
name: merge-pr
description: Squash-merge a PR and clean up the branch — parallel to OpenClaw's /merge-pr
argument-hint: '[PR_NUMBER_OR_URL]'
---

# Merge PR Skill

Squash-merges a PR, deletes the remote branch, and cleans up the local branch. Parallel to OpenClaw's `/merge-pr`.

## Usage

```
/merge-pr           # Merge the PR for the current branch
/merge-pr 42        # Merge PR #42
/merge-pr https://github.com/owner/repo/pull/42
```
