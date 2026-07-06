#!/usr/bin/env bash
# ensure-dev-server.sh — idempotent dev-server discovery/start, shared state.
#
# Round-4 gap (Thorsten Ball, ampcode.com): /verify, verify-app, and
# session-context.sh each independently re-derived dev-server reuse/restart/
# cold-start logic with no shared state — real risk of duplicate dev-server
# starts across concurrent worktree workers hammering the same port.
#
# This script is the single source of truth: check .claude/dev-server.json
# first (reuse if the recorded pid is actually still alive AND the port is
# reachable); otherwise detect + start the project's dev server, wait for it
# to become reachable, and persist the discovery record. flock-guarded (mkdir
# fallback on platforms without flock, same pattern as run-tasks-parallel.sh's
# update_progress) so concurrent callers serialize instead of racing a
# double-start.
#
# Usage:
#   ensure-dev-server.sh [port] [project_dir]
#   port defaults to CLAUDE.md's "Frontend: ... port NNNN" line, else 3000.
#   project_dir defaults to $CLAUDE_PROJECT_DIR or the cwd.
#
# Output (stdout, one line, machine-parseable):
#   PORT=<port> STATUS=reused|started|unreachable [PID=<pid>]
# Exit code: 0 = reachable (reused or freshly started), 1 = unreachable.

set -u

PROJECT_DIR="${2:-${CLAUDE_PROJECT_DIR:-$(pwd)}}"
CLAUDE_DIR="$PROJECT_DIR/.claude"
mkdir -p "$CLAUDE_DIR"

STATE_FILE="$CLAUDE_DIR/dev-server.json"
LOCK_FILE="$CLAUDE_DIR/dev-server.lock"
LOCK_DIR="$CLAUDE_DIR/dev-server.lockdir"

# ─── Port resolution ────────────────────────────────────────────────
PORT="${1:-}"
if [ -z "$PORT" ] && [ -f "$PROJECT_DIR/CLAUDE.md" ]; then
  PORT=$(grep -oE '^Frontend:.*[Pp]ort[[:space:]]+[0-9]+' "$PROJECT_DIR/CLAUDE.md" 2>/dev/null \
         | grep -oE '[0-9]+$' | head -1)
fi
PORT="${PORT:-3000}"

is_reachable() {
  curl -sf -o /dev/null --max-time 2 "http://localhost:$PORT" 2>/dev/null
}

pid_alive() {
  [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null
}

emit() {
  # $1=status  $2=optional pid
  if [ -n "${2:-}" ]; then
    echo "PORT=$PORT STATUS=$1 PID=$2"
  else
    echo "PORT=$PORT STATUS=$1"
  fi
}

_ensure_locked() {
  # Reuse: state file claims a pid, that pid is alive, AND the port answers.
  if [ -f "$STATE_FILE" ] && command -v jq &>/dev/null; then
    _rec_pid=$(jq -r '.pid // empty' "$STATE_FILE" 2>/dev/null)
    _rec_port=$(jq -r '.port // empty' "$STATE_FILE" 2>/dev/null)
    if [ -n "$_rec_pid" ] && [ "$_rec_port" = "$PORT" ] && pid_alive "$_rec_pid" && is_reachable; then
      emit reused "$_rec_pid"
      return 0
    fi
  fi

  # Already reachable but untracked (started outside this script, e.g. the
  # user's own terminal) — record it as reused, never start a second one.
  if is_reachable; then
    emit reused
    return 0
  fi

  # Not reachable — detect a start command.
  START_CMD=""
  if [ -f "$PROJECT_DIR/package.json" ] && command -v jq &>/dev/null \
     && jq -e '.scripts.dev' "$PROJECT_DIR/package.json" &>/dev/null; then
    if [ -f "$PROJECT_DIR/pnpm-lock.yaml" ]; then START_CMD="pnpm dev"
    elif [ -f "$PROJECT_DIR/yarn.lock" ]; then START_CMD="yarn dev"
    else START_CMD="npm run dev"
    fi
  fi
  if [ -z "$START_CMD" ]; then
    emit unreachable
    return 1
  fi

  LOG_FILE="$CLAUDE_DIR/dev-server.log"
  PID_TMP="$CLAUDE_DIR/dev-server.pid.tmp"
  rm -f "$PID_TMP"
  # The detached process reports its OWN pid via $$ as its first action (more
  # robust than capturing $! from the parent — avoids any ambiguity around
  # which layer of nested subshell/background job $! would refer to). `exec`
  # replaces that reporting shell with the real dev-server command, so the pid
  # stays valid for the process's whole lifetime.
  # 200>&- closes the inherited flock fd in the detached child — without it,
  # the long-lived dev server holds fd 200 open forever and the exclusive
  # lock on dev-server.lock never releases, wedging every future call.
  ( cd "$PROJECT_DIR" \
      && exec setsid bash -c "echo \$\$ > $(printf '%q' "$PID_TMP"); exec $START_CMD" \
              > "$LOG_FILE" 2>&1 200>&- ) &
  disown %% 2>/dev/null || true
  _waited_pid=0
  while [ "$_waited_pid" -lt 20 ]; do
    [ -s "$PID_TMP" ] && break
    sleep 0.1
    _waited_pid=$((_waited_pid + 1))
  done
  NEW_PID=$(cat "$PID_TMP" 2>/dev/null || true)
  rm -f "$PID_TMP"

  # Wait up to 30s for it to become reachable.
  _waited=0
  while [ "$_waited" -lt 30 ]; do
    is_reachable && break
    sleep 1
    _waited=$((_waited + 1))
  done

  if is_reachable; then
    if command -v jq &>/dev/null; then
      jq -n --arg port "$PORT" --arg pid "$NEW_PID" --arg cmd "$START_CMD" \
         --arg started "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '{port: ($port|tonumber), pid: ($pid|tonumber), command: $cmd, started_at: $started}' \
        > "$STATE_FILE"
    fi
    emit started "$NEW_PID"
    return 0
  else
    emit unreachable
    return 1
  fi
}

(
  if command -v flock &>/dev/null; then
    flock -x 200
  else
    # macOS-without-flock fallback: portable atomic mkdir spin-lock.
    while ! mkdir "$LOCK_DIR" 2>/dev/null; do sleep 0.1; done
    trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT
  fi
  _ensure_locked
) 200>"$LOCK_FILE"
exit $?
