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

Start a new Codex thread after installation. Run `/hooks` once, review the two
Clade hook definitions, and trust them if they match the checked-in files.

For local development from a Clade checkout:

```bash
codex plugin marketplace add /absolute/path/to/Clade
codex plugin add clade@clade
```

## What Is Native

The plugin under `plugins/clade/` contains:

- 25 core workflows: commit, Codex usage pace, security review, release documentation, frontend
  design, handoff/pickup, incident response, investigation, architecture maps,
  PR review/merge, research, retrospectives, project review, sync, verification,
  worktrees, and supporting decision workflows.
- A `SessionStart` hook that injects concise branch, recent-commit, dirty-tree,
  handoff, repository-guidance, and delivery-completion context without mutating
  the repository.
- A `PreToolUse` safety hook that blocks catastrophic deletion, destructive SQL,
  migrations, and force-pushes to shared branches. Feature-branch force pushes
  are rewritten to `--force-with-lease`.

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

## State and Guidance

Native Codex workflows read `AGENTS.md` first and fall back to `CLAUDE.md` for
older Clade-enabled repositories. New runtime state is written under `.clade/`
or `~/.clade/`; native workflows may read legacy Claude state when migrating an
existing project but do not create new vendor-specific state.

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
xingyushen(main)-9% (6d)
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
`codex_cheap_model` (`gpt-5.6-terra` by default), while critical-path or
low-readiness tasks use `codex_strong_model` (`gpt-5.6-sol` by default).
Routing remains off by default until replay evaluation demonstrates that both
verified success per dollar and per wall-hour hold for a task class.

`./install.sh` also installs two native profiles under `~/.codex/agents/` and
merges an idempotent managed block into `~/.codex/AGENTS.md` without replacing
user instructions. The block carries both adaptive-delegation rules and the
delivery-completion invariant. The lead keeps architecture and
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
and correction-learning hooks still depend on the Claude CLI layer. They remain
outside the native plugin rather than being presented as native while secretly
invoking Claude.

Worker **command construction, model resolution, and cancellation** are now
provider-neutral (see above); the remaining Codex-worker gaps before the
orchestrator layer is fully provider-neutral are **JSONL event streaming,
thread resume semantics, and structured-result/usage accounting** — tracked as
Phase 2 in `worker_provider.py`.
