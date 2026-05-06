#!/usr/bin/env bash
# doc-align-check.sh — Real-time doc-drift guard after .md edits.
# Triggered by PostToolUse on Edit|Write.
#
# If you edited a Markdown file in a repo with docs/facts.json, this runs
# `doc-align check` and surfaces any drift entries that mention the edited
# file. Non-blocking: emits a systemMessage with the drift, no exit-1.
#
# Silent no-op when:
#   - the edit was not on a .md file
#   - the project has no docs/facts.json
#   - python3 or the doc-align script is unavailable

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

# Only check Markdown edits
[[ -z "$FILE_PATH" ]] && exit 0
case "$FILE_PATH" in
  *.md|*.markdown) ;;
  *) exit 0 ;;
esac

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0

# Project must have opted in
[[ -f docs/facts.json ]] || exit 0

DOC_ALIGN="${HOME}/.claude/scripts/doc-align.py"
[[ -x "$DOC_ALIGN" ]] || exit 0
command -v python3 &>/dev/null || exit 0

# Compute repo-relative path so we can match doc-align's output format
REL_PATH=$(python3 -c "
import os, sys
try: print(os.path.relpath(sys.argv[1], sys.argv[2]))
except Exception: print(sys.argv[1])
" "$FILE_PATH" "$PWD" 2>/dev/null)

[[ -z "$REL_PATH" ]] && exit 0

# Run drift check; filter to lines mentioning the edited file.
# doc-align emits drift lines like:
#   <rel_path>:<line>  <fact>=<expected> but found '<found>' in: '<text>'
DRIFTS=$(python3 "$DOC_ALIGN" check 2>/dev/null \
  | awk -v f="$REL_PATH" 'index($0, "  " f ":") == 1 || index($0, " " f ":") > 0' \
  | head -5)

if [[ -n "$DRIFTS" ]]; then
  MSG="⚠ doc-align: drift in $REL_PATH after edit"$'\n'"$DRIFTS"$'\n'"Run: ~/.claude/scripts/doc-align.py apply  to auto-fix"
  jq -n --arg msg "$MSG" '{"systemMessage": $msg}'
fi

exit 0
