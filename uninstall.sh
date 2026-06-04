#!/usr/bin/env bash
# uninstall.sh — Remove Claude Code customizations deployed by install.sh
#
# Mirrors install.sh: removal lists are DERIVED from configs/ at runtime
# (never hardcoded), so the two scripts cannot drift apart.
#
# Removes only files managed by this repo. Does NOT delete:
#   - corrections/ (user data)
#   - ~/.claude/CLAUDE.md (may contain user content + auto-promoted rules)
#   - ~/.claude/orchestrator-settings.json (user overrides; only the .example is removed)
#   - Skills/agents/hooks not shipped by this repo
#   - Non-hook settings in settings.json (env, permissions)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"

echo "Uninstalling Claude Code customizations (derived from $SCRIPT_DIR/configs)..."
echo ""

# ─── 1. Remove hooks (mirror of install.sh §2) ───────────────────────

echo "Removing hooks..."
removed=0
for src in "$SCRIPT_DIR/configs/hooks/"*.sh; do
  [[ -f "$src" ]] || continue
  hook=$(basename "$src")
  if [[ -f "$CLAUDE_DIR/hooks/$hook" ]]; then
    rm "$CLAUDE_DIR/hooks/$hook"
    removed=$((removed + 1))
  fi
done
echo "  Removed: $removed hooks"

# Hook libraries
if [[ -d "$SCRIPT_DIR/configs/hooks/lib" && -d "$CLAUDE_DIR/hooks/lib" ]]; then
  for src in "$SCRIPT_DIR/configs/hooks/lib/"*.sh; do
    [[ -f "$src" ]] || continue
    rm -f "$CLAUDE_DIR/hooks/lib/$(basename "$src")"
  done
  rmdir "$CLAUDE_DIR/hooks/lib" 2>/dev/null || true
  echo "  Removed: hooks/lib/"
fi

# ─── 2. Remove agents (mirror of install.sh §3) ──────────────────────

echo "Removing agents..."
removed=0
for src in "$SCRIPT_DIR/configs/agents/"*.md; do
  [[ -f "$src" ]] || continue
  agent=$(basename "$src")
  if [[ -f "$CLAUDE_DIR/agents/$agent" ]]; then
    rm "$CLAUDE_DIR/agents/$agent"
    removed=$((removed + 1))
  fi
done
rm -f "$CLAUDE_DIR/agents/available-skills.md"
echo "  Removed: $removed agents (+ available-skills.md)"

# ─── 3. Remove skills (mirror of install.sh §4) ──────────────────────

echo "Removing skills..."
removed=0
for src in "$SCRIPT_DIR/configs/skills/"*/; do
  [[ -d "$src" ]] || continue
  skill=$(basename "$src")
  if [[ -d "$CLAUDE_DIR/skills/$skill" ]]; then
    rm -rf "$CLAUDE_DIR/skills/$skill"
    removed=$((removed + 1))
  fi
done
rm -f "$CLAUDE_DIR/available_skills.md"
echo "  Removed: $removed skills (+ available_skills.md)"

# ─── 4. Remove scripts + symlinks (mirror of install.sh §5, §6b) ─────

echo "Removing scripts..."
removed=0
for src in "$SCRIPT_DIR/configs/scripts/"*.sh "$SCRIPT_DIR/configs/scripts/"*.py; do
  [[ -f "$src" ]] || continue
  script=$(basename "$src")
  if [[ -f "$CLAUDE_DIR/scripts/$script" ]]; then
    rm "$CLAUDE_DIR/scripts/$script"
    removed=$((removed + 1))
  fi
done
echo "  Removed: $removed scripts"

# Script subdirectories (e.g. seo/, ads/, blog/)
for src in "$SCRIPT_DIR/configs/scripts/"*/; do
  [[ -d "$src" ]] || continue
  sub=$(basename "$src")
  [[ "$sub" == "__pycache__" ]] && continue
  if [[ -d "$CLAUDE_DIR/scripts/$sub" ]]; then
    rm -rf "$CLAUDE_DIR/scripts/$sub"
    echo "  Removed: scripts/$sub/"
  fi
done
rm -rf "$CLAUDE_DIR/scripts/__pycache__"

# MCP server (installed from orchestrator/ by install.sh §4b)
rm -f "$CLAUDE_DIR/scripts/mcp_server.py"

# Symlinks created by install.sh (committer, slt, devmode)
for link in committer slt devmode; do
  if [[ -L "$HOME/.local/bin/$link" ]]; then
    rm "$HOME/.local/bin/$link"
    echo "  Removed: ~/.local/bin/$link symlink"
  fi
done

# ─── 5. Remove commands (mirror of install.sh §6) ────────────────────

if compgen -G "$SCRIPT_DIR/configs/commands/*.md" > /dev/null 2>&1; then
  echo "Removing commands..."
  for src in "$SCRIPT_DIR/configs/commands/"*.md; do
    rm -f "$CLAUDE_DIR/commands/$(basename "$src")"
  done
fi

# ─── 6. Remove templates (mirror of install.sh §6c) ──────────────────

echo "Removing templates..."
if [[ -d "$SCRIPT_DIR/configs/templates" && -d "$CLAUDE_DIR/templates" ]]; then
  for src in "$SCRIPT_DIR/configs/templates/"*; do
    [[ -e "$src" ]] || continue
    rm -rf "$CLAUDE_DIR/templates/$(basename "$src")"
  done
  rmdir "$CLAUDE_DIR/templates" 2>/dev/null || true
  echo "  Removed: templates/"
fi

# ─── 7. Remove models.env + statusline (install.sh §5, §6d) ──────────

rm -f "$CLAUDE_DIR/models.env" && echo "Removed models.env" || true
rm -f "$CLAUDE_DIR/statusline-command.sh" && echo "Removed statusline-command.sh" || true

# ─── 8. Remove reference copies + kit markers (§7b, §11) ─────────────

rm -f "$CLAUDE_DIR/orchestrator-settings.example.json"
rm -f "$CLAUDE_DIR/.kit-source-dir" "$CLAUDE_DIR/.kit-checksum"
echo "Removed orchestrator-settings.example.json + kit markers"

# ─── 9. Remove hooks + statusLine from settings.json (§8) ────────────

echo "Cleaning settings.json..."
if [[ -f "$CLAUDE_DIR/settings.json" ]] && command -v jq &>/dev/null; then
  jq 'del(.hooks) | del(.statusLine)' "$CLAUDE_DIR/settings.json" > /tmp/claude-settings-clean.json
  mv /tmp/claude-settings-clean.json "$CLAUDE_DIR/settings.json"
  echo "  Removed hooks + statusLine from settings.json"
else
  echo "  Skipped (no settings.json or jq not available)"
fi

# ─── 10. Remove shell aliases (§9) ───────────────────────────────────

echo "Removing shell aliases..."
for rc_file in "$HOME/.zshrc" "$HOME/.bashrc"; do
  [[ -f "$rc_file" ]] || continue
  if grep -q "dangerously-skip-permissions" "$rc_file" 2>/dev/null; then
    # Remove the block added by install.sh (comment + 2 alias lines)
    sed -i '/# Claude Code: skip permission prompts (added by clade)/,/^alias cc=/d' "$rc_file"
    echo "  Removed aliases from $rc_file"
  fi
done

# ─── 11. Clean up empty directories ──────────────────────────────────

for dir in hooks agents scripts commands skills templates; do
  rmdir "$CLAUDE_DIR/$dir" 2>/dev/null && echo "  Removed empty dir: $dir" || true
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Uninstall complete."
echo ""
echo "Preserved:"
echo "  - ~/.claude/corrections/ (user data)"
echo "  - ~/.claude/CLAUDE.md (may contain user content + auto-promoted rules)"
echo "  - ~/.claude/orchestrator-settings.json (user overrides)"
echo "  - ~/.claude/settings.json (env, permissions — hooks/statusLine removed)"
echo "  - Skills/agents/hooks not shipped by this repo"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
