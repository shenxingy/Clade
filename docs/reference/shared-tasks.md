# Shared project tasks

`/tasks` (Codex: `$clade:tasks`) coordinates native Codex, Claude Code, Kimi and
human work through one Beads project database. It adds dependency-aware plans,
atomic ready-task claims, explicit session handoffs, and review before downstream
tasks become ready. It does not start model sessions or replace Git delivery.

The canonical implementation and workflow are in
[`configs/skills/tasks`](../../configs/skills/tasks/SKILL.md). Use the
[service guide](../../configs/skills/tasks/references/service.md) for setup and
the [plan example](../../configs/skills/tasks/references/plan.json) for decomposition.

## Decisions

- Task truth is Beads; Git stores code and delivery evidence. Markdown stores
  explanations and handoff context, not distributed ownership locks.
- Pin Beads 1.3.1 / Dolt 2.2.0 and explicit external server mode. The released
  proxied default rejects strict read-only calls, so it is not used for monitoring.
- Each independent execution gets a session ID; child sessions retain a parent
  ID. Claims and status transitions use backend transactions, not local locks.
- An immutable import receipt is created in the graph transaction. Competing
  revisions of one plan ID cannot both commit, even with disjoint task keys.
- Submission remains blocked pending review. A unique review holder per
  submission fences stale reviews, including return/resubmit races by one worker.
- No automatic reclaim in this version. Humans and interrupted agents require
  deliberate handoff/recovery with preserved code.
- Plans validate file/directory overlap within their own dependency graph.
  Cross-plan ownership and real CPU/GPU admission remain separate coordination
  responsibilities. There is no claim of a global filesystem/resource lock.
- Personal and trusted-team service instances have separate credentials. Project
  IDs and session actors provide correlation, not authenticated user isolation.

## Integration

`pickup` consults live claims before resuming a handoff. `worktree` keeps writers
isolated and records task references in delivery. `handoff` preserves the code
and transfers ownership explicitly. `status` reads a snapshot without mutation.
`delivery start --project-id ... --task-id ... --session-id ...` retains an
immutable task reference, separate from any orchestrator attempt ID.

## Future monitoring

The old Web Orchestrator is preserved for a future agent monitor. It can consume
[`clade.task-snapshot/v1` and per-task history](../../configs/skills/tasks/references/monitoring.md)
to show project progress, parent/child sessions, stale observations and delivery
evidence. The Web UI is not wired to this source yet. Monitoring must not create
a second authoritative task queue or launch models just to keep a dashboard alive.

## Verification

Fast tests run in the normal suite. Real backend tests are opt-in and create only
temporary services, repositories and credentials:

```bash
CLADE_TEST_BD=/absolute/bin/bd CLADE_TEST_DOLT=/absolute/bin/dolt \
  orchestrator/.venv/bin/python -m pytest \
  orchestrator/tests/test_shared_tasks_live.py -q
```

That lane requires the pinned binaries; a skipped lane is not evidence of a
working database integration. Production host placement, boot persistence,
remote-team access and a Web dashboard require their own runtime verification.
