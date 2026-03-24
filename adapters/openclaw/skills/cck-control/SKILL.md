---
name: cck-control
version: 1.0.0
description: Start, stop, or manage Claude Code Kit autonomous coding loops remotely
author: alexshen
tags: [claude-code, orchestrator, automation, devtools, coding-automation]
requires:
  env:
    - CCK_BASE_URL
    - CCK_API_KEY
---

# Claude Code Kit — Control

Start, stop, or manage autonomous coding loops on a remote machine.

## When to use

User wants to:
- Start a new coding loop with a goal
- Stop a running loop
- Clear blockers so a loop can resume

## API

**Endpoint:** `POST {CCK_BASE_URL}/control`

**Headers:**
```
Authorization: Bearer {CCK_API_KEY}
Content-Type: application/json
```

### Action: start

Start a new autonomous coding loop with a goal.

**Request:**
```json
{
  "project": "/home/user/myproject",
  "action": "start",
  "goal": "Fix all failing tests and ensure 100% pass rate",
  "max_iter": 5,
  "max_workers": 4,
  "model": "sonnet"
}
```

**Translating user intent to parameters:**
- "run 3 times" / "跑3次" → `max_iter: 3`
- "use opus" / "用opus" → `model: "opus"`
- "2 workers" / "2个worker" → `max_workers: 2`
- "quick run" → `max_iter: 3, model: "haiku"`
- "thorough run" → `max_iter: 10, model: "opus"`
- If user doesn't specify: default to `max_iter: 10, max_workers: 4, model: "sonnet"`

**The goal can be:**
- A natural language description: `"Fix the login page CSS on mobile"`
- A file path on the server: `"/home/user/myproject/goals/feature-x.md"`

**Response:**
```json
{
  "ok": true,
  "action": "start",
  "pid": 12345,
  "goal": "/home/user/myproject/.claude/monitor-goal.md",
  "max_iter": 5
}
```

### Action: stop

Stop the currently running loop gracefully.

**Request:**
```json
{
  "project": "/home/user/myproject",
  "action": "stop"
}
```

**Response:**
```json
{"ok": true, "action": "stop", "sentinel": "/home/user/myproject/.claude/stop-start"}
```

### Action: clear-blockers

Clear blockers so the loop can be restarted.

**Request:**
```json
{
  "project": "/home/user/myproject",
  "action": "clear-blockers"
}
```

## How to format the response

### On start:
```
🚀 Loop started!
📋 Goal: {goal summary, first 80 chars}
⚙️ Config: {max_iter} iterations, {max_workers} workers, {model}
🔢 PID: {pid}

Use "status" to check progress.
```

### On stop:
```
🛑 Stop signal sent. The loop will finish its current task and exit gracefully.
```

### On clear-blockers:
```
🧹 Blockers cleared. You can now restart the loop.
```

## Error handling

- **Connection refused**: "Monitor is not running."
- **401 Unauthorized**: "Check your CCK_API_KEY."
- **400 "goal is required"**: Ask the user what they want the AI to work on.
- **500 "start.sh not found"**: "Claude Code Kit is not installed on the server. Run ./install.sh first."
