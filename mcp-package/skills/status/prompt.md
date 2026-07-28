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
