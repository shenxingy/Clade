#!/usr/bin/env bash
# regen-mcp-package.sh — regenerate mcp-package/skills/ from configs/skills/
#
# mcp-package/skills/ is a DERIVED copy: the clade-mcp PyPI package bundles a
# curated subset of configs/skills/ (force-included into the wheel as
# clade_mcp/skills by mcp-package/pyproject.toml). The curation manifest is
# mcp-package/skills.list — one skill directory name per line.
#
# Usage:
#   configs/scripts/regen-mcp-package.sh [DEST_DIR]
#
#   DEST_DIR defaults to <repo>/mcp-package/skills. CI passes a tmpdir and
#   diffs it against the committed copy to detect drift.
#
# Behavior:
#   - rsync -a --delete per listed skill (full dir incl. references/ subdirs,
#     so package copies never silently lose companion files)
#   - removes committed skill dirs that are no longer in the manifest
#   - fails loudly on manifest entries missing from configs/skills/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="$ROOT/mcp-package/skills.list"
SRC_DIR="$ROOT/configs/skills"
DEST_DIR="${1:-$ROOT/mcp-package/skills}"

if [ ! -f "$MANIFEST" ]; then
  echo "ERROR: manifest not found: $MANIFEST" >&2
  echo "       (run from a clade repo checkout — this script resolves paths" >&2
  echo "        relative to its own location, not \$PWD)" >&2
  exit 1
fi
if [ ! -d "$SRC_DIR" ]; then
  echo "ERROR: source skills dir not found: $SRC_DIR" >&2
  exit 1
fi
if ! command -v rsync >/dev/null 2>&1; then
  echo "ERROR: rsync is required" >&2
  exit 1
fi

# Read manifest, skipping blank lines and comments
SKILLS=()
while IFS= read -r line; do
  line="${line%%#*}"
  line="$(echo "$line" | tr -d '[:space:]')"
  [ -n "$line" ] && SKILLS+=("$line")
done < "$MANIFEST"

if [ "${#SKILLS[@]}" -eq 0 ]; then
  echo "ERROR: manifest is empty: $MANIFEST" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"

# Sync each listed skill — --delete prunes files removed upstream
for skill in "${SKILLS[@]}"; do
  if [ ! -d "$SRC_DIR/$skill" ]; then
    echo "ERROR: manifest entry '$skill' has no source dir at $SRC_DIR/$skill" >&2
    exit 1
  fi
  rsync -a --delete "$SRC_DIR/$skill/" "$DEST_DIR/$skill/"
done

# Remove skill dirs present in dest but absent from the manifest
for dest_path in "$DEST_DIR"/*/; do
  [ -d "$dest_path" ] || continue
  name="$(basename "$dest_path")"
  keep=0
  for skill in "${SKILLS[@]}"; do
    if [ "$skill" = "$name" ]; then keep=1; break; fi
  done
  if [ "$keep" -eq 0 ]; then
    echo "removing unlisted skill dir: $name"
    rm -rf "$dest_path"
  fi
done

echo "regenerated ${#SKILLS[@]} skill(s) into $DEST_DIR"
