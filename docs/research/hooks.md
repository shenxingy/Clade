# Hooks System Research

## Overview

Hooks are user-defined shell commands or LLM prompts that execute at specific lifecycle points. They are the **single most impactful** automation feature in Claude Code.

## Hook Events (Lifecycle Order)

| Event | When | Can Block? | Key Use Case |
|-------|------|-----------|--------------|
| `SessionStart` | Session begins/resumes | No | Load context, set env vars |
| `UserPromptSubmit` | Before prompt processed | Yes | Validate/filter prompts |
| `PreToolUse` | Before tool executes | Yes | Block dangerous commands, modify input |
| `PermissionRequest` | Permission dialog shown | Yes | Auto-approve/deny |
| `PostToolUse` | After tool succeeds | No* | Auto-lint, type-check, notify |
| `PostToolUseFailure` | After tool fails | No | Log failures, suggest fixes |
| `Notification` | Notification sent | No | Send to Telegram/Slack |
| `SubagentStart` | Subagent spawned | No | Inject context |
| `SubagentStop` | Subagent finished | Yes | Verify subagent output |
| `Stop` | Claude stops responding | Yes | Verify all tasks done |
| `TeammateIdle` | Agent team member idle | Yes | Quality gate |
| `TaskCompleted` | Task marked complete | Yes | Run tests before completing |
| `PreCompact` | Before context compaction | No | Save important context |
| `SessionEnd` | Session terminates | No | Cleanup, save metrics |

*PostToolUse can provide feedback to Claude via `decision: "block"` but the tool already ran.

## Hook Types

### 1. Command Hooks (`type: "command"`)
Run a shell script. Receives JSON on stdin, communicates via exit codes + stdout JSON.

```json
{
  "type": "command",
  "command": "/path/to/script.sh",
  "timeout": 600,
  "async": false
}
```

### 2. Prompt Hooks (`type: "prompt"`)
Single-turn LLM evaluation. Returns `{ok: true/false, reason: "..."}`.

```json
{
  "type": "prompt",
  "prompt": "Evaluate if this is safe: $ARGUMENTS",
  "model": "haiku",
  "timeout": 30
}
```

### 3. Agent Hooks (`type: "agent"`)
Multi-turn LLM with tool access. Can Read, Grep, Glob to verify conditions.

```json
{
  "type": "agent",
  "prompt": "Verify all tests pass: $ARGUMENTS",
  "timeout": 60
}
```

## Exit Code Semantics

| Exit Code | Meaning | Effect |
|-----------|---------|--------|
| `0` | Success | Proceed; parse stdout JSON if present |
| `2` | Blocking error | Block the action; stderr shown to Claude |
| Other | Non-blocking error | stderr shown in verbose mode; continue |

## JSON Output Fields (on exit 0)

| Field | Default | Description |
|-------|---------|-------------|
| `continue` | `true` | `false` stops Claude entirely |
| `stopReason` | — | Message to user when `continue: false` |
| `suppressOutput` | `false` | Hide stdout from verbose mode |
| `systemMessage` | — | Warning shown to user |

## Matcher Patterns

Matchers are regex strings:
- `"Bash"` — match Bash tool
- `"Edit|Write"` — match Edit OR Write
- `"mcp__memory__.*"` — match all memory MCP tools
- `"*"` or omit — match everything

## Configuration Locations

| Location | Scope | Priority |
|----------|-------|----------|
| `~/.claude/settings.json` | All projects | User-level |
| `.claude/settings.json` | Single project (committable) | Project-level |
| `.claude/settings.local.json` | Single project (gitignored) | Local-level |
| Plugin `hooks/hooks.json` | Plugin scope | Plugin-level |
| Skill/Agent frontmatter | Component lifecycle | Component-level |

## Environment Variables Available

- `$CLAUDE_PROJECT_DIR` — project root
- `$CLAUDE_PLUGIN_ROOT` — plugin root (in plugin hooks)
- `$CLAUDE_ENV_FILE` — write env vars here (SessionStart only)
- `$CLAUDE_CODE_REMOTE` — `"true"` in web environments

## Practical Patterns

### Auto-format after edits (async)
```json
{
  "PostToolUse": [{
    "matcher": "Edit|Write",
    "hooks": [{
      "type": "command",
      "command": "prettier --write $(echo $TOOL_INPUT | jq -r .file_path)",
      "async": true,
      "timeout": 30
    }]
  }]
}
```

### Block dangerous commands
```json
{
  "PreToolUse": [{
    "matcher": "Bash",
    "hooks": [{
      "type": "command",
      "command": ".claude/hooks/block-dangerous.sh"
    }]
  }]
}
```

### Verify completion with LLM
```json
{
  "Stop": [{
    "hooks": [{
      "type": "prompt",
      "prompt": "Did Claude complete all requested tasks? $ARGUMENTS"
    }]
  }]
}
```

### Chain: Stop hook that runs tests
```json
{
  "Stop": [{
    "hooks": [{
      "type": "agent",
      "prompt": "Run the test suite and check if all tests pass. If tests fail, return {ok: false, reason: 'Tests failing: ...'}. $ARGUMENTS",
      "timeout": 120
    }]
  }]
}
```

## Key Gotchas

1. **Hooks are snapshotted at session start** — editing settings mid-session requires restart
2. **`async: true`** hooks can't block actions — the action already happened
3. **Stop hooks must check `stop_hook_active`** to avoid infinite loops
4. **Prompt/Agent hooks** only support specific events (not TeammateIdle)
5. **JSON on stdout must be clean** — shell profile output can break parsing
6. **Async hook results** delivered on next conversation turn, not immediately
