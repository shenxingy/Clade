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
# Strip comment-only lines AND pure-assignment lines before scanning.
# A "pure assignment" is a line whose ENTIRE content is a single variable
# assignment (optionally followed by `;`). Lines like
#   DATABASE_URL="..." alembic upgrade head
# are NOT stripped — the assignment is a prefix, and the rest is a real
# command that must be scanned. (Earlier revisions over-stripped these,
# allowing env-prefixed migrations to slip past the guardian — KL1.)
#
# Prevented false positives (still stripped):
#   - Shell comments:       # alembic upgrade head
#   - String assignments:   INPUT='{"command":"alembic upgrade",...}'
#   - Heredoc data lines:   VAR="alembic upgrade head"
SCANNABLE=$(echo "$COMMAND" \
  | grep -v '^\s*#' \
  | grep -vE "^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*='[^']*'[[:space:]]*;?[[:space:]]*$" \
  | grep -vE '^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*="[^"]*"[[:space:]]*;?[[:space:]]*$' \
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
# `~` needs its own anchoring, NOT the trailing \b the other alternatives use:
# \b requires a word/non-word transition, and `~` is itself a non-word char, so
# `~\b` could never match `~` or `~/...` (it only matched nonsense like `~abc`)
# — i.e. `rm -rf ~` sailed straight through. Anchor it as a home reference
# instead: start/space/`=` before it, and `/`, whitespace, or end after the
# optional ~user part. That still lets a trailing-tilde backup file through
# (`rm -rf /tmp/file~`), which is not a home reference.
DANGEROUS_TILDE='(^|[[:space:]]|=)~[a-zA-Z0-9._-]*(/|[[:space:]]|$)'
DANGEROUS_NAMED_PATHS="($DANGEROUS_TILDE|\\\$HOME\\b|(/home|/etc|/usr|/var|/sys|/proc|/boot)\\b)"
DANGEROUS_ROOT='(^|[[:space:]])/([[:space:]]|$|\*)'
# Split into individual shell statements before testing, then require ONE
# statement to satisfy every condition on its own.
#
# Per-LINE matching was too coarse in both directions:
#   - False positive: `SRC=/home/me/.claude; rm -rf /tmp/shadow-test` blocked a
#     benign temp delete because a home path shared its line. Shell one-liners
#     chain statements with ; && || far more often than they use newlines, so
#     "only look at rm lines" did not actually isolate the rm.
#   - False negative direction: the three greps ran independently over the whole
#     set of rm lines, so `rm -r a` on one line plus `rm -f /home/b` on another
#     combined into a block that neither statement earned.
# `tr` (not sed \n, which BSD sed rejects) keeps this portable to macOS.
RM_STATEMENTS=$(printf '%s' "$COMMAND" | tr ';|&' '\n\n\n' | grep -E '\brm\b' || true)
CATASTROPHIC_RM=false
while IFS= read -r _stmt; do
  [[ -z "$_stmt" ]] && continue
  echo "$_stmt" | grep -qE '\brm\b.*-[a-zA-Z]*r' || continue
  echo "$_stmt" | grep -qE '\brm\b.*-[a-zA-Z]*f' || continue
  if echo "$_stmt" | grep -qE "$DANGEROUS_NAMED_PATHS" \
    || echo "$_stmt" | grep -qE "$DANGEROUS_ROOT"; then
    CATASTROPHIC_RM=true
    break
  fi
done <<< "$RM_STATEMENTS"
if [[ "$CATASTROPHIC_RM" == true ]]; then
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

# ─── Self-killing pkill -f ───────────────────────────────────────────
# `pkill -f PAT` matches against full command lines, including the command line
# of the shell that launched it. Inside an ssh one-liner or a compound command
# whose own text contains PAT, the launching shell matches its own pattern and
# kills itself: exit 255/144, and the work after the `&&` never runs. It looks
# like the remote host rejected the connection, so the time goes into debugging
# ssh. Blocked only in the shape that actually self-destructs, because a guard
# that fires on ordinary `pkill -f name` is one you learn to ignore.
# `pkill` must sit at a COMMAND position — start of string, or after a
# separator or an opening quote. Matching it anywhere caught prose: this very
# guard's own commit message ("block the pkill -f shape that kills its own
# launcher") was refused, which is the failure mode the rule below warns about.
if echo "$COMMAND" | grep -qE '(^|[;&|(]|[[:space:]]&&[[:space:]]|["'"'"'])[[:space:]]*pkill[[:space:]]+(-[a-zA-Z]*f|--full)'; then
  _PK_PAT=$(echo "$COMMAND" \
    | sed -nE "s/.*(^|[;&|('\"]|[[:space:]])pkill[[:space:]]+(-[a-zA-Z]*f|--full)[[:space:]]+['\"]?([^'\"[:space:]]+).*/\3/p" \
    | head -1)
  if [[ -n "$_PK_PAT" ]]; then
    # Occurrences of the pattern in the command the shell will carry.
    _PK_N=$(echo "$COMMAND" | grep -oF -- "$_PK_PAT" | wc -l | tr -d ' ')
    # A wrapped/remote one-liner carries the pattern in the wrapper's own argv,
    # so a single textual occurrence is still a self-match there.
    _PK_WRAPPED=false
    echo "$COMMAND" | grep -qE '(^|[[:space:]])(ssh|bash[[:space:]]+-c|sh[[:space:]]+-c)([[:space:]]|$)' \
      && _PK_WRAPPED=true
    if [[ "${_PK_N:-0}" -ge 2 || "$_PK_WRAPPED" == true ]]; then
      jq -n \
        --arg pat "$_PK_PAT" \
        --arg cmd "$COMMAND" \
        '{"decision":"block","reason":("pkill -f " + $pat + " will match the command line of the shell running it, so this kills its own launcher (exit 255/144) and everything after it never runs. Fixes: put the pkill in a script file, so the pattern is not in the caller argv; anchor the pattern (\"name\\.py --flag\"); and in monitors use the bracket trick pgrep \"na[m]e\". Command: " + $cmd)}'
      exit 0
    fi
  fi
fi

# ─── Allow everything else ───────────────────────────────────────────
exit 0
