#!/usr/bin/env bash
# sync-store-heal.sh — Shared append-only healers for sync-store metadata.

sync_store_append_missing_lines() {
  local _target="$1" _line _last_char
  while IFS= read -r _line; do
    if grep -qxF -- "$_line" "$_target" 2>/dev/null; then
      continue
    fi
    {
      _last_char=$(tail -c 1 "$_target") || return 1
      if [[ -n "$_last_char" ]]; then
        printf '\n'
      fi
      printf '%s\n' "$_line"
    } 2>/dev/null >> "$_target" || return 1
  done
  return 0
}

_sync_store_heal_gitignore_group() {
  local _target="$1" _comment="$2" _pattern _missing=false
  shift 2
  for _pattern in "$@"; do
    if ! grep -qxF -- "$_pattern" "$_target" 2>/dev/null; then
      _missing=true
    fi
  done
  [[ "$_missing" == true ]] || return 0
  {
    printf '%s\n' "$_comment"
    for _pattern in "$@"; do
      printf '%s\n' "$_pattern"
    done
  } | sync_store_append_missing_lines "$_target"
}

sync_store_heal_gitignore() {
  local _target="$1"
  _sync_store_heal_gitignore_group "$_target" \
    '# Raw correction events are private; keep them local.' \
    'corrections/history.jsonl' || return 1
  _sync_store_heal_gitignore_group "$_target" \
    '# Local safety backups.' \
    '*.bak-*' '.backups/' || return 1
  _sync_store_heal_gitignore_group "$_target" \
    "# Claude Code's regenerated skill cache stays local." \
    'skills/synced/' || return 1
  _sync_store_heal_gitignore_group "$_target" \
    '# Byte-compiled Python caches cause cross-machine conflicts.' \
    '__pycache__/' '*.py[cod]' || return 1
  _sync_store_heal_gitignore_group "$_target" \
    '# Self-heal forensic backups stay local.' \
    '*.corrupt.*' || return 1
  _sync_store_heal_gitignore_group "$_target" \
    "# Claude Code's removed-skill trash stays local." \
    'skills/.trash/' || return 1
  _sync_store_heal_gitignore_group "$_target" \
    "# Claude Code's auto-dream lock and session logs are per-host and private." \
    '.consolidate-lock' 'projects-memory/*/logs/' || return 1
}
