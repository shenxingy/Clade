#!/usr/bin/env bash
# prompt-tracker.sh — Fingerprint recurring prompts and suggest /skill creation
# Fires on UserPromptSubmit (async=true, non-blocking)

set -euo pipefail

LOG_FILE="${HOME}/.claude/prompt-log.jsonl"

# Read stdin JSON
input=$(cat)
prompt=$(echo "$input" | jq -r '.prompt // .message // ""')

# Skip short prompts (not a recurring pattern)
if [[ ${#prompt} -lt 20 ]]; then
  exit 0
fi

# Generate fingerprint: first 80 chars, lowercased, spaces collapsed
fingerprint=$(echo "$prompt" | tr '[:upper:]' '[:lower:]' | tr -s ' ' | cut -c1-80)

# Append to log
date_str=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "{\"date\":\"${date_str}\",\"fp\":\"${fingerprint}\",\"prompt\":\"${fingerprint}\"}" >> "$LOG_FILE" 2>/dev/null || true

# Count occurrences of this fingerprint
count=$(grep -c "\"fp\":\"${fingerprint}\"" "$LOG_FILE" 2>/dev/null || echo 0)

# Suggest skill creation if repeated >= 3 times
if [[ "${count}" -ge 3 ]]; then
  echo "{\"systemMessage\": \"💡 You've run a similar prompt ${count}x — consider making it a /skill: '${fingerprint}'\"}"
fi

exit 0
