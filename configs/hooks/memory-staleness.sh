#!/usr/bin/env bash
# memory-staleness.sh — Print anchored memories changed in git (SessionStart).
# exists-for: no incident recorded; stale-memory need identified 2026-11-07, implementation based on e97312e · retire-when: Claude Code natively marks memories stale when their declared anchors change
# Stdout reaches the model beside the auto-loaded MEMORY.md index. The index is
# deliberately read-only: it lives in the multi-host sync store.

set -u

INPUT=$(cat 2>/dev/null || true)

PARSED=$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except (ValueError, TypeError):
    raise SystemExit(1)
transcript = data.get("transcript_path", "")
cwd = data.get("cwd", "")
if not isinstance(transcript, str) or not isinstance(cwd, str):
    raise SystemExit(1)
print(transcript + "\x1f" + cwd)
' 2>/dev/null)
IFS=$'\037' read -r TRANSCRIPT_PATH CWD <<< "$PARSED"
[ -n "$TRANSCRIPT_PATH" ] && [ -n "$CWD" ] || exit 0

TRANSCRIPT_DIR=$(dirname "$TRANSCRIPT_PATH" 2>/dev/null) || exit 0
MEMORY_DIR="$TRANSCRIPT_DIR/memory"
[ -d "$MEMORY_DIR" ] || exit 0
PROJECT_DIR="$CWD"

SCRIPT="$HOME/.claude/scripts/memory-staleness.py"
if [ ! -f "$SCRIPT" ]; then
  HOOK_DIR=$(CDPATH= cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)
  SCRIPT="$HOOK_DIR/../scripts/memory-staleness.py"
fi

OUTPUT=$(python3 "$SCRIPT" "$MEMORY_DIR" "$PROJECT_DIR" 2>/dev/null) || exit 0
[ -n "$OUTPUT" ] || exit 0

TOTAL=$(printf '%s\n' "$OUTPUT" | wc -l | tr -d ' ')
printf '## Memory staleness\n'
if [ "$TOTAL" -gt 10 ]; then
  printf '%s\n' "$OUTPUT" | head -n 10
  printf '... and %s more\n' "$((TOTAL - 10))"
else
  printf '%s\n' "$OUTPUT"
fi
exit 0
