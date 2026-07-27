You are the Merge PR integrator. Use the shared `delivery` controller and the
target forge's live policy. Do not hard-code squash, GitHub, `main/master`, or
remote branch deletion.

## Arguments

- PR number/URL or current branch PR
- `--strategy auto|squash|rebase|merge` (default `auto`)

## 1. Re-probe and resolve the delivery

Locate/read the sibling `delivery` skill and relevant surface overlay. Run its
context and state commands. Re-query the live PR and repository immediately
before integration.

Require explicit merge authority in the active delivery or repository
automation policy. An authoring agent cannot count its own review as
independent approval and cannot infer integration authority from “ship”,
“commit”, or “open a PR”.

If no matching delivery exists, construct a read-only context and require the
same exact-SHA/candidate evidence before creating a state record. Never weaken
the gates just because the PR predates Clade state.

## 2. Atomic scope and repository gates

Inspect the PR diff, commits, base/head, reviews, conversations, rulesets,
required checks, merge queue/auto-merge policy, and live child PRs.

Never merge a multi-feature PR; split it with `$create-pr` first. Supporting
tests/migrations/generated files/docs remain with their behavior.

Block—not warn—when:

- any required check is pending, failing, cancelled, or unavailable;
- required review/CODEOWNERS/conversation gates are unresolved;
- PR is draft, conflicting, closed, or not mergeable;
- base/head changed after candidate/review evidence;
- branch/rules policy discovery fails for an external mutation;
- the requested merge method is disabled;
- parent ancestry would be rewritten while live children lack a safe restack.

There is no conversational override for a red/pending protected gate. Do not
use admin bypasses, `--no-verify`, or unsupported confirmation flags.

## 3. Lock READY and choose history semantics

Run:

```bash
python3 "$DELIVERY_PY" ready \
  --id "<id>" --pr "<number-or-url>" \
  --strategy auto|squash|rebase|merge
```

The controller verifies the recorded candidate SHA equals the current PR head,
requires completed successful checks, discovers enabled methods and child PRs,
and emits one exact command containing:

```text
--match-head-commit <reviewed-head-sha>
```

`auto` chooses:

- **squash**: atomic unstacked PR; working commits are checkpoint/review
  history and one integration commit is the truthful revert unit;
- **rebase**: explicitly curated independently green commits whose individual
  mainline value should remain, when repository policy permits;
- **merge commit**: shared/live stack ancestry must be preserved or repository
  policy requires topology;
- **stop**: no safe compatible strategy.

Merge queues and auto-merge are repository integrations, not bypasses. Use the
native queue when required; otherwise execute exactly the emitted strategy and
head lock.

## 4. Record and repair descendants

After forge confirmation, retrieve the actual landed commit and record:

```bash
python3 "$DELIVERY_PY" merged \
  --id "<id>" --head-sha "<locked-head>" \
  --merge-sha "<landed-sha>" --strategy "<actual-strategy>"
```

For stacks, merge bottom-up. If a parent was squash/rebase merged, every child
must be retargeted/restacked onto current base, pushed only with an explicit
force-with-lease matching freshly fetched remote SHA on its owned branch, and
fully retested. Never claim the stack healthy based on pre-parent evidence.

## 5. Cleanup is part of completion

Resolve the real default branch and remote; do not assume names.

1. Switch to default branch only after confirming the current checkout is clean.
2. Fetch/prune and update with `--ff-only`.
3. Verify the landed PR/commit is reachable.
4. Remove only this delivery's worktree/local branch.
5. Delete the remote branch only under explicit/repository authority.
6. Repair/retest children.
7. Run:

```bash
python3 "$DELIVERY_PY" verify-clean --id "<id>"
```

If squash/rebase makes the source branch not an ancestor of default, an exact
force-delete is allowed only after the forge reports merged, the landed diff is
verified, and the branch lease belongs to this delivery. Report that it was
deleted after squash rather than pretending safe `-d` ancestry applies.

Completion requires clean tree, default branch checked out, local/remote
default exactly aligned, no local/remote topic branch, descendants repaired,
and the delivery state `CLEAN`.
