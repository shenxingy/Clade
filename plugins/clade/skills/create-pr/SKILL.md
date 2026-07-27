---
name: create-pr
description: "Create an atomic, tested pull request; split multi-feature branches into stacked PRs before opening them"
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

# Create PR

Create a reviewable pull request whose diff contains one feature, bug fix,
refactor, or other independently reversible behavior change. Tests, migrations,
generated contracts, and documentation for that same behavior belong in the
same PR.

## Invariant

**One PR = one independently reviewable and reversible delivery unit.**

Multiple commits do not make a multi-feature branch acceptable. A completed
roadmap, multiple TODO phases, or several independently valuable capabilities
must become separate PRs. Use stacked PRs when later work depends on earlier
work.

Do not use a raw line limit as the sole decision. A coherent foundation can be
large; a 50-line diff can still mix unrelated features. Diff size is a review
risk signal:

- over 500 changed lines: explain why the unit is still atomic;
- over 1,000 changed lines: default to splitting unless generated files or a
  single inseparable foundation dominate the diff.

## Step 1: Resolve repository state

1. Read the nearest `AGENTS.md`/project instructions and current TODO.
2. Resolve the default or requested base branch.
3. Inspect:

```bash
git status --short
git log --oneline <base>..HEAD
git diff --stat <base>...HEAD
git diff --name-only <base>...HEAD
```

Stop if unrelated uncommitted changes overlap the PR. Use an isolated worktree
when branch reconstruction could disturb user changes.

## Step 2: Scope gate

Build a scope map before creating a PR:

1. Identify each user-visible behavior, TODO Feature/phase, bug root cause, or
   independently deployable capability in the diff.
2. Assign every changed file and commit to one scope. Shared scaffolding belongs
   to the earliest scope that requires it.
3. Verify the candidate PR has exactly one scope and one primary reason to
   change.

Treat these as separate PR scopes:

- independently usable endpoints or products;
- separate roadmap phases;
- unrelated fixes discovered while implementing a feature;
- infrastructure that can land without the feature;
- provider integrations that can be reviewed or rolled back separately.

Do not split tests, migrations, generated schemas, or documentation away from
the behavior they validate.

## Step 3: Split multi-scope branches

If the scope map has more than one delivery unit, do not open one aggregate PR.

1. Preserve the original branch as a recovery reference.
2. Start from the latest base in an isolated worktree.
3. Rebuild one branch per scope using explicit cherry-picks or patches.
4. For independent scopes, target the default branch.
5. For dependent scopes, create a stack:

```text
main <- feature-a <- feature-b <- feature-c
```

Each PR targets its immediate predecessor. Its diff must show only that scope.
Record stack position and dependency in every PR body.

Never force-push or close an existing PR until all replacement branches are
pushed and recoverable.

## Step 4: Per-PR verification

For every candidate branch, discover and run the project's CI commands using
the same rules as `/commit`. Each branch must have its own evidence:

- tests for the behavior and failure paths;
- lint/typecheck/build as applicable;
- migrations/contracts if changed;
- generated-file drift checks;
- remote CI after opening the PR.

A later branch passing does not prove an earlier branch passes. Do not reuse an
aggregate branch's result as the only evidence for every split PR.

## Step 5: Create the PR

Create one PR per passing scope. The body must include:

- **Scope:** the one behavior delivered;
- **Out of scope:** adjacent work deliberately excluded;
- **Stack:** position, base PR/branch, and merge order when stacked;
- **Evidence:** exact commands and results;
- **Risk/rollback:** the main hazard and how to revert or disable it.

Use draft status only when explicitly requested or when remote CI cannot yet
run. After creation, wait for required checks. Fix failures on that PR's branch.

## Step 6: Supersede an oversized PR safely

When replacing an existing multi-feature PR:

1. Create and push every replacement branch.
2. Create every replacement PR and verify its base/head pair.
3. Comment on the old PR with the ordered replacement links.
4. Close the old PR without deleting its branch until the stack is accepted.

## Completion

Report the ordered PR list, base/head relationships, per-PR test status, and
any remaining human review or external gates.

## Rules

- Never represent split commits inside one PR as independent delivery.
- Never mix “while here” fixes into the current PR.
- Never merge the stack out of order.
- Never claim a PR is ready while its own required CI is pending or failing.
- A release PR may aggregate only changes already reviewed independently; use
  `/ship` for that explicit workflow.
