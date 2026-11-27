**English** | [中文](codex.zh-CN.md)

← Back to [README](../README.md)

# Native Codex Support

Clade supports Codex through a native plugin and, for external MCP clients, a
selectable Codex execution runtime. The native plugin is the recommended path
because its skills execute in the current Codex thread without spawning a
nested agent CLI.

## Install from GitHub

```bash
codex plugin marketplace add shenxingy/Clade
codex plugin add clade@clade
```

Start a new Codex thread after installation. Run `/hooks` once, review the
plugin's two Clade hook definitions, and trust them if they match the checked-in
files. If you also ran `./install.sh`, `/hooks` includes ten portable user-hook
wirings appended to `~/.codex/hooks.json` (and to each Codex profile's
`hooks.json`, below); review those new entries too. The installer never writes
trust state to `config.toml`.

For local development from a Clade checkout:

```bash
codex plugin marketplace add /absolute/path/to/Clade
codex plugin add clade@clade
```

## Updating while sessions exist

An existing thread can keep executing hooks from its original version even
after a plugin update ([related upstream issue](https://github.com/openai/codex/issues/36605)).
On Codex CLI 0.156.1, reinstalling Clade removed the old cache and blocked even
`pwd` in another thread because `pre_tool_guardian.py` no longer existed.

Pause other sessions' tool work while updating. From a Clade checkout, use:

```bash
python3 configs/scripts/codex-plugin-update.py
```

The helper uses the already configured `clade@clade` marketplace. For local
development, update the source manifest's cachebuster first. It saves complete
old bundles under `~/.clade/codex-plugin-backups/`, runs the official
`codex plugin add`, then restores missing old paths even if installation fails
or is interrupted. Checksums and conflicts are checked before restoration;
existing different files, hook logic and trust settings are never replaced.
Already broken cache aliases are reported and skipped; symlinks in a bundle
or to a live bundle are rejected.
This does not make the CLI's replacement atomic: resume other sessions only
after the helper returns. Raw CLI/app updates do not use this protection.

Keep snapshots and restored versions while old threads still use them. If the
updater is killed before cleanup, use an ordinary terminal to recover:

```bash
python3 configs/scripts/codex-plugin-update.py --restore /path/to/printed/backup
```

Confirm the updater has exited before manually removing a stale `update.lock`
directory in the backup root. Missing files with no prior snapshot must be
restored from the exact trusted release, never an arbitrary newer hook or a
disabled safety check. Start a new thread to load newly added skills; restoring
old files does not refresh a thread's skill catalog. Native Windows behavior
has not been exercised for this helper.

## What Is Native

The plugin under `plugins/clade/` contains:

- 31 core workflows: commit, Codex usage pace, security review, release documentation, frontend
  design, local CI repair, handoff/pickup, incident response, investigation, architecture maps,
  PR review/merge, research, retrospectives, project review, sync, verification,
  worktrees, compute profiling/scheduling/recovery, and supporting decision workflows.
- A `SessionStart` hook that injects concise branch, recent-commit, dirty-tree,
  handoff, repository-guidance, and delivery-completion context without mutating
  the repository.
- A `PreToolUse` safety hook that blocks catastrophic deletion, destructive SQL,
  migrations, and force-pushes to shared branches. Feature-branch force pushes
  are rewritten to `--force-with-lease`.

Separately, `./install.sh` installs `configs/codex-hooks/decision-to-codex.sh`
as `~/.codex/clade-hooks/decision-to-codex.sh` and appends ten portable command
hook wirings to `~/.codex/hooks.json`. This user-level bridge adds the linter
config guard, secret and correction detection, correction-pairing state, stop
cleanliness, session cleanup, and memory sync without running either plugin hook
a second time. Existing groups stay at their original indices, a no-op reinstall
does not rewrite the file, and new or configuration-changed entries still
require the owner's review in `/hooks`.

A Codex profile (`CODEX_HOME=~/.codex-profiles/<name>`) reads its own
`hooks.json`, `agents/` and `AGENTS.md`, not those in `~/.codex`. For each
profile, `./install.sh` merges the same ten wirings into its `hooks.json`
(through the `~/.codex` adapter, reported per file with its own `/hooks` review
line), copies the two Clade agents into its `agents/`, and refreshes the managed
block in its `AGENTS.md` if it has one. A `hooks.json` or `agents/` the profile
lacks is created, as it is in `~/.codex`, once Codex has used the directory as
its home (it holds `config.toml` or `auth.json`); an empty directory is not a
profile, and a missing `AGENTS.md` is not created, since instruction files there
are the user's call. One that is a link is left alone (a link into `~/.codex`
already gets them there), and a `hooks.json` or `agents/` the installer cannot
write gets a warning naming it instead of stopping the install. The profile's
trust state is not touched.

`./uninstall.sh` takes that wiring out again: every handler whose command starts
with the quoted `"$HOME/.codex/clade-hooks/decision-to-codex.sh"`, in
`~/.codex/hooks.json` and in each `~/.codex-profiles/*/hooks.json` that is a
file of its own, then any group or event list the removal emptied, then
`~/.codex/clade-hooks/` once no hooks.json names the adapter. User groups keep
their order and fields, a file holding nothing of Clade's is not rewritten, and
a file it cannot parse (or a machine with no working Python) is left as it was,
together with the adapter it still runs. `config.toml` is not edited. Codex
keys hook trust by position (`<hooks.json path>:<event>:<group>:<handler>`), so a
user handler that sat behind a removed Clade group or handler in the same event
moves up onto a key it was never trusted under, and Codex does not run it until
it is reviewed again in `/hooks`. The uninstall names each such handler with its
old and new position. Trust entries for positions no handler holds any more stay
there unused. Clade's agents and `AGENTS.md` blocks, in `~/.codex` and in each
profile, are not removed yet.

Codex loads executable workflow instructions from `SKILL.md`, while Clade's
original Claude distribution executes `prompt.md`. The generator combines both
canonical sources and applies Codex compatibility rules:

```bash
python3 configs/scripts/regen-codex-plugin.py
python3 configs/scripts/regen-codex-plugin.py --check
```

Edit canonical skills under `configs/skills/`, not the generated copies under
`plugins/clade/skills/`. Curated membership lives in
`plugins/clade/skills.list`.

`$clade:green` is portable outside the Clade repository. Its generated skill
bundles a byte-identical copy of `configs/scripts/ci-local.py`, resolves that
copy from the installed plugin root, and derives the target repository's real
GitHub Actions jobs before attempting a repair.

## Claude-to-Codex Migration Contract

Clade does not bulk-import the full Claude installation into Codex. That would
duplicate native plugin skills and would copy hooks, agents, output styles, and
state paths whose lifecycle or trust semantics differ between runtimes.

The machine-readable [`configs/codex-migration.json`](../configs/codex-migration.json)
records every configuration surface as native, a native subset, a semantic
adaptation, or an intentional exclusion. It also classifies every canonical
Claude skill exactly once: either it appears in `plugins/clade/skills.list`, or
it matches one documented exclusion group. CI fails when a new skill is added
without an explicit Codex disposition.

The installer adapts the provider-neutral parts of Clade's global policy into
the managed block in `~/.codex/AGENTS.md`: atomic PR scope, local-CI-first
verification, evidence completeness, concise response register, configuration
wiring, deployment proof, and the don't-block escalation ladder. It leaves
model selection, trust, permissions, MCP authentication, and personal plugin
settings under the user's own `~/.codex/config.toml`.
Context compaction is reported, not configured: `context-policy.py status`
prints where Codex compacts (gpt-6-astra at 244,800 tokens, derived on codex
0.166.0) and nothing is written to `config.toml` for it; see
[Context window policy](configuration.md#context-window-policy).

Claude output styles have no distributable one-to-one Codex primitive. Their
Evidence First and Terse invariants are therefore carried as durable Codex
guidance, without claiming system-prompt equivalence. Claude lifecycle
orchestration and the MCP bridge stay outside the native plugin until they have
real native semantics.

### Portable hook matrix

All source citations below are to `rust-v0.169.0`. The adapter translates
`apply_patch` into one Write/Edit payload per affected path. Add carries `content`;
Update carries removed/added lines as `old_string`/`new_string`; Delete is an Edit
with empty `old_string` and `new_string`, because a delete hunk has no body
(`codex-rs/apply-patch/src/parser.rs:13`); Move calls the hook for both source and destination
and supplies `old_file_path` and `new_file_path`. Paths are resolved against the
payload's `cwd`. This is necessary because Codex keeps `tool_name=apply_patch`
and puts the raw patch in `tool_input.command`
(`codex-rs/core/src/tools/handlers/apply_patch.rs:370-418`). The Edit and Write
matcher aliases select that call without changing its stdin name
(`codex-rs/core/src/tools/hook_names.rs:27-38`).

Codex runs command strings through a login shell, so installed paths are quoted
(`codex-rs/hooks/src/engine/command_runner.rs:444-470`). It discovers the user
file at `<CODEX_HOME>/hooks.json`
(`codex-rs/hooks/src/engine/discovery.rs:390-430`). Only trusted or managed
handlers enter the runnable set (`discovery.rs:917-925`); this also applies to
`codex exec` unless its explicit dangerous trust-bypass flag is set. The trust
hash covers the normalized event/group/handler configuration, not the wrapped
hook file's bytes (`discovery.rs:972-998`). The installer therefore leaves both
trust and `config.toml` untouched.

Async handlers are scheduled rather than awaited
(`codex-rs/hooks/src/engine/dispatcher.rs:123-153`) and cannot apply control
effects (`engine/mod.rs:194-208`). Their stdout is parsed, not wholly discarded:
context/warning/error entries survive in completion reporting, while Stop and
Feedback entries are removed (`engine/command_runner.rs:119-165`). SessionEnd is forced synchronous
and its timeout is capped at three seconds (`discovery.rs:678-684,946-968`).

| `configs/settings-hooks.json` hook | Codex disposition | Evidence or exclusion reason |
|---|---|---|
| `session-baseline` | **Ported:** SessionStart `^(startup|clear|fork)$`, sync, 5 s | Codex supplies all three source values (`events/session_start.rs:23-40`) and the session id/cwd needed for the baseline (`schema.rs:499-511`). |
| `session-context` | **Plugin-owned** | `plugins/clade/hooks/hooks.json` already runs the Python port; install.sh must not duplicate it. |
| `memory-staleness` | Excluded | Reads Claude memory/index state; not part of the reviewed portable correction/safety subset. |
| `memory-sync-pull` | Excluded | Startup pulling is a separate sync policy with a 30 s budget; only the established post-write push triggers are ported. |
| `sync-health` | Excluded | Claude sync-store reporting needs a separate Codex context/noise policy; it is not a portable data-only detector. |
| `commit-archeology` | Excluded | Repository-specific advisory context is outside this unit and needs its own context-budget review. |
| `post-compact-reinject` | Excluded | Depends on the Claude compact-state pipeline and the excluded PreCompact checkpoint below. |
| `session-end-cleanup` | **Ported:** SessionEnd, no matcher, sync, 3 s | SessionEnd supplies `session_id` (`schema.rs:515-524`); Codex forces sync and caps the timeout at 3 s (`discovery.rs:678-684,946-968`). |
| `pre-tool-guardian` | **Plugin-owned** | The plugin already runs `pre_tool_guardian.py` on `^Bash$`; wiring the shell hook again would run the guardian twice. |
| `revert-detector` | **Ported:** PreToolUse `^Bash$`, async, 5 s | Shell `tool_input.command` is a string (`core/src/tools/handlers/unified_exec/exec_command.rs:336-346`). PreToolUse async is supported, preserving Claude's pre-command, data-only recording (`dispatcher.rs:143-153`). |
| `workflow-preflight` | Excluded | Claude Workflow has no Codex matcher alias in the reviewed tool table (`core/src/tools/hook_names.rs:27-51`). |
| `linter-config-guard` | **Ported:** PreToolUse `^(Edit|Write)$`, sync, 5 s | Edit/Write aliases match apply_patch (`events/common.rs:158-166`); synchronous deny blocks the call (`events/pre_tool_use.rs:119-150`). |
| `ask-while-live` | Excluded | Claude's AskUserQuestion and transcript background-task model are not Codex's `request_user_input` contract; no alias is declared (`core/src/tools/hook_names.rs:27-51`). |
| `post-edit-check` | Excluded in this unit | Its delivery needs Claude `asyncRewake`; Codex drops async Feedback (`command_runner.rs:147-165`). The path-scoped rule channel it also waited on was re-measured and kept (TODO.md, 2026-11-16 and 2026-11-26), so the `asyncRewake` gap is the remaining reason. |
| `post-tool-use-lint` | Excluded | Its per-profile `verify_cmd` and 30 s synchronous edit-path policy need a separate Codex configuration and latency design. |
| `rule-injector` (Edit/Write and Bash) | Excluded in this unit | The path-scoped rule channel was re-measured and kept (TODO.md, 2026-11-16, and on Claude Code 2.1.331 on 2026-11-26, when Claude Code's own loader covered 6 of the hook's 1,283 deliveries). A Codex port is a separate unit and is not designed yet. |
| `edit-shadow-detector` | **Ported:** PostToolUse `^(Edit|Write)$`, async, 5 s | PostToolUse carries the same apply_patch command and aliases (`apply_patch.rs:403-418`); the adapter writes one absolute-path shadow record per affected path. |
| `worker-checkpoint` (Edit/Write and Bash) | Excluded | Worker-only snapshots remain launcher-armed through `CLADE_WORKER_SHADOW_DIR`; this unit installs no global Codex worker checkpoint policy. |
| `memory-sync-edit` and `memory-sync-bash` | **Ported:** PostToolUse `^(Edit|Write)$` and `^Bash$`, async, 10 s | Both Codex tool shapes are available (`apply_patch.rs:403-418`; `exec_command.rs:336-346`); async preserves the existing fire-and-forget trigger. |
| `doc-align-check` | Excluded | Its advisory doc-drift delivery is not part of the reviewed data-only subset and needs a separate notification-policy decision. |
| `skill-suggest` | Excluded | Claude's skill catalog and suggestion rules differ from the curated `$clade:*` plugin catalog; a native mapping is required first. |
| `failure-detector` | Excluded | Claude-specific failure/output parsing has not been validated against Codex's `tool_response` shapes (`schema.rs:324-343`). |
| `mailbox-drain` | Excluded | Orchestrator-worker-only mailbox delivery remains with its launcher, not a global Codex user hook. |
| `context-warning-drain` | Excluded | Orchestrator-worker-only context warnings remain with their producer and launcher. |
| `iloop-continue` | Excluded | Claude iloop lifecycle and prompt re-feeding are not a native Codex loop contract. |
| `stop-completeness-check` | Excluded | Codex 0.169.0 explicitly skips prompt handlers (`discovery.rs:782-799`). |
| `stop-uncommitted-guard` (`stop-check.sh`) | **Ported:** Stop, no matcher, sync, 10 s | Stop input includes `stop_hook_active` (`schema.rs:587-602`); a block creates continuation feedback and resumes the turn with the flag set (`events/stop.rs:245-275`; `core/src/session/turn.rs:824-842`). |
| `precompact-state-save` | Excluded | Prompt handlers are unsupported (`discovery.rs:782-799`). |
| `precompact-script` | Excluded | Its Claude compact-state counterpart and post-compaction re-injection pipeline are not ported. |
| `telegram-notify` | Excluded | Notification is not among Codex's command-hook output event contracts (`schema.rs:102-125`). |
| `verify-task-completed` | Excluded | TaskCompleted is not a Codex 0.169.0 hook event (`schema.rs:102-125`). |
| `correction-detector` | **Ported:** UserPromptSubmit, sync, 5 s | Codex supplies a string `prompt`, session id, cwd and transcript path (`events/user_prompt_submit.rs:82-94`); `additionalContext` is accepted (`schema.rs:430-450`). |
| `prompt-tracker` | Excluded | Its Claude transcript analytics and loop-detection state require a separate Codex storage/consumer contract. |
| `secret-scanner` | **Ported:** UserPromptSubmit, sync, 5 s | Same string prompt and `additionalContext` support as correction-detector (`user_prompt_submit.rs:82-94`; `schema.rs:430-450`). |
| `post-tool-use-failure` | Excluded | PostToolUseFailure is not a Codex 0.169.0 hook event (`schema.rs:102-125`). |
| `permission-request` | Excluded | Codex rejects `updatedPermissions`, which this Claude hook uses to persist approvals (`schema.rs:199-218`; `output_parser.rs:401-410`). |

## State and Guidance

Codex resolves agent instructions per scope, first filename wins, with no
merge between them: `AGENTS.override.md` is probed before `AGENTS.md` at both
home scope (`~/.codex/`) and project scope, so wherever an override exists that
directory's `AGENTS.md` is not read at all. `CLAUDE.md` is Clade's own legacy
fallback for older Clade-enabled repositories, not a filename Codex itself
resolves. Because the managed block is merged into `~/.codex/AGENTS.md`,
`install.sh` warns when `~/.codex/AGENTS.override.md` would shadow it; it
reports the conflict and never deletes or moves the override.

New runtime state is written under `.clade/` or `~/.clade/`; native workflows
may read legacy Claude state when migrating an existing project but do not
create new vendor-specific state.

The canonical wording of the shared policy lives in `configs/AGENTS.md`, the
kit's AGENTS.md open-standard file, rather than in any vendor's channel.
`install.sh` merges the same marked block into the cross-tool location
`~/.agents/AGENTS.md` (read by OpenCode, Goose, and other AAIF-convention
runtimes). When the Kimi bridge is active, it instead merges the adapted
`configs/KIMI_AGENTS.md` into `~/.kimi-code/AGENTS.md`, which Kimi Code reads
natively as its global instruction file. Each vendor channel (Claude's
`~/.claude/CLAUDE.md`, this Codex block, and Kimi's block) adapts that text
instead of restating it from scratch.

Every generated native skill also ends with the same delivery boundary: a
writable task cannot report `DONE` with task-owned uncommitted changes, and a
live-URL or deployed-service request cannot be silently downgraded to local-only
work. Missing publication/deployment authority is reported as a blocker rather
than a completion caveat.

Explicit native skill invocation uses Codex's `$skill-name` form, for example:

```text
$clade:investigate why the integration test hangs
$clade:verify all behavior anchors
$clade:review the whole project and fix failures until clean
```

Natural-language activation works too.

## Codex Usage and Status Line

Clade 0.3 adds a native `$clade:codex-usage` workflow. It reads rate-limit snapshots
through the authenticated `codex app-server` protocol, so it never opens or
prints `~/.codex/auth.json`.

```text
$clade:codex-usage
$clade:codex-usage setup minimal
$clade:codex-usage style icon
$clade:codex-usage style detail
$clade:codex-usage theme bird
$clade:codex-usage --json
```

The default `minimal` view is deliberately terse:

```text
xingyushen main -9% (6d)
```

It contains project, branch, pace versus a 95% utilization target, and reset
time. `style icon` inserts the selected theme symbol; `style detail` expands all
available Codex limit buckets and percentages. Plain `setup` safely merges the
native `five-hour-limit` and `weekly-limit` footer fields into
`~/.codex/config.toml`. `setup minimal` selects the short project name, branch,
and the weekly limit; `setup full` also shows model, context, and both limit
windows. The project name is used instead of the full working-directory path
because the Codex footer truncates from the right, and a long path would push the
weekly-limit usage figure off-screen. Only the explicit layout commands replace
the existing `status_line` array.

Codex also provides `/usage` for its built-in account view, `/status` for the
current session, and `/statusline` for interactive footer configuration. Start
a new Codex session after changing the footer. Codex's native footer accepts a
fixed list of fields rather than an arbitrary formatter command, so the exact
Clade compact string is produced by `$clade:codex-usage`; the persistent footer uses
the closest native field combination.

## MCP 0.2.0 Runtime Selection

For Cursor, Windsurf, or another MCP client that should delegate Clade skills to
Codex, configure the `clade-mcp` server with:

```json
{
  "mcpServers": {
    "clade": {
      "command": "uvx",
      "args": ["clade-mcp"],
      "env": {
        "CLADE_RUNTIME": "codex",
        "CLADE_CODEX_SANDBOX": "workspace-write"
      }
    }
  }
}
```

Supported runtime settings:

| Variable | Default | Meaning |
|----------|---------|---------|
| `CLADE_RUNTIME` | `claude` | `claude`, `codex`, or conservative `auto` selection |
| `CLADE_CODEX_SANDBOX` | `workspace-write` | Codex sandbox for delegated skill execution |
| `CLADE_CODEX_BYPASS_PERMISSIONS` | unset | Set to `1` only in an externally isolated environment |

Do not configure this MCP server inside Codex when the native plugin is enabled.
Doing so duplicates tool descriptions and turns a native workflow into a nested
`codex exec` session.

See the [MCP package guide](../mcp-package/README.md) for the complete bundled
skill catalog and upgrade instructions.

## Codex as a Worker Provider (orchestrator)

The FastAPI orchestrator can run its pool workers on `codex exec` as a
first-class backend, not just via manual orchestration. `worker_provider.py`
abstracts *which* agent CLI a worker runs (parallel to `execution_backend.py`,
which abstracts *how* a process is spawned). Because a worker's completion is
process exit and its results come from `git diff` of the worktree — both
provider-agnostic — a Codex worker flows through the same WorkerPool, oracle
gate, and `WorkerEnvelope` pipeline as a Claude worker.

Select it globally or per task:

| Where | Key | Values |
|-------|-----|--------|
| `~/.claude/orchestrator-settings.json` | `worker_provider` | `claude` (default) · `codex` |
| task row | `provider` | overrides the setting for one task |
| task row | `effort` | `low`, `medium`, `high`, `xhigh`, or `max` |
| task row | `route_reason` | resolved audit reason, written at worker start |

The Codex worker runs `codex exec --dangerously-bypass-approvals-and-sandbox
"$(cat <task>)" < /dev/null` (the worktree is throwaway and the oracle gate
still guards every merge; `< /dev/null` is mandatory — `codex exec` otherwise
blocks on stdin EOF and hangs). An explicit Codex model id (`gpt-*`, `o4-*`,
`codex-*`) is passed with `-m`; a Claude alias means "use the `~/.codex`
default". The default `claude` path is byte-identical to before — verified by
`tests/test_worker_provider.py`. Codex effort is passed as
`-c 'model_reasoning_effort="…"'`; Claude uses `--effort` and omits it for
Haiku, which does not support the control.

With `auto_model_routing` enabled, high-readiness Codex tasks use
`codex_cheap_model` (`gpt-5.6-luna` by default), while critical-path or
low-readiness tasks use `codex_strong_model` (`gpt-5.6-sol` by default).
Routing remains off by default until replay evaluation demonstrates that both
verified success per dollar and per wall-hour hold for a task class.

`./install.sh` also installs two native profiles under `~/.codex/agents/` and
merges an idempotent managed block into `~/.codex/AGENTS.md` without replacing
user instructions (and does both in each Codex profile, above: the agents
wherever its `agents/` is not a link, the block where it holds its own
`AGENTS.md`). The block carries adaptive-delegation rules, the
delivery-completion invariant, and the don't-block escalation ladder. The lead keeps architecture and
ambiguous/high-risk work, delegates bounded read-only discovery to
`clade_cheap_explorer`, and uses `clade_cheap_worker` only with explicit file
ownership and a deterministic verifier. Spark is not assumed or installed as
the cheap tier because its availability is plan-dependent.

**Phase 2 (not yet wired):** consume `codex exec --json` JSONL (persist
`thread_id` from `thread.started`), enforce `--output-schema` on the result and
capture it into `completion_summary`, and resume a thread by id on retry instead
of a fresh run. Cancellation already works (the process-group kill is
provider-agnostic) and per-machine usage is tracked separately by `ccusage`.

## Compatibility Boundary

Claude-specific agents, the provider switcher, cross-machine usage aggregation,
prompt-based completion checks, and Claude orchestration loops still depend on
the Claude CLI layer. Correction-learning command hooks now run through the
user-level Codex adapter documented above; they are not presented as plugin
hooks and do not invoke Claude. The remaining incompatible surfaces stay
outside the native plugin.

Worker **command construction, model resolution, and cancellation** are now
provider-neutral (see above); the remaining Codex-worker gaps before the
orchestrator layer is fully provider-neutral are **JSONL event streaming,
thread resume semantics, and structured-result/usage accounting** — tracked as
Phase 2 in `worker_provider.py`.

## Artifact reports across projects

`$clade:artifact` selects a report structure from the reader question, then
checks language, rendered figures and fresh-reader comprehension. The plugin
bundles its lint tools and review reference, so another repository does not
need a Claude installation. Global Clade instructions route artifact/report
tasks here; product UI and marketing pages continue through frontend-design.
Use a new thread after updating the plugin. Each project supplies its own
facts, audience and design system; an unavailable render lane is unverified.
