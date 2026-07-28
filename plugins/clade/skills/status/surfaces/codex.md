# Codex status adapter

- Use Codex task/tool activity exposed in the current conversation.
- Codex TUI status-line configuration is an ordered list of native fields, not
  an arbitrary command renderer. Do not claim Claude-style custom rendering.
- Use `$codex-usage --json` when installed for authenticated native limit
  observations; otherwise report limits as unavailable/unknown.
- Read applicable `AGENTS.md` and trusted legacy `CLAUDE.md` guidance before
  interpreting repository-specific progress.
- Do not launch a nested Codex CLI to discover status.
