# Clade Ground Rules for Codex

## Repository Delivery

- One PR equals one independently reviewable and reversible feature, fix, or
  refactor. Keep its tests, generated contracts, migrations, and documentation
  in the same delivery unit; split independent behavior into separate or
  explicitly stacked PRs.
- Stage and commit only task-owned paths. Preserve unrelated user or agent
  changes, and use the repository's commit convention.
- A commit preserves work but does not grant push, PR, merge, deployment, or
  outbound-message authority. Resolve those transitions from the user request
  and trusted repository policy.

## Verification Discipline

- The local run is the gate; hosted CI is the receipt. Run the repository's
  real documented gates before publication. Use `$clade:green` when installed
  to derive runnable jobs from GitHub Actions instead of maintaining a second
  checklist.
- Never weaken, skip, ignore, or mask a gate merely to make it green. Do not
  append `|| true`, pipe a failing gate into a successful final command, or
  treat an unavailable lane as passing.
- Read complete results before reporting them. Name every skipped or
  unavailable lane and its reason; a partial suite cannot support a claim about
  the whole build.

## Communication and Evidence

- Match response length to the question while keeping paths, commands, flags,
  errors, and measurements exact.
- Separate verified, unverified, and unmeasurable results. Every completion
  claim names the command or live observation that supports it.
- Lead with the outcome, then assumptions and untested boundaries. Surface a
  blocker once with the evidence already gathered instead of retrying blindly.

## Engineering Checks

- Trace settings from definition through read, callsite, and observable effect.
  A documented or parsed setting that never changes behavior is incomplete.
- Check first-run, empty, null, duplicate, concurrent, timeout, and
  cross-platform behavior in proportion to the change.
- Validate untrusted data at the system boundary and keep credentials out of
  commands, logs, committed policy, and model-visible output.
- Source is not deployment, configuration is not loading, and definition is
  not execution. Verify the runtime or deployed artifact when the request is
  about live behavior.

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
