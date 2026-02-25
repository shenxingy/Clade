#!/usr/bin/env bash
# typecheck.sh — Shared type-check / lint helpers for hook scripts
#
# Functions:
#   run_typecheck_for_file  FILE_PATH        — per-file check (post-edit)
#   run_typecheck_for_project DIR STRICT_MODE — project-level check (task verify)
#
# Supported: TypeScript/JS (monorepo-aware), Python (pyright/mypy/ruff),
#            Rust (cargo), Go (go vet/build), Swift, Kotlin/Java (gradle), LaTeX (chktex)

# ─── Per-File Type Check ─────────────────────────────────────────────

run_typecheck_for_file() {
  local file_path="$1"
  local exit_code=0
  local result=""

  case "$file_path" in
    *.ts|*.tsx|*.js|*.jsx)
      if [[ -f "pnpm-workspace.yaml" ]]; then
        # Auto-detect monorepo package with type-check script
        local pkg
        pkg=$(find apps packages -name package.json -maxdepth 2 2>/dev/null \
          | xargs grep -l '"type-check"' 2>/dev/null | head -1)
        if [[ -n "$pkg" ]]; then
          local pkg_name
          pkg_name=$(jq -r '.name' "$pkg")
          result=$(pnpm --filter "$pkg_name" type-check 2>&1 | tail -30)
          exit_code=$?
        else
          result=$(pnpm type-check 2>&1 | tail -30)
          exit_code=$?
        fi
      elif [[ -f "tsconfig.json" ]]; then
        result=$(npx tsc --noEmit 2>&1 | tail -30)
        exit_code=$?
      else
        return 0
      fi
      ;;

    *.py)
      if command -v pyright &>/dev/null; then
        result=$(pyright "$file_path" 2>&1 | tail -20)
        exit_code=$?
      elif command -v mypy &>/dev/null; then
        result=$(mypy "$file_path" 2>&1 | tail -20)
        exit_code=$?
      else
        return 0
      fi
      ;;

    *.rs)
      if command -v cargo &>/dev/null && [[ -f "Cargo.toml" ]]; then
        result=$(cargo check --message-format short 2>&1 | tail -30)
        exit_code=$?
      else
        return 0
      fi
      ;;

    *.go)
      if command -v go &>/dev/null; then
        local dir
        dir=$(dirname "$file_path")
        result=$(go vet "./$dir/..." 2>&1 | tail -20)
        exit_code=$?
      else
        return 0
      fi
      ;;

    *.swift)
      if command -v swiftc &>/dev/null && [[ -f "Package.swift" ]]; then
        result=$(swift build 2>&1 | tail -30)
        exit_code=$?
      else
        return 0
      fi
      ;;

    *.kt|*.java)
      if [[ -f "build.gradle" || -f "build.gradle.kts" ]]; then
        result=$(./gradlew compileKotlin 2>&1 | tail -30)
        exit_code=$?
      else
        return 0
      fi
      ;;

    *.tex)
      if command -v chktex &>/dev/null; then
        result=$(chktex -q "$file_path" 2>&1 | tail -20)
        exit_code=$?
      else
        return 0
      fi
      ;;

    *)
      return 0
      ;;
  esac

  if [[ -n "$result" ]]; then
    echo "$result"
  fi
  return $exit_code
}

# ─── Project-Level Type Check ────────────────────────────────────────

run_typecheck_for_project() {
  local dir="$1"
  local strict_mode="${2:-false}"
  local exit_code=0
  local result=""

  cd "$dir" 2>/dev/null || return 0

  # ── TypeScript / JavaScript ──────────────────────────────────────

  if [[ -f "pnpm-workspace.yaml" ]] || [[ -f "tsconfig.json" ]] || [[ -f "package.json" ]]; then
    if [[ -f "pnpm-workspace.yaml" ]]; then
      local pkg pkg_name
      pkg=$(find apps packages -name package.json -maxdepth 2 2>/dev/null \
        | xargs grep -l '"type-check"' 2>/dev/null | head -1)
      if [[ -n "$pkg" ]]; then
        pkg_name=$(jq -r '.name' "$pkg")
        result=$(pnpm --filter "$pkg_name" type-check 2>&1)
      else
        result=$(pnpm type-check 2>&1)
      fi
    elif [[ -f "tsconfig.json" ]]; then
      result=$(npx tsc --noEmit 2>&1)
    else
      result=""
    fi

    exit_code=$?
    if [[ -n "$result" ]] && [[ $exit_code -ne 0 ]]; then
      echo "Type-check failing. Fix TypeScript errors before completing this task:" >&2
      echo "$result" | tail -15 >&2
      return 2
    fi

    # Strict mode: also run build
    if [[ "$strict_mode" == "true" ]] && [[ -f "package.json" ]]; then
      local build_result
      if [[ -f "pnpm-workspace.yaml" ]] && [[ -n "${pkg_name:-}" ]]; then
        build_result=$(pnpm --filter "$pkg_name" build 2>&1)
      elif command -v pnpm &>/dev/null; then
        build_result=$(pnpm build 2>&1)
      else
        build_result=$(npm run build 2>&1)
      fi
      if [[ $? -ne 0 ]]; then
        echo "Build failing (strict mode). Fix build errors before completing this task:" >&2
        echo "$build_result" | tail -20 >&2
        return 2
      fi
    fi
  fi

  # ── Python ───────────────────────────────────────────────────────

  if [[ -f "pyproject.toml" ]] || [[ -f "setup.py" ]] || [[ -f "requirements.txt" ]]; then
    if command -v ruff &>/dev/null; then
      result=$(ruff check . 2>&1 | head -20)
      if [[ $? -ne 0 ]]; then
        echo "Ruff lint errors. Fix before completing this task:" >&2
        echo "$result" >&2
        return 2
      fi
    fi

    # Strict mode: also run type checker
    if [[ "$strict_mode" == "true" ]]; then
      local type_result=""
      if command -v pyright &>/dev/null; then
        type_result=$(pyright 2>&1 | tail -20)
      elif command -v mypy &>/dev/null; then
        type_result=$(mypy . 2>&1 | tail -20)
      fi
      if [[ -n "$type_result" ]] && [[ $? -ne 0 ]]; then
        echo "Type errors (strict mode). Fix before completing this task:" >&2
        echo "$type_result" >&2
        return 2
      fi
    fi
  fi

  # ── Rust ─────────────────────────────────────────────────────────

  if [[ -f "Cargo.toml" ]] && command -v cargo &>/dev/null; then
    result=$(cargo check 2>&1 | tail -20)
    if [[ $? -ne 0 ]]; then
      echo "Cargo check failing. Fix Rust errors before completing this task:" >&2
      echo "$result" >&2
      return 2
    fi

    if [[ "$strict_mode" == "true" ]]; then
      local test_result
      test_result=$(cargo test 2>&1 | tail -20)
      if [[ $? -ne 0 ]]; then
        echo "Cargo test failing (strict mode). Fix before completing this task:" >&2
        echo "$test_result" >&2
        return 2
      fi
    fi
  fi

  # ── Go ───────────────────────────────────────────────────────────

  if [[ -f "go.mod" ]] && command -v go &>/dev/null; then
    result=$(go build ./... 2>&1 | tail -20)
    if [[ $? -ne 0 ]]; then
      echo "Go build failing. Fix errors before completing this task:" >&2
      echo "$result" >&2
      return 2
    fi

    result=$(go vet ./... 2>&1 | tail -20)
    if [[ $? -ne 0 ]]; then
      echo "Go vet errors. Fix before completing this task:" >&2
      echo "$result" >&2
      return 2
    fi

    if [[ "$strict_mode" == "true" ]]; then
      local test_result
      test_result=$(go test ./... 2>&1 | tail -20)
      if [[ $? -ne 0 ]]; then
        echo "Go test failing (strict mode). Fix before completing this task:" >&2
        echo "$test_result" >&2
        return 2
      fi
    fi
  fi

  # ── Swift ────────────────────────────────────────────────────────

  if [[ -f "Package.swift" ]] && command -v swift &>/dev/null; then
    result=$(swift build 2>&1 | tail -20)
    if [[ $? -ne 0 ]]; then
      echo "Swift build failing. Fix errors before completing this task:" >&2
      echo "$result" >&2
      return 2
    fi

    if [[ "$strict_mode" == "true" ]]; then
      local test_result
      test_result=$(swift test 2>&1 | tail -20)
      if [[ $? -ne 0 ]]; then
        echo "Swift test failing (strict mode). Fix before completing this task:" >&2
        echo "$test_result" >&2
        return 2
      fi
    fi
  elif ls *.xcodeproj &>/dev/null || ls *.xcworkspace &>/dev/null; then
    if command -v xcodebuild &>/dev/null; then
      result=$(xcodebuild build -quiet 2>&1 | tail -20)
      if [[ $? -ne 0 ]]; then
        echo "Xcode build failing. Fix errors before completing this task:" >&2
        echo "$result" >&2
        return 2
      fi
    fi
  fi

  # ── Kotlin / Java (Gradle) ──────────────────────────────────────

  if [[ -f "build.gradle" || -f "build.gradle.kts" ]]; then
    if [[ -f "./gradlew" ]]; then
      result=$(./gradlew compileKotlin 2>&1 | tail -20)
      if [[ $? -ne 0 ]]; then
        # Fallback to Java compilation
        result=$(./gradlew compileJava 2>&1 | tail -20)
      fi
      if [[ $? -ne 0 ]]; then
        echo "Gradle compile failing. Fix errors before completing this task:" >&2
        echo "$result" >&2
        return 2
      fi

      if [[ "$strict_mode" == "true" ]]; then
        local test_result
        test_result=$(./gradlew test 2>&1 | tail -20)
        if [[ $? -ne 0 ]]; then
          echo "Gradle test failing (strict mode). Fix before completing this task:" >&2
          echo "$test_result" >&2
          return 2
        fi
      fi
    fi
  fi

  # ── LaTeX ────────────────────────────────────────────────────────

  if ls *.tex &>/dev/null 2>&1 && command -v chktex &>/dev/null; then
    local main_tex
    main_tex=$(ls *.tex | head -1)
    result=$(chktex -q "$main_tex" 2>&1 | head -20)
    if [[ $? -ne 0 ]] && [[ "$strict_mode" == "true" ]]; then
      echo "LaTeX lint warnings (strict mode). Review before completing:" >&2
      echo "$result" >&2
      # Don't block on LaTeX warnings, just warn
    fi
  fi

  return 0
}
