---
name: clade-status
version: 1.0.0
description: Check Clade loop progress, worker status, costs, and recent commits
author: alexshen
tags: [claude-code, orchestrator, monitoring, devtools, coding-automation]
requires:
  env:
    - CLADE_BASE_URL
    - CLADE_API_KEY
---

# Clade — Status

Check the progress of autonomous coding loops running on a remote machine.

## When to use

User asks about:
- Loop progress, iteration count, convergence status
- What the AI is working on
- How much it costs / has cost
- Recent commits
- Whether there are blockers

## API

**Endpoint:** `GET {CLADE_BASE_URL}/status`

**Optional query:** `?project=/path/to/project` (omit to use default)

**Headers:**
```
Authorization: Bearer {CLADE_API_KEY}
```

**Response:**
```json
{
  "project": "/home/user/myproject",
  "loop": {
    "iteration": 3,
    "converged": false,
    "goal": "/home/user/myproject/goals/fix-tests.md",
    "started": "2025-03-24T14:30:45+0000"
  },
  "session": {
    "mode": "run",
    "status": "running",
    "outer_iter": 2,
    "feature": "auth-middleware"
  },
  "cost": {"total": "2.14", "last_iter": "0.43"},
  "recent_commits": [
    "abc1234 feat: add auth middleware",
    "def5678 fix: login redirect bug",
    "ghi9012 test: add auth integration tests"
  ],
  "last_supervisor": "Planning 2 tasks: fix login test, update schema...",
  "has_blockers": false
}
```

## How to format the response

Format as a compact, phone-friendly message:

```
{converged ? "✅" : "🔄"} Loop: iter {iteration}/{max_iter if known, else "?"} ({converged ? "CONVERGED" : status})
📋 Goal: {goal filename, not full path}
🏷️ Feature: {feature}
💰 Cost: ${total} (last iter: ${last_iter})

Recent commits:
  {each commit on its own line, indented}

{if has_blockers: "⚠️ BLOCKERS detected — run clade-report for details"}
{if last_supervisor not empty: "🧠 Supervisor: \"{first 100 chars}...\""}
```

## Error handling

- **Connection refused**: "Monitor is not running. Start it with: `python monitor.py -p /project`"
- **401 Unauthorized**: "Check your CLADE_API_KEY — it doesn't match the monitor's key."
- **404 project not found**: "Project path not recognized. Check the --project flag on monitor.py."
