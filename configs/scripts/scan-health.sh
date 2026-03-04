#!/usr/bin/env bash
# scan-health — Generate tasks from code health issues
#
# Usage: bash scan-health.sh [project-dir]
#
# Checks: TODO/FIXME comments, lint warnings, type errors, large files.
# Output format: ===TASK=== blocks (compatible with batch-tasks / start.sh)
#
# Why: Continuous code health — auto-detect issues and generate worker-friendly
# tasks so the system self-heals between feature iterations.

set -euo pipefail

PROJECT_DIR="${1:-.}"

if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "Error: Directory not found: $PROJECT_DIR" >&2
  exit 1
fi

cd "$PROJECT_DIR"

TASK_COUNT=0

# ─── TODO/FIXME/HACK/XXX Comments ───────────────────────────────────────────
_scan_todos() {
  local matches
  matches=$(grep -rn \
    --include="*.sh" --include="*.py" --include="*.js" --include="*.ts" \
    --include="*.go" --include="*.rb" --include="*.rs" --include="*.tsx" \
    --include="*.jsx" \
    --exclude-dir=".git" --exclude-dir="node_modules" --exclude-dir=".venv" \
    --exclude-dir="venv" --exclude-dir="dist" --exclude-dir="build" \
    -E "(TODO|FIXME|HACK|XXX):" . 2>/dev/null || true)

  [[ -z "$matches" ]] && return

  local count
  count=$(echo "$matches" | wc -l | tr -d ' ')
  [[ "$count" -eq 0 ]] && return

  # Group by file, emit one task per file with multiple TODOs
  local files
  files=$(echo "$matches" | cut -d: -f1 | sort -u)

  while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    local file_matches file_count
    file_matches=$(echo "$matches" | grep "^${file}:" || true)
    file_count=$(echo "$file_matches" | wc -l | tr -d ' ')

    # Truncate to first 5 matches for task description
    local sample
    sample=$(echo "$file_matches" | head -5 | sed 's/^/  /')

    cat <<EOF
===TASK===
model: haiku
timeout: 600
source_ref: health_todo_${file//\//_}
---
fix: resolve ${file_count} TODO/FIXME comment(s) in ${file}

## Context
File: ${file}
Found ${file_count} TODO/FIXME/HACK/XXX comment(s):

${sample}

## What to do
1. Read ${file} and address each TODO/FIXME comment
2. Implement the described functionality or remove stale comments
3. Commit with: committer "fix: resolve TODOs in ${file}" ${file}

EOF
    TASK_COUNT=$((TASK_COUNT + 1))
  done <<< "$files"
}

# ─── Type Errors (Python mypy / TypeScript tsc) ─────────────────────────────
_scan_type_errors() {
  # Python: mypy
  if [[ -f "pyproject.toml" || -f "setup.py" || -f "requirements.txt" ]]; then
    if command -v mypy &>/dev/null; then
      local mypy_output mypy_count
      mypy_output=$(mypy . --no-error-summary --no-color 2>/dev/null | head -50 || true)
      mypy_count=$(echo "$mypy_output" | grep -c ": error:" 2>/dev/null) || mypy_count=0

      if [[ "$mypy_count" -gt 0 ]]; then
        local sample
        sample=$(echo "$mypy_output" | grep ": error:" | head -10 | sed 's/^/  /')

        cat <<EOF
===TASK===
model: sonnet
timeout: 1800
source_ref: health_mypy
---
fix: resolve ${mypy_count} mypy type error(s)

## Context
Found ${mypy_count} type error(s) via mypy:

${sample}

## What to do
1. Run \`mypy .\` to see full error list
2. Fix type annotations and type errors
3. Re-run mypy to verify errors are resolved
4. Commit with: committer "fix: resolve mypy type errors" <files>

EOF
        TASK_COUNT=$((TASK_COUNT + 1))
      fi
    fi
  fi

  # TypeScript: tsc
  if [[ -f "tsconfig.json" ]]; then
    if command -v npx &>/dev/null; then
      local tsc_output tsc_count
      tsc_output=$(npx tsc --noEmit 2>/dev/null | head -50 || true)
      tsc_count=$(echo "$tsc_output" | grep -c ": error TS" 2>/dev/null) || tsc_count=0

      if [[ "$tsc_count" -gt 0 ]]; then
        local sample
        sample=$(echo "$tsc_output" | grep ": error TS" | head -10 | sed 's/^/  /')

        cat <<EOF
===TASK===
model: sonnet
timeout: 1800
source_ref: health_tsc
---
fix: resolve ${tsc_count} TypeScript error(s)

## Context
Found ${tsc_count} TypeScript compilation error(s):

${sample}

## What to do
1. Run \`npx tsc --noEmit\` to see full error list
2. Fix type errors in the reported files
3. Re-run tsc to verify errors are resolved
4. Commit with: committer "fix: resolve TypeScript errors" <files>

EOF
        TASK_COUNT=$((TASK_COUNT + 1))
      fi
    fi
  fi
}

# ─── Lint Warnings (ruff for Python, eslint for JS/TS) ──────────────────────
_scan_lint() {
  # Python: ruff (fast linter)
  if [[ -f "pyproject.toml" || -f "setup.py" || -f "requirements.txt" ]]; then
    if command -v ruff &>/dev/null; then
      local ruff_output ruff_count
      ruff_output=$(ruff check . 2>/dev/null | head -50 || true)
      ruff_count=$(echo "$ruff_output" | grep -cE "^[^ ].*:" 2>/dev/null) || ruff_count=0

      if [[ "$ruff_count" -gt 5 ]]; then
        local sample
        sample=$(echo "$ruff_output" | head -10 | sed 's/^/  /')

        cat <<EOF
===TASK===
model: haiku
timeout: 900
source_ref: health_ruff
---
fix: resolve ${ruff_count} ruff lint warning(s)

## Context
Found ${ruff_count} lint warning(s) via ruff:

${sample}

## What to do
1. Run \`ruff check . --fix\` for auto-fixable issues
2. Manually fix remaining warnings
3. Re-run \`ruff check .\` to verify
4. Commit with: committer "fix: resolve ruff lint warnings" <files>

EOF
        TASK_COUNT=$((TASK_COUNT + 1))
      fi
    fi
  fi

  # JavaScript/TypeScript: eslint
  if [[ -f "package.json" ]] && [[ -f ".eslintrc" || -f ".eslintrc.js" || -f ".eslintrc.json" || -f "eslint.config.js" || -f "eslint.config.mjs" ]]; then
    if command -v npx &>/dev/null; then
      local eslint_output eslint_count
      eslint_output=$(npx eslint . --format compact 2>/dev/null | head -50 || true)
      eslint_count=$(echo "$eslint_output" | grep -cE "^/" 2>/dev/null) || eslint_count=0

      if [[ "$eslint_count" -gt 5 ]]; then
        local sample
        sample=$(echo "$eslint_output" | head -10 | sed 's/^/  /')

        cat <<EOF
===TASK===
model: haiku
timeout: 900
source_ref: health_eslint
---
fix: resolve ${eslint_count} ESLint warning(s)

## Context
Found ${eslint_count} lint issue(s) via ESLint:

${sample}

## What to do
1. Run \`npx eslint . --fix\` for auto-fixable issues
2. Manually fix remaining warnings
3. Re-run \`npx eslint .\` to verify
4. Commit with: committer "fix: resolve ESLint warnings" <files>

EOF
        TASK_COUNT=$((TASK_COUNT + 1))
      fi
    fi
  fi
}

# ─── Large Files (>1500 lines, per project convention) ───────────────────────
_scan_large_files() {
  local large_files
  large_files=$(find . \
    -type f \( -name "*.py" -o -name "*.js" -o -name "*.ts" -o -name "*.tsx" -o -name "*.sh" -o -name "*.go" -o -name "*.rs" \) \
    ! -path "./.git/*" ! -path "./node_modules/*" ! -path "./.venv/*" ! -path "./venv/*" \
    ! -path "./dist/*" ! -path "./build/*" \
    -exec awk 'END {if (NR > 1500) print FILENAME ":" NR}' {} \; 2>/dev/null || true)

  [[ -z "$large_files" ]] && return

  while IFS=: read -r file lines; do
    [[ -z "$file" ]] && continue

    cat <<EOF
===TASK===
model: sonnet
timeout: 1800
source_ref: health_large_${file//\//_}
---
refactor: split ${file} (${lines} lines, exceeds 1500-line limit)

## Context
File: ${file}
Lines: ${lines} (project limit: 1500)

## What to do
1. Read ${file} and identify logical sections that can be extracted
2. Extract cohesive sections into separate modules
3. Update imports in files that reference the extracted code
4. Verify no circular imports introduced
5. Commit with: committer "refactor: split ${file} into modules" <files>

EOF
    TASK_COUNT=$((TASK_COUNT + 1))
  done <<< "$large_files"
}

# ─── Run all scans ──────────────────────────────────────────────────────────
_scan_todos
_scan_type_errors
_scan_lint
_scan_large_files

echo "# scan-health: found ${TASK_COUNT} issue(s)" >&2
