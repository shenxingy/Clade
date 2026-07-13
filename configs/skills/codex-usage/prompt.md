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
