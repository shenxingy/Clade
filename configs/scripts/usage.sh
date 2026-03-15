#!/usr/bin/env bash
# usage — Auto-detect subscription and run appropriate usage checker.
#
# Detects: Minimax vs Claude Code
# - If MINIMAX_CODING_API_KEY or MINIMAX_GROUP_ID set → Minimax
# - If ANTHROPIC_BASE_URL contains "minimax.io" → Minimax
# - Otherwise → Claude Code

# Helper to get value from settings.json (top-level or .env)
get_setting() {
    local key="$1"
    python3 -c "
import json
from pathlib import Path
p = Path.home() / '.claude' / 'settings.json'
if p.exists():
    d = json.load(open(p))
    # Check top-level
    if '$key' in d:
        print(d['$key'])
        return
    # Check .env section
    env = d.get('env', {})
    if '$key' in env:
        print(env['$key'])
" 2>/dev/null
}

# Check for Minimax indicators (env vars)
if [[ -n "${MINIMAX_CODING_API_KEY:-}" ]] || [[ -n "${MINIMAX_GROUP_ID:-}" ]]; then
    exec ~/.claude/scripts/minimax-usage.sh
fi

# Check for Minimax in settings.json
MM_API_KEY=$(get_setting "minimax_api_key")
MM_GROUP_ID=$(get_setting "minimax_group_id")
if [[ -n "$MM_API_KEY" ]] || [[ -n "$MM_GROUP_ID" ]]; then
    export MINIMAX_CODING_API_KEY="$MM_API_KEY"
    export MINIMAX_GROUP_ID="$MM_GROUP_ID"
    exec ~/.claude/scripts/minimax-usage.sh
fi

# Check ANTHROPIC_BASE_URL for minimax (env or settings)
ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-$(get_setting 'ANTHROPIC_BASE_URL')}"
if [[ "$ANTHROPIC_BASE_URL" == *"minimax.io"* ]]; then
    exec ~/.claude/scripts/minimax-usage.sh
fi

# Fall back to Claude Code usage
exec ~/.claude/scripts/claude-usage-watch.py
