# Changelog

All notable Clade releases are documented here. The project follows semantic
versioning for the `clade-mcp` Python package and tagged public releases.

[中文](CHANGELOG.zh-CN.md)

## Unreleased

## [0.3.1] — 2026-09-02

### Security

- The orchestrator control plane required no authentication. Every route and
  both WebSockets answered anyone who could open the socket, and `start.sh`
  binds `0.0.0.0` whenever it detects Tailscale — the documented way to run
  the server — so "it is only on loopback" was never true. Any mutating route
  can open a session whose workers run with permissions bypassed as the
  account that started the server, and `GET /api/settings` returned
  `webhook_secret` and the usage-hub tokens verbatim. A bearer token is now
  required by ASGI middleware, which — unlike `BaseHTTPMiddleware` — also sees
  WebSocket scopes. Default-closed on the same terms already set for
  `webhook_secret`: no token configured means reject, unless
  `api_allow_unauthenticated` says otherwise. The token is minted on first
  start into the settings file the saver already chmods 0600. Three exemptions
  are argued in `orchestrator/api_auth.py`: the SPA shell and the version
  probe, the signed GitHub webhook, and usage ingest — but only while
  `usage_ingest_token` is set, which closes that endpoint's old
  empty-means-open default rather than inheriting it
- Settings secrets are masked by key-name suffix on the way out, and a save
  that echoes a mask back leaves the stored value alone. The settings panel
  round-trips the whole object, so without that the first save would have
  overwritten every secret with its own mask
- CORS admitted every origin. `allow_origins` is an exact-match list, so the
  `http://localhost:*` default matched nothing while the regex beside it
  granted the request on its own. The regex now covers `https` (a TLS front
  end is no longer silently blocked) and is pinned to Tailscale's actual CGNAT
  range `100.64.0.0/10` — it had held a CORS grant over all of `100.0.0.0/8`,
  most of which is publicly routable. Configured origins are whitespace-stripped
  before the exact-match compare, so ` http://b` from a space-separated value
  no longer silently matches nothing
- A worktree bounds the working tree, not `.git`. From inside a worker's
  worktree, `git rev-parse --git-common-dir` resolves to the parent repository,
  so an agent could write `<main>/.git/hooks/pre-commit` and have it execute on
  the operator's next commit. Workers now snapshot the parent repo's hooks and
  config before spawning and refuse to verify or commit if either moved
  (`worker_git_surface_guard`, default on)
- That escape is now prevented as well as detected: an optional Landlock
  ruleset makes the shared `.git/hooks` and `.git/config` unwritable to the
  worker process itself (`worker_sandbox`, default off)
- `install.sh` upgrades never received the deny rules. `templates/settings.json`
  ships `Read(~/.ssh/**)`, `Read(~/.aws/**)` and `Read(~/**/.env)`, but the
  merge path wrote only `.hooks` and `.statusLine`, so every machine installed
  before the deny list existed kept `permissions: null` — while spawning
  workers with permissions bypassed, where deny rules are the last remaining
  bind. The union is deny-only; a user's own `allow` list is never widened
- Git worktree isolation failed open. Every failure path discarded git's stderr
  and left the worker on the shared checkout; it now raises rather than run an
  unsandboxed agent in the operator's own tree (`worker_require_worktree`)
- The worker secret denylist shipped empty, so it never once applied and
  nothing was ever redacted out of persisted worker output
- A webhook signature proves an event came from GitHub, not that its author may
  direct a permission-bypassed worker. Webhook-triggered work is now gated on a
  fail-closed actor check computed from the payload itself
  (`orchestrator/webhook_trust.py`) — there is no API call in the path that
  could fail open
- The two workflows that run on fork pull requests were the two that skipped
  SHA pinning, and they are the ones that run with write scopes. Every `uses:`
  is a commit SHA now, enforced by `configs/scripts/check-action-pinning.py`
- The destructive-command guardian matched substrings rather than command
  positions, and never actually blocked `rm -rf ~`. It now also blocks the
  `pkill -f` pattern that kills its own launcher

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
- A worker had no record between its single verification commit and the forced
  removal of its worktree, so "correct at call 14, wrong at 15" was not
  observable. `worker-checkpoint.sh` now commits the whole worktree into a
  shadow repository outside it, once per agent write, under a separate
  `--git-dir` so checkpoints cannot contend with the worker's own index. The
  final SHA and count land in the evidence bundle before cleanup deletes the
  repo (`worker_checkpoint_shadow`)
- Attempt evidence is now an immutable, versioned `clade.evidence/v1` record
  with a digest chain, written incrementally. Verification used to land in one
  terminal write, so a crash lost the record of where it went wrong
- `configs/scripts/red-phase-audit.py` runs the tests a commit *adds* against
  its parent: one that already passes needed nothing from the change. It is a
  diagnostic, not a gate, and fires on roughly 17% of commits here.
  `--self-test` asks the instrument whether it can still go red — a harness
  that cannot fire reports a clean 0% exactly like a clean codebase, which this
  repo has shipped before — and CI runs that control pair on every push
- The reward-hacking gap is measured rather than asserted: the test-integrity
  detector is scored against a labelled adversarial corpus (`evals/hack_cases/`,
  60% to 100% recall and 27% to 7% false alarms), its per-signal counts are fed
  to the oracle instead of auto-failing, and the resolve eval re-runs held-out
  tests so a patch that games the visible suite reports GAMED, not RESOLVED
- Output styles (`configs/output-styles/`) — the one primitive that edits the
  *system* prompt rather than appending a user message, so it reaches turns
  `CLAUDE.md` cannot. All ship `keep-coding-instructions: true`, and
  `install.sh` activates none of them; selection stays the user's
- `/radar` — three-lane discovery of unknown-unknowns (the field, practitioners,
  your own usage) — plus `radar-cron.sh` for a durable unattended weekly sweep
- `/outbound` — verify artifacts before they leave the building
- `/loop` runs are bounded by wall clock (`--max-runtime`, default 8h) and by
  spend (`--max-cost`), both checked between iterations, plus crash-safe phase
  recovery with explicit, identity-matched `--resume`: normal launches ignore
  stale checkpoints and `--help` has no side effects
- Müller-Brockmann grid and Vignelli canon design skills, absorbed under MIT,
  and `design-lint` — a rendered-output validator that resolves CSS custom
  properties before contrast checks and catches inherited-colour contrast
  across inversion bands
- `frontend-design` became a platform-aware interface pipeline covering web,
  Apple, Android, Windows, cross-platform and presentation surfaces
- Gates that run the real thing rather than assert its spelling:
  `check-cc-plugin-components.sh` loads the plugin and compares the resolved
  inventory to the tree, `check-ci-checklist.py` compares the documented
  pre-commit list against the gates CI invokes and rejects a documented command
  that cannot execute, `regen-settings-example.py` generates the settings
  reference from `_SETTINGS_DEFAULTS`, `check-references.py` resolves every
  markdown link, anchor and path, `check-arch-map.py` fails on an orchestrator
  module missing from the architecture map, and `doc-align.py verify` gates the
  counts the docs derive from the tree
- The correction-pairing pipeline gained the collaboration root causes measured
  by arXiv:2605.29442 — inaccurate self-reporting and constraint violation are
  now promotable — and promotion into the global `CLAUDE.md` is gated on
  root-cause severity rather than on how long a rule survived
- Fresh Windows Git Bash installs wrap every hook and status-line command
  through `bash.exe`, matching the existing-settings migration path
- `delivery abandon` transition for superseded, unpublished work — requires an
  exact HEAD lease and non-empty reason; published GitHub PR work can only
  abandon after a live check proves the PR is closed at that exact head
- Native `$codex-usage` workflow with Clade's 95%-target pace view,
  credential-safe rate-limit reads through the authenticated Codex app-server,
  idempotent setup for Codex's native five-hour and weekly status-line fields,
  and minimal, optional-icon and detailed styles across ten themes plus JSON
  output

### Changed

- `opus` and `sonnet` aliases resolve to Opus 5 and Sonnet 5; superseded ids
  stay accepted so existing task rows and evidence bundles keep resolving.
  `configs/models.env` is now sourced by `loop-runner.sh` instead of being
  shadowed by a hardcoded `claude-sonnet-4-6`
- Orchestrator worktrees moved out of `.claude/worktrees/`, which Claude Code
  claims as its own managed pool and deletes along with a session
- `task_queue.py` and `worker.py` both sat on the 1500-line ceiling. The DDL
  moved to `task_schema.py` and worker scheduling to `worker_pool.py`, which
  `worker.py` subclasses to bind its own `Worker`. No behaviour change
- Automated commits carry the operator's own identity, and Claude co-author
  attribution is off
- The README moved its reference material into `docs/` and now stays inside its
  own 300-line rule
- Generated MCP skill catalogs match the manifest, and the Codex plugin cache
  version refreshes whenever generated plugin content changes
- One version now spans every surface. The Codex plugin manifest is canonical,
  `.claude-plugin/plugin.json` is generated from it, and `clade-mcp` reports
  0.3.1 from `pyproject.toml`, `server.json` and `__version__` alike — the
  package had been pinned at 0.2.0 for 241 commits while both plugin manifests
  advertised 0.3.1

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
- A `/loop` run that gave up reported success. Convergence is checked before the
  ceilings now, and the runner exits 2 when goal items remain
- Routing settings reject `NaN` and infinite thresholds instead of persisting
  values that cannot round-trip through JSON
- `delivery abandon` now discovers PRs by branch instead of trusting a
  possibly stale `published` flag — an unrecorded open PR blocks abandonment,
  and a merged PR at the recorded head is reconciled rather than mislabeled
  abandoned
- Task updates revalidate the effective persisted connection against the
  effective runtime before mutation, instead of only failing at execution time
- The correction-history append was not atomic: concurrent writers spliced
  records into each other and truncated every reader
- The PreCompact prompt hook dumped its entire prompt into the UI for want of a
  `statusMessage`, and auto-audit promoted raw prompt excerpts into the global
  `CLAUDE.md`
- Three verification paths silently measured nothing off Linux, and the
  PID-reuse safety net never existed on macOS at all
- pytest output is read through one colour-proof contract
  (`orchestrator/pytest_report.py`); the resolve eval and the regression
  detector had both been structurally blind to coloured output
- The settings reference promised every supported key and shipped 33 of 75, one
  of which was no longer a setting
- The CI checklist gate passed a documented command that exits 126, and a
  syntax-check gate imported `aiosqlite` in a job that installs no dependencies
- 135 dead cross-references left by the flow-skill absorption, 18 links to
  upstream files the sync never fetched, and skill descriptions truncated at
  the 1024-character limit on absorption
- The oracle was handed a review rule that could not apply to 86% of test
  traffic
- Users were instructed to run a flow-skill sync script that never existed

### Compatibility

- The control plane is default-closed from this release. A deployment that
  relied on an unauthenticated socket must either send the bearer token minted
  into `~/.claude/orchestrator-settings.json` on first start, or set
  `api_allow_unauthenticated` deliberately
- `usage_ingest_token` no longer means "open" when empty. A node posting usage
  to a hub needs the token configured on both ends
- Superseded model ids are still accepted, so existing task rows and evidence
  bundles keep resolving
- `worker_sandbox` (Landlock) and `worker_checkpoint_shadow` ship default off;
  `worker_git_surface_guard` and `worker_require_worktree` are on
- The FastAPI multi-worker orchestrator remains Claude-specific

### Upgrade

```bash
pip install --upgrade clade-mcp
./install.sh          # refreshes skills, hooks, scripts — and the deny rules
```

For native Codex use:

```bash
codex plugin marketplace add shenxingy/Clade
codex plugin add clade@clade
```

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

[0.3.1]: https://github.com/shenxingy/Clade/compare/v0.2.0...v0.3.1
[0.2.0]: https://github.com/shenxingy/Clade/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/shenxingy/Clade/releases/tag/v0.1.0
