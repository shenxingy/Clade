#!/usr/bin/env bash
# install.sh — Deploy Claude Code customizations to ~/.claude/
#
# Idempotent: safe to run multiple times.
# Does NOT overwrite user data (corrections/rules.md, corrections/history.jsonl).
# Merges hooks into existing settings.json without losing other fields.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Cross-platform sha256 (Linux: sha256sum, macOS: shasum -a 256)
if command -v sha256sum &>/dev/null; then
  _SHA256=(sha256sum)
else
  _SHA256=(shasum -a 256)
fi
CLAUDE_DIR="$HOME/.claude"

echo "Installing Claude Code customizations..."
echo "Source: $SCRIPT_DIR"
echo "Target: $CLAUDE_DIR"
echo ""

# ─── 1. Create directories ───────────────────────────────────────────

echo "Creating directories..."
mkdir -p "$CLAUDE_DIR"/{hooks/lib,agents,skills,scripts,corrections,commands,templates}

# ─── 2. Copy hooks (chmod +x) ────────────────────────────────────────

echo "Installing hooks..."
cp "$SCRIPT_DIR/configs/hooks/"*.sh "$CLAUDE_DIR/hooks/"
chmod +x "$CLAUDE_DIR/hooks/"*.sh
echo "  Installed: $(ls "$SCRIPT_DIR/configs/hooks/"*.sh | xargs -I{} basename {} | tr '\n' ' ')"

# Copy hook libraries
if [[ -d "$SCRIPT_DIR/configs/hooks/lib" ]]; then
  cp "$SCRIPT_DIR/configs/hooks/lib/"*.sh "$CLAUDE_DIR/hooks/lib/"
  echo "  Installed lib: $(ls "$SCRIPT_DIR/configs/hooks/lib/"*.sh | xargs -I{} basename {} | tr '\n' ' ')"
fi

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
# Also copy Python utility scripts
for f in "$SCRIPT_DIR/configs/scripts/"*.py; do
  [[ -f "$f" ]] && cp "$f" "$CLAUDE_DIR/scripts/" && chmod +x "$CLAUDE_DIR/scripts/$(basename "$f")"
done
echo "  Installed: $(ls "$SCRIPT_DIR/configs/scripts/"*.sh "$SCRIPT_DIR/configs/scripts/"*.py 2>/dev/null | xargs -I{} basename {} | tr '\n' ' ')"

# Deploy models.env (canonical model IDs)
if [[ -f "$SCRIPT_DIR/configs/models.env" ]]; then
  cp "$SCRIPT_DIR/configs/models.env" "$CLAUDE_DIR/models.env"
  echo "  Installed models.env (canonical model IDs)"
fi

# ─── 6. Copy commands ────────────────────────────────────────────────

echo "Installing commands..."
if compgen -G "$SCRIPT_DIR/configs/commands/*.md" > /dev/null 2>&1; then
  cp "$SCRIPT_DIR/configs/commands/"*.md "$CLAUDE_DIR/commands/"
  echo "  Installed: $(ls "$SCRIPT_DIR/configs/commands/"*.md | xargs -I{} basename {} | tr '\n' ' ')"
else
  echo "  (no commands to install)"
fi

# ─── 6b. Symlink committer to ~/.local/bin (for PATH access) ─────────

if [[ -f "$CLAUDE_DIR/scripts/committer.sh" ]]; then
  mkdir -p "$HOME/.local/bin"
  ln -sf "$CLAUDE_DIR/scripts/committer.sh" "$HOME/.local/bin/committer"
  echo "  Symlinked committer → ~/.local/bin/committer"
  # Remind if ~/.local/bin is not in PATH
  if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    echo "  WARNING: ~/.local/bin is not in your PATH."
    echo "  Add this to ~/.zshrc or ~/.bashrc:"
    echo '    export PATH="$HOME/.local/bin:$PATH"'
  fi
fi

if [[ -f "$CLAUDE_DIR/scripts/statusline-toggle.sh" ]]; then
  mkdir -p "$HOME/.local/bin"
  ln -sf "$CLAUDE_DIR/scripts/statusline-toggle.sh" "$HOME/.local/bin/slt"
  echo "  Symlinked statusline-toggle → ~/.local/bin/slt  (usage: slt to cycle modes)"
fi

if [[ -f "$CLAUDE_DIR/scripts/devmode.sh" ]]; then
  mkdir -p "$HOME/.local/bin"
  ln -sf "$CLAUDE_DIR/scripts/devmode.sh" "$HOME/.local/bin/devmode"
  chmod +x "$CLAUDE_DIR/scripts/devmode.sh"
  echo "  Symlinked devmode → ~/.local/bin/devmode  (usage: devmode [on|off|status])"
fi

# ─── 6c. Deploy templates ────────────────────────────────────────────

echo "Installing templates..."
if [[ -d "$SCRIPT_DIR/configs/templates" ]]; then
  cp -r "$SCRIPT_DIR/configs/templates/"* "$CLAUDE_DIR/templates/"
  echo "  Installed: $(ls "$SCRIPT_DIR/configs/templates/" | tr '\n' ' ')"
fi

# ─── 6d. Deploy + configure status line ──────────────────────────────

echo "Configuring status line..."
cp "$SCRIPT_DIR/configs/scripts/statusline-command.sh" "$CLAUDE_DIR/statusline-command.sh"
chmod +x "$CLAUDE_DIR/statusline-command.sh"
echo "  Installed statusline-command.sh"

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

  STATUSLINE='{"type":"command","command":"bash ~/.claude/statusline-command.sh"}'

  if [[ -f "$CLAUDE_DIR/settings.json" ]]; then
    # Merge: update hooks + statusLine, preserve everything else
    jq --argjson hooks "$HOOKS" --argjson sl "$STATUSLINE" \
      '.hooks = $hooks | .statusLine = $sl' \
      "$CLAUDE_DIR/settings.json" > /tmp/claude-settings-merged.json
    mv /tmp/claude-settings-merged.json "$CLAUDE_DIR/settings.json"
    echo "  Merged hooks + statusLine into existing settings.json"
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

# ─── 9. Set up shell aliases (cc + claude bypass) ────────────────────

echo "Configuring shell aliases..."

setup_alias() {
  local rc_file="$1"
  [[ -f "$rc_file" ]] || return
  if grep -q "dangerously-skip-permissions" "$rc_file" 2>/dev/null; then
    echo "  Aliases already in $rc_file — skipping"
    return
  fi
  cat >> "$rc_file" << 'SHELLEOF'

# Claude Code: skip permission prompts (added by clade)
alias claude='claude --dangerously-skip-permissions'
alias cc='claude --dangerously-skip-permissions'
SHELLEOF
  echo "  Added aliases to $rc_file"
}

setup_alias "$HOME/.zshrc"
setup_alias "$HOME/.bashrc"
echo "  Run: source ~/.zshrc  (or open a new terminal) to activate"

# ─── 10. Deploy Agent Ground Rules to ~/.claude/CLAUDE.md ────────────

GLOBAL_CLAUDE="$CLAUDE_DIR/CLAUDE.md"
TEMPLATE_CLAUDE="$SCRIPT_DIR/templates/CLAUDE.md"

if [[ -f "$TEMPLATE_CLAUDE" ]]; then
  echo "Configuring ~/.claude/CLAUDE.md..."
  if [[ ! -f "$GLOBAL_CLAUDE" ]]; then
    cp "$TEMPLATE_CLAUDE" "$GLOBAL_CLAUDE"
    echo "  Created ~/.claude/CLAUDE.md with Agent Ground Rules"
  elif ! grep -q "Agent Ground Rules" "$GLOBAL_CLAUDE" 2>/dev/null; then
    { echo ""; cat "$TEMPLATE_CLAUDE"; } >> "$GLOBAL_CLAUDE"
    echo "  Appended Agent Ground Rules to existing ~/.claude/CLAUDE.md"
  else
    echo "  ~/.claude/CLAUDE.md already has Agent Ground Rules — skipping"
  fi
fi

# ─── 11. Write staleness detection markers ───────────────────────────

echo "Writing kit version markers..."
echo "$SCRIPT_DIR" > "$CLAUDE_DIR/.kit-source-dir"
# Combined checksum of all source configs — session-context.sh and start.sh compare against this
find "$SCRIPT_DIR/configs" -type f | LC_ALL=C sort | xargs "${_SHA256[@]}" 2>/dev/null | "${_SHA256[@]}" | cut -d' ' -f1 > "$CLAUDE_DIR/.kit-checksum"
echo "  Written .kit-source-dir + .kit-checksum for stale-script detection"

# ─── 12. Summary ─────────────────────────────────────────────────────

echo ""
# ─── 13. Optional: set up sync (--sync flag) ─────────────────────────────────

for arg in "$@"; do
  if [[ "$arg" == "--sync" ]]; then
    echo ""
    echo "Setting up sync..."
    bash "$SCRIPT_DIR/configs/scripts/sync-setup.sh"
    break
  fi
  if [[ "$arg" == --sync=* ]]; then
    SYNC_BACKEND="${arg#--sync=}"
    echo ""
    echo "Setting up sync (backend: $SYNC_BACKEND)..."
    if [[ "$SYNC_BACKEND" == nfs:* ]]; then
      NFS_PATH="${SYNC_BACKEND#nfs:}"
      bash "$SCRIPT_DIR/configs/scripts/sync-setup.sh" --nfs "$NFS_PATH"
    else
      bash "$SCRIPT_DIR/configs/scripts/sync-setup.sh" "--$SYNC_BACKEND"
    fi
    break
  fi
done

# ─── 14. Sync prompt (if not already handled by --sync flag) ─────────────────

_sync_requested=false
for arg in "$@"; do
  [[ "$arg" == "--sync" || "$arg" == --sync=* ]] && _sync_requested=true && break
done

if [[ "$_sync_requested" == false && ! -f "$CLAUDE_DIR/.sync-config" ]]; then
  # Detect available backend
  _sync_available=""
  if [[ -d "$HOME/shared-nfs" ]]; then
    _sync_available="NFS detected at ~/shared-nfs"
  elif command -v gh &>/dev/null && gh auth status &>/dev/null 2>&1; then
    _sync_available="gh CLI detected"
  fi

  if [[ -n "$_sync_available" ]]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Sync available ($_sync_available)"
    echo "Enable memory + skills sync across machines? [y/N] "
    read -r _sync_reply 2>/dev/null || _sync_reply="n"
    if [[ "$_sync_reply" =~ ^[Yy]$ ]]; then
      bash "$SCRIPT_DIR/configs/scripts/sync-setup.sh"
    else
      echo "  Skipped. Run './install.sh --sync' anytime to enable."
    fi
  fi
fi

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
echo "Next steps:"
echo "  1. source ~/.zshrc   (or ~/.bashrc) to activate shell aliases"
echo "  2. Start a new Claude Code session to activate all hooks"
echo "  3. Use 'cc' to launch Claude Code in fully autonomous mode"
echo "  4. Run ./orchestrator/start.sh to open the Orchestrator Web UI"
echo ""
echo "Optional — enable memory sync across machines:"
echo "  ./install.sh --sync                       # auto-detect NFS or GitHub"
echo "  ./install.sh --sync=nfs:/path/to/nfs      # specify NFS path"
echo "  ./install.sh --sync=github                # force GitHub backend"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
