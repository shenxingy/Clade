#!/usr/bin/env bash
# frustration-trigger.sh — UserPromptSubmit hook: inject systematic debugging protocol
#
# Fires when user expresses frustration (via matcher in settings-hooks.json).
# Injects a structured debugging reminder so Claude doesn't spin or give up.
#
# Adapted from pua (MIT) — https://github.com/tanweai/pua

MSG="[User Frustration Detected — Systematic Debugging Protocol]

The user is unsatisfied. STOP the current approach and execute this protocol:

1. AUDIT what you have tried: list each attempt and WHY it failed
2. READ the error signal word by word — what does it literally say?
3. SEARCH before guessing: use WebSearch / Grep / Read on the actual problem
4. FORM 3 different hypotheses about the root cause — not variations of the same one
5. VERIFY your top hypothesis with tools BEFORE implementing the fix

Blocked behaviors (do not do these):
- Retry the same approach with minor parameter changes
- Blame environment without verifying (\"probably a permissions issue\")
- Suggest the user handle it manually
- Claim done without running verification commands and showing output
- Ask for more context when you have tools available to investigate"

jq -n --arg ctx "$MSG" \
  '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":$ctx}}'

exit 0
