#!/usr/bin/env bash
# uninstall.sh — Remove Claude Code customizations deployed by install.sh
#
# Removes only files managed by this repo. Does NOT delete:
#   - corrections/ (user data)
#   - Skills not managed by this repo
#   - Non-hook settings in settings.json (env, permissions)

set -euo pipefail

CLAUDE_DIR="$HOME/.claude"

echo "Uninstalling Claude Code customizations..."
echo ""

# ─── 1. Remove hooks ─────────────────────────────────────────────────

MANAGED_HOOKS=(
  session-context.sh
  post-edit-check.sh
  notify-telegram.sh
  verify-task-completed.sh
  correction-detector.sh
)

echo "Removing hooks..."
for hook in "${MANAGED_HOOKS[@]}"; do
  if [[ -f "$CLAUDE_DIR/hooks/$hook" ]]; then
    rm "$CLAUDE_DIR/hooks/$hook"
    echo "  Removed: $hook"
  fi
done

# ─── 2. Remove agents ────────────────────────────────────────────────

MANAGED_AGENTS=(
  code-reviewer.md
  test-runner.md
  type-checker.md
  verify-app.md
)

echo "Removing agents..."
for agent in "${MANAGED_AGENTS[@]}"; do
  if [[ -f "$CLAUDE_DIR/agents/$agent" ]]; then
    rm "$CLAUDE_DIR/agents/$agent"
    echo "  Removed: $agent"
  fi
done

# ─── 3. Remove managed skills ────────────────────────────────────────

MANAGED_SKILLS=(
  batch-tasks
  sync
  model-research
)

echo "Removing managed skills..."
for skill in "${MANAGED_SKILLS[@]}"; do
  if [[ -d "$CLAUDE_DIR/skills/$skill" ]]; then
    rm -rf "$CLAUDE_DIR/skills/$skill"
    echo "  Removed skill: $skill"
  fi
done

# ─── 4. Remove scripts ───────────────────────────────────────────────

MANAGED_SCRIPTS=(
  run-tasks.sh
  run-tasks-parallel.sh
)

echo "Removing scripts..."
for script in "${MANAGED_SCRIPTS[@]}"; do
  if [[ -f "$CLAUDE_DIR/scripts/$script" ]]; then
    rm "$CLAUDE_DIR/scripts/$script"
    echo "  Removed: $script"
  fi
done

# ─── 5. Remove commands ──────────────────────────────────────────────

MANAGED_COMMANDS=(
  review.md
)

echo "Removing commands..."
for cmd in "${MANAGED_COMMANDS[@]}"; do
  if [[ -f "$CLAUDE_DIR/commands/$cmd" ]]; then
    rm "$CLAUDE_DIR/commands/$cmd"
    echo "  Removed: $cmd"
  fi
done

# ─── 6. Remove hooks from settings.json ──────────────────────────────

echo "Cleaning settings.json..."
if [[ -f "$CLAUDE_DIR/settings.json" ]] && command -v jq &>/dev/null; then
  jq 'del(.hooks)' "$CLAUDE_DIR/settings.json" > /tmp/claude-settings-clean.json
  mv /tmp/claude-settings-clean.json "$CLAUDE_DIR/settings.json"
  echo "  Removed hooks from settings.json"
else
  echo "  Skipped (no settings.json or jq not available)"
fi

# ─── 7. Clean up empty directories ───────────────────────────────────

for dir in hooks agents scripts commands; do
  rmdir "$CLAUDE_DIR/$dir" 2>/dev/null && echo "  Removed empty dir: $dir" || true
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Uninstall complete."
echo ""
echo "Preserved:"
echo "  - ~/.claude/corrections/ (user data)"
echo "  - ~/.claude/settings.json (env, permissions — only hooks removed)"
echo "  - Other skills not managed by this repo"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
