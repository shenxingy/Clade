**English**（中文版尚未提供 — [README 中文版](../README.zh-CN.md)）

← Back to [README](../README.md)

# Compatibility retirement

Clade uses evidence from a compatibility window before deleting persisted or
public fields. Passing current tests is not evidence that an older settings
file, SQLite database, or API client no longer exists.

## Current runtime-field migration

`agent_runtime` is the only runtime identity used by routing, workers, status
serialization, telemetry, and the web application.

- On startup, a settings file containing only `worker_provider` is rewritten
  once with `agent_runtime`. If both exist, the canonical field wins and a
  conflict is logged.
- On database initialization, historical task rows with an empty
  `agent_runtime` are backfilled from `provider`. New rows write only
  `agent_runtime`; task responses no longer serialize `provider`.
- Settings and Tasks APIs temporarily accept the old input names. Such calls
  return `Deprecation: true` and a `Warning: 299 Clade ...` header.
- `GET /api/compatibility` returns aggregate counters for the current window.
  The file contains only an allowlisted event identifier, count, and
  timestamps. It never records field values, endpoints, profiles, or secrets.

The compatibility file is
`~/.claude/compatibility-telemetry.json` with owner-only permissions.

## Removal gate

Delete the remaining input aliases and the historical SQLite column only in a
major or otherwise announced compatibility release after all of these are
true:

1. at least one stable release has completed with zero
   `settings.worker_provider`, `tasks.api.provider`, and
   `tasks.sqlite.provider_backfill` events;
2. supported Claude, Codex, MCP, and generic surface conformance remains green;
3. the operator has migrated every configured settings file and task database;
4. old inputs fail with a documented, deterministic client error before the
   SQLite table-rebuild migration drops `tasks.provider`.

`usage_provider`, `provider-switch.sh`, MCP `auto` runtime selection, the
`~/.claude/skills` import path, and Codex generator replacements are not part of
this migration. They remain supported behavior until their own native
replacement and release boundary exist.
