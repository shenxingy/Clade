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

# ─── Database migrations ──────────────────────────────────────────────
# These require interactive confirmation or long timeouts — must run manually.
# Common ORM/migration tools that block or timeout inside Claude Code.
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
  if echo "$COMMAND" | grep -qF "$pattern"; then
    jq -n \
      --arg reason "Database migration detected: '$pattern' cannot run inside Claude Code (interactive prompts / timeouts). Run manually in your terminal: $COMMAND" \
      '{"decision":"block","reason":$reason}'
    exit 0
  fi
done

# ─── Catastrophic rm -rf on system/home directories ──────────────────
# Block rm -rf targeting /, ~, $HOME, or critical system paths.
if echo "$COMMAND" | grep -qE 'rm[[:space:]]+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*[[:space:]]+(\/[^a-zA-Z]|~|~\/|\$HOME|\/home|\/etc|\/usr|\/var|\/sys|\/proc|\/boot|\/dev|\/root)'; then
  jq -n \
    --arg cmd "$COMMAND" \
    '{"decision":"block","reason":("Catastrophic rm -rf blocked on system/home directory. Command: " + $cmd + ". If intentional, run manually in your terminal.")}'
  exit 0
fi

# ─── Force push to main/master ────────────────────────────────────────
# Force-pushing to shared branches destroys history. Block unconditionally.
if echo "$COMMAND" | grep -qE 'git[[:space:]]+push[[:space:]]+.*(--force|-f).*[[:space:]]+(origin[[:space:]]+)?(main|master)([[:space:]]|$)'; then
  jq -n \
    --arg cmd "$COMMAND" \
    '{"decision":"block","reason":("Force push to main/master blocked. This destroys shared history. Use --force-with-lease on a feature branch, or ask the user explicitly. Command: " + $cmd)}'
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
