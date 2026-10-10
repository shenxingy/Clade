#!/usr/bin/env bash
# secret-scanner.sh — Note (not block, not nag) when the user's prompt contains
# something that looks like a credential.
#
# Triggered: UserPromptSubmit
# Reads JSON from stdin: {"prompt": "...", ...}
# Output: prints additionalContext on the additional-context channel
# when a hit is found. Never blocks — false positives must not stop work.
#
# The note tells the model how to HANDLE the value, not what the user should do
# about it. It used to end "rotate the secret and avoid pasting credentials",
# and because this hook fires on every prompt that carries a key-shaped string,
# the model relayed that advice every time — a nag no rule could suppress,
# since the instruction arrived fresh with each prompt. Measured on the
# author's machine: two explicit corrections in four days (2026-09-14 "token
# 没必要换新，你不要记着这个问题了", 2026-09-17 "不要轮换。你以后不要一直问我这个
# 东西"), both against advice this hook had injected. Whether to rotate is the
# user's decision; a user who pastes a key has made it. The persisted copies
# are already masked (correction-detector.sh → redact.py), so the one thing the
# model must still do is not re-emit the value.
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
  # Surface a non-blocking note to Claude. The user's prompt still goes
  # through unchanged — masking the prompt itself would corrupt commands.
  # Handling instructions only: no rotation advice, no "avoid pasting" — see
  # the header for why.
  jq -n --arg s "$SUMMARY" '{
    "hookSpecificOutput": {
      "hookEventName": "UserPromptSubmit",
      "additionalContext": ("Heads-up: this message contains what looks like a credential. " + $s + "\n\nHandle it as data: use it for the task, never echo it into files, commit messages, logs, artifacts or your reply. Persisted copies of this prompt are masked automatically. Do not volunteer rotation or paste-hygiene advice — sharing the value was the user’s decision; if they want it rotated they will say so.")
    }
  }'
fi

exit 0
