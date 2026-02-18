#!/usr/bin/env bash
# install.sh — Deploy Claude Code customizations to ~/.claude/
#
# Idempotent: safe to run multiple times.
# Does NOT overwrite user data (corrections/rules.md, corrections/history.jsonl).
# Merges hooks into existing settings.json without losing other fields.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"

echo "Installing Claude Code customizations..."
echo "Source: $SCRIPT_DIR"
echo "Target: $CLAUDE_DIR"
echo ""

# ─── 1. Create directories ───────────────────────────────────────────

echo "Creating directories..."
mkdir -p "$CLAUDE_DIR"/{hooks,agents,skills,scripts,corrections,commands}

# ─── 2. Copy hooks (chmod +x) ────────────────────────────────────────

echo "Installing hooks..."
cp "$SCRIPT_DIR/configs/hooks/"*.sh "$CLAUDE_DIR/hooks/"
chmod +x "$CLAUDE_DIR/hooks/"*.sh
echo "  Installed: $(ls "$SCRIPT_DIR/configs/hooks/"*.sh | xargs -I{} basename {} | tr '\n' ' ')"

# ─── 3. Copy agents ──────────────────────────────────────────────────

echo "Installing agents..."
cp "$SCRIPT_DIR/configs/agents/"*.md "$CLAUDE_DIR/agents/"
echo "  Installed: $(ls "$SCRIPT_DIR/configs/agents/"*.md | xargs -I{} basename {} | tr '\n' ' ')"

# ─── 4. Copy skills (only repo-managed skills, don't overwrite others) ─

echo "Installing skills..."
for skill_dir in "$SCRIPT_DIR/configs/skills/"/*/; do
  skill_name=$(basename "$skill_dir")
  mkdir -p "$CLAUDE_DIR/skills/$skill_name"
  cp "$skill_dir"* "$CLAUDE_DIR/skills/$skill_name/"
  echo "  Installed skill: $skill_name"
done

# ─── 5. Copy scripts (chmod +x) ──────────────────────────────────────

echo "Installing scripts..."
cp "$SCRIPT_DIR/configs/scripts/"*.sh "$CLAUDE_DIR/scripts/"
chmod +x "$CLAUDE_DIR/scripts/"*.sh
echo "  Installed: $(ls "$SCRIPT_DIR/configs/scripts/"*.sh | xargs -I{} basename {} | tr '\n' ' ')"

# ─── 6. Copy commands ────────────────────────────────────────────────

echo "Installing commands..."
cp "$SCRIPT_DIR/configs/commands/"*.md "$CLAUDE_DIR/commands/"
echo "  Installed: $(ls "$SCRIPT_DIR/configs/commands/"*.md | xargs -I{} basename {} | tr '\n' ' ')"

# ─── 7. Initialize corrections (don't overwrite existing) ────────────

if [[ ! -f "$CLAUDE_DIR/corrections/rules.md" ]]; then
  echo "Initializing corrections/rules.md..."
  cp "$SCRIPT_DIR/templates/corrections/rules.md" "$CLAUDE_DIR/corrections/"
else
  echo "Corrections rules.md already exists — skipping"
fi

if [[ ! -f "$CLAUDE_DIR/corrections/stats.json" ]]; then
  cp "$SCRIPT_DIR/templates/corrections/stats.json" "$CLAUDE_DIR/corrections/"
fi

# ─── 8. Merge hooks into settings.json ───────────────────────────────

echo "Configuring settings.json..."

if ! command -v jq &>/dev/null; then
  echo "WARNING: jq not found. Cannot merge hooks into settings.json."
  echo "Please install jq and re-run, or manually copy hooks from configs/settings-hooks.json."
else
  HOOKS=$(jq '.hooks' "$SCRIPT_DIR/configs/settings-hooks.json")

  if [[ -f "$CLAUDE_DIR/settings.json" ]]; then
    # Merge: update hooks field, preserve everything else
    jq --argjson hooks "$HOOKS" '.hooks = $hooks' "$CLAUDE_DIR/settings.json" > /tmp/claude-settings-merged.json
    mv /tmp/claude-settings-merged.json "$CLAUDE_DIR/settings.json"
    echo "  Merged hooks into existing settings.json"
  else
    # Fresh install: copy template
    cp "$SCRIPT_DIR/templates/settings.json" "$CLAUDE_DIR/settings.json"
    echo "  Created settings.json from template"
    echo ""
    echo "  IMPORTANT: Configure these in ~/.claude/settings.json:"
    echo "    - TG_BOT_TOKEN: Your Telegram bot token (for notifications)"
    echo "    - TG_CHAT_ID: Your Telegram chat ID"
  fi
fi

# ─── 9. Summary ──────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Installation complete!"
echo ""
echo "Installed components:"
echo "  Hooks:    $(ls "$CLAUDE_DIR/hooks/"*.sh 2>/dev/null | wc -l) scripts"
echo "  Agents:   $(ls "$CLAUDE_DIR/agents/"*.md 2>/dev/null | wc -l) definitions"
echo "  Skills:   $(ls -d "$CLAUDE_DIR/skills/"*/ 2>/dev/null | wc -l) skills"
echo "  Scripts:  $(ls "$CLAUDE_DIR/scripts/"*.sh 2>/dev/null | wc -l) scripts"
echo "  Commands: $(ls "$CLAUDE_DIR/commands/"*.md 2>/dev/null | wc -l) commands"
echo ""
echo "Start a new Claude Code session to activate all hooks."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
