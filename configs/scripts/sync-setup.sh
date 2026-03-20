#!/usr/bin/env bash
# sync-setup.sh — Set up Claude Code dotfiles sync across machines
#
# Usage:
#   sync-setup.sh --nfs /path/to/shared-nfs   # NFS backend
#   sync-setup.sh --github                     # GitHub private repo backend
#   sync-setup.sh --skip                       # Skip sync setup
#   sync-setup.sh                              # Auto-detect

set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
SYNC_CONFIG="$CLAUDE_DIR/.sync-config"

# ─── Parse args ──────────────────────────────────────────────────────────────

MODE="${1:-auto}"
NFS_PATH="${2:-}"

# ─── Auto-detect backend ─────────────────────────────────────────────────────

if [[ "$MODE" == "auto" ]]; then
  if [[ -d "$HOME/shared-nfs" ]]; then
    MODE="--nfs"
    NFS_PATH="$HOME/shared-nfs"
    echo "Auto-detected NFS at $NFS_PATH"
  elif command -v gh &>/dev/null && gh auth status &>/dev/null 2>&1; then
    MODE="--github"
    echo "Auto-detected gh CLI — using GitHub backend"
  else
    echo "No sync backend detected (no NFS, no gh CLI)."
    echo "  To use GitHub: install gh CLI and run 'gh auth login', then re-run with --github"
    echo "  To use NFS:    re-run with --nfs /path/to/shared-nfs"
    echo "Skipping sync setup."
    exit 0
  fi
fi

[[ "$MODE" == "--skip" ]] && echo "Sync setup skipped." && exit 0

# ─── Determine SYNC_DIR ──────────────────────────────────────────────────────

SYNC_DIR=""
SYNC_BACKEND=""
SYNC_REPO_URL=""

if [[ "$MODE" == "--nfs" ]]; then
  [[ -z "$NFS_PATH" ]] && echo "ERROR: --nfs requires a path argument" && exit 1
  [[ ! -d "$NFS_PATH" ]] && echo "ERROR: NFS path does not exist: $NFS_PATH" && exit 1
  SYNC_DIR="$NFS_PATH/claude-dotfiles"
  SYNC_BACKEND="nfs"
  # Also set up GitHub remote as backup if gh is available
  if command -v gh &>/dev/null && gh auth status &>/dev/null 2>&1; then
    GITHUB_USER=$(gh api user --jq .login 2>/dev/null)
    SYNC_REPO_URL="git@github.com:$GITHUB_USER/claude-dotfiles.git"
    echo "  Also configuring GitHub backup: github.com/$GITHUB_USER/claude-dotfiles"
    if ! gh repo view "$GITHUB_USER/claude-dotfiles" &>/dev/null 2>&1; then
      gh repo create "$GITHUB_USER/claude-dotfiles" \
        --private \
        --description "Claude Code dotfiles sync (skills, memory, hooks, scripts)" || true
      echo "  Created: github.com/$GITHUB_USER/claude-dotfiles"
    fi
  fi

elif [[ "$MODE" == "--github" ]]; then
  if ! command -v gh &>/dev/null; then
    echo "ERROR: gh CLI not found. Install from https://cli.github.com"
    exit 1
  fi
  if ! gh auth status &>/dev/null 2>&1; then
    echo "ERROR: gh CLI not authenticated. Run: gh auth login"
    exit 1
  fi
  GITHUB_USER=$(gh api user --jq .login 2>/dev/null)
  REPO_NAME="claude-dotfiles"
  SYNC_REPO_URL="git@github.com:$GITHUB_USER/$REPO_NAME.git"
  SYNC_DIR="$HOME/claude-dotfiles"
  SYNC_BACKEND="github"

  # Create GitHub repo if it doesn't exist
  if ! gh repo view "$GITHUB_USER/$REPO_NAME" &>/dev/null 2>&1; then
    echo "Creating private GitHub repo: $GITHUB_USER/$REPO_NAME ..."
    gh repo create "$GITHUB_USER/$REPO_NAME" \
      --private \
      --description "Claude Code dotfiles sync (skills, memory, hooks, scripts)"
    echo "  Created: github.com/$GITHUB_USER/$REPO_NAME"
  else
    echo "  Found existing repo: github.com/$GITHUB_USER/$REPO_NAME"
  fi

  # Clone or pull
  if [[ -d "$SYNC_DIR/.git" ]]; then
    echo "  Updating existing clone at $SYNC_DIR ..."
    git -C "$SYNC_DIR" pull --rebase --autostash --quiet 2>/dev/null || true
  elif [[ ! -d "$SYNC_DIR" ]]; then
    echo "  Cloning to $SYNC_DIR ..."
    git clone "$SYNC_REPO_URL" "$SYNC_DIR" 2>/dev/null || {
      # Repo exists but is empty (just created)
      mkdir -p "$SYNC_DIR"
      git -C "$SYNC_DIR" init
      git -C "$SYNC_DIR" remote add origin "$SYNC_REPO_URL"
    }
  fi
fi

# ─── Initialize SYNC_DIR structure ───────────────────────────────────────────

echo "Initializing sync directory at $SYNC_DIR ..."
mkdir -p "$SYNC_DIR"/{skills,memory,hooks,hooks/lib,scripts,corrections,projects-memory}

# Init git repo in SYNC_DIR if not already
if [[ ! -d "$SYNC_DIR/.git" ]]; then
  git -C "$SYNC_DIR" init --quiet
fi
# Add/update GitHub remote if we have a URL
if [[ -n "$SYNC_REPO_URL" ]]; then
  git -C "$SYNC_DIR" remote add origin "$SYNC_REPO_URL" 2>/dev/null || \
  git -C "$SYNC_DIR" remote set-url origin "$SYNC_REPO_URL" 2>/dev/null || true
fi

# ─── Migrate existing ~/.claude content into SYNC_DIR ────────────────────────

migrate_dir() {
  local src="$CLAUDE_DIR/$1"
  local dst="$SYNC_DIR/$1"
  # If src is a real directory (not a symlink), migrate contents
  if [[ -d "$src" && ! -L "$src" ]]; then
    cp -rn "$src/." "$dst/" 2>/dev/null || true
    echo "  Migrated $1/ → sync"
  fi
}

migrate_dir skills
migrate_dir memory
migrate_dir hooks
migrate_dir scripts
migrate_dir corrections

# ─── Create symlinks ─────────────────────────────────────────────────────────

echo "Creating symlinks ~/.claude/* → $SYNC_DIR/ ..."

make_symlink() {
  local name="$1"
  local src="$CLAUDE_DIR/$name"
  local dst="$SYNC_DIR/$name"
  # Remove existing real directory (already migrated above)
  if [[ -d "$src" && ! -L "$src" ]]; then
    rm -rf "$src"
  fi
  ln -sfn "$dst" "$src"
  echo "  ~/.claude/$name → $SYNC_DIR/$name"
}

make_symlink skills
make_symlink memory
make_symlink hooks
make_symlink scripts
make_symlink corrections

# ─── Write .sync-config ──────────────────────────────────────────────────────

cat > "$SYNC_CONFIG" << EOF
# Claude Code sync config — generated by sync-setup.sh
SYNC_BACKEND=$SYNC_BACKEND
SYNC_DIR=$SYNC_DIR
SYNC_REPO_URL=$SYNC_REPO_URL
EOF

echo "  Written $SYNC_CONFIG"

# ─── Initial commit + push ───────────────────────────────────────────────────

cd "$SYNC_DIR"
if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
  git add -A
  git commit -m "init: claude dotfiles sync from $(hostname)" --quiet
  if [[ -n "$SYNC_REPO_URL" ]]; then
    git push -u origin main --quiet 2>/dev/null || \
    git push -u origin master --quiet 2>/dev/null || true
  fi
  echo "  Initial commit pushed"
fi

# ─── Set up project memory symlinks for existing local projects ──────────────

"$(dirname "$0")/sync-link-projects.sh" 2>/dev/null || true

# ─── Done ────────────────────────────────────────────────────────────────────

echo ""
echo "✓ Sync configured (backend: $SYNC_BACKEND)"
echo "  Sync dir: $SYNC_DIR"
echo "  Memory, skills, hooks, scripts auto-sync across machines"
[[ -n "$SYNC_REPO_URL" ]] && echo "  GitHub backup: $SYNC_REPO_URL" || true
