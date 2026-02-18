# Custom Subagents Research

## Overview

Subagents are specialized AI assistants with their own context window, system prompt, tool access, and permissions. They run in isolation and return results to the main conversation.

## Why Subagents

1. **Preserve context** — verbose test/lint output stays in subagent, not main conversation
2. **Enforce constraints** — limit tools (read-only reviewer, no-write debugger)
3. **Specialize behavior** — focused prompts for specific domains
4. **Control costs** — route simple tasks to Haiku ($$$→$)
5. **Persistent memory** — learn across sessions

## Built-in Subagents

| Agent | Model | Tools | Purpose |
|-------|-------|-------|---------|
| Explore | Haiku | Read-only | Fast codebase search |
| Plan | Inherit | Read-only | Research for plan mode |
| General-purpose | Inherit | All | Complex multi-step tasks |
| Bash | Inherit | Terminal | Command execution |

## Creating Custom Subagents

### File Locations (priority order)

1. `--agents` CLI flag (session only, highest priority)
2. `.claude/agents/` (project-level, committable)
3. `~/.claude/agents/` (user-level, all projects)
4. Plugin `agents/` (plugin scope)

### File Format

```markdown
---
name: my-agent
description: When Claude should delegate to this agent
tools: Read, Grep, Glob, Bash
disallowedTools: Write, Edit
model: sonnet
permissionMode: default
maxTurns: 50
memory: user
skills:
  - api-conventions
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./scripts/validate.sh"
---

System prompt goes here in markdown body.
```

### Frontmatter Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique identifier (lowercase, hyphens) |
| `description` | Yes | When Claude should use this agent (critical for auto-delegation) |
| `tools` | No | Allowlist; inherits all if omitted |
| `disallowedTools` | No | Denylist; removed from inherited/specified |
| `model` | No | `sonnet`, `opus`, `haiku`, `inherit` (default: inherit) |
| `permissionMode` | No | `default`, `acceptEdits`, `plan`, `dontAsk`, `bypassPermissions` |
| `maxTurns` | No | Max agentic turns before stopping |
| `skills` | No | Skills to preload into context |
| `mcpServers` | No | MCP servers available to this agent |
| `hooks` | No | Lifecycle hooks scoped to this agent |
| `memory` | No | `user`, `project`, or `local` — enables persistent memory |

## Persistent Memory

When `memory` is set, the agent gets a directory that persists across sessions:

| Scope | Location | Use Case |
|-------|----------|----------|
| `user` | `~/.claude/agent-memory/<name>/` | Cross-project learnings |
| `project` | `.claude/agent-memory/<name>/` | Project-specific, shareable |
| `local` | `.claude/agent-memory-local/<name>/` | Project-specific, private |

The agent's `MEMORY.md` (first 200 lines) is auto-loaded into its system prompt. Read/Write/Edit tools are auto-enabled.

**Best practice**: Ask the agent to "consult your memory before starting" and "save what you learned after completing."

## Interaction Patterns

### Auto-delegation
Claude uses the `description` field to decide when to delegate. Include "use proactively" for automatic delegation.

### Foreground vs Background
- **Foreground**: Blocks main conversation, permission prompts pass through
- **Background**: Runs concurrently, permissions pre-approved, `AskUserQuestion` fails gracefully

### Resuming
Each subagent gets an `agent_id`. Ask Claude to "continue that work" to resume with full context preserved.

### Chaining
```
Use code-reviewer to find issues, then use debugger to fix them
```

## Practical Agent Designs

### Read-only Reviewer (safest)
```yaml
tools: Read, Grep, Glob, Bash
disallowedTools: Write, Edit
model: sonnet
memory: user
```

### Fix-and-verify Agent
```yaml
tools: Read, Edit, Bash, Grep, Glob
model: sonnet
hooks:
  Stop:
    - hooks:
        - type: command
          command: "./scripts/run-tests.sh"
```

### Cost-optimized Explorer
```yaml
tools: Read, Grep, Glob
model: haiku
maxTurns: 20
```

### Restricted Bash Agent
```yaml
tools: Bash
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./scripts/validate-command.sh"
```

## Disabling Subagents

In settings.json:
```json
{
  "permissions": {
    "deny": ["Task(Explore)", "Task(my-agent)"]
  }
}
```

Or CLI: `claude --disallowedTools "Task(Explore)"`

## Key Considerations

1. **Subagents cannot spawn other subagents** — only one level deep
2. **Context isolation** — subagent results return as summaries to main conversation
3. **Model selection matters** — Haiku for simple reads, Sonnet for analysis, Opus for architecture
4. **Description is critical** — poorly described agents won't get auto-delegated
5. **Memory accumulates** — periodically review agent memory for stale entries
6. **Background agents** can't use MCP tools or ask user questions
