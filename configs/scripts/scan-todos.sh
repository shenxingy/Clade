#!/usr/bin/env bash
set -euo pipefail

# Cross-platform readlink -f (macOS lacks -f flag)
_readlink_f() {
  if readlink -f "$1" 2>/dev/null; then return; fi
  # macOS fallback
  python3 -c "import os; print(os.path.realpath('$1'))" 2>/dev/null || echo "$1"
}

# ─── Usage ───────────────────────────────────────────────────────────────────

usage() {
  cat <<'EOF'
Usage: scan-todos.sh [OPTIONS] [project-dir]

Scan source files for TODO/FIXME/HACK/XXX comments and emit ===TASK=== blocks.

Arguments:
  project-dir   Directory to scan (default: current directory)

Options:
  --help        Show this help message

Output format (one block per match):
  ===TASK===
  model: haiku
  timeout: 600
  ---
  fix(todo): <comment> in <file>:<line>

  File: <file>
  Line: <line>
  Comment: <full matched line>

  Fix the TODO comment by implementing it properly.

Deduplication:
  If output is redirected to a file (tasks.txt) that already exists,
  entries whose file:line already appear in it are skipped.

Examples:
  scan-todos.sh                          # scan current directory
  scan-todos.sh /path/to/project         # scan specific directory
  scan-todos.sh . > tasks.txt            # write tasks to file (with dedup on re-run)
  scan-todos.sh . >> tasks.txt           # append (same dedup logic)
EOF
}

# ─── Args ────────────────────────────────────────────────────────────────────

if [[ "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

# Print usage if no args and stdin is a tty
if [[ $# -eq 0 && -t 0 ]]; then
  usage
  exit 0
fi

PROJECT_DIR="${1:-.}"

if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "Error: directory not found: $PROJECT_DIR" >&2
  exit 1
fi

# ─── Dedup: load existing file:line entries ───────────────────────────────────

declare -A SEEN=()

# Check if stdout is redirected to a file that already exists
OUTPUT_FILE=""
if [[ ! -t 1 ]]; then
  # Try to get the output file path via /proc/self/fd/1
  if [[ -L /proc/self/fd/1 ]]; then
    fd1_target=$(_readlink_f /proc/self/fd/1)
    if [[ -f "$fd1_target" ]]; then
      OUTPUT_FILE="$fd1_target"
    fi
  fi
fi

if [[ -n "$OUTPUT_FILE" && -f "$OUTPUT_FILE" ]]; then
  # Extract file:line pairs already present in the tasks file
  while IFS= read -r line; do
    if [[ "$line" =~ ^File:\ (.+)$ ]]; then
      current_file="${BASH_REMATCH[1]}"
    elif [[ "$line" =~ ^Line:\ ([0-9]+)$ ]]; then
      current_line="${BASH_REMATCH[1]}"
      SEEN["${current_file}:${current_line}"]=1
    fi
  done < "$OUTPUT_FILE"
fi

# ─── Scan ────────────────────────────────────────────────────────────────────

found=0

while IFS= read -r match; do
  # match format: filepath:linenum:content
  file="${match%%:*}"
  rest="${match#*:}"
  line_num="${rest%%:*}"
  full_line="${rest#*:}"

  key="${file}:${line_num}"

  # Dedup check
  if [[ -n "${SEEN[$key]+_}" ]]; then
    continue
  fi

  # Extract the comment text (everything after TODO:/FIXME:/HACK:/XXX:)
  comment_text=$(echo "$full_line" | sed -E 's/.*\b(TODO|FIXME|HACK|XXX):[[:space:]]*//' | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//')

  found=$((found + 1))

  cat <<EOF
===TASK===
model: haiku
timeout: 600
---
fix(todo): ${comment_text} in ${file}:${line_num}

File: ${file}
Line: ${line_num}
Comment: ${full_line}

Fix the TODO comment by implementing it properly.
EOF

done < <(
  grep -rn \
    --include="*.sh" \
    --include="*.py" \
    --include="*.js" \
    --include="*.ts" \
    --include="*.go" \
    --include="*.rb" \
    --include="*.rs" \
    --exclude-dir=".git" \
    --exclude-dir="node_modules" \
    --exclude-dir=".venv" \
    --exclude-dir="venv" \
    -E "(TODO|FIXME|HACK|XXX):" \
    "$PROJECT_DIR" 2>/dev/null || true
)

# ─── Summary ─────────────────────────────────────────────────────────────────

echo "# Found ${found} TODO items" >&2
