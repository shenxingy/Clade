## Adaptive Delegation

Before broad repository reads, decide whether the task is better handled by the
lead or one direct subagent.

- Keep architecture, ambiguous requirements, security-sensitive changes,
  migrations, broad refactors, and work without a deterministic verifier in the
  lead session.
- Delegate bounded read-heavy discovery to `clade_cheap_explorer` when available.
- Delegate one low-risk implementation to `clade_cheap_worker` only when file
  ownership and a deterministic verifier are explicit.
- Use at most three subagents for genuinely independent read-only work. Never
  run concurrent writers on the same files, and do not edit a delegated file
  until its owner returns.
- Subagents must not delegate recursively. Permit one cheap retry at most; then
  the lead resumes with the collected evidence.
- The lead reviews every returned diff and verifier result before acceptance.
- Cross-vendor delegation is explicit-only; do not silently launch another
  vendor's CLI.

Use `gpt-5.6-terra` as the default cheap Codex tier. Spark is opt-in only because
availability depends on the user's plan; never assume it exists.

## Delivery Completion

For any task that changes files or external state:

- Before the final response, inspect the real final state (at minimum
  `git status`) and enter `$clade:delivery` when it is installed and a
  repository delivery is in scope. Otherwise follow the repository's native
  checkpoint and publication process.
- Never report `DONE` while task-owned changes are uncommitted. Create a
  repository-compliant commit or preserve the work through the delivery
  workflow when committing is unavailable.
- Use the user request and trusted repository policy to decide whether push,
  PR, merge, deployment, or live verification is required. Never silently
  downgrade a live-URL or deployed-service task to local-only work.
- If a required publication or deployment cannot be completed because
  authority, credentials, destination, or external state is missing, report
  `BLOCKED` or `NEEDS_CONTEXT` instead of declaring completion with a
  commit/push/deploy caveat.
