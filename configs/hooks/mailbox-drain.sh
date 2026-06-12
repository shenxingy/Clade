#!/usr/bin/env bash
# mailbox-drain.sh — PostToolUse hook (all tools)
#
# Mid-flight worker steering: orchestrator workers run as headless `claude -p`
# processes, so the supervisor normally has no way to correct a misdirected
# worker short of killing it. This hook is the low-latency correction channel:
# the orchestrator (routes/tasks.py:send_task_message) drops a message into
#   $CLAUDE_PROJECT_DIR/.claude/worker-inbox-$CLADE_WORKER_TASK_ID.md
# and this hook injects it as additionalContext on the worker's next tool call.
#
# Delivery semantics (keep in sync with routes/tasks.py + worker_taskfile.py):
#   - The inbox file is drained AT MOST ONCE: atomic mv-then-read claims the
#     file before reading, so a concurrent writer (os.replace on the
#     orchestrator side) or a racing second drainer can never split a message
#     or deliver it twice from the same file.
#   - This is the MID-FLIGHT channel only. Spawn-time mailbox injection
#     (worker_taskfile.py, unread worker_messages DB rows) remains the
#     at-spawn channel; the DB row is the durable source of truth.
#   - A message written after the worker's final tool call is simply never
#     drained here — it is left for the next spawn, where the at-spawn channel
#     delivers it and worker_taskfile.py removes the stale inbox file.
#   - Non-worker sessions: CLADE_WORKER_TASK_ID is unset (worker.py exports it
#     only into orchestrator worker env), so this hook is a no-op everywhere
#     else.
#
# Output: hookSpecificOutput.additionalContext with the inbox content.
# Silent (no output, exit 0) when there is nothing to drain — failure paths
# included.

set -u

# jq is required to emit valid JSON. Check BEFORE claiming the inbox so a
# jq-less machine never destroys a message it cannot deliver.
command -v jq &>/dev/null || exit 0

# Consume hook-input JSON so the writer never sees EPIPE (content unused —
# the drain decision is keyed on env + filesystem state, not the tool call).
if [ ! -t 0 ]; then
  cat > /dev/null 2>&1 || true
fi

TASK_ID="${CLADE_WORKER_TASK_ID:-}"
[ -z "$TASK_ID" ] && exit 0

# Path-safety: the env var is orchestrator-set, but never interpolate
# uncontrolled text into a filesystem path (defense in depth).
case "$TASK_ID" in
  *[!A-Za-z0-9._-]*) exit 0 ;;
esac

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
INBOX="$PROJECT_DIR/.claude/worker-inbox-$TASK_ID.md"

# Regular file only — refuse symlinks so a planted link can never pull
# arbitrary file content into the worker's context.
[ -L "$INBOX" ] && exit 0
[ -f "$INBOX" ] || exit 0

# Atomic claim: rename first, read after. mv within the same directory is
# rename(2) — a concurrent os.replace by the orchestrator either lands before
# (we drain the new content) or after (the new file waits for the next tool
# call). A racing second drainer loses the mv and exits silently.
DRAIN="$INBOX.draining.$$"
mv -- "$INBOX" "$DRAIN" 2>/dev/null || exit 0

# Cap injected bytes — steering messages are guidance, not payloads.
CONTENT=$(head -c 10000 "$DRAIN" 2>/dev/null || true)
rm -f -- "$DRAIN"

[ -z "$CONTENT" ] && exit 0

jq -n --arg ctx "[Worker inbox — mid-flight steering from the orchestrator]
$CONTENT
[End of inbox. Adjust course accordingly and continue the task — do not stop to acknowledge.]" \
  '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":$ctx}}'

exit 0
