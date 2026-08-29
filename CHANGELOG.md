# Changelog

All notable Clade releases are documented here. The project follows semantic
versioning for the `clade-mcp` Python package and tagged public releases.

[中文](CHANGELOG.zh-CN.md)

## Unreleased

### Security

- A worktree bounds the working tree, not `.git`. From inside a worker's
  worktree, `git rev-parse --git-common-dir` resolves to the parent repository,
  so an agent could write `<main>/.git/hooks/pre-commit` and have it execute on
  the operator's next commit. Workers now snapshot the parent repo's hooks and
  config before spawning and refuse to verify or commit if either moved
  (`worker_git_surface_guard`, default on)
- `install.sh` upgrades never received the deny rules. `templates/settings.json`
  ships `Read(~/.ssh/**)`, `Read(~/.aws/**)` and `Read(~/**/.env)`, but the
  merge path wrote only `.hooks` and `.statusLine`, so every machine installed
  before the deny list existed kept `permissions: null` — while spawning
  workers with permissions bypassed, where deny rules are the last remaining
  bind. The union is deny-only; a user's own `allow` list is never widened
- Git worktree isolation failed open. Every failure path discarded git's stderr
  and left the worker on the shared checkout; it now raises rather than run an
  unsandboxed agent in the operator's own tree (`worker_require_worktree`)

### Added

- Workers report their own spend: spawns carry `--output-format stream-json`
  and `orchestrator/agent_output.py` reads `total_cost_usd`, per-model
  `modelUsage`, and real token counts back, projecting the event stream to
  prose so every existing log consumer is unaffected
- Per-model pricing (`config.py:_MODEL_RATES`) replaces a flat Sonnet rate that
  understated Opus 1.67x and overstated Haiku 3x on the figure the token budget
  and the routing break-even analysis both depend on
- A `quota_exhausted` error class. A spent balance and a spent usage window
  both returned 429 and were retried on a 30s backoff until the run's budget
  ran out; both now abort
- Stopping a worker preserves its work as a `wip:` commit on its own branch
  before the worktree is force-removed — including on the automatic loop-detection
  and stuck-timeout paths, where nobody is watching
- Three gates that run the real thing rather than assert its spelling:
  `check-cc-plugin-components.sh` loads the plugin and compares the resolved
  inventory to the tree, `check-ci-checklist.py` compares the documented
  pre-commit list against the gates CI invokes and rejects a documented command
  that cannot execute, and `regen-settings-example.py` generates the settings
  reference from `_SETTINGS_DEFAULTS`
- `frontend-design` became a platform-aware interface pipeline covering web,
  Apple, Android, Windows, cross-platform and presentation surfaces

### Changed

- `opus` and `sonnet` aliases resolve to Opus 5 and Sonnet 5; superseded ids
  stay accepted so existing task rows and evidence bundles keep resolving.
  `configs/models.env` is now sourced by `loop-runner.sh` instead of being
  shadowed by a hardcoded `claude-sonnet-4-6`
- Orchestrator worktrees moved out of `.claude/worktrees/`, which Claude Code
  claims as its own managed pool and deletes along with a session

### Fixed

- The Claude Code plugin advertised 37 agents and 14 hooks and loaded none of
  them: `agents` as an array of file paths is schema-valid and resolves
  nothing, and `plugin validate --strict` exits 0 on it
- The memory watchdog matched none of the commands the orchestrator builds —
  its pattern required a token between `claude` and `-p` — so it freed nothing
  under memory pressure. It also signalled the `sh -c` wrapper rather than the
  agent, and ordered by pid rather than age
- The worker activity heuristic read a transcript path Claude Code has never
  written, and its test built that same wrong layout, so it stayed green while
  always returning "unknown"
- A GitHub issue-create timeout forked one task into a growing pair of
  duplicates; `task_id` was stamped into every issue body and never read back
- `/brief` probed `localhost:4000`; the orchestrator binds 8765
- Two consumers parsed `.claude/loop-state` as KEY=VALUE while `loop-runner.sh`
  writes JSON to `.claude/loop-state.json`, so the session-start loop banner
  was silently empty. `converged` is now persisted rather than left a shell local
- Every session start injected model guidance naming a superseded generation

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

- Reinstalling now mirrors each repo-managed skill subtree exactly, removing
  stale or accidentally nested content while preserving unrelated user-owned
  skill directories
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
