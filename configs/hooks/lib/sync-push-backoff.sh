#!/usr/bin/env bash
# Shared sync-push circuit-breaker state and exponential backoff arithmetic.

# Return 0 while pushes are paused. An expired window returns 1 and sets
# _backoff_half_open=true so memory-sync can claim one probe. sync-health uses
# _backoff_status to distinguish absent, unreadable, active and expired state.
sync_push_backoff_active() {
  _backoff_half_open=false
  _backoff_status=absent
  _backoff_until=""
  local _file="${CLADE_SYNC_PUSH_BACKOFF_FILE:-$CLAUDE_DIR/.sync-push-backoff}"
  local _failed_at="" _failures="" _reason="" _extra=""
  _backoff_file="$_file"
  _backoff_reason=""
  [[ -f "$_file" ]] || return 1
  _backoff_status=unreadable
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
  _backoff_until=$((_failed_at + _window))
  _backoff_file="$_file"
  _backoff_now="$_now"
  _backoff_failures="$_failures"
  _backoff_reason="$_reason"
  if [[ $((_now - _failed_at)) -lt "$_window" ]]; then
    _backoff_status=active
    return 0
  fi
  _backoff_status=expired
  _backoff_half_open=true
  return 1
}
