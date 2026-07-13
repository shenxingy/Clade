**English**（中文版尚未提供 — [README 中文版](../README.zh-CN.md)）

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

- 20 core workflows: commit, security review, release documentation, frontend
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

## MCP Runtime Selection

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

## Compatibility Boundary

The full overnight orchestrator, Claude-specific agents, status line, provider
switcher, quota integrations, and correction-learning hooks still depend on the
Claude CLI layer. They are deliberately excluded from the first native plugin
release rather than presented as native while secretly invoking Claude.

The MCP package now has a real Codex runtime, but the FastAPI worker orchestrator
still uses Claude-specific session streaming and model routing. A future
orchestrator runtime adapter must cover command construction, resume semantics,
JSONL events, model aliases, usage accounting, and cancellation together before
that layer can honestly be called provider-neutral.
