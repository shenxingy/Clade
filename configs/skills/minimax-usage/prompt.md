You are the usage skill. Check API usage quota and display pace indicator.

## What this skill does

Automatically detects if user is on Minimax or Claude Code subscription and shows appropriate usage.

## Auto-Detection

The skill detects subscription type in this order:
1. If `MINIMAX_CODING_API_KEY` is set → use Minimax
2. If `MINIMAX_GROUP_ID` is set → use Minimax
3. If `ANTHROPIC_BASE_URL` contains "minimax.io" → use Minimax
4. Otherwise → use Claude Code (original usage tracking)

## Execute

Run the usage wrapper script:

```bash
~/.claude/scripts/usage.sh
```

The wrapper auto-detects Minimax vs Claude Code and runs the appropriate checker.
