#!/usr/bin/env bash
# post-edit-check.sh — Auto type-check / lint after file edits (runs async)
# Triggered by PostToolUse on Edit|Write
#
# Supported: TypeScript, Python, Rust, Go, Swift, Kotlin/Java, LaTeX

LIBDIR="$(cd "$(dirname "$0")" && pwd)/lib"
source "$LIBDIR/typecheck.sh"

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0

report_error() {
  local msg="$1"
  jq -n --arg msg "$msg" '{"systemMessage": $msg}'
}

RESULT=$(run_typecheck_for_file "$FILE_PATH" 2>&1)
EXIT_CODE=$?

if [[ $EXIT_CODE -ne 0 ]] && [[ -n "$RESULT" ]]; then
  report_error "Type-check errors after editing $FILE_PATH:\n$RESULT"
fi

exit 0
