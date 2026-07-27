You are the Worktree skill. Use the shared `delivery` context/state controller
and the current runtime surface overlay.

## Invariants

- One mutable branch per live session; one branch cannot be checked out in two
  worktrees.
- Parallel writers receive separate worktrees/clones/containers/detached
  snapshots and non-overlapping delivery units.
- Do not write tracked `TASK.md` or other Clade bookkeeping into an arbitrary
  repository. Task/ownership/progress live in Git-common delivery state.
- Completion publishes/reviews through repository policy; it does not locally
  merge every worktree into whichever branch happens to be active.
- Remove only a worktree and branch owned by the selected terminal delivery.

## Create

1. Run `delivery context` and inspect `git worktree list --porcelain`.
2. Resolve the real base/default branch and ensure the source tree has no
   unrelated dirty changes.
3. Choose the runtime-native isolation:
   - normal local Git: explicit worktree path plus owned topic branch;
   - Codex-managed worktree: detached start is valid; attach a branch only for
     preservation/publication;
   - cloud/CI: runtime-provided clone/container;
   - unsupported client: report required isolation instead of sharing a branch.
4. Create a delivery record containing task source, base SHA, owner, optional
   stack parent, runtime, surface, and publication authorities.
5. Pass the task through runtime-native context/handoff, not a tracked project
   file.

Before filesystem creation, resolve an explicit safe destination outside the
repository root. Never derive a destructive target from an empty variable,
home directory, workspace root, or broad glob.

## List

Combine:

- `git worktree list --porcelain`;
- active `delivery list`;
- each worktree's branch/detached HEAD, dirty state, owner, delivery state,
  base/head SHA, and last checkpoint.

Mark stale/prunable/unknown ownership; do not mutate it during list.

## Preserve/handoff

Before runtime termination, context switch, compaction, or provider handoff:

- commit coherent work and record focused checkpoint evidence;
- for detached committed work, run `delivery preserve-ref`;
- when commits are prohibited, run `delivery export-patch`;
- record reduced-fidelity handoff when native session resume is unavailable.

No worktree may be auto-removed while its head is unreachable or dirty state
lacks a patch/blocker.

## Integrate

Route the worktree's independently reviewable result through `$create-pr`,
`$review-pr`, and `$merge-pr`. A throw-away integration worktree may test
several candidate heads, but durable work must never be based on it and it is
never itself merged as a product change.

For explicit stacks, record parent relationships, merge bottom-up, and restack
each child after parent ancestry changes.

## Clean

1. Re-probe worktrees and active delivery state.
2. Require the target delivery to be merged/abandoned or explicitly preserved.
3. Verify no dirty/unreachable work and no other live owner.
4. Remove the exact worktree path.
5. Delete only its exact owned local branch; delete remote only with authority.
6. prune stale metadata and run delivery cleanup verification where applicable.

Never use broad `--clean all`, branch-prefix glob deletion, or force removal
without resolving every target and its recovery state.
