#!/usr/bin/env bash
# post-compact-reinject.sh — SessionStart hook (matcher: compact)
# exists-for: the PreCompact-saved task goal was silently lost on every compaction because SessionStart was wired for startup only (fixed 2026-07-05 in 677aa5d) · retire-when: pre-compact.sh retires, or Claude Code carries the pinned task state across compaction itself
#
# Closes a "Defined ≠ called" wiring hole. The PreCompact hook already SAVES
# active task state to .claude/compact-state.md (pre-compact.sh), and
# session-context.sh can RELOAD it — but that reload only ran under
# matcher:"startup", which never fires on a compaction. Claude Code fires
# SessionStart with source "compact" for BOTH auto- and manual (/compact)
# compaction (docs: "Auto or manual compaction"); a startup-only matcher misses
# it, so after an in-session auto-compaction the pinned task goal was silently
# lost — exactly the long-run failure the orchestrator exists to prevent.
#
# This hook is the missing "after" half. On the compact source it re-injects
# ONLY the pinned invariants (the saved task goal/state). It is deliberately
# lean: it does NOT re-run the heavy startup session-context.sh (git fetch /
# memory-sync / commit-archeology), which would dump the full context blob on
# every compaction.
#
# It also clears the path-scoped rule sentinel (<session_id>.rules-injected) so
# rules that compaction dropped re-inject on the next matching Edit/Write or
# Bash file access via rule-injector.sh. Path-scoped rules matter most exactly
# when you next touch a matching path, so re-arming on the next touch is the
# correct semantics (and reuses the already-tested injector path instead of
# duplicating its parser).
#
# Output: hookSpecificOutput.additionalContext with the saved state. Silent
# (no output, exit 0) whenever there is nothing fresh to restore.

set -u

command -v jq >/dev/null 2>&1 || exit 0

INPUT=""
if [ ! -t 0 ]; then
  INPUT=$(cat 2>/dev/null || true)
fi

# Belt-and-braces: only act on the compaction source even if the matcher widens
# later. An empty source (e.g. a bare `echo '{}' | hook` in tests) still proceeds.
SOURCE=$(printf '%s' "$INPUT" | jq -r '.source // empty' 2>/dev/null || true)
if [ -n "$SOURCE" ] && [ "$SOURCE" != "compact" ]; then
  exit 0
fi

SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)
# Same reduction rule-injector.sh applies before naming its sentinel.
SESSION_ID="${SESSION_ID//[^A-Za-z0-9_-]/_}"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
CLAUDE_DIR="$PROJECT_DIR/.claude"

# ─── A subagent compacted: leave the main thread's state alone ───────
# Claude Code fires this hook when a SUBAGENT compacts too. Until 2.1.323 the
# input carried no agent_id ("Fixed PreCompact, PostCompact and post-compaction
# SessionStart hooks not receiving agent_id and agent_type when a subagent
# compacts"), so this hook cleared the MAIN thread's rule sentinel and told the
# subagent to "resume" from the project snapshot below: the main checkout's
# commits, status and TODO backlog, not the subagent's brief. Measured
# 2026-11-16 on one host: 167 retained subagent transcripts, Workflow agents
# among them, received that restore as hook context. A subagent's task is its
# brief, so re-arm only its own sentinel and inject nothing.
# transcript_path is the fallback for versions without agent_id: a subagent's
# transcript is .../subagents/.../agent-<id>.jsonl. Whether those versions pass
# the subagent's path here is unverified; when they do not, nothing changes.
AGENT_ID=$(printf '%s' "$INPUT" | jq -r '.agent_id // empty' 2>/dev/null || true)
if [ -z "$AGENT_ID" ]; then
  TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null || true)
  case "$TRANSCRIPT_PATH" in
    */subagents/agent-*.jsonl|*/subagents/*/agent-*.jsonl)
      AGENT_ID="${TRANSCRIPT_PATH##*/agent-}"
      AGENT_ID="${AGENT_ID%.jsonl}"
      ;;
  esac
fi
if [ -n "$AGENT_ID" ]; then
  # Same reduction rule-injector.sh applies to name the subagent's sentinel.
  AGENT_ID="${AGENT_ID//[^A-Za-z0-9_-]/_}"
  if [ -n "$SESSION_ID" ]; then
    rm -f "$CLAUDE_DIR/sessions/${SESSION_ID}.agent-${AGENT_ID}.rules-injected" 2>/dev/null || true
  fi
  exit 0
fi

# ─── Re-arm path-scoped rules dropped by compaction ──────────────────
# rule-injector.sh injects each rule file at most once/session via this sentinel.
# Compaction erases the injected rule text, so clear the sentinel: the next
# Edit/Write or Bash access to a matching path re-injects the rule through the
# already-tested injector. Only the main thread's sentinel: a subagent's
# (<session_id>.agent-<agent_id>.rules-injected) belongs to its own context.
if [ -n "$SESSION_ID" ]; then
  rm -f "$CLAUDE_DIR/sessions/${SESSION_ID}.rules-injected" 2>/dev/null || true
fi

# ─── Re-inject the pinned task goal / working state ──────────────────
# compact-state.md is written by pre-compact.sh immediately before compaction.
# Guard on age (< 2h, mirrors session-context.sh) so a stale file from a much
# earlier run is not resurfaced.
COMPACT_STATE="$CLAUDE_DIR/compact-state.md"
[ -f "$COMPACT_STATE" ] || exit 0

CS_MTIME=$(stat -c %Y "$COMPACT_STATE" 2>/dev/null || stat -f %m "$COMPACT_STATE" 2>/dev/null || echo 0)
CS_AGE_HOURS=$(( ( $(date +%s) - CS_MTIME ) / 3600 ))
[ "$CS_AGE_HOURS" -lt 2 ] || exit 0

COMPACT_CONTENT=$(cat "$COMPACT_STATE" 2>/dev/null)
[ -n "$COMPACT_CONTENT" ] || exit 0

# ─── Frame it by whether a task was recorded ─────────────────────────
# A snapshot with no recorded task is orientation, not an instruction. Every
# restore on the author's machine (25 of 25, 2026-09-18 → 10-26) was that kind:
# nothing writes current-task.md, and the PreCompact `prompt` hook cannot write
# at all (a prompt hook is a single-turn evaluation with no tools). 19 of them
# carried open TODO items, under a header that said "resume from it rather than
# re-deriving intent from the summary" — ranking a backlog above the summary of
# what the user asked. Anthropic's 2026-10-23 assessment of the UK AISI incident
# calls the failure this feeds "momentum": compaction notes that "imply to it
# that its current path has been (correctly) sanctioned". "(no current-task.md
# found)" is the marker an older pre-compact.sh still writes on other machines.
if grep -qF -e '(none recorded' -e '(no current-task.md found)' <<< "$COMPACT_CONTENT"; then
  CTX="## Post-compaction context (the conversation was just compacted)
No task was recorded before compaction. The summary above and the user's latest
message say what you are doing; the repository snapshot below is orientation
only. Its open TODO items are backlog, not instructions: do not start one the
user has not asked for in this session. Path-scoped rules re-inject when you
next edit a matching file.

${COMPACT_CONTENT}"
else
  CTX="## Post-compaction restore (the conversation was just compacted)
Your task state below was saved immediately before compaction — resume from it
rather than re-deriving intent from the summary. Path-scoped rules re-inject when
you next edit a matching file.

${COMPACT_CONTENT}"
fi

jq -n --arg ctx "$CTX" \
  '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$ctx}}'

exit 0
