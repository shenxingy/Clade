#!/usr/bin/env bash
# post-edit-check.sh — Auto type-check after file edits (runs async)
# Triggered by PostToolUse on Edit|Write

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0

case "$FILE_PATH" in
  *.ts|*.tsx|*.js|*.jsx)
    # Check if this is a pnpm/turborepo project
    if [[ -f "pnpm-workspace.yaml" ]]; then
      # Auto-detect package with type-check script
      PKG=$(find apps packages -name package.json -maxdepth 2 2>/dev/null \
        | xargs grep -l '"type-check"' 2>/dev/null | head -1)
      if [[ -n "$PKG" ]]; then
        PKG_NAME=$(jq -r '.name' "$PKG")
        RESULT=$(pnpm --filter "$PKG_NAME" type-check 2>&1 | tail -30)
        EXIT_CODE=$?
      else
        RESULT=$(pnpm type-check 2>&1 | tail -30)
        EXIT_CODE=$?
      fi
    elif [[ -f "tsconfig.json" ]]; then
      RESULT=$(npx tsc --noEmit 2>&1 | tail -30)
      EXIT_CODE=$?
    else
      exit 0
    fi

    if [[ $EXIT_CODE -ne 0 ]]; then
      jq -n --arg msg "Type-check errors after editing $FILE_PATH:\n$RESULT" \
        '{"systemMessage": $msg}'
    fi
    ;;

  *.py)
    # Python type checking with mypy if available
    if command -v mypy &>/dev/null; then
      RESULT=$(mypy "$FILE_PATH" 2>&1 | tail -20)
      EXIT_CODE=$?
      if [[ $EXIT_CODE -ne 0 ]]; then
        jq -n --arg msg "Mypy errors in $FILE_PATH:\n$RESULT" \
          '{"systemMessage": $msg}'
      fi
    fi
    ;;
esac

exit 0
