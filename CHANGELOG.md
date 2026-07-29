# Changelog

All notable Clade releases are documented here. The project follows semantic
versioning for the `clade-mcp` Python package and tagged public releases.

[中文](CHANGELOG.zh-CN.md)

## Unreleased

### Added

- Crash-safe Loop phase recovery with explicit, identity-matched `--resume`;
  normal launches ignore stale checkpoints and `--help` has no side effects
- Fresh Windows Git Bash installs wrap every hook and status-line command
  through `bash.exe`, matching the existing-settings migration path
- `delivery abandon` transition for superseded, unpublished work — requires an
  exact HEAD lease and non-empty reason; published GitHub PR work can only
  abandon after a live check proves the PR is closed at that exact head
- Native `$codex-usage` workflow with Clade's 95%-target pace view
- Credential-safe rate-limit reads through the authenticated Codex app-server
- Idempotent setup for Codex's native five-hour and weekly status-line fields
- Minimal, optional-icon, and detailed styles; ten themes; and JSON output

### Fixed

- Loop completion is now coordinator-owned and fail-closed: exact task-to-goal
  evidence is reconciled only after worker, syntax, test, and final verification
  gates pass; worker-created commits count even when the leftover sweep is empty,
  and serial/parallel worker failures propagate as non-zero exits
- Loop supervisor CLI failures now preserve the raw provider response and stop
  once with a distinct resumable `supervisor_failed` outcome instead of being
  retried as empty plans and mislabeled `max_iterations`; the runner exits
  non-zero for this and other terminal execution failures
- Loop planning now keeps raw supervisor output, extracts nested JSON safely,
  bounds planner tools, initializes custom log directories before checkpoint
  work, verifies only current-iteration changes, shares one task JSON parser,
  and dispatches recovery tasks in the worker format
- Routing settings reject `NaN` and infinite thresholds instead of persisting
  values that cannot round-trip through JSON
- `delivery abandon` now discovers PRs by branch instead of trusting a
  possibly stale `published` flag — an unrecorded open PR blocks abandonment,
  and a merged PR at the recorded head is reconciled rather than mislabeled
  abandoned
- Task updates revalidate the effective persisted connection against the
  effective runtime before mutation, instead of only failing at execution time

### Changed

- Generated MCP skill catalogs now match the manifest, and the Codex plugin
  cache version refreshes whenever generated plugin content changes

## [0.2.0] — 2026-07-13

### Added

- Native Codex plugin with 20 generated core workflows
- Codex `SessionStart` context hook and destructive-command `PreToolUse` guard
- Provider-neutral MCP runtime adapter selected with
  `CLADE_RUNTIME=claude|codex|auto`
- Configurable Codex sandbox and an explicit permission-bypass escape hatch
- Deterministic Codex skill generator plus CI drift protection
- English and Chinese documentation for Codex and `clade-mcp` 0.2.0

### Changed

- `clade-mcp` now bundles 32 workflows, up from 29 in 0.1.0
- MCP server and package metadata now report version 0.2.0 consistently
- `clade_list_skills` reports the selected execution runtime
- Root documentation presents Claude Code, Codex plugin, and MCP as separate
  product surfaces

### Compatibility

- Existing MCP installations remain on the Claude runtime by default
- Native Codex users should install the plugin instead of mounting `clade-mcp`
  inside Codex
- The FastAPI multi-worker orchestrator remains Claude-specific in this release

### Upgrade

```bash
pip install --upgrade clade-mcp
```

For native Codex use:

```bash
codex plugin marketplace add shenxingy/Clade
codex plugin add clade@clade
```

## [0.1.0] — 2026-04-02

### Added

- First public Clade release
- Initial `clade-mcp` package with 29 coding workflows and Claude execution
- Claude Code skills, hooks, agents, scripts, and the FastAPI orchestrator

[0.2.0]: https://github.com/shenxingy/Clade/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/shenxingy/Clade/releases/tag/v0.1.0
