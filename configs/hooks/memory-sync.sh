#!/usr/bin/env bash
# memory-sync.sh — Auto-push after writes to synced ~/.claude/ directories (PostToolUse, async)
# exists-for: no incident recorded (added 2026-03-19 in 485d6a9); need: push writes under synced ~/.claude dirs to the dotfiles sync store · retire-when: no machine keeps a ~/.claude/.sync-config, i.e. the sync store is retired
#
# Triggers sync-push.sh when Claude writes/edits a file under any synced dir:
#   ~/.claude/memory/             (global memory)
#   ~/.claude/projects/*/memory/  (project memory, and the same under
#                                 $CLAUDE_CONFIG_DIR/projects and
#                                 ~/.claude-profiles/*/projects)
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

sync_push_backoff_active() {
  _backoff_half_open=false
  local _file="${CLADE_SYNC_PUSH_BACKOFF_FILE:-$CLAUDE_DIR/.sync-push-backoff}"
  local _failed_at="" _failures="" _reason="" _extra=""
  [[ -f "$_file" ]] || return 1
  IFS=' ' read -r _failed_at _failures _reason _extra < "$_file"
  case "$_failed_at" in ''|*[!0-9]*) return 1 ;; esac
  case "$_failures" in ''|*[!0-9]*) return 1 ;; esac
  [[ "$_failures" -ge 1 && -n "$_reason" && -z "$_extra" ]] || return 1

  local _base="${CLADE_SYNC_PUSH_BACKOFF_BASE_SECONDS:-1800}"
  local _max="${CLADE_SYNC_PUSH_BACKOFF_MAX_SECONDS:-86400}"
  local _now="${CLADE_SYNC_PUSH_BACKOFF_NOW:-$(date +%s)}"
  case "$_base" in ''|*[!0-9]*|0) _base=1800 ;; esac
  case "$_max" in ''|*[!0-9]*) _max=86400 ;; esac
  case "$_now" in ''|*[!0-9]*) _now=$(date +%s) ;; esac

  local _window="$_base" _remaining
  _remaining=$((_failures - 1))
  while [[ "$_remaining" -gt 0 && "$_window" -lt "$_max" ]]; do
    _window=$((_window * 2))
    _remaining=$((_remaining - 1))
  done
  [[ "$_window" -gt "$_max" ]] && _window="$_max"
  if [[ $((_now - _failed_at)) -lt "$_window" ]]; then
    return 0
  fi
  _backoff_half_open=true
  _backoff_file="$_file"
  _backoff_now="$_now"
  _backoff_failures="$_failures"
  _backoff_reason="$_reason"
  return 1
}

# A project memory under any projects directory sync-link-projects.sh scans:
# ~/.claude/projects, $CLAUDE_CONFIG_DIR/projects and
# ~/.claude-profiles/*/projects. Matching ~/.claude/projects alone left every
# session run under a profile (CLAUDE_CONFIG_DIR) unpushed until some other
# trigger came along.
is_project_memory() {   # PATH -> 0 when PATH is <projects dir>/<slug>/memory/...
  local d rel
  for d in "$CLAUDE_DIR/projects" ${CLAUDE_CONFIG_DIR:+"$CLAUDE_CONFIG_DIR/projects"} \
           "$HOME"/.claude-profiles/*/projects; do
    rel="${1#"$d"/}"
    [[ "$rel" != "$1" && "$rel" == */* && "${rel#*/}" == memory/* ]] && return 0
  done
  return 1
}

is_synced_path=false
# Bound for every tool: the memory-path test below reads it, and under `set -u`
# a Bash call left it unset, so the hook died there ("FILE_PATH: unbound
# variable") before it reached sync-push. A synced change made through Bash
# never pushed: 4,916 such failures in 30 days of one host's transcripts.
FILE_PATH=""
_backoff_half_open=false

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
  if is_project_memory "$FILE_PATH"; then
    is_synced_path=true
  fi

elif [[ "$TOOL_NAME" == "Bash" ]]; then
  # ─── Bash: check if command touches a synced directory (covers rm/mv/mkdir) ─
  COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
  _synced_re="(~/.claude|$CLAUDE_DIR)/(skills|memory|hooks|scripts|corrections|projects/[^/]+/memory)"
  _synced_re="$_synced_re|(~|$HOME)/\.claude-profiles/[^/]+/projects/[^/]+/memory"
  [[ -n "${CLAUDE_CONFIG_DIR:-}" ]] && _synced_re="$_synced_re|$CLAUDE_CONFIG_DIR/projects/[^/]+/memory"
  if echo "$COMMAND" | grep -qE "$_synced_re"; then
    is_synced_path=true
  fi
fi

[[ "$is_synced_path" == false ]] && exit 0

# The breaker precedes every memory topic gate and every non-memory path class.
if sync_push_backoff_active; then
  exit 0
fi

# ─── DreamConsolidator: 7-gate quality filter for memory paths ───────────────
# Only applies to memory/ directories — skills/hooks/scripts/corrections always sync.
# Gates prevent low-value, duplicate, or premature memory writes from polluting sync.

_is_memory_path=false
if [[ "$FILE_PATH" == "$CLAUDE_DIR/memory/"* ]] || is_project_memory "$FILE_PATH"; then
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
    # `set -o pipefail` + grep-no-match would trip the `|| echo 0` and
    # produce "0\n0", breaking the numeric compare. Brace-group with `|| true`
    # absorbs grep's exit before the pipe to wc.
    _hedge_count=$({ grep -ioE '\b(might|probably|unsure|maybe|not sure|could be|possibly)\b' "$FILE_PATH" 2>/dev/null || true; } | wc -l)
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

if [[ "$_backoff_half_open" == true ]]; then
  _backoff_tmp="$_backoff_file.tmp.$$"
  # After a claim the timestamp is the last probe time. A failed claim degrades
  # to an unclaimed probe rather than aborting the hook.
  {
    printf '%s %s %s\n' "$_backoff_now" "$_backoff_failures" "$_backoff_reason" \
      > "$_backoff_tmp"
    mv -f "$_backoff_tmp" "$_backoff_file"
  } 2>/dev/null || {
    rm -f "$_backoff_tmp" 2>/dev/null || true
  }
fi

"$SYNC_PUSH" &>/dev/null &
disown

exit 0
