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
  pre-tool-guardian.sh
  post-edit-check.sh
  post-tool-use-lint.sh
  edit-shadow-detector.sh
  revert-detector.sh
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

# Remove hook libraries
if [[ -d "$CLAUDE_DIR/hooks/lib" ]]; then
  rm -rf "$CLAUDE_DIR/hooks/lib"
  echo "  Removed: hooks/lib/"
fi

# ─── 2. Remove agents ────────────────────────────────────────────────

MANAGED_AGENTS=(
  code-reviewer.md
  paper-reviewer.md
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
  audit
  batch-tasks
  commit
  handoff
  loop
  model-research
  orchestrate
  pickup
  sync
)

echo "Removing managed skills..."
for skill in "${MANAGED_SKILLS[@]}"; do
  if [[ -d "$CLAUDE_DIR/skills/$skill" ]]; then
    rm -rf "$CLAUDE_DIR/skills/$skill"
    echo "  Removed skill: $skill"
  fi
done

# ─── 4. Remove scripts + committer symlink ───────────────────────────

MANAGED_SCRIPTS=(
  committer.sh
  loop-runner.sh
  rule-cluster.sh
  run-tasks.sh
  run-tasks-parallel.sh
  session-scorecard.sh
)

echo "Removing scripts..."
for script in "${MANAGED_SCRIPTS[@]}"; do
  if [[ -f "$CLAUDE_DIR/scripts/$script" ]]; then
    rm "$CLAUDE_DIR/scripts/$script"
    echo "  Removed: $script"
  fi
done

if [[ -L "$HOME/.local/bin/committer" ]]; then
  rm "$HOME/.local/bin/committer"
  echo "  Removed: ~/.local/bin/committer symlink"
fi

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

# ─── 6. Remove templates ─────────────────────────────────────────────

echo "Removing templates..."
if [[ -d "$CLAUDE_DIR/templates" ]]; then
  rm -rf "$CLAUDE_DIR/templates"
  echo "  Removed: templates/"
fi

# ─── 7. Remove models.env ────────────────────────────────────────────

if [[ -f "$CLAUDE_DIR/models.env" ]]; then
  rm "$CLAUDE_DIR/models.env"
  echo "Removed models.env"
fi

# ─── 8. Remove status line script ────────────────────────────────────

if [[ -f "$CLAUDE_DIR/statusline-command.sh" ]]; then
  rm "$CLAUDE_DIR/statusline-command.sh"
  echo "Removed statusline-command.sh"
fi

# ─── 9. Remove hooks + statusLine from settings.json ─────────────────

echo "Cleaning settings.json..."
if [[ -f "$CLAUDE_DIR/settings.json" ]] && command -v jq &>/dev/null; then
  jq 'del(.hooks) | del(.statusLine)' "$CLAUDE_DIR/settings.json" > /tmp/claude-settings-clean.json
  mv /tmp/claude-settings-clean.json "$CLAUDE_DIR/settings.json"
  echo "  Removed hooks + statusLine from settings.json"
else
  echo "  Skipped (no settings.json or jq not available)"
fi

# ─── 10. Remove shell aliases ─────────────────────────────────────────

echo "Removing shell aliases..."
for rc_file in "$HOME/.zshrc" "$HOME/.bashrc"; do
  [[ -f "$rc_file" ]] || continue
  if grep -q "dangerously-skip-permissions" "$rc_file" 2>/dev/null; then
    # Remove the block added by install.sh (comment + 2 alias lines)
    sed -i '/# Claude Code: skip permission prompts (added by claude-code-kit)/,/^alias cc=/d' "$rc_file"
    echo "  Removed aliases from $rc_file"
  fi
done

# ─── 11. Clean up empty directories ──────────────────────────────────

for dir in hooks agents scripts commands; do
  rmdir "$CLAUDE_DIR/$dir" 2>/dev/null && echo "  Removed empty dir: $dir" || true
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Uninstall complete."
echo ""
echo "Preserved:"
echo "  - ~/.claude/corrections/ (user data)"
echo "  - ~/.claude/settings.json (env, permissions — hooks/statusLine removed)"
echo "  - Other skills not managed by this repo"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
