#!/usr/bin/env bash
# research-router.sh — Route personal-topic research findings to ~/.claude/research/
#
# Post-write hook: when BRAINSTORM.md is modified via /research skill,
# detect if the entry is for a personal topic and move it to ~/.claude/research/ instead.
#
# Triggered by: PostToolUse Edit/Write (file-path: BRAINSTORM.md)
# Pattern: [Research] entries added after /research invocation

set -e

# Only intercept BRAINSTORM.md writes
if [[ "$CLAUDE_CODE_MODIFIED_FILE" != *"BRAINSTORM.md" ]]; then
  exit 0
fi

# Check if we're in a /research skill context
# (Claude Code doesn't provide skill context, so we detect via recent file changes)
BRAINSTORM="$(pwd)/BRAINSTORM.md"
[[ -f "$BRAINSTORM" ]] || exit 0

# Extract the most recent [Research] entry that was just added
# Format: ## [Research] {date} — {topic}
latest_entry=$(grep -A 100 "^## \[Research\]" "$BRAINSTORM" 2>/dev/null | head -1)
[[ -z "$latest_entry" ]] && exit 0

# Extract topic from the entry line
# Expected: "## [Research] 2026-06-12 — {topic}"
topic=$(echo "$latest_entry" | sed 's/^## \[Research\] [0-9-]* — //' | xargs)
[[ -z "$topic" ]] && exit 0

# Determine if topic is personal using the criteria from the prompt
# Personal topics: user's own infrastructure/accounts/hardware/life decisions
is_personal=0

# Check for personal keywords
personal_keywords=(
  "laptop" "computer" "buy" "personal" "home" "my account" "my" "myself"
  "finance" "money" "investment" "health" "exercise" "diet"
  "apartment" "house" "rent" "mortgage" "move"
  "car" "vehicle" "phone" "device"
  "password" "security" "privacy" "identity"
)

for keyword in "${personal_keywords[@]}"; do
  if [[ "${topic,,}" =~ ${keyword,,} ]]; then
    is_personal=1
    break
  fi
done

# If personal, extract the entry from BRAINSTORM.md and move it to ~/.claude/research/
if [[ $is_personal -eq 1 ]]; then
  # Create research dir if needed
  mkdir -p ~/.claude/research/

  # Generate filename from topic
  date_str=$(date +%Y-%m-%d)
  slug=$(echo "$topic" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/-\+/-/g' | sed 's/-$//')
  research_file="$HOME/.claude/research/${date_str}-${slug}.md"

  # Extract the full entry (## [Research] ... to the next ## or EOF)
  entry_start=$(grep -n "^## \[Research\] [0-9-]* — ${topic}" "$BRAINSTORM" 2>/dev/null | cut -d: -f1 | head -1)

  if [[ -n "$entry_start" ]]; then
    # Find the next heading or EOF
    entry_end=$(tail -n +$((entry_start + 1)) "$BRAINSTORM" | grep -n "^## " | head -1 | cut -d: -f1)

    if [[ -z "$entry_end" ]]; then
      # No next heading, take to EOF
      entry_lines=$(sed -n "${entry_start},\$p" "$BRAINSTORM")
    else
      # Take up to next heading
      entry_lines=$(sed -n "${entry_start},$((entry_start + entry_end - 2))p" "$BRAINSTORM")
    fi

    # Write to research directory
    echo "$entry_lines" > "$research_file"

    # Remove from BRAINSTORM.md
    if [[ -z "$entry_end" ]]; then
      # Delete from entry_start to EOF
      sed -i "${entry_start},\$d" "$BRAINSTORM"
    else
      # Delete the entry lines
      sed -i "${entry_start},$((entry_start + entry_end - 2))d" "$BRAINSTORM"
    fi

    # Log the action
    echo "📍 Personal-topic research routed: $topic → $research_file"
  fi
fi

exit 0
