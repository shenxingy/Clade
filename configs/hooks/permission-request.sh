#!/usr/bin/env bash
# permission-request.sh — Auto-allow known-safe read-only operations (Hooks §Gap5)
#
# Triggered: PermissionRequest
# Purpose:   For clearly safe, read-only tool patterns, auto-approve and inject
#            updatedPermissions so the same pattern is never asked again.
#
# Safety principle: ONLY auto-allow operations that cannot modify state.
# Everything else falls through to the normal permission dialog.
#
# Output: hookSpecificOutput JSON to auto-allow, or exit 0 to defer to user.

set -euo pipefail

INPUT=$(cat)

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null || echo "")

# ─── Non-Bash tools: Read, Glob, Grep are always safe ──────────────────────
if [[ "$TOOL_NAME" == "Read" || "$TOOL_NAME" == "Glob" || "$TOOL_NAME" == "Grep" ]]; then
  jq -n \
    --arg tool "$TOOL_NAME" \
    '{
      "hookSpecificOutput": {
        "hookEventName": "PermissionRequest",
        "decision": {
          "behavior": "allow",
          "updatedPermissions": [{
            "type": "addRules",
            "rules": [{"toolName": ($tool), "ruleContent": "*"}],
            "behavior": "allow",
            "destination": "localSettings"
          }]
        }
      }
    }'
  exit 0
fi

# ─── Bash tool: only allow specific read-only patterns ─────────────────────
if [[ "$TOOL_NAME" != "Bash" ]]; then
  exit 0  # Unknown tool — defer to user
fi

COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null || echo "")
if [[ -z "$COMMAND" ]]; then
  exit 0
fi

# Trim whitespace for matching
CMD_TRIMMED=$(echo "$COMMAND" | sed 's/^[[:space:]]*//' | cut -c1-200)

# ─── Read-only git commands ─────────────────────────────────────────────────
READONLY_GIT_PATTERNS=(
  "^git status"
  "^git log"
  "^git diff"
  "^git show"
  "^git branch"
  "^git remote"
  "^git tag"
  "^git rev-parse"
  "^git ls-files"
  "^git blame"
)

for pattern in "${READONLY_GIT_PATTERNS[@]}"; do
  if echo "$CMD_TRIMMED" | grep -qE "$pattern"; then
    RULE=$(echo "$CMD_TRIMMED" | sed 's/[[:space:]].*//')  # "git" → store as rule prefix
    jq -n \
      --arg rule "$(echo "$CMD_TRIMMED" | awk '{print $1, $2}')*" \
      '{
        "hookSpecificOutput": {
          "hookEventName": "PermissionRequest",
          "decision": {
            "behavior": "allow",
            "updatedPermissions": [{
              "type": "addRules",
              "rules": [{"toolName": "Bash", "ruleContent": ($rule)}],
              "behavior": "allow",
              "destination": "localSettings"
            }]
          }
        }
      }'
    exit 0
  fi
done

# ─── Read-only file inspection commands ────────────────────────────────────
READONLY_FILE_PATTERNS=(
  "^ls\b"
  "^cat\b"
  "^head\b"
  "^tail\b"
  "^wc\b"
  "^grep\b"
  "^find\b"
  "^rg\b"
  "^echo\b"
  "^printf\b"
  "^pwd$"
  "^which\b"
  "^type\b"
)

for pattern in "${READONLY_FILE_PATTERNS[@]}"; do
  if echo "$CMD_TRIMMED" | grep -qE "$pattern"; then
    CMD_BASE=$(echo "$CMD_TRIMMED" | awk '{print $1}')
    jq -n \
      --arg rule "${CMD_BASE} *" \
      '{
        "hookSpecificOutput": {
          "hookEventName": "PermissionRequest",
          "decision": {
            "behavior": "allow",
            "updatedPermissions": [{
              "type": "addRules",
              "rules": [{"toolName": "Bash", "ruleContent": ($rule)}],
              "behavior": "allow",
              "destination": "localSettings"
            }]
          }
        }
      }'
    exit 0
  fi
done

# ─── Python/test read-only commands ────────────────────────────────────────
TEST_PATTERNS=(
  "^python.*-m pytest"
  "^pytest\b"
  "^\.venv/bin/pytest\b"
  "^python.*-c\b"
  "^python.*--version"
)

for pattern in "${TEST_PATTERNS[@]}"; do
  if echo "$CMD_TRIMMED" | grep -qE "$pattern"; then
    jq -n '{
      "hookSpecificOutput": {
        "hookEventName": "PermissionRequest",
        "decision": {
          "behavior": "allow",
          "updatedPermissions": [{
            "type": "addRules",
            "rules": [{"toolName": "Bash", "ruleContent": "pytest *"}],
            "behavior": "allow",
            "destination": "localSettings"
          }]
        }
      }
    }'
    exit 0
  fi
done

# Default: defer to normal permission dialog (user decides)
exit 0
