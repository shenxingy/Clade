<command-metadata>
name: tasks
contract: clade.tasks/v1
completion-status: DONE | DONE_WITH_CONCERNS | BLOCKED
</command-metadata>

Resolve this skill's `scripts/tasks.py` as TASKS_PY. Use the current Python
interpreter; no nested model CLI or MCP execution bridge is needed.
Global `--repo` and `--timeout` arguments go before the subcommand. All output
is JSON. Exit 2 means failure, not an empty queue.

## Connect and identify

First run `snapshot`. If this repository has no binding, follow
`references/service.md`. A binding is private and lives in the Git common
directory: every worktree shares it. Each separate clone must bind explicitly
to a workspace targeting the same live project database. The operator supplies
the expected project ID. Credentials and service addresses stay outside Git.

Create one identity per independent session/attempt:

```bash
python3 "$TASKS_PY" session --runtime codex
python3 "$TASKS_PY" session --runtime claude --parent-session PARENT_SESSION_ID
python3 "$TASKS_PY" session --runtime kimi
python3 "$TASKS_PY" session --runtime human
```

Retain the returned `session_id` as TASK_SESSION. A child agent gets a fresh ID
and its caller's parent ID; it never inherits its caller's ownership identity.
IDs are correlation data, not user authentication. Sharing service credentials
is sharing write authority within that personal/trusted-team service.

## Plan and claim

Translate the goal into small reviewable outputs, explicit acceptance criteria,
dependencies and literal owned files/directories. Use `references/plan.json`.
`depends_on` means the named task must be accepted first. List only real
dependencies: independent tasks should remain independent. Coordinate overlaps
across existing plans before importing; the built-in scope validator checks
overlaps within this plan and is not a filesystem lock or resource scheduler.

```bash
python3 "$TASKS_PY" plan --session "$TASK_SESSION" --file plan.json --dry-run
python3 "$TASKS_PY" plan --session "$TASK_SESSION" --file plan.json
python3 "$TASKS_PY" ready
python3 "$TASKS_PY" claim TASK_ID --session "$TASK_SESSION"
```

Import is atomic. Retrying the same plan returns its IDs; changing the content
under an existing plan ID is refused. Choose a new ID for a revised/new graph.
Claiming a specific task uses Beads' atomic *ready claim*, so blockers and the
winning assignee are evaluated together. Read the claim result before editing.
After an uncertain timeout inspect `show TASK_ID`; do not blindly repeat a
write or create a replacement local database.

For code work use `/worktree` and `/delivery`. Pass the exact task reference to
delivery start alongside its existing branch/base/owner arguments:

```text
--project-id PROJECT_ID --task-id TASK_ID --session-id TASK_SESSION
```

These are separate from an orchestrator `attempt_id`. One mutable worktree per
writer remains required. The task helper does not create or merge worktrees.

## Work, hand off and review

Refresh `heartbeat TASK_ID --session "$TASK_SESSION"` while working. No
background reclaimer is enabled. Lease expiry is a stale observation, not
permission to steal work; human assignments are not recycled automatically.

For a cooperating handoff, preserve code through delivery, then:

```bash
python3 "$TASKS_PY" handoff TASK_ID --session "$TASK_SESSION" \
  --to-session NEW_SESSION_ID --expected-status in_progress \
  --context 'Checkpoint, remaining work and exact resume instructions'
```

The recipient calls `claim` with its fresh registered session ID to attach
its runtime metadata. An unexpected owner/status change rejects the old worker.
For a crashed holder, the operator first inspects its worktree/checkpoints and
uses Beads' explicit holder-guarded reassignment with a fresh session ID; this
adapter does not automatically reclaim tasks.

Submit a clean committed checkout after running the real verification:

```bash
python3 "$TASKS_PY" submit TASK_ID --session "$TASK_SESSION" \
  --head FULL_COMMIT_SHA --verification 'exact command' --result 'observed result' \
  --delivery-id DELIVERY_ID
```

`--delivery-id` is optional for a human/manual checkpoint. When present it must
match this task, project, session and commit in the local delivery record.
The helper records the provided evidence; it does not run that command or
certify the prose result. A submitted task stays blocked pending review.

A different reviewing session checks the acceptance criteria and exact commit:

```bash
python3 "$TASKS_PY" accept TASK_ID --session REVIEW_SESSION_ID \
  --holder WORKING_SESSION_ID --head FULL_COMMIT_SHA --review 'evidence checked'
```

Use `request-changes` with the same arguments to return it to the working
session. Each submission has a new review holder, so a stale review cannot
accept a later submission even when the original worker and status match.
Acceptance releases dependencies; it does not grant push/PR/merge authority.
If acceptance requires merged code, verify that through delivery before accepting.

## Observe

`snapshot`, `ready`, `show TASK_ID` and `history TASK_ID` use strict read-only
Beads calls. `snapshot` carries project/task/session/parent identity, progress
states, heartbeat observations and commit/delivery links. It omits private
workspace and connection configuration. Report unavailable/stale observations
honestly; do not equate missing heartbeat with a dead agent.

Finish with the actual task IDs, state and verification evidence. Follow
`/delivery` for repository changes, including checkpointing task-owned files.
