---
name: merge-pr
description: "Squash-merge a PR and clean up the branch — parallel to OpenClaw's /merge-pr"
---

# Clade for Codex

This workflow runs **directly in Codex**. Do not launch the `claude` CLI or
delegate the workflow to Clade's MCP bridge.

Codex compatibility rules:

- Read the nearest `AGENTS.md` files for repository instructions. If a project
  has only `CLAUDE.md`, treat it as legacy project guidance and read it too.
- Store new Clade working state under `.clade/` (or `~/.clade/` for personal
  state). Existing legacy Claude state may be read for migration, but do not
  create new vendor-specific state.
- A `/skill-name` reference means the corresponding Codex `$skill-name` skill,
  or the same workflow invoked naturally when explicit skill invocation is not
  available.
- Use Codex web, file, shell, image, and subagent capabilities when the source
  workflow names a vendor-specific tool. If a capability is unavailable, use
  the documented fallback instead of spawning another agent CLI.
- Paths such as `<plugin-root>/...` are relative to the installed Clade plugin
  containing this `SKILL.md`; resolve that root before invoking a helper.

## Canonical Clade workflow

You are the Merge PR skill. You squash-merge a PR and clean up its branch.

## Step 1: Resolve the PR

Parse the argument (if any):
- No argument → use current branch: `gh pr view --json number,url,state` to get the PR
- Number (e.g. `42`) → PR #42 in current repo
- Full URL → use directly

If no PR found, say so and exit. If PR state is already `MERGED` or `CLOSED`, say so and exit.

## Step 1.5: Scope gate

Inspect PR metadata and diff before checking CI:

```bash
gh pr view {PR_NUMBER_OR_URL} --json title,body,additions,deletions,changedFiles,commits,baseRefName,headRefName
gh pr diff {PR_NUMBER_OR_URL}
```

Map the diff to independently useful features, TODO Feature tags, bug root
causes, or roadmap phases. If it contains more than one independent delivery
unit, stop and require separate or stacked PRs. Passing CI and multiple clean
commits do not override this gate.

Allow tests, migrations, generated contracts, and documentation that support
the same feature. For diffs over 500 lines require explicit atomic-scope
justification; over 1,000 lines defaults to stop unless generated files or a
single inseparable foundation dominate.

## Step 2: Check CI status

```bash
gh pr checks {PR_NUMBER_OR_URL}
```

If any required checks are **failing**, report them and ask the user to confirm before proceeding. Don't merge a broken PR silently.

If checks are pending, warn but proceed (user is explicitly requesting merge).

## Step 3: Squash merge

```bash
gh pr merge {PR_NUMBER_OR_URL} --squash --delete-branch --yes
```

`--squash` — combine all commits into one clean commit on main
`--delete-branch` — delete the remote branch after merge
`--yes` — skip interactive confirmation

If merge fails (conflicts, branch protection, etc.), report the error clearly and stop.

## Step 4: Clean up local branch (if applicable)

If the merged branch exists locally:
```bash
git branch -d {branch_name}
```

Use `-d` (safe delete), not `-D`. If it fails because it's not fully merged, that's expected and fine — skip.

Pull main to stay current:
```bash
git checkout main && git pull --ff-only
```

(Only run checkout/pull if we're not currently on main or if the user would benefit.)

## Step 5: Report

```
✓ Merged PR #{number}: {title}
  Branch: {branch_name} → deleted
  Squash commit on main: {short_hash}
```

## Rules

- Never force-push or rebase without explicit user instruction
- Never merge PRs targeting branches other than main/master without confirming with user
- Never merge a multi-feature PR; split it with `/create-pr` first
- If `--delete-branch` fails (e.g. branch already deleted), that's fine — continue


---

## Completion Status

- ✅ **DONE** — task completed successfully
- ⚠ **DONE_WITH_CONCERNS** — completed but with caveats to note
- ❌ **BLOCKED** — cannot proceed; write details to `.clade/blockers.md`
- ❓ **NEEDS_CONTEXT** — missing information; use AskUserQuestion

**3-strike rule:** If the same approach fails 3 times, switch to BLOCKED — do not retry indefinitely.

## Additional skill reference

# Merge PR Skill

Squash-merges a PR, deletes the remote branch, and cleans up the local branch. Parallel to OpenClaw's `/merge-pr`.

## Usage

```
/merge-pr           # Merge the PR for the current branch
/merge-pr 42        # Merge PR #42
/merge-pr https://github.com/owner/repo/pull/42
```
