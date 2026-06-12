#!/usr/bin/env bash
# scan-deps — Generate tasks from outdated dependencies
#
# Usage: bash scan-deps.sh [project-dir] [max-tasks]
#
# Detects outdated packages and generates update tasks.
# Supports Python (pip) and Node.js (npm/yarn).
# Filters to minor/patch updates only (skips major version bumps).
# Output format: ===TASK=== blocks (can append to tasks.txt)
#
# Why: Proactive dependency maintenance — instead of letting deps rot,
# auto-generate update tasks and let workers verify compatibility.

set -euo pipefail

PROJECT_DIR="${1:-.}"
MAX_TASKS="${2:-10}"

if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "Error: Directory not found: $PROJECT_DIR" >&2
  exit 1
fi

cd "$PROJECT_DIR"

TASK_COUNT=0

# Scan Python dependencies
if [[ -f "pyproject.toml" || -f "setup.py" || -f "requirements.txt" ]]; then
  echo "# Dependency Update Tasks — Python"
  echo ""

  if ! command -v pip &>/dev/null; then
    echo "Warning: pip not found" >&2
  else
    # Get outdated packages as JSON
    OUTDATED=$(pip list --outdated --format=json 2>/dev/null || echo "[]")

    if [[ "$OUTDATED" != "[]" ]]; then
      # Export BEFORE the heredoc runs — the script reads these from env.
      # (A previous copy ran an identical heredoc before this export: it
      # always saw OUTDATED_JSON='[]' and emitted nothing — dead code.)
      export OUTDATED_JSON="$OUTDATED"
      export MAX_TASKS="$MAX_TASKS"

      python3 <<'PYTHON_EXEC'
import json
import os

MAX_TASKS = int(os.environ.get('MAX_TASKS', 10))
OUTDATED_JSON = os.environ.get('OUTDATED_JSON', '[]')

try:
  packages = json.loads(OUTDATED_JSON)
except:
  import sys
  sys.exit(0)

task_count = 0

for pkg in packages:
  if task_count >= MAX_TASKS:
    break

  name = pkg.get('name', '')
  current = pkg.get('version', '')
  latest = pkg.get('latest_version', '')

  if not name or not current or not latest:
    continue

  # Parse versions: skip major bumps
  try:
    current_parts = current.split('.')
    latest_parts = latest.split('.')
    current_major = int(current_parts[0]) if current_parts else 0
    latest_major = int(latest_parts[0]) if latest_parts else 0

    if current_major != latest_major:
      continue
  except:
    continue

  print(f"""===TASK===
model: haiku
TYPE: HORIZONTAL
source_ref: dep_python_{name}
---
chore: upgrade {name} {current} → {latest}

## Context
Current version: {current}
Latest version: {latest}

## What to do
1. Update {name}: `pip install --upgrade {name}=={latest}`
2. Run tests to verify compatibility
3. Update requirements.txt or pyproject.toml
4. Commit with `committer "chore: upgrade {name} {current} → {latest}"` when done
5. If the upgrade exposes a bug in {name} itself: dependency-bug doctrine (/investigate Phase 6b) — minimal repro, then upstream patch > pin with linked issue > documented workaround. Never a silent workaround.

""")
  task_count += 1
PYTHON_EXEC
    fi
  fi
fi

# Scan Node.js dependencies
if [[ -f "package.json" ]]; then
  echo "# Dependency Update Tasks — Node.js"
  echo ""

  if ! command -v npm &>/dev/null; then
    echo "Warning: npm not found" >&2
  else
    # Get outdated packages as JSON. npm outdated exits 1 when packages ARE
    # outdated — '|| echo "{}"' would APPEND {} to the valid JSON and break
    # the parse, so capture first and only fall back when output is empty.
    OUTDATED_JSON=$(npm outdated --json 2>/dev/null) || true
    [[ -z "$OUTDATED_JSON" ]] && OUTDATED_JSON="{}"

    if [[ "$OUTDATED_JSON" != "{}" ]]; then
      # Export BEFORE the heredoc — without it the script reads env default
      # '{}' and emits nothing on npm-only projects (pip branch never ran).
      export OUTDATED_JSON
      export MAX_TASKS

      python3 <<'NODE_SCRIPT'
import json
import os

MAX_TASKS = int(os.environ.get('MAX_TASKS', 10))
OUTDATED_JSON = os.environ.get('OUTDATED_JSON', '{}')

try:
  packages = json.loads(OUTDATED_JSON)
except:
  import sys
  sys.exit(0)

task_count = 0

for name, pkg_info in packages.items():
  if task_count >= MAX_TASKS:
    break

  current = pkg_info.get('current', '')
  latest = pkg_info.get('latest', '')
  wanted = pkg_info.get('wanted', '')

  if not current or not latest:
    continue

  # Prefer "wanted" over "latest" for npm
  target_version = wanted or latest

  # Skip major bumps
  try:
    current_major = int(current.split('.')[0])
    target_major = int(target_version.split('.')[0])
    if current_major != target_major:
      continue
  except:
    continue

  print(f"""===TASK===
model: haiku
TYPE: HORIZONTAL
source_ref: dep_node_{name}
---
chore: upgrade {name} {current} → {target_version}

## Context
Current version: {current}
Latest version: {latest}
Wanted version: {wanted}

## What to do
1. Update {name}: `npm install {name}@{target_version}`
2. Run tests to verify compatibility
3. Verify package-lock.json is updated
4. Commit with `committer "chore: upgrade {name} {current} → {target_version}"` when done
5. If the upgrade exposes a bug in {name} itself: dependency-bug doctrine (/investigate Phase 6b) — minimal repro, then upstream patch > pin with linked issue > documented workaround. Never a silent workaround.

""")
  task_count += 1
NODE_SCRIPT
    fi
  fi
fi

echo "# End of dependency update tasks"
