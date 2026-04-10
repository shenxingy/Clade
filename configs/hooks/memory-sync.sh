#!/usr/bin/env bash
# memory-sync.sh — Auto-push after writes to synced ~/.claude/ directories (PostToolUse, async)
#
# Triggers sync-push.sh when Claude writes/edits a file under any synced dir:
#   ~/.claude/memory/             (global memory)
#   ~/.claude/projects/*/memory/  (project memory)
#   ~/.claude/skills/             (skills)
#   ~/.claude/hooks/              (hooks)
#   ~/.claude/scripts/            (scripts)
#   ~/.claude/corrections/        (corrections)
#
# Non-blocking: runs sync-push in background.

set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
SYNC_CONFIG="$CLAUDE_DIR/.sync-config"

# Skip entirely if sync not configured
[[ -f "$SYNC_CONFIG" ]] || exit 0

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)

is_synced_path=false

if [[ "$TOOL_NAME" == "Write" || "$TOOL_NAME" == "Edit" ]]; then
  # ─── Write/Edit: check file_path ─────────────────────────────────────────
  FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
  [[ -z "$FILE_PATH" ]] && exit 0
  FILE_PATH="${FILE_PATH/#\~/$HOME}"

  for synced_dir in memory skills hooks scripts corrections; do
    if [[ "$FILE_PATH" == "$CLAUDE_DIR/$synced_dir/"* ]]; then
      is_synced_path=true; break
    fi
  done
  if [[ "$FILE_PATH" =~ ^$CLAUDE_DIR/projects/[^/]+/memory/ ]]; then
    is_synced_path=true
  fi

elif [[ "$TOOL_NAME" == "Bash" ]]; then
  # ─── Bash: check if command touches a synced directory (covers rm/mv/mkdir) ─
  COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
  if echo "$COMMAND" | grep -qE "(~/.claude|$CLAUDE_DIR)/(skills|memory|hooks|scripts|corrections|projects/[^/]+/memory)"; then
    is_synced_path=true
  fi
fi

[[ "$is_synced_path" == false ]] && exit 0

# ─── DreamConsolidator: 7-gate quality filter for memory paths ───────────────
# Only applies to memory/ directories — skills/hooks/scripts/corrections always sync.
# Gates prevent low-value, duplicate, or premature memory writes from polluting sync.

_is_memory_path=false
if [[ "$FILE_PATH" == "$CLAUDE_DIR/memory/"* ]] || \
   [[ "$FILE_PATH" =~ ^$CLAUDE_DIR/projects/[^/]+/memory/ ]]; then
  _is_memory_path=true
fi

if [[ "$_is_memory_path" == true && "$TOOL_NAME" != "Bash" ]]; then
  # Gate 1: Specificity — content too short to be useful
  _content_len=0
  if [[ -f "$FILE_PATH" ]]; then
    _content_len=$(wc -c < "$FILE_PATH" 2>/dev/null || echo 0)
  fi
  if [[ "$_content_len" -lt 80 ]]; then
    exit 0  # too vague, skip sync
  fi

  # Gate 2: Scope — skip draft/tmp/wip files
  _basename=$(basename "$FILE_PATH")
  if echo "$_basename" | grep -qiE '(-draft|-tmp|-wip|\.tmp|\.draft)'; then
    exit 0
  fi

  # Gate 3: Recency — file touched in last 60 seconds (already synced this session)
  _now=$(date +%s)
  _mtime=$(stat -c %Y "$FILE_PATH" 2>/dev/null || stat -f %m "$FILE_PATH" 2>/dev/null || echo 0)
  _age=$(( _now - _mtime ))
  # Allow if file is very new (< 5s = just written) but skip if recently synced (5-60s)
  # We want to sync new writes, not re-sync unchanged files opened mid-session
  if [[ "$_age" -gt 5 && "$_age" -lt 60 ]]; then
    exit 0
  fi

  # Gate 4: Confidence — hedged/uncertain content (3+ hedging words = skip)
  if [[ -f "$FILE_PATH" ]]; then
    _hedge_count=$(grep -ioE '\b(might|probably|unsure|maybe|not sure|could be|possibly)\b' "$FILE_PATH" 2>/dev/null | wc -l || echo 0)
    if [[ "$_hedge_count" -ge 3 ]]; then
      exit 0
    fi
  fi

  # Gate 5: 24h per-topic cooldown — prevent redundant syncs of same topic
  _cooldown_file="$CLAUDE_DIR/memory/.sync-cooldown.json"
  _topic=$(basename "$(dirname "$FILE_PATH")")/$(basename "$FILE_PATH" .md)
  if [[ -f "$_cooldown_file" ]]; then
    _last_ts=$(python3 -c "
import json, sys
try:
    d = json.load(open('$_cooldown_file'))
    print(d.get('$_topic', 0))
except Exception:
    print(0)
" 2>/dev/null || echo 0)
    _elapsed=$(( _now - ${_last_ts%.*} ))
    if [[ "$_elapsed" -lt 86400 ]]; then
      exit 0  # within 24h cooldown, skip
    fi
  fi

  # All gates passed — update cooldown timestamp
  python3 -c "
import json, os, time
f = '$_cooldown_file'
try:
    d = json.load(open(f)) if os.path.exists(f) else {}
except Exception:
    d = {}
d['$_topic'] = time.time()
with open(f, 'w') as fp:
    json.dump(d, fp)
" 2>/dev/null || true
fi

# ─── Trigger async push ──────────────────────────────────────────────────────

SYNC_PUSH="$CLAUDE_DIR/scripts/sync-push.sh"
[[ -x "$SYNC_PUSH" ]] || exit 0

"$SYNC_PUSH" &>/dev/null &
disown

exit 0
