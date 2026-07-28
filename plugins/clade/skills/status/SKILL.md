---
name: status
description: "Show a provider-neutral, freshness-aware snapshot of active Agent work, Git delivery, execution identity, and usage limits. Use for “what's going on right now”, what is running, progress updates, active runtime/provider/model, or stuck-work checks."
---

# Clade for Codex

This package composes the provider-neutral Clade core contract with the native
Codex surface adapter. Run the workflow directly in Codex; do not launch
another agent CLI or route it through Clade MCP.

Package provenance:

- core contract: `clade.status/v1`
- surface adapter: `codex/v1`
- explicit invocation: `$clade:status`
- generated from: `configs/skills/<name>`

## Canonical Clade workflow

<command-metadata>
name: status
contract: clade.status/v1
completion-status: DONE | DONE_WITH_CONCERNS | BLOCKED
</command-metadata>

Build one compact status snapshot from sources available on the current
surface. Keep collection read-only.

## Required semantic fields

- `observed_at`
- task identity/state and progress `{completed,total,source}`
- Git branch, dirty state, checkpoint SHA, upstream divergence
- execution runtime, connection, inference provider, wire model, degradations
- usage/rate-limit observations with source and observed/reset timestamps
- freshness per source

Unknown is a first-class value:

- Never render missing progress or quota data as `0`, `0%`, unlimited, or done.
- Never infer a provider from a model prefix or a model from the runtime name.
- Mark estimates explicitly and show the evidence behind them.
- Distinguish stale data, unreachable sources, unsupported capabilities, and
  authoritative zero values.

## Collection order

1. Read conversation/runtime activity exposed by this surface.
2. Inspect local Git without mutation. Prefer the delivery controller's
   `git_context.py` when installed; otherwise use read-only Git commands.
3. Read Clade worker `status_snapshot` / `execution_envelope` if an
   orchestrator is reachable.
4. Query forge/CI only when a related PR is in scope.
5. Query native usage data only through the current surface adapter.

## Output

Keep the human view under 20 lines unless the user asks for JSON. Show:

```text
Work:       state · factual progress or unknown · freshness
Git:        branch · dirty/clean/unknown · checkpoint/upstream
Execution:  runtime · connection · inference provider · wire model
Limits:     authoritative windows, or unknown/unavailable with reason
Delivery:   PR/checks/merge state when in scope
Concern:    stale/hung/degraded evidence, if any
Next:       one concrete recommendation
```

Call work “hung” only when a source provides timestamps and no relevant change
has occurred past the repository/runtime threshold. Do not kill, restart,
commit, push, or merge from this read-only skill.

## Completion

- `DONE`: snapshot is clear and all relevant sources were observed.
- `DONE_WITH_CONCERNS`: one or more sources are stale, unavailable, or
  degraded; name them.
- `BLOCKED`: even local/runtime state cannot be read; show the exact failure.

## Codex surface adapter

# Codex status adapter

- Invoke the installed plugin workflow explicitly as `$clade:status`; bare
  `$status` is not the Clade plugin identity.
- Use Codex task/tool activity exposed in the current conversation.
- Codex TUI status-line configuration is an ordered list of native fields, not
  an arbitrary command renderer. Do not claim Claude-style custom rendering.
- Use `$clade:codex-usage --json` when installed for authenticated native limit
  observations; otherwise report limits as unavailable/unknown.
- Read applicable `AGENTS.md` and trusted legacy `CLAUDE.md` guidance before
  interpreting repository-specific progress.
- Do not launch a nested Codex CLI to discover status.

## Additional skill reference

# Status

Render one `clade.status/v1` snapshot. Separate observed facts from estimates,
attach source/freshness, and preserve unknown values as unknown. Read
`prompt.md` for the core contract and only the current runtime file under
`surfaces/` for collection mechanics.

## Delivery completion

If this workflow changes files or external state:

- Inspect the real final state before responding, including `git status` for a
  repository task.
- Never report `DONE` while task-owned changes are uncommitted. Use or continue
  `$clade:delivery` and create a repository-compliant checkpoint or preserve
  the work when committing is unavailable.
- When the user request or trusted repository policy makes publication,
  deployment, or live verification part of the task, do not silently downgrade
  the result to local-only work.
- If a required delivery transition lacks authority, credentials, a destination,
  or reachable external state, report `BLOCKED` or `NEEDS_CONTEXT` rather than
  appending a "not committed/pushed/deployed" caveat after `DONE`.
