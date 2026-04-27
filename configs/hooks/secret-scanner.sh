#!/usr/bin/env bash
# secret-scanner.sh — Warn (not block) when the user's prompt contains
# something that looks like a credential.
#
# Triggered: UserPromptSubmit
# Reads JSON from stdin: {"prompt": "...", ...}
# Output: prints additionalContext on the additional-context channel
# when a hit is found. Never blocks — false positives must not stop work.
#
# Backed by configs/scripts/redact.py (installed to ~/.claude/scripts/redact.py).

set -euo pipefail

REDACT_PY="$HOME/.claude/scripts/redact.py"
[[ -x "$REDACT_PY" ]] || exit 0  # gracefully no-op if redact.py is not installed

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty' 2>/dev/null || echo "")
[[ -z "$PROMPT" ]] && exit 0

# Run redact.py --check; capture its exit code (1 = secret found).
SUMMARY=$(printf '%s' "$PROMPT" | "$REDACT_PY" --check 2>&1 >/dev/null) || HIT=true
HIT=${HIT:-false}

if [[ "$HIT" == true ]]; then
  # Surface a non-blocking hint to Claude. The user's prompt still goes
  # through unchanged — masking the prompt itself would corrupt commands.
  jq -n --arg s "$SUMMARY" '{
    "hookSpecificOutput": {
      "hookEventName": "UserPromptSubmit",
      "additionalContext": ("Heads-up: your message appears to contain a credential. " + $s + "\n\nIf this was unintentional, rotate the secret and avoid pasting credentials into the chat.")
    }
  }'
fi

exit 0
