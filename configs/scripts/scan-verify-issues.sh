#!/usr/bin/env bash
# scan-verify-issues — Process annotated verify-issues.md into tasks
#
# Usage: bash scan-verify-issues.sh [project-dir]
#
# Reads .claude/verify-issues.md, processes annotations:
#   [fix]    → emit ===TASK=== blocks to stdout
#   [skip]   → append to .claude/skipped.md
#   [wontfix] → append to .claude/skipped.md
# Unannotated items are left in place.
#
# Output format: ===TASK=== blocks (compatible with start.sh / batch-tasks)

set -euo pipefail

PROJECT_DIR="${1:-.}"

if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "Error: Directory not found: $PROJECT_DIR" >&2
  exit 1
fi

cd "$PROJECT_DIR"

ISSUES_FILE=".claude/verify-issues.md"
SKIPPED_FILE=".claude/skipped.md"

# Exit cleanly if no issues file or no annotations
if [[ ! -f "$ISSUES_FILE" ]]; then
  exit 0
fi

if ! grep -qE '\[(fix|skip|wontfix)\]' "$ISSUES_FILE" 2>/dev/null; then
  exit 0
fi

TASK_COUNT=0
TIMESTAMP=$(date -Iseconds)

# ─── Process [skip] and [wontfix] → skipped.md ───────────────────────────────
_process_skips() {
  local skip_items
  skip_items=$(grep -E '\[(skip|wontfix)\]' "$ISSUES_FILE" 2>/dev/null || true)

  if [[ -n "$skip_items" ]]; then
    {
      echo ""
      echo "## [$TIMESTAMP] Verify issues — skipped/wontfix"
      echo "$skip_items" | sed 's/^- \[ \] /- /'
    } >> "$SKIPPED_FILE"
    echo "# scan-verify-issues: $(echo "$skip_items" | wc -l | tr -d ' ') item(s) → skipped.md" >&2
  fi
}

# ─── Process [fix] → ===TASK=== blocks by section ────────────────────────────
_process_fixes() {
  local current_section=""
  local section_items=""
  local section_count=0

  while IFS= read -r line; do
    # Track current section header
    if [[ "$line" =~ ^##[[:space:]]+(.*) ]]; then
      # Emit task for previous section if it had [fix] items
      if [[ -n "$section_items" && $section_count -gt 0 ]]; then
        _emit_task "$current_section" "$section_items" "$section_count"
      fi
      current_section="${BASH_REMATCH[1]}"
      section_items=""
      section_count=0
      continue
    fi

    # Collect [fix] items
    if echo "$line" | grep -q '\[fix\]'; then
      local cleaned
      cleaned=$(echo "$line" | sed 's/^- \[ \] //' | sed 's/\[fix\] *//')
      section_items="${section_items}${cleaned}"$'\n'
      section_count=$((section_count + 1))
    fi
  done < "$ISSUES_FILE"

  # Emit task for the last section
  if [[ -n "$section_items" && $section_count -gt 0 ]]; then
    _emit_task "$current_section" "$section_items" "$section_count"
  fi
}

_emit_task() {
  local section="$1" items="$2" count="$3"

  # Cap at 5 tasks total
  if [[ $TASK_COUNT -ge 5 ]]; then
    return
  fi

  # Model/timeout based on section type
  local model="sonnet" timeout=900
  case "$section" in
    *Lint*|*lint*)
      model="haiku"
      timeout=600
      ;;
  esac

  cat <<EOF
===TASK===
model: $model
timeout: $timeout
source_ref: verify_fix_$(echo "$section" | tr ' ' '_' | tr '[:upper:]' '[:lower:]')
---
fix: resolve ${count} issue(s) from verify — ${section}

## Context
These issues were flagged by /verify and marked [fix] by the reviewer.

## Issues
${items}
## What to do
1. Read the relevant files and fix each issue listed above
2. Re-run the relevant test/check to confirm the fix
3. Commit with: committer "fix: resolve verify issues — ${section}" <files>

EOF
  TASK_COUNT=$((TASK_COUNT + 1))
}

# ─── Run ─────────────────────────────────────────────────────────────────────
_process_skips
_process_fixes

# ─── Clean up processed items from issues file ──────────────────────────────
# Remove all annotated lines; keep unannotated ones
_cleanup_issues() {
  local remaining
  remaining=$(grep -v -E '\[(fix|skip|wontfix)\]' "$ISSUES_FILE" 2>/dev/null || true)

  # Check if anything meaningful remains (non-empty, non-header lines)
  local has_items=false
  while IFS= read -r line; do
    if [[ -n "$line" && ! "$line" =~ ^## && ! "$line" =~ ^[[:space:]]*$ ]]; then
      has_items=true
      break
    fi
  done <<< "$remaining"

  if [[ "$has_items" == "true" ]]; then
    echo "$remaining" > "$ISSUES_FILE"
  else
    rm -f "$ISSUES_FILE"
  fi
}
_cleanup_issues

echo "# scan-verify-issues: emitted ${TASK_COUNT} task(s)" >&2
