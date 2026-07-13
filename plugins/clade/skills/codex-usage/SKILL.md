---
name: codex-usage
description: "Show Codex rate-limit usage and pace, or configure the native Codex status line"
---

# Clade for Codex

This workflow runs **directly in Codex**. Do not launch the `claude` CLI or
delegate the workflow to Clade's MCP bridge.

Codex compatibility rules:

- Read the nearest `AGENTS.md` files for repository instructions. If a project
  has only `CLAUDE.md`, treat it as legacy project guidance and read it too.
- Store new Clade working state under `.clade/` (or `~/.clade/` for personal
  state). Existing legacy Claude state may be read for migration, but do not
  create new vendor-specific state.
- A `/skill-name` reference means the corresponding Codex `$skill-name` skill,
  or the same workflow invoked naturally when explicit skill invocation is not
  available.
- Use Codex web, file, shell, image, and subagent capabilities when the source
  workflow names a vendor-specific tool. If a capability is unavailable, use
  the documented fallback instead of spawning another agent CLI.
- Paths such as `<plugin-root>/...` are relative to the installed Clade plugin
  containing this `SKILL.md`; resolve that root before invoking a helper.

## Canonical Clade workflow

You are the Codex Usage skill. Show Codex account rate-limit usage or configure
the native Codex status line.

## Execute

1. Resolve this installed skill's directory — the directory containing this
   `SKILL.md`.
2. Run its bundled helper with Python 3:

   ```bash
   python3 <skill-dir>/scripts/codex_usage.py [arguments]
   ```

3. Pass through arguments exactly:

   | User request | Helper arguments |
   |--------------|------------------|
   | no arguments, "usage", "quota" | none |
   | "setup", "add it to my footer" | `setup` |
   | "minimal footer" | `setup minimal` |
   | "full footer" | `setup full` |
   | "style" or "list styles" | `style` |
   | "minimal/icon/detail style" | `style minimal|icon|detail` |
   | "theme" or "list themes" | `theme` |
   | "theme NAME" | `theme NAME` |
   | "json" or machine-readable output | `--json` |

4. Report the helper output directly. If `setup` changed the configuration,
   remind the user to start a new Codex session so the footer reloads.

## Safety and scope

- Never read, print, copy, or parse `~/.codex/auth.json`.
- Do not call private HTTP endpoints directly. The helper uses the authenticated
  Codex app-server protocol.
- Plain `setup` preserves existing status-line items and only adds the native
  `five-hour-limit` and `weekly-limit` fields. `setup minimal` or `setup full`
  may replace only the `status_line` array because the user explicitly selected
  a layout; all other Codex configuration must remain unchanged.
- Do not consume a rate-limit reset credit. This workflow is read-only except
  for the explicit `setup`, `style`, or `theme` commands.

## Additional skill reference

# Codex Usage

Shows authenticated Codex rate-limit windows and compares usage with a 95%
target pace. It can also add Codex's native five-hour and weekly limit fields to
the TUI footer without replacing existing status-line fields.

## Usage

```text
/codex-usage
/codex-usage setup minimal
/codex-usage style icon
/codex-usage theme
/codex-usage theme bird
/codex-usage --json
```

The helper talks to `codex app-server`; it does not read or print Codex login
credentials.
