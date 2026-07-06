#!/usr/bin/env bash
# scan-health — Generate tasks from code health issues
#
# Usage: bash scan-health.sh [project-dir]
#
# Checks: TODO/FIXME comments, lint warnings, type errors, large files,
# verify/test suite runtime (slow suites erode loop clock speed).
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

# ─── Test Suite Runtime (slow suite erodes loop clock speed) ─────────────────
_scan_test_runtime() {
  # loop-runner.sh caps its verify node at TEST_SAMPLE_TIMEOUT=120s — a verify
  # command slower than ~100s silently degrades every loop iteration, so a slow
  # suite is a health finding, not a nit. This probe RUNS the real suite once
  # (bounded by threshold+80s); skip with SCAN_HEALTH_SKIP_RUNTIME=1.
  [[ "${SCAN_HEALTH_SKIP_RUNTIME:-0}" == "1" ]] && return

  local threshold="${TEST_RUNTIME_THRESHOLD:-100}"
  local probe_timeout=$((threshold + 80))

  # Resolve the command the same way loop-runner.sh's verify node does:
  # verify_cmd: → Verify command: — then fall back to Test command:
  local cmd=""
  if [[ -f "CLAUDE.md" ]]; then
    cmd=$(grep -m1 'verify_cmd:' CLAUDE.md 2>/dev/null | sed 's/.*verify_cmd:[[:space:]]*//' || true)
    [[ -z "$cmd" ]] && cmd=$(grep -m1 'Verify command:' CLAUDE.md 2>/dev/null | sed 's/.*Verify command:[[:space:]]*//' || true)
    [[ -z "$cmd" ]] && cmd=$(grep -m1 'Test command:' CLAUDE.md 2>/dev/null | sed 's/.*Test command:[[:space:]]*//' || true)
  fi
  # Template placeholders ("[e.g. pytest ...]") and N/A are not runnable
  case "$cmd" in ""|"N/A"|"["*) return ;; esac

  local start_ts end_ts duration rc=0
  start_ts=$(date +%s)
  timeout "$probe_timeout" bash -c "$cmd" >/dev/null 2>&1 || rc=$?
  end_ts=$(date +%s)
  duration=$((end_ts - start_ts))

  [[ "$duration" -le "$threshold" ]] && return

  local timeout_note=""
  [[ "$rc" -eq 124 ]] && timeout_note=" (killed at ${probe_timeout}s probe timeout)"

  cat <<EOF
===TASK===
model: sonnet
timeout: 1800
source_ref: health_slow_tests
---
perf: verify/test suite took ${duration}s${timeout_note} — over the ${threshold}s loop budget, run /trim-tests

## Context
Command: ${cmd}
Measured: ${duration}s (threshold: ${threshold}s, exit code: ${rc})${timeout_note}
loop-runner.sh caps its verify node at 120s (TEST_SAMPLE_TIMEOUT) — a suite slower
than ~100s silently degrades every loop iteration's verification.

## What to do
1. Run the /trim-tests skill (prompt: ~/.claude/skills/trim-tests/prompt.md), scoped to the slowest test files
2. Consolidate near-identical tests into table-driven cases; delete trivial / mock-only / brittle ones
3. Re-run the suite and confirm runtime is back under ${threshold}s
4. Include the skill's "Coverage intentionally given up" section in the commit body

EOF
  TASK_COUNT=$((TASK_COUNT + 1))
}

# ─── MCP Server Context-Budget Audit (tw93/Waza pattern) ────────────────────
# Every configured MCP server's tool schemas load into the system prompt on
# EVERY turn — an unbounded server list silently eats context budget the same
# way an unbounded log tail does (worker.py's estimate is reused conceptually
# here: len(text) // 4 chars-to-tokens). Reachability IS a live probe: stdio
# servers are checked via `command -v` on PATH; http/sse servers get a short
# connection check. The token cost is NOT a live measurement — introspecting
# each server's REAL tool list would mean spawning it (network installs via
# npx/uvx, docker pulls, required credentials), which is unsafe and slow for a
# fast, side-effect-free scan. Instead it's a documented flat per-server
# placeholder (a typical server exposes ~5-15 tools at ~150-300 tokens each
# once serialized) — override with MCP_TOOL_TOKEN_ESTIMATE if you have better
# data for your fleet. Threshold override: MCP_TOKEN_BUDGET_THRESHOLD.
_scan_mcp_budget() {
  local mcp_config=".claude/mcp.json"
  [[ -f "$mcp_config" ]] || return 0
  command -v python3 &>/dev/null || return 0

  local per_server_est budget_threshold
  per_server_est="${MCP_TOOL_TOKEN_ESTIMATE:-2500}"
  budget_threshold="${MCP_TOKEN_BUDGET_THRESHOLD:-20000}"

  # name<TAB>transport(stdio|http)<TAB>target(command|url) — one server per line
  local servers
  servers=$(python3 - "$mcp_config" <<'PYEOF' 2>/dev/null
import json, sys

try:
    with open(sys.argv[1]) as fh:
        data = json.load(fh)
except Exception:
    sys.exit(0)

for name, entry in (data.get("mcpServers") or {}).items():
    if not isinstance(entry, dict):
        continue
    url = entry.get("url")
    if url:
        print(f"{name}\thttp\t{url}")
    else:
        print(f"{name}\tstdio\t{entry.get('command', '')}")
PYEOF
) || true

  [[ -z "$servers" ]] && return

  local total_tokens=0 server_count=0
  local unreachable="" breakdown=""

  while IFS=$'\t' read -r name transport target; do
    [[ -z "$name" ]] && continue
    server_count=$((server_count + 1))
    total_tokens=$((total_tokens + per_server_est))

    local reachable="unknown"
    if [[ "$transport" == "stdio" ]]; then
      if [[ -n "$target" ]] && command -v "$target" &>/dev/null; then
        reachable="reachable"
      else
        reachable="unreachable"
      fi
    elif [[ "$transport" == "http" ]]; then
      if command -v curl &>/dev/null; then
        if curl -s -o /dev/null --max-time 3 "$target" 2>/dev/null; then
          reachable="reachable"
        else
          reachable="unreachable"
        fi
      fi
    fi

    breakdown="${breakdown}  - ${name} (${transport}): ~${per_server_est} tokens, ${reachable}"$'\n'
    if [[ "$reachable" == "unreachable" ]]; then
      unreachable="${unreachable}  - ${name} (${transport}): ${target:-<missing command/url>}"$'\n'
    fi
  done <<< "$servers"

  # Finding 1: unreachable server(s) — always reported, independent of budget
  if [[ -n "$unreachable" ]]; then
    cat <<EOF
===TASK===
model: haiku
timeout: 600
source_ref: health_mcp_unreachable
---
fix: unreachable MCP server(s) in ${mcp_config}

## Context
${server_count} MCP server(s) configured in ${mcp_config}. The following
failed a live reachability probe (stdio: binary on PATH via \`command -v\`;
http/sse: short-timeout connection check):

${unreachable}
## What to do
1. Confirm each server's command/binary is installed, or its URL is reachable
   from this machine
2. Fix or remove the broken entry in ${mcp_config}
3. Re-run \`bash configs/scripts/scan-health.sh\` to verify
4. Commit with: committer "fix: repair unreachable MCP server config" ${mcp_config}

EOF
    TASK_COUNT=$((TASK_COUNT + 1))
  fi

  # Finding 2: tool-schema token budget exceeded
  if [[ "$total_tokens" -gt "$budget_threshold" ]]; then
    cat <<EOF
===TASK===
model: sonnet
timeout: 900
source_ref: health_mcp_budget
---
perf: MCP tool-schema context budget exceeded (~${total_tokens} tokens across ${server_count} server(s), threshold ${budget_threshold})

## Context
Every configured MCP server's tool schemas load into the system prompt on
EVERY turn. ${mcp_config} configures ${server_count} server(s):

${breakdown}
Estimate: ~${per_server_est} tokens/server (documented flat placeholder — a
typical server exposes ~5-15 tools at ~150-300 tokens each once serialized;
live introspection of arbitrary MCP servers was out of scope for this fast,
side-effect-free scan). Total: ~${total_tokens} tokens vs a ${budget_threshold}
token budget.

## What to do
1. Review ${mcp_config} and drop MCP servers not actively used by this project
2. For occasionally-needed servers, pass --mcp-config per-invocation instead
   of keeping them in the standing project config
3. Re-run \`bash configs/scripts/scan-health.sh\` to confirm the estimate is
   back under budget
4. Commit with: committer "perf: trim MCP server context budget" ${mcp_config}

EOF
    TASK_COUNT=$((TASK_COUNT + 1))
  fi
}

# ─── Run all scans ──────────────────────────────────────────────────────────
_scan_todos
_scan_type_errors
_scan_lint
_scan_large_files
_scan_test_runtime
_scan_mcp_budget

echo "# scan-health: found ${TASK_COUNT} issue(s)" >&2
