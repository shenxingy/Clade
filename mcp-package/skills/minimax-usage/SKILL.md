---
name: minimax-usage
description: Check your API usage quota (auto-detects Minimax vs Claude Code)
when_to_use: "check usage, API quota, minimax usage, usage stats"
argument-hint: ''
user_invocable: true
---

# Minimax Usage Skill

Check your API usage quota. Auto-detects Minimax or Claude Code subscription.

## Auto-Detection

- Minimax: if `MINIMAX_CODING_API_KEY`, `MINIMAX_GROUP_ID`, or `ANTHROPIC_BASE_URL` contains "minimax.io"
- Claude Code: default

## Usage

```
/minimax-usage
```

Shows usage %, pace indicator, and remaining quota.
