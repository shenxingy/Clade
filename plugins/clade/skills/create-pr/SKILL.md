---
name: create-pr
description: "Publish or update one repository-adaptive, exact-SHA pull request without duplicating or broadening authority"
---

# Clade for Codex

This package composes the provider-neutral Clade core contract with the native
Codex surface adapter. Run the workflow directly in Codex; do not launch
another agent CLI or route it through Clade MCP.

Package provenance:

- core contract: `clade.delivery/v1`
- surface adapter: `codex/v1`
- explicit invocation: `$clade:create-pr`
- generated from: `configs/skills/<name>`

## Canonical Clade workflow

You are the Create PR skill. Publish or update the active Clade delivery
idempotently.

## 1. Resolve policy and authority

Locate/read the sibling `delivery` skill, relevant surface overlay, and active
delivery state. Run its context probe again immediately before publication.

Stop or choose a non-PR fallback when:

- no authenticated forge adapter exists;
- PR publication authority is pending;
- current branch is default/shared/unknown-owned/detached;
- a fork/human-owned PR cannot be updated safely;
- trusted repository PR policy/template cannot be resolved.

GitHub uses `gh`; GitLab/Bitbucket use their available adapters; plain Git
returns a pushed branch, request-pull, or patch/bundle. Never invoke `gh` in a
non-GitHub repository.

## 2. Scope and exact candidate gate

Inspect the complete diff/commits from the resolved PR base. Map every file to
one behavior/root cause. Multiple commits do not make a multi-feature branch
acceptable.

- Tests, migrations, generated contracts, and docs for one behavior are one
  scope.
- Independent endpoints, roadmap phases, refactors, provider integrations, or
  “while here” fixes are separate scopes.
- Over 500 changed lines requires an explicit atomicity explanation.
- Over 1,000 defaults to split unless generated output or one inseparable
  foundation explains it.

For multiple scopes, preserve the source branch, then create independent or
stacked delivery records in isolated worktrees. Each stacked PR targets its
immediate parent and owns its own candidate/remote evidence. Never close or
rewrite the recovery branch before replacements are reachable.

Require complete candidate evidence for the exact current head:

```bash
python3 "$DELIVERY_PY" show --id "<id>"
git rev-parse HEAD
```

If evidence is absent/stale, align the base, run full repository checks, and
record `delivery candidate` before publication.

## 3. Reuse existing PR

Query the forge for an open PR with this exact head branch before creating one.

- Existing agent-owned PR: update title/body/draft state as needed.
- Open human-owned PR: create a child repair branch/PR unless direct-update
  authority was explicit.
- Closed/merged predecessor: create a new PR from current base and link it.
- Fork PR: do not assume write access to its head.

PR creation is idempotent. Never open a duplicate because a previous process
crashed after the forge write but before local state recording.

## 4. Build repository-native metadata

Honor the repository PR template, required labels/reviewers, contribution
token/instructions, and forge conventions. The body records:

- problem/root cause and one scope;
- out-of-scope adjacent work;
- stack parent/children and merge order;
- exact base and head SHAs;
- exact local verification and remote-check status;
- risk and rollback;
- proposed merge strategy and why;
- whether intermediate commits are review checkpoints;
- required agent/runtime disclosure.

Do not include secrets, raw auth endpoints, machine-private paths, or claims of
independent human approval.

Draft only when requested, repository policy opens drafts early, or remote CI
must run before ready.

## 5. Publish and record

Push with an explicit same-name refspec/upstream only under recorded push
authority. Then create or update the PR through the selected forge adapter.

Record the result:

```bash
python3 "$DELIVERY_PY" publish \
  --id "<id>" --pr <number> --url "<url>" \
  --base "<resolved-base>" --head-sha "$(git rev-parse HEAD)" [--draft]
```

If recording fails after PR creation, re-query by head and repair the existing
record; do not create another PR.

Wait for this PR's remote checks. Fix failures with new checkpoint commits,
rerun full candidate verification for the new SHA, push, and update the same
PR. Completion reports the URL, base/head, stack position, exact evidence, and
remaining external review—not “ready” while gates are pending.

## Codex surface adapter

# Codex surface adapter

- Installed Clade plugin skills are namespaced. Invoke this workflow as
  `$clade:delivery`, and use `$clade:<skill-name>` for companion workflows.
- Read the closest applicable `AGENTS.md`; read legacy `CLAUDE.md` only when it
  is trusted repository guidance.
- Codex-managed worktrees may begin at detached HEAD. A local detached commit
  is valid, but create/attach an owned branch or preserve a reachable Clade ref
  before the runtime deletes the worktree.
- Inspect `git worktree list --porcelain` before checkout, rewrite, or cleanup:
  one branch cannot be checked out by multiple worktrees.
- Use Codex native review/worktree/handoff capabilities where available. Do
  not launch Claude Code or a nested Codex CLI to emulate the workflow.
- Project configuration is trust-gated. Provider credentials and user
  connections remain user-scoped and cannot be donated by repository files.

## Additional skill reference

# Create or update PR

Publish one independently reviewable and reversible delivery unit. Use the
shared `$clade:delivery` context/state controller; do not assume GitHub, `origin`,
`main`, branch ownership, or autonomous PR authority.

**One PR = one independently reviewable and reversible delivery unit.**

Tests, migrations, generated files, and documentation for that same behavior
belong together. Independent behavior becomes independent or explicitly
stacked delivery records.
