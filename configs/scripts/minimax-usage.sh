#!/usr/bin/env bash
# minimax-usage — check Minimax Coding Plan usage.
#
# Usage:
#   ~/.claude/scripts/minimax-usage.sh
#
# Requires:
#   MINIMAX_CODING_API_KEY
#   MINIMAX_GROUP_ID
# Or reads from ~/.claude/settings.json

# Helper to get value from settings.json (top-level or .env)
get_setting() {
    local key="$1"
    python3 -c "
import json
from pathlib import Path
p = Path.home() / '.claude' / 'settings.json'
if p.exists():
    d = json.load(open(p))
    v = d.get('$key', '')
    if v:
        print(v)
    else:
        env = d.get('env', {})
        v = env.get('$key', '')
        if v:
            print(v)
" 2>/dev/null
}

# Get from env, fall back to settings.json (top-level or .env)
API_KEY="${MINIMAX_CODING_API_KEY:-$(get_setting 'minimax_api_key')}"
GROUP_ID="${MINIMAX_GROUP_ID:-$(get_setting 'minimax_group_id')}"

# Check if using Minimax via ANTHROPIC_BASE_URL
ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-$(get_setting 'ANTHROPIC_BASE_URL')}"
if [[ -n "$ANTHROPIC_BASE_URL" ]] && [[ "$ANTHROPIC_BASE_URL" == *"minimax.io"* ]]; then
    # Use ANTHROPIC_AUTH_TOKEN as API key for Minimax
    if [[ -z "$API_KEY" ]]; then
        API_KEY="$(get_setting 'ANTHROPIC_AUTH_TOKEN')"
    fi
fi

# ─── Validate ───
if [[ -z "$API_KEY" ]]; then
    echo "Error: MINIMAX_CODING_API_KEY not set"
    echo ""
    echo "Configure with:"
    echo '  export MINIMAX_CODING_API_KEY="sk-..."'
    exit 1
fi

if [[ -z "$GROUP_ID" ]]; then
    echo "Error: MINIMAX_GROUP_ID not set"
    echo ""
    echo "Configure with:"
    echo '  export MINIMAX_GROUP_ID="group_xxx"'
    exit 1
fi

# ─── Fetch usage ───
URL="https://platform.minimax.io/v1/api/openplatform/coding_plan/remains?GroupId=${GROUP_ID}"
HEADERS=(
    -H "accept: application/json"
    -H "authorization: Bearer ${API_KEY}"
    -H "referer: https://platform.minimax.io/user-center/payment/coding-plan"
)

RESPONSE=$(curl -s -w "\n%{http_code}" "${HEADERS[@]}" "$URL")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [[ "$HTTP_CODE" != "200" ]]; then
    echo "Error: API request failed (HTTP $HTTP_CODE)"
    echo "$BODY" | head -5
    exit 1
fi

# ─── Parse JSON ───
# Response format: { "model_remains": [{ "current_interval_total_count": 4500, "current_interval_usage_count": 3087 }] }
# IMPORTANT: current_interval_usage_count = REMAINS (not used!)
TOTAL=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); mr=d.get('model_remains',[]); print(mr[0].get('current_interval_total_count','?') if mr else '?')" 2>/dev/null)
REMAINS=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); mr=d.get('model_remains',[]); print(mr[0].get('current_interval_usage_count','?') if mr else '?')" 2>/dev/null)

if [[ "$TOTAL" == "?" || "$REMAINS" == "?" ]]; then
    echo "Error: Failed to parse API response"
    echo "$BODY"
    exit 1
fi

USED=$((TOTAL - REMAINS))
USAGE_PCT=$(awk "BEGIN {printf \"%.1f\", ($USED/$TOTAL)*100}")

# ─── Calculate pace ───
now=$(date +%s)
day_of_month=$(date +%-d)
days_in_month=$(date -d "$(date -d "+1 month" +%Y-%m-01) -1 day" +%d)
elapsed_pct=$(awk "BEGIN {printf \"%.1f\", ($day_of_month/$days_in_month)*100}")
delta=$(awk "BEGIN {printf \"%.1f\", $USAGE_PCT - $elapsed_pct * 0.95}")
remaining_days=$((days_in_month - day_of_month))

# ─── Display ───
echo "╭─────────────────────────────────╮"
echo "│      Minimax Coding Plan        │"
echo "├─────────────────────────────────┤"
echo "│  Total:     $TOTAL prompts        │"
echo "│  Used:      $USED prompts         │"
echo "│  Remaining: $REMAINS prompts       │"
echo "├─────────────────────────────────┤"
echo "│  Usage:     $USAGE_PCT%              │"
echo "│  Elapsed:   $elapsed_pct%              │"
echo "│  Days left: $remaining_days             │"
echo "├─────────────────────────────────┤"

# Pace indicator
if (( $(echo "$delta > 5" | bc -l) )); then
    symbol="✅"
    status="ahead of pace"
elif (( $(echo "$delta > -5" | bc -l) )); then
    symbol="⏸️"
    status="on track"
else
    symbol="⚠️"
    status="behind pace"
fi

sign=""
if (( $(echo "$delta > 0" | bc -l) )); then
    sign="+"
fi

echo "│  Pace:      $symbol $sign${delta}% ($status)    │"
echo "╰─────────────────────────────────╯"
