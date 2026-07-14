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

- 21 core workflows: commit, Codex usage pace, security review, release documentation, frontend
  design, handoff/pickup, incident response, investigation, architecture maps,
  PR review/merge, research, retrospectives, project review, sync, verification,
  worktrees, and supporting decision workflows.
- A `SessionStart` hook that injects concise branch, recent-commit, dirty-tree,
  handoff, and repository-guidance context without mutating the repository.
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

Explicit native skill invocation uses Codex's `$skill-name` form, for example:

```text
$investigate why the integration test hangs
$verify all behavior anchors
$review the whole project and fix failures until clean
```

Natural-language activation works too.

## Codex Usage and Status Line

Clade 0.3 adds a native `$codex-usage` workflow. It reads rate-limit snapshots
through the authenticated `codex app-server` protocol, so it never opens or
prints `~/.codex/auth.json`.

```text
$codex-usage
$codex-usage setup minimal
$codex-usage style icon
$codex-usage style detail
$codex-usage theme bird
$codex-usage --json
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
Clade compact string is produced by `$codex-usage`; the persistent footer uses
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

## Compatibility Boundary

The full overnight orchestrator, Claude-specific agents, provider switcher,
cross-machine usage aggregation, and correction-learning hooks still depend on
the Claude CLI layer. They remain outside the native plugin rather than being
presented as native while secretly invoking Claude.

The MCP package now has a real Codex runtime, but the FastAPI worker orchestrator
still uses Claude-specific session streaming and model routing. A future
orchestrator runtime adapter must cover command construction, resume semantics,
JSONL events, model aliases, usage accounting, and cancellation together before
that layer can honestly be called provider-neutral.
