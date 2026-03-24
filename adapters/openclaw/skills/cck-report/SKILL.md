---
name: cck-report
version: 1.0.0
description: Get session reports, cost breakdowns, and blocker details from Claude Code Kit
author: alexshen
tags: [claude-code, orchestrator, reporting, devtools, coding-automation]
requires:
  env:
    - CCK_BASE_URL
    - CCK_API_KEY
---

# Claude Code Kit — Report

Get detailed session reports, cost breakdowns, blockers, and skipped tasks.

## When to use

User asks about:
- Session summary / what was accomplished
- Cost breakdown per iteration
- What tasks were skipped and why
- What blockers exist
- "What happened overnight" / "今天干了什么"

## API

**Endpoint:** `GET {CCK_BASE_URL}/report`

**Optional query:** `?project=/path/to/project`

**Headers:**
```
Authorization: Bearer {CCK_API_KEY}
```

**Response:**
```json
{
  "project": "/home/user/myproject",
  "report": "## Session: 2025-03-24 14:30 → 22:15 (465min)\n\n### Status: converged\n\n### Completed\n12 commits since session start.\n\n### Skipped (2 tasks)\n## Skipped: flaky integration test\nReason: External API timeout\n\n### Blockers (0)\nNone\n\n### Cost: $8.42\n\n### Iterations: 5\n\n### Feature: auth-middleware",
  "cost_history": [
    {"ITER": "1", "COST": "1.50", "CUMULATIVE": "1.50", "TASKS": "3", "DURATION": "8min"},
    {"ITER": "2", "COST": "2.10", "CUMULATIVE": "3.60", "TASKS": "4", "DURATION": "12min"},
    {"ITER": "3", "COST": "1.80", "CUMULATIVE": "5.40", "TASKS": "2", "DURATION": "6min"}
  ],
  "blockers": "",
  "skipped": "## [2025-03-24T18:30:00+0000] Skipped: flaky integration test\nReason: External API timeout during test run\nAttempted: Retry 3 times, all timed out"
}
```

## How to format the response

### Full report:
```
📊 Session Report — {project name}
⏱️ {start time} → {end time} ({duration})
✅ Status: {status}

📈 Progress: {completed_count} commits in {iterations} iterations
💰 Total cost: ${cost}

{if cost_history:}
Cost per iteration:
  Iter 1: ${cost} ({tasks} tasks, {duration})
  Iter 2: ${cost} ({tasks} tasks, {duration})
  ...

{if skipped not empty:}
⏭️ Skipped tasks:
{skipped content, summarized to 2-3 lines max}

{if blockers not empty:}
⚠️ Blockers:
{blockers content, summarized to 2-3 lines max}
```

### Quick cost summary (when user just asks "how much"):
```
💰 Total: ${cumulative from last cost_history entry}
Last iteration: ${cost} for {tasks} tasks in {duration}
```

## Error handling

- **Connection refused**: "Monitor is not running."
- **401 Unauthorized**: "Check your CCK_API_KEY."
- **"No session report found"**: "No completed session yet. The loop may still be running — try 'status' instead."
