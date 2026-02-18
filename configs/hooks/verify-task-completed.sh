#!/usr/bin/env bash
# verify-task-completed.sh — Adaptive quality gate before marking a task as completed
# Triggered by TaskCompleted
# Exit 2 = block completion, exit 0 = allow
#
# Reads ~/.claude/corrections/stats.json for error rates per domain.
# High error rate domains (>0.3) → strict checks (type-check + build/test)
# Low error rate domains (<0.1) → basic checks only
# Default (no stats or medium error rate) → standard checks
#
# Supported: TypeScript, Python, Rust, Go, Swift, Kotlin/Java

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0

# ─── Read adaptive thresholds ────────────────────────────────────────

STATS_FILE="$HOME/.claude/corrections/stats.json"
STRICT_MODE=false

if [[ -f "$STATS_FILE" ]] && command -v jq &>/dev/null; then
  # Determine domain from changed files
  CHANGED_FILES=$(git diff --name-only HEAD~1 2>/dev/null || git diff --name-only 2>/dev/null)

  # Categorize domain
  DOMAIN="unknown"
  if echo "$CHANGED_FILES" | grep -qE '\.(tsx?|jsx?)$'; then
    DOMAIN="frontend"
  elif echo "$CHANGED_FILES" | grep -qE '\.(py|ipynb)$'; then
    if echo "$CHANGED_FILES" | grep -qE 'train|model|dataset|experiment|notebook'; then
      DOMAIN="ml"
    else
      DOMAIN="backend"
    fi
  elif echo "$CHANGED_FILES" | grep -qE 'schema|migration|drizzle|prisma'; then
    DOMAIN="schema"
  elif echo "$CHANGED_FILES" | grep -qE '\.swift$|\.xib$|\.storyboard$|Podfile|\.xcodeproj'; then
    DOMAIN="ios"
  elif echo "$CHANGED_FILES" | grep -qE '\.(kt|java)$|\.gradle'; then
    DOMAIN="android"
  elif echo "$CHANGED_FILES" | grep -qE '\.rs$'; then
    DOMAIN="systems"
  elif echo "$CHANGED_FILES" | grep -qE '\.go$'; then
    DOMAIN="systems"
  elif echo "$CHANGED_FILES" | grep -qE '\.tex$|\.bib$'; then
    DOMAIN="academic"
  fi

  # Read error rate for this domain
  ERROR_RATE=$(jq -r --arg d "$DOMAIN" '.[$d] // 0' "$STATS_FILE" 2>/dev/null)

  if [[ -n "$ERROR_RATE" ]]; then
    IS_HIGH=$(awk "BEGIN {print ($ERROR_RATE > 0.3) ? 1 : 0}")
    IS_LOW=$(awk "BEGIN {print ($ERROR_RATE < 0.1) ? 1 : 0}")

    if [[ "$IS_HIGH" -eq 1 ]]; then
      STRICT_MODE=true
    elif [[ "$IS_LOW" -eq 1 ]]; then
      :
    fi
  fi
fi

# ─── TypeScript / JavaScript project check ────────────────────────────

if [[ -f "pnpm-workspace.yaml" ]] || [[ -f "tsconfig.json" ]] || [[ -f "package.json" ]]; then
  if [[ -f "pnpm-workspace.yaml" ]]; then
    PKG=$(find apps packages -name package.json -maxdepth 2 2>/dev/null \
      | xargs grep -l '"type-check"' 2>/dev/null | head -1)
    if [[ -n "$PKG" ]]; then
      PKG_NAME=$(jq -r '.name' "$PKG")
      RESULT=$(pnpm --filter "$PKG_NAME" type-check 2>&1)
    else
      RESULT=$(pnpm type-check 2>&1)
    fi
  elif [[ -f "tsconfig.json" ]]; then
    RESULT=$(npx tsc --noEmit 2>&1)
  else
    RESULT=""
  fi

  if [[ -n "$RESULT" ]] && [[ $? -ne 0 ]]; then
    echo "Type-check failing. Fix TypeScript errors before completing this task:" >&2
    echo "$RESULT" | tail -15 >&2
    exit 2
  fi

  # Strict mode: also run build
  if $STRICT_MODE && [[ -f "package.json" ]]; then
    echo "High error rate detected for $DOMAIN — running stricter checks..." >&2
    if [[ -f "pnpm-workspace.yaml" ]] && [[ -n "${PKG_NAME:-}" ]]; then
      BUILD_RESULT=$(pnpm --filter "$PKG_NAME" build 2>&1)
    elif command -v pnpm &>/dev/null; then
      BUILD_RESULT=$(pnpm build 2>&1)
    else
      BUILD_RESULT=$(npm run build 2>&1)
    fi
    if [[ $? -ne 0 ]]; then
      echo "Build failing (strict mode). Fix build errors before completing this task:" >&2
      echo "$BUILD_RESULT" | tail -20 >&2
      exit 2
    fi
  fi
fi

# ─── Python project check ────────────────────────────────────────────

if [[ -f "pyproject.toml" ]] || [[ -f "setup.py" ]] || [[ -f "requirements.txt" ]]; then
  if command -v ruff &>/dev/null; then
    RESULT=$(ruff check . 2>&1 | head -20)
    if [[ $? -ne 0 ]]; then
      echo "Ruff lint errors. Fix before completing this task:" >&2
      echo "$RESULT" >&2
      exit 2
    fi
  fi

  # Strict mode: also run type checker
  if $STRICT_MODE; then
    echo "High error rate detected for $DOMAIN — running type checker..." >&2
    if command -v pyright &>/dev/null; then
      TYPE_RESULT=$(pyright 2>&1 | tail -20)
    elif command -v mypy &>/dev/null; then
      TYPE_RESULT=$(mypy . 2>&1 | tail -20)
    else
      TYPE_RESULT=""
    fi
    if [[ -n "$TYPE_RESULT" ]] && [[ $? -ne 0 ]]; then
      echo "Type errors (strict mode). Fix before completing this task:" >&2
      echo "$TYPE_RESULT" >&2
      exit 2
    fi
  fi
fi

# ─── Rust project check ──────────────────────────────────────────────

if [[ -f "Cargo.toml" ]] && command -v cargo &>/dev/null; then
  RESULT=$(cargo check 2>&1 | tail -20)
  if [[ $? -ne 0 ]]; then
    echo "Cargo check failing. Fix Rust errors before completing this task:" >&2
    echo "$RESULT" >&2
    exit 2
  fi

  if $STRICT_MODE; then
    echo "High error rate detected for $DOMAIN — running cargo test..." >&2
    TEST_RESULT=$(cargo test 2>&1 | tail -20)
    if [[ $? -ne 0 ]]; then
      echo "Cargo test failing (strict mode). Fix before completing this task:" >&2
      echo "$TEST_RESULT" >&2
      exit 2
    fi
  fi
fi

# ─── Go project check ────────────────────────────────────────────────

if [[ -f "go.mod" ]] && command -v go &>/dev/null; then
  RESULT=$(go build ./... 2>&1 | tail -20)
  if [[ $? -ne 0 ]]; then
    echo "Go build failing. Fix errors before completing this task:" >&2
    echo "$RESULT" >&2
    exit 2
  fi

  RESULT=$(go vet ./... 2>&1 | tail -20)
  if [[ $? -ne 0 ]]; then
    echo "Go vet errors. Fix before completing this task:" >&2
    echo "$RESULT" >&2
    exit 2
  fi

  if $STRICT_MODE; then
    echo "High error rate detected for $DOMAIN — running go test..." >&2
    TEST_RESULT=$(go test ./... 2>&1 | tail -20)
    if [[ $? -ne 0 ]]; then
      echo "Go test failing (strict mode). Fix before completing this task:" >&2
      echo "$TEST_RESULT" >&2
      exit 2
    fi
  fi
fi

# ─── Swift project check ─────────────────────────────────────────────

if [[ -f "Package.swift" ]] && command -v swift &>/dev/null; then
  RESULT=$(swift build 2>&1 | tail -20)
  if [[ $? -ne 0 ]]; then
    echo "Swift build failing. Fix errors before completing this task:" >&2
    echo "$RESULT" >&2
    exit 2
  fi

  if $STRICT_MODE; then
    echo "High error rate detected for $DOMAIN — running swift test..." >&2
    TEST_RESULT=$(swift test 2>&1 | tail -20)
    if [[ $? -ne 0 ]]; then
      echo "Swift test failing (strict mode). Fix before completing this task:" >&2
      echo "$TEST_RESULT" >&2
      exit 2
    fi
  fi
elif ls *.xcodeproj &>/dev/null || ls *.xcworkspace &>/dev/null; then
  if command -v xcodebuild &>/dev/null; then
    RESULT=$(xcodebuild build -quiet 2>&1 | tail -20)
    if [[ $? -ne 0 ]]; then
      echo "Xcode build failing. Fix errors before completing this task:" >&2
      echo "$RESULT" >&2
      exit 2
    fi
  fi
fi

# ─── Kotlin / Java (Gradle) project check ────────────────────────────

if [[ -f "build.gradle" || -f "build.gradle.kts" ]]; then
  if [[ -f "./gradlew" ]]; then
    RESULT=$(./gradlew compileKotlin 2>&1 | tail -20)
    if [[ $? -ne 0 ]]; then
      # Fallback to Java compilation
      RESULT=$(./gradlew compileJava 2>&1 | tail -20)
    fi
    if [[ $? -ne 0 ]]; then
      echo "Gradle compile failing. Fix errors before completing this task:" >&2
      echo "$RESULT" >&2
      exit 2
    fi

    if $STRICT_MODE; then
      echo "High error rate detected for $DOMAIN — running tests..." >&2
      TEST_RESULT=$(./gradlew test 2>&1 | tail -20)
      if [[ $? -ne 0 ]]; then
        echo "Gradle test failing (strict mode). Fix before completing this task:" >&2
        echo "$TEST_RESULT" >&2
        exit 2
      fi
    fi
  fi
fi

# ─── LaTeX project check ─────────────────────────────────────────────

if ls *.tex &>/dev/null 2>&1 && command -v chktex &>/dev/null; then
  MAIN_TEX=$(ls *.tex | head -1)
  RESULT=$(chktex -q "$MAIN_TEX" 2>&1 | head -20)
  if [[ $? -ne 0 ]] && $STRICT_MODE; then
    echo "LaTeX lint warnings (strict mode). Review before completing:" >&2
    echo "$RESULT" >&2
    # Don't block on LaTeX warnings, just warn
  fi
fi

exit 0
