#!/usr/bin/env bash
# post-tool-use-lint.sh — fast per-file check (or full verify_cmd) after edits
# Reads verify_cmd from .claude/orchestrator.json in the project directory.
# When the edited file (tool_input.file_path from the hook's stdin JSON) has a
# cheap single-file checker (.py / .sh / .js), that runs INSTEAD of the full
# verify_cmd — a full-tree verify per edit is redundant work under MAX_WORKERS
# parallel editors. The full verify_cmd remains the fallback whenever no
# per-file check applies (unknown extension, missing tool, unparseable input).
# On failure: writes .claude/lint-feedback.md and exits 2 (Claude sees and fixes).

set -euo pipefail

# ─── Read hook input ─────────────────────────────────────────────────────────

INPUT=$(cat 2>/dev/null || true)

# ─── Find project root ───────────────────────────────────────────────────────

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

CONFIG_FILE="$PROJECT_DIR/.claude/orchestrator.json"

if [[ ! -f "$CONFIG_FILE" ]]; then
  exit 0
fi

# ─── Read verify_cmd ─────────────────────────────────────────────────────────

if ! command -v jq &>/dev/null; then
  exit 0
fi

VERIFY_CMD=$(jq -r '.verify_cmd // empty' "$CONFIG_FILE" 2>/dev/null)

if [[ -z "$VERIFY_CMD" ]]; then
  exit 0
fi

# ─── Per-file fast path ──────────────────────────────────────────────────────
# Map the edited file's extension to a single-file checker. Empty PER_FILE_CMD
# means "no per-file check applies" → fall back to the full verify_cmd.
# Checkers are syntax gates on purpose: mid-edit states (e.g. an import added
# before its first use) must not be blocked by style rules.

FILE_PATH=$(jq -r '.tool_input.file_path // empty' <<< "$INPUT" 2>/dev/null || true)
if [[ -n "$FILE_PATH" && "$FILE_PATH" != /* ]]; then
  FILE_PATH="$PROJECT_DIR/$FILE_PATH"
fi

PER_FILE_CMD=""
if [[ -n "$FILE_PATH" && -f "$FILE_PATH" ]]; then
  case "$FILE_PATH" in
    *.py)
      if command -v python3 &>/dev/null; then
        PER_FILE_CMD="python3 -m py_compile"
      elif command -v ruff &>/dev/null; then
        PER_FILE_CMD="ruff check --no-cache"
      fi
      ;;
    *.sh|*.bash)
      PER_FILE_CMD="bash -n"
      ;;
    *.js|*.mjs|*.cjs)
      if command -v node &>/dev/null; then
        PER_FILE_CMD="node --check"
      fi
      ;;
  esac
fi

# ─── Run the check ───────────────────────────────────────────────────────────

FEEDBACK_FILE="$PROJECT_DIR/.claude/lint-feedback.md"

if [[ -n "$PER_FILE_CMD" ]]; then
  FAILED_KIND="per-file check"
  FAILED_CMD="$PER_FILE_CMD $FILE_PATH"
  FAILED_DESC="The per-file check failed after your last edit:"
  # shellcheck disable=SC2086  # PER_FILE_CMD is an intentional multi-word command
  OUTPUT=$(cd "$PROJECT_DIR" && $PER_FILE_CMD "$FILE_PATH" 2>&1) && exit 0
else
  FAILED_KIND="verify_cmd"
  FAILED_CMD="$VERIFY_CMD"
  FAILED_DESC="The \`verify_cmd\` from \`.claude/orchestrator.json\` failed after your last edit:"
  OUTPUT=$(cd "$PROJECT_DIR" && eval "$VERIFY_CMD" 2>&1) && exit 0
fi

# Command failed — write feedback for Claude
mkdir -p "$PROJECT_DIR/.claude"
cat > "$FEEDBACK_FILE" << EOF
## Lint/Build Failure

$FAILED_DESC

\`\`\`
$FAILED_CMD
\`\`\`

**Output:**
\`\`\`
$OUTPUT
\`\`\`

Please fix the error above before continuing.
EOF

echo "$FAILED_KIND failed — see .claude/lint-feedback.md" >&2
exit 2
