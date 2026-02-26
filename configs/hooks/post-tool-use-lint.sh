#!/usr/bin/env bash
# post-tool-use-lint.sh — run project's verify_cmd after every file edit
# Reads verify_cmd from .claude/orchestrator.json in the project directory.
# On failure: writes .claude/lint-feedback.md and exits 2 (Claude sees and fixes).

set -euo pipefail

# ─── Find project root ───────────────────────────────────────────────────────

# Claude passes the edited file path via CLAUDE_TOOL_INPUT_FILE_PATH or we
# derive project root from the cwd set by the hook runtime.
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

# ─── Run verify_cmd ──────────────────────────────────────────────────────────

FEEDBACK_FILE="$PROJECT_DIR/.claude/lint-feedback.md"

OUTPUT=$(cd "$PROJECT_DIR" && eval "$VERIFY_CMD" 2>&1) && exit 0

# Command failed — write feedback for Claude
mkdir -p "$PROJECT_DIR/.claude"
cat > "$FEEDBACK_FILE" << EOF
## Lint/Build Failure

The \`verify_cmd\` from \`.claude/orchestrator.json\` failed after your last edit:

\`\`\`
$VERIFY_CMD
\`\`\`

**Output:**
\`\`\`
$OUTPUT
\`\`\`

Please fix the error above before continuing.
EOF

echo "verify_cmd failed — see .claude/lint-feedback.md" >&2
exit 2
