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

# True when the project configures mypy itself (cwd is the project root here).
_project_has_mypy_config() {
  [[ -f mypy.ini || -f .mypy.ini ]] && return 0
  grep -qs '^\[tool\.mypy' pyproject.toml && return 0
  grep -qs '^\[mypy' setup.cfg && return 0
  return 1
}

# mypy output for FILE, less every error the file's HEAD version already had (matched by message, not by line,
# since lines move). An agent editing a legacy file was woken on every edit by an error it did not write: one
# `fcntl = None` fallback, unchanged since it was committed, re-reported after each of a dozen edits (2026-11-04).
# A file git does not know, or output with no parseable error line (a crash), passes through unchanged.
_mypy_new_only() {  # <file> <mypy output> <mypy flags...>
  local f="$1" out="$2" dir base tmp before
  shift 2
  dir=$(cd "$(dirname "$f")" 2>/dev/null && pwd -P) || { printf '%s\n' "$out"; return 0; }
  base=$(basename "$f")
  if ! git -C "$dir" cat-file -e "HEAD:./$base" 2>/dev/null; then
    printf '%s\n' "$out"; return 0
  fi
  tmp=$(mktemp -d "${TMPDIR:-/tmp}/clade-mypy-base.XXXXXX") || { printf '%s\n' "$out"; return 0; }
  git -C "$dir" show "HEAD:./$base" > "$tmp/$base" 2>/dev/null
  before=$(cd "$dir" && MYPYPATH="$dir${MYPYPATH:+:$MYPYPATH}" mypy "$@" "$tmp/$base" 2>&1)
  rm -rf "$tmp"
  python3 - "$out" "$before" <<'PY'
import re, sys
pat = re.compile(r'^.*?:\d+(?::\d+)?: error: (.*)$')
now, before = sys.argv[1].splitlines(), sys.argv[2].splitlines()
if not any(pat.match(l) for l in now):
    print(sys.argv[1]); sys.exit(0)            # a crash or an unparsed message: report it as is
seen = {}
for l in before:
    m = pat.match(l)
    if m:
        seen[m.group(1)] = seen.get(m.group(1), 0) + 1
kept, dropped = [], 0
for l in now:
    m = pat.match(l)
    if not m:
        continue
    if seen.get(m.group(1), 0) > 0:
        seen[m.group(1)] -= 1; dropped += 1
    else:
        kept.append(l)
if kept:
    print('\n'.join(kept))
    print(f"{len(kept)} new error(s) in this file" + (f"; {dropped} already in its HEAD version not shown" if dropped else ""))
PY
}

run_typecheck_for_file() {
  local file_path="$1"
  local exit_code=0
  local result=""
  # Ensure pipe exit codes propagate (e.g. cmd | tail returns cmd's exit code)
  local _prev_pipefail=$(set +o | grep pipefail)
  set -o pipefail

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
        # Only the edited file's own errors. A bare `mypy FILE` follows its imports and reported a
        # sibling module's old errors, and every missing third-party stub (pandas, pyarrow,
        # lightgbm), as "Type-check errors after editing FILE": 11 such errors in 2 files, 0 of them
        # in the edited code, woke one session six times in 20 minutes (2026-11-04). The project's
        # own mypy config, when it has one, still decides whether missing imports are errors.
        local _mypy_flags=(--follow-imports=silent)
        _project_has_mypy_config || _mypy_flags+=(--ignore-missing-imports)
        result=$(mypy "${_mypy_flags[@]}" "$file_path" 2>&1)
        exit_code=$?
        if [[ $exit_code -ne 0 ]]; then
          result=$(_mypy_new_only "$file_path" "$result" "${_mypy_flags[@]}")
          [[ -z "$result" ]] && exit_code=0
        fi
        result=$(printf '%s\n' "$result" | tail -20)
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
  eval "$_prev_pipefail"
  return $exit_code
}

# ─── Project-Level Type Check ────────────────────────────────────────

run_typecheck_for_project() {
  local dir="$1"
  local strict_mode="${2:-false}"
  local ec=0
  local result=""

  cd "$dir" 2>/dev/null || return 0
  # Ensure pipe exit codes propagate (e.g. cmd | tail returns cmd's exit code)
  local _prev_pipefail=$(set +o | grep pipefail)
  set -o pipefail

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

    ec=$?
    if [[ $ec -ne 0 ]] && [[ -n "$result" ]]; then
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
      ec=$?
      if [[ $ec -ne 0 ]]; then
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
      ec=$?
      if [[ $ec -ne 0 ]]; then
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
      ec=$?
      if [[ $ec -ne 0 ]] && [[ -n "$type_result" ]]; then
        echo "Type errors (strict mode). Fix before completing this task:" >&2
        echo "$type_result" >&2
        return 2
      fi
    fi
  fi

  # ── Rust ─────────────────────────────────────────────────────────

  if [[ -f "Cargo.toml" ]] && command -v cargo &>/dev/null; then
    result=$(cargo check 2>&1 | tail -20)
    ec=$?
    if [[ $ec -ne 0 ]]; then
      echo "Cargo check failing. Fix Rust errors before completing this task:" >&2
      echo "$result" >&2
      return 2
    fi

    if [[ "$strict_mode" == "true" ]]; then
      local test_result
      test_result=$(cargo test 2>&1 | tail -20)
      ec=$?
      if [[ $ec -ne 0 ]]; then
        echo "Cargo test failing (strict mode). Fix before completing this task:" >&2
        echo "$test_result" >&2
        return 2
      fi
    fi
  fi

  # ── Go ───────────────────────────────────────────────────────────

  if [[ -f "go.mod" ]] && command -v go &>/dev/null; then
    result=$(go build ./... 2>&1 | tail -20)
    ec=$?
    if [[ $ec -ne 0 ]]; then
      echo "Go build failing. Fix errors before completing this task:" >&2
      echo "$result" >&2
      return 2
    fi

    result=$(go vet ./... 2>&1 | tail -20)
    ec=$?
    if [[ $ec -ne 0 ]]; then
      echo "Go vet errors. Fix before completing this task:" >&2
      echo "$result" >&2
      return 2
    fi

    if [[ "$strict_mode" == "true" ]]; then
      local test_result
      test_result=$(go test ./... 2>&1 | tail -20)
      ec=$?
      if [[ $ec -ne 0 ]]; then
        echo "Go test failing (strict mode). Fix before completing this task:" >&2
        echo "$test_result" >&2
        return 2
      fi
    fi
  fi

  # ── Swift ────────────────────────────────────────────────────────

  if [[ -f "Package.swift" ]] && command -v swift &>/dev/null; then
    result=$(swift build 2>&1 | tail -20)
    ec=$?
    if [[ $ec -ne 0 ]]; then
      echo "Swift build failing. Fix errors before completing this task:" >&2
      echo "$result" >&2
      return 2
    fi

    if [[ "$strict_mode" == "true" ]]; then
      local test_result
      test_result=$(swift test 2>&1 | tail -20)
      ec=$?
      if [[ $ec -ne 0 ]]; then
        echo "Swift test failing (strict mode). Fix before completing this task:" >&2
        echo "$test_result" >&2
        return 2
      fi
    fi
  elif ls *.xcodeproj &>/dev/null || ls *.xcworkspace &>/dev/null; then
    if command -v xcodebuild &>/dev/null; then
      result=$(xcodebuild build -quiet 2>&1 | tail -20)
      ec=$?
      if [[ $ec -ne 0 ]]; then
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
      ec=$?
      if [[ $ec -ne 0 ]]; then
        # Fallback to Java compilation
        result=$(./gradlew compileJava 2>&1 | tail -20)
        ec=$?
      fi
      if [[ $ec -ne 0 ]]; then
        echo "Gradle compile failing. Fix errors before completing this task:" >&2
        echo "$result" >&2
        return 2
      fi

      if [[ "$strict_mode" == "true" ]]; then
        local test_result
        test_result=$(./gradlew test 2>&1 | tail -20)
        ec=$?
        if [[ $ec -ne 0 ]]; then
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
    ec=$?
    if [[ $ec -ne 0 ]] && [[ "$strict_mode" == "true" ]]; then
      echo "LaTeX lint warnings (strict mode). Review before completing:" >&2
      echo "$result" >&2
      # Don't block on LaTeX warnings, just warn
    fi
  fi

  eval "$_prev_pipefail"
  return 0
}
