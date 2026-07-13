---
name: codex-usage
description: Show Codex rate-limit usage and pace, or configure the native Codex status line
when_to_use: "Codex usage, quota, rate limits, weekly limit, five-hour limit, usage pace, configure Codex statusline"
argument-hint: '[setup [minimal|full]|style [minimal|icon|detail]|theme [name]|--json]'
user_invocable: true
---

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
