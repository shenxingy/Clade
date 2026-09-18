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

DECISION=$(printf '%s' "$OUTPUT" | jq -r '.decision // empty' 2>/dev/null || true)
if [[ "$DECISION" == "block" ]]; then
  REASON=$(printf '%s' "$OUTPUT" | jq -r '.reason // empty' 2>/dev/null || true)
  jq -n --arg reason "${REASON:-blocked by $(basename "$WRAPPED")}" \
    '{hookSpecificOutput: {permissionDecision: "deny", permissionDecisionReason: $reason}}' \
    2>/dev/null
fi
exit 0
