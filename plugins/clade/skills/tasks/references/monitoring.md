# Observation contract and the future Web monitor

The existing Web Orchestrator remains dormant and preserved. The next intended
role is a monitor of work performed by native sessions and their child agents.
Beads remains authoritative for task ownership and dependencies; delivery
remains authoritative for Git evidence. Do not copy tasks into the old SQLite
queue or revive automatic dispatch merely to display status.

`tasks.py snapshot` emits `clade.task-snapshot/v1`:

- `project_id`, `observed_at`, `source`, `consistency`;
- `ready_task_ids` and `tasks` (empty arrays mean a successful empty query);
- each task's `task_id`, title, state, assignee, acceptance, ownership scope,
  update/heartbeat/lease timestamps and submission evidence;
- session metadata: `session_id`, runtime, `parent_session_id`, started time;
- submitted commit SHA and optional delivery ID, plus handoff context.

States are `open`, `in_progress`, `submitted`, `accepted`, or another explicit
Beads status. A task with stored `open` status is runnable only if its ID is in
`ready_task_ids`. Readiness and the task list are sequential database reads, not
an atomic snapshot: a monitor should tolerate brief differences and refresh.
Claim always rechecks readiness in a transaction, irrespective of this view.

`history TASK_ID` exposes Beads' durable per-task event history. This is not a
global streaming API. A future dashboard can poll snapshots and open a task's
history; a cursor-based event stream requires a separate implementation.

Session records are attached to tasks when claimed. Sessions with no task are
not globally discoverable yet. Runtime/provider/model identities are distinct:
only runtime is currently recorded; do not infer provider or model from it.
Parent IDs allow nesting but are caller-provided correlation, not permissions.

Freshness does not prove process liveness. Surface old heartbeats as stale or
unknown. Human work and submitted reviews can legitimately have no heartbeat.
No automatic cancellation, reclaim, retry, launch or merge is part of monitoring.

The observation projection omits connection configuration and local workspace
paths. Titles, descriptions, evidence and handoff text are still project data:
serve the view only to authorized project users. Server credentials grant write
authority; a future untrusted viewer needs a separately enforced read-only
identity/API, not just a hidden button in the UI.
