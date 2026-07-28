# Claude Code status adapter

- Use in-conversation background tool and subagent handles as the authoritative
  activity source.
- A Claude Code status-line command receives a changing JSON object on stdin.
  Treat absent fields as unknown and use native rate-limit/worktree/PR/context
  observations when present.
- `/slt` remains the Claude-specific display adapter. It changes presentation,
  not the `clade.status/v1` meaning.
- Do not launch another Claude process to discover status.
