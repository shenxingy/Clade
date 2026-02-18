#!/usr/bin/env bash
# post-edit-check.sh — Auto type-check / lint after file edits (runs async)
# Triggered by PostToolUse on Edit|Write
#
# Supported: TypeScript, Python, Rust, Go, Swift, Kotlin/Java, LaTeX

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

case "$FILE_PATH" in
  *.ts|*.tsx|*.js|*.jsx)
    if [[ -f "pnpm-workspace.yaml" ]]; then
      # Auto-detect monorepo package with type-check script
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
    [[ $EXIT_CODE -ne 0 ]] && report_error "Type-check errors after editing $FILE_PATH:\n$RESULT"
    ;;

  *.py)
    if command -v pyright &>/dev/null; then
      RESULT=$(pyright "$FILE_PATH" 2>&1 | tail -20)
      EXIT_CODE=$?
    elif command -v mypy &>/dev/null; then
      RESULT=$(mypy "$FILE_PATH" 2>&1 | tail -20)
      EXIT_CODE=$?
    else
      exit 0
    fi
    [[ $EXIT_CODE -ne 0 ]] && report_error "Type errors in $FILE_PATH:\n$RESULT"
    ;;

  *.rs)
    if command -v cargo &>/dev/null && [[ -f "Cargo.toml" ]]; then
      RESULT=$(cargo check --message-format short 2>&1 | tail -30)
      EXIT_CODE=$?
      [[ $EXIT_CODE -ne 0 ]] && report_error "Cargo check errors after editing $FILE_PATH:\n$RESULT"
    fi
    ;;

  *.go)
    if command -v go &>/dev/null; then
      DIR=$(dirname "$FILE_PATH")
      RESULT=$(go vet "./$DIR/..." 2>&1 | tail -20)
      EXIT_CODE=$?
      [[ $EXIT_CODE -ne 0 ]] && report_error "Go vet errors after editing $FILE_PATH:\n$RESULT"
    fi
    ;;

  *.swift)
    if command -v swiftc &>/dev/null && [[ -f "Package.swift" ]]; then
      RESULT=$(swift build 2>&1 | tail -30)
      EXIT_CODE=$?
      [[ $EXIT_CODE -ne 0 ]] && report_error "Swift build errors after editing $FILE_PATH:\n$RESULT"
    fi
    ;;

  *.kt|*.java)
    if [[ -f "build.gradle" || -f "build.gradle.kts" ]]; then
      RESULT=$(./gradlew compileKotlin 2>&1 | tail -30)
      EXIT_CODE=$?
      if [[ $EXIT_CODE -ne 0 ]]; then
        report_error "Kotlin/Java compile errors after editing $FILE_PATH:\n$RESULT"
      fi
    fi
    ;;

  *.tex)
    if command -v chktex &>/dev/null; then
      RESULT=$(chktex -q "$FILE_PATH" 2>&1 | tail -20)
      EXIT_CODE=$?
      [[ $EXIT_CODE -ne 0 ]] && report_error "LaTeX lint warnings in $FILE_PATH:\n$RESULT"
    fi
    ;;
esac

exit 0
