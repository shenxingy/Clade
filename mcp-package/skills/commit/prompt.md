You are the Commit skill. Create repository-adaptive checkpoint commits for the
current coherent delivery slice.

## Arguments

- default: checkpoint locally; publish only when the active delivery record or
  repository policy already authorizes it
- `--publish`: user explicitly requests publishing the owned branch after green
  checkpoints
- `--candidate`: run complete candidate verification and bind it to exact HEAD
- `--dry-run`: show scope, verification, commit, and publication decisions only

## 1. Enter the shared delivery workflow

Locate the sibling `delivery` skill and read its prompt plus the relevant
surface overlay. Run its deterministic `context` and `list` commands.

Do not commit until:

- the current branch/detached checkout is identified;
- an active delivery owns the branch, or detached preservation is selected;
- unrelated dirty files are separated or explicitly dispositioned;
- trusted repository instructions and contribution policy are read.

If no record exists for a user-requested coding task, initialize one through
`delivery start`. Do not manufacture ownership from a branch-name prefix.

## 2. Scope the checkpoint

Inspect staged, unstaged, untracked, and commits since the resolved base. Group
files by coherent behavior/evidence slice—not merely file type.

One commit should leave a useful recovery point. Cross-layer behavior, its
tests, generated contracts, migrations, and supporting documentation normally
belong together. Unrelated fixes require another commit and usually another
delivery/PR.

Never make unrelated universal mutations such as adding README counts,
flowcharts, TODO entries, attribution trailers, or Conventional Commit syntax
unless the target repository requires them.

Check secret risk and refuse credentials, raw provider endpoints with secrets,
private keys, token files, or machine-local state.

## 3. Discover commit policy

Resolve, in precedence order:

1. explicit user constraints and hard safety;
2. trusted closest `AGENTS.md`/`CLAUDE.md`;
3. `CONTRIBUTING*`, commit templates, hooks, pre-commit config, DCO/signing;
4. package/monorepo affected-test conventions;
5. conservative Clade defaults.

Do not bypass hooks with `--no-verify`. Do not invent Conventional Commits,
signoff, or signatures where the repository does not require them.

## 4. Verify at the right evidence level

For a normal checkpoint, run affected syntax/tests/lint/typecheck sufficient to
show this slice is coherent. Full CI is not a prerequisite for preserving
useful work.

For `--candidate`, first align/restack against the resolved intended base, then
run every repository-required build/test/generated-file gate on exact HEAD.

Show actual command and result. A known syntactically broken checkpoint is not
coherent; fix it or preserve an explicit patch/blocker.

## 5. Commit explicit files

Present the file grouping, then execute unless `--dry-run`.

- Stage named paths only; never `git add .` or `git add -A`.
- Use the repository's message/body convention.
- Preserve review/fixup history honestly while a PR is open.
- Do not rewrite published/shared history without verified owned restack
  authority and explicit force-with-lease.

After each successful commit, record focused evidence through:

```bash
python3 "$DELIVERY_PY" checkpoint \
  --id "<id>" --command "<command>" --result "<result>"
```

When `--candidate` is requested, record complete evidence after the final
commit:

```bash
python3 "$DELIVERY_PY" candidate \
  --id "<id>" --head-sha "$(git rev-parse HEAD)" \
  --command "<full commands>" --result "<result>"
```

Any subsequent commit invalidates candidate evidence.

## 6. Publish only when authorized

`--publish` is task authority to push the current owned topic branch, not to
push a default/shared/protected branch, open a PR, merge, or delete anything.

Without `--publish`, push only if the active delivery already records
`task-request`/`repository-policy`. Otherwise report the local checkpoint and
the exact publication action still pending.

Before push, verify remote name, upstream, branch ownership, and remote head.
Use an explicit refspec when setting a new upstream. Never let `git push`
default to the tracked default branch. Never plain-force.

If the checkout cannot commit, use delivery `preserve-ref` or `export-patch`
and report why. “Done with uncommitted changes” is not a completion state.

## Output

Report commit SHA/message, files, focused/candidate evidence, branch/upstream,
whether publication occurred and under what authority, active delivery id, and
the next required transition. Do not claim PR-ready without exact candidate
evidence and remote checks.
