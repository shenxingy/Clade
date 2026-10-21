#!/usr/bin/env bash
# decision-to-kimi.sh — run a Claude-Code-style hook script unmodified under
# Kimi Code CLI, by translating its blocking convention into Kimi's.
#
# Clade's PreToolUse guardian scripts (pre-tool-guardian.sh) always exit 0
# and signal a block by printing {"decision":"block","reason":"..."} to
# stdout — Claude Code's own convention. Kimi Code CLI does not recognize
# that shape at all: verified live (Kimi 2.0.0) that a hook printing
# {"decision":"block",...} with exit 0 is silently treated as ALLOW, because
# Kimi checks only the exit code (2 = block) or a JSON object shaped
# {"hookSpecificOutput":{"permissionDecision":"deny","permissionDecisionReason":...}}.
# Both of those were verified live to actually block, the second with the
# custom reason surfaced to the model.
#
# This script is the translation shim — the wrapped script itself (and
# Claude Code's own use of it via settings-hooks.json) is untouched.
#
# Three input shapes, since pre-tool-guardian.sh moved to Claude Code's current
# schema on 2026-10-20 (its legacy top-level decision was deprecated, and the
# "allow" form was rejected outright):
#   {"decision":"block","reason":…}                         legacy → deny
#   {"hookSpecificOutput":{"permissionDecision":"deny",…}}  current → deny
#   {"hookSpecificOutput":{"updatedInput":{"command":…}}}   a REWRITE → deny,
#     naming the safer command. Kimi's support for rewriting input is not
#     verified, so the shim does not forward it; before 2026-10-20 it dropped
#     rewrites and Kimi ran the ORIGINAL command (an unset-variable recursive
#     delete, a plain force push). Refusing with the safer command in the
#     reason lets the model run that instead.
#
# Usage, as a Kimi [[hooks]] `command`:
#   /path/to/decision-to-kimi.sh /path/to/claude-style-hook.sh
#
# Fails open on any error (missing wrapped script, non-JSON output, jq
# missing) — same default Kimi itself documents for a hook that errors.

set -uo pipefail

WRAPPED="${1:-}"
if [[ -z "$WRAPPED" || ! -x "$WRAPPED" ]]; then
  exit 0
fi

INPUT=$(cat)
OUTPUT=$(printf '%s' "$INPUT" | "$WRAPPED" 2>/dev/null)

REASON=$(printf '%s' "$OUTPUT" | jq -r '
  if .decision? == "block" then (.reason // "")
  elif .hookSpecificOutput?.permissionDecision? == "deny" then (.hookSpecificOutput.permissionDecisionReason // "")
  elif (.hookSpecificOutput?.updatedInput?.command? | type) == "string" then
    "Refused as written. Run this safer form instead: " + .hookSpecificOutput.updatedInput.command
      + (if (.hookSpecificOutput.additionalContext // "") != "" then " — " + .hookSpecificOutput.additionalContext else "" end)
  else empty end' 2>/dev/null || true)
if [[ -n "$REASON" ]]; then
  jq -n --arg reason "$REASON" \
    '{hookSpecificOutput: {permissionDecision: "deny", permissionDecisionReason: $reason}}' \
    2>/dev/null
fi
exit 0
