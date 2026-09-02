#!/usr/bin/env bash
# runtime-dir.sh — a private, per-user scratch root for Clade runtime state.
#
# Why this exists: every lock, pid file and shadow directory used to be a fixed
# path in /tmp (/tmp/claude-edit-shadows, /tmp/clade-radar.lock, ...). On a
# shared host that is a first-writer-wins race, and it is not hypothetical —
# measured on aries (40+ accounts, dotfiles shared over NFS):
#
#   /tmp/claude-edit-shadows   drwxrwxr-x alexshen alexshen
#   /tmp/claude-skill-suggest  drwxrwxr-x alexshen alexshen
#   /tmp/clade-radar.lock      -rw-rw-r-- alexshen alexshen
#
# Every other account's hooks then fail in three different ways, none of them
# loud: correction pairing fails OPEN (jq append gets EACCES, silently), radar
# and sync-push fail CLOSED and SILENT (`exec 9>` on an unopenable lock takes
# the `|| exit 0` branch before the first log line, or dies under `set -e`),
# and skill-suggest actively INTERFERES — its throttle key is derived from the
# suggestion text, not the user, so account B reads account A's timestamp and
# suppresses its own suggestion.
#
# `${XDG_RUNTIME_DIR:-/tmp/clade-$(id -u)}` is NOT enough on its own:
#   - /tmp/clade-<uid> is still a predictable path in a world-writable sticky
#     directory. Another account can pre-create it (or plant a symlink) and our
#     `mkdir -p` then succeeds against a directory we do not own. So the root is
#     validated after creation — real directory, not a symlink, owned by our
#     euid, mode 0700 — and the helper FAILS CLOSED when it is not.
#   - Writing straight into $XDG_RUNTIME_DIR puts Clade state in systemd's
#     namespace; use a `clade` subdirectory.
#   - `$(id -u)` forks, and two callers (skill-suggest, edit-shadow-detector)
#     sit on the Edit/Write critical path. Prefer the $EUID builtin.
#   - XDG_RUNTIME_DIR is unset under cron, which is exactly how radar-cron.sh
#     runs, so the ${TMPDIR:-/tmp} leg is a normal path, not an edge case.
#
# Callers must treat a non-zero return as "no scratch root available" and
# degrade deliberately (skip the feature), never as a hard error.

# clade_runtime_dir — echo a private per-user scratch root, or return 1.
# Order: $CLADE_RUNTIME_DIR (tests/overrides) → $XDG_RUNTIME_DIR/clade →
# ${TMPDIR:-/tmp}/clade-$EUID.
clade_runtime_dir() {
  local uid="${EUID:-}" d owner perm
  [ -n "$uid" ] || uid=$(id -u 2>/dev/null)
  [ -n "$uid" ] || return 1

  if [ -n "${CLADE_RUNTIME_DIR:-}" ]; then
    d="$CLADE_RUNTIME_DIR"
  elif [ -n "${XDG_RUNTIME_DIR:-}" ] && [ -d "${XDG_RUNTIME_DIR:-}" ] && [ -w "${XDG_RUNTIME_DIR:-}" ]; then
    d="$XDG_RUNTIME_DIR/clade"
  else
    d="${TMPDIR:-/tmp}/clade-$uid"
  fi

  mkdir -p "$d" 2>/dev/null || return 1

  # Fail closed on a squatted path: a symlink, someone else's directory, or one
  # other accounts can write into.
  [ -d "$d" ] && [ ! -L "$d" ] || return 1
  owner=$(stat -c %u "$d" 2>/dev/null || stat -f %u "$d" 2>/dev/null) || return 1
  [ -n "$owner" ] && [ "$owner" = "$uid" ] || return 1
  perm=$(stat -c %a "$d" 2>/dev/null || stat -f %Lp "$d" 2>/dev/null) || return 1
  case "$perm" in
    700) ;;
    *) chmod 700 "$d" 2>/dev/null || return 1 ;;
  esac

  printf '%s' "$d"
}

# clade_state_dir <name> — echo (creating) a subdirectory of the runtime root.
# Returns 1 when no usable root exists; the caller decides how to degrade.
clade_state_dir() {
  local root
  [ -n "${1:-}" ] || return 1
  root=$(clade_runtime_dir) || return 1
  [ -n "$root" ] || return 1
  mkdir -p "$root/$1" 2>/dev/null || return 1
  printf '%s/%s' "$root" "$1"
}
