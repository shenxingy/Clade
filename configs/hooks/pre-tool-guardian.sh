#!/usr/bin/env bash
# pre-tool-guardian.sh — Block dangerous Bash commands before they execute
#
# Triggered: PreToolUse (matcher: Bash)
# Purpose:   Auto-block operations that either:
#   1. Timeout inside Claude Code (database migrations)
#   2. Are catastrophically destructive (rm -rf /, DROP DATABASE)
#   3. Could corrupt parallel agent sessions (force push to main)
#
# Output: JSON {"decision":"block","reason":"..."} to block, or exit 0 to allow

set -euo pipefail

# Read JSON input from stdin
INPUT=$(cat)

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null || echo "")

# Only act on Bash tool
if [[ "$TOOL_NAME" != "Bash" ]]; then
  exit 0
fi

COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null || echo "")

if [[ -z "$COMMAND" ]]; then
  exit 0
fi

# ─── Dev mode check ───────────────────────────────────────────────────
# When ~/.claude/.dev-mode exists, skip migration blocking.
# Run `devmode` to toggle. Catastrophic operations are ALWAYS blocked.
DEV_MODE=false
[[ -f "$HOME/.claude/.dev-mode" ]] && DEV_MODE=true

# ─── Database migrations ──────────────────────────────────────────────
# These require interactive confirmation or long timeouts — must run manually.
# Common ORM/migration tools that block or timeout inside Claude Code.
# (Skipped in dev mode — toggle with: devmode on/off)
if [[ "$DEV_MODE" == false ]]; then
# Strip comment-only lines AND variable assignment lines before scanning.
# This prevents false positives when a blocked pattern appears in:
#   - Shell comments:       # alembic upgrade head
#   - String assignments:   INPUT='{"command":"alembic upgrade",...}'
#   - Heredoc data lines:   VAR="alembic upgrade head"
SCANNABLE=$(echo "$COMMAND" \
  | grep -v '^\s*#' \
  | grep -v "^\s*[A-Za-z_][A-Za-z0-9_]*='" \
  | grep -v '^\s*[A-Za-z_][A-Za-z0-9_]*="' \
  || true)

MIGRATION_PATTERNS=(
  "db:push"
  "db:migrate"
  "prisma migrate"
  "drizzle-kit push"
  "alembic upgrade"
  "alembic downgrade"
  "rake db:migrate"
  "rake db:rollback"
  "knex migrate:latest"
  "knex migrate:rollback"
  "sequelize db:migrate"
  "flyway migrate"
  "liquibase update"
)

for pattern in "${MIGRATION_PATTERNS[@]}"; do
  if echo "$SCANNABLE" | grep -qF "$pattern"; then
    jq -n \
      --arg reason "Database migration detected: '$pattern' cannot run inside Claude Code (interactive prompts / timeouts). Run manually in your terminal: $COMMAND" \
      '{"decision":"block","reason":$reason}'
    exit 0
  fi
done
fi  # end dev-mode gate

# ─── Catastrophic rm -rf on system/home directories ──────────────────
# Block rm with both -r and -f flags targeting /, ~, $HOME, or critical system paths.
# Handles any flag order: -rf, -fr, -r -f, -f -r, -rfi, etc.
# Root (/) matched with word-boundary-aware pattern: space+slash+(space|end|star)
DANGEROUS_NAMED_PATHS='(~|\$HOME|/home|/etc|/usr|/var|/sys|/proc|/boot)\b'
DANGEROUS_ROOT='(^|[[:space:]])/([[:space:]]|$|\*)'
# Extract only the lines that contain rm — avoid false positives where
# a dangerous path appears elsewhere in the script (e.g. "cd /home/...")
RM_LINES=$(echo "$COMMAND" | grep -E '\brm\b' || true)
if [[ -n "$RM_LINES" ]] \
  && echo "$RM_LINES" | grep -qE '\brm\b.*-[a-zA-Z]*r' \
  && echo "$RM_LINES" | grep -qE '\brm\b.*-[a-zA-Z]*f' \
  && (echo "$RM_LINES" | grep -qE "$DANGEROUS_NAMED_PATHS" \
    || echo "$RM_LINES" | grep -qE "$DANGEROUS_ROOT"); then
  jq -n \
    --arg cmd "$COMMAND" \
    '{"decision":"block","reason":("Catastrophic rm -rf blocked on system/home directory. Command: " + $cmd + ". If intentional, run manually in your terminal.")}'
  exit 0
fi

# ─── Force push to main/master ────────────────────────────────────────
# Force-pushing to shared branches destroys history. Block unconditionally.
# Handles flags before or after branch name: git push --force origin main, git push origin main -f
if echo "$COMMAND" | grep -qE 'git[[:space:]]+push[[:space:]]' \
  && echo "$COMMAND" | grep -qE '(--force\b|-f\b)' \
  && echo "$COMMAND" | grep -qE '\b(main|master)\b'; then
  jq -n \
    --arg cmd "$COMMAND" \
    '{"decision":"block","reason":("Force push to main/master blocked. This destroys shared history. Use --force-with-lease on a feature branch, or ask the user explicitly. Command: " + $cmd)}'
  exit 0
fi

# ─── Rewrite force push on feature branches ───────────────────────────
# git push --force / -f on non-main branches is risky — rewrite to --force-with-lease
# which refuses to overwrite if the remote was updated by someone else.
if echo "$COMMAND" | grep -qE 'git[[:space:]]+push[[:space:]]' \
  && echo "$COMMAND" | grep -qE '(--force\b|-f\b)'; then
  SAFER=$(echo "$COMMAND" \
    | sed 's/--force\b/--force-with-lease/g' \
    | sed 's/\(git[[:space:]]*push[[:space:]].*\)-f\b/\1--force-with-lease/g')
  jq -n \
    --arg safer "$SAFER" \
    '{"decision":"allow","updatedInput":{"command":$safer}}'
  exit 0
fi

# ─── SQL DROP DATABASE / DROP TABLE ──────────────────────────────────
# These are irreversible. Redirect to manual execution.
if echo "$COMMAND" | grep -qiE '\bDROP[[:space:]]+(DATABASE|TABLE|SCHEMA)\b'; then
  jq -n \
    --arg cmd "$COMMAND" \
    '{"decision":"block","reason":("SQL DROP statement blocked. Irreversible operation must be run manually in your terminal after review. Command: " + $cmd)}'
  exit 0
fi

# ─── Allow everything else ───────────────────────────────────────────
exit 0
