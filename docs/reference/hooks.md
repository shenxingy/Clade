# Hooks System Research

---
name: hooks.md
date: 2026-02-XX
status: integrated
review_date: 2026-08-10
summary:
  - "Claude Code hooks system: lifecycle events, types, exit codes, patterns"
integrated_items:
  - "All major lifecycle hooks implemented (SessionStart, PreToolUse, PostToolUse, Stop, PreCompact, SessionEnd, TaskCompleted, Notification, UserPromptSubmit) — settings.json 全部有配置"
  - "Command, prompt, agent 三种 hook type 全部使用"
  - "Auto-format/lint on edit, block dangerous commands, verify completion patterns — 全部实现"
  - "SessionEnd hook used for shadow cleanup — removes /tmp/claude-edit-shadows/session-<session_id>.jsonl when session terminates"
needs_work_items: []
reference_items:
  - "SubagentStart/SubagentStop hooks — not implemented. 早期理由「Clade 只用 subprocess worker，场景不匹配」已过期：configs/agents/ 现有 37 个 agent 定义，多个 skill 会 fan-out 到 Task subagent，而且 Claude Code 2.1.221 把默认 spawn 深度从 1 提到 3。真正的现状是尚未评估，不是不适用"
  - "TeammateIdle hook — 仅适用于 multi-agent team workflow，Clade 用 WorkerPool 模式不适用，not implemented"

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

## Intentional No-ops

Some hooks are deliberately left as async to avoid latency cost and waking the
LLM with low-value advisory output.

Be precise about what "async" costs, because two hooks in this repo were already
found emitting into a void believing otherwise (`secret-scanner.sh`,
`skill-suggest.sh`): a plain `async: true` command hook has **no channel back
into the turn at all**. Its stdout is discarded — `systemMessage` included, so
nobody reads it, not even in verbose mode. `asyncRewake` is the only way a
background hook reaches Claude, and only via stderr on exit code 2. So keeping a
hook async is a decision to **discard** its output, not to deliver it quietly.
That is acceptable only when the output was never worth acting on:

- **`doc-align-check.sh`** (PostToolUse, async) — Real-time doc-drift warning
  after markdown edits, advisory only (disagreement with `docs/facts.json`),
  never blocking. Its `systemMessage` is discarded, and that is the accepted
  outcome: the drift is visible in the diff being written anyway, and firing an
  `asyncRewake` interrupt on every markdown edit would cost far more attention
  than the warning is worth. Left async knowingly, not by oversight.

- **`prompt-tracker.sh`** (UserPromptSubmit, async) — Analytics hook tracking user prompts for correction learning and loop detection. Produces no output to Claude; runs async because it is pure telemetry. Waking the LLM or waiting on the result adds latency with zero benefit to the interaction.

These hooks are deliberately NOT turned into `action: "block"` prompt hooks or sync command hooks with statusMessage — the cost (context wake, prompt latency, LLM invocation) exceeds the value (advisory noise for the former, telemetry-only for the latter). This trade-off is intentional and should not be changed to "proper" sync hooks without first confirming the value justifies the latency cost.

## Key Gotchas

1. **Hooks are snapshotted at session start** — editing settings mid-session requires restart
2. **`async: true`** hooks can't block actions — the action already happened
3. **Stop hooks must check `stop_hook_active`** to avoid infinite loops
4. **Prompt/Agent hooks** only support specific events (not TeammateIdle)
5. **JSON on stdout must be clean** — shell profile output can break parsing
6. **Async hook results** delivered on next conversation turn, not immediately
