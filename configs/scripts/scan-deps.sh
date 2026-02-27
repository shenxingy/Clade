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
      python3 <<'PYTHON_SCRIPT'
import json
import re
import sys
import os

MAX_TASKS = int(os.environ.get('MAX_TASKS', 10))
OUTDATED_JSON = os.environ.get('OUTDATED_JSON', '[]')

try:
  packages = json.loads(OUTDATED_JSON)
except:
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

  # Parse versions: skip major bumps (e.g., 1.x -> 2.x)
  current_major = current.split('.')[0]
  latest_major = latest.split('.')[0]

  if current_major != latest_major:
    continue  # Skip major version updates

  print(f"""===TASK===
model: haiku
TYPE: HORIZONTAL
source_ref: dep_python_{name}
---
chore: upgrade {name} {current} → {latest}

## Context
Current version: {current}
Latest version: {latest}
Update type: {"patch" if current.split(".")[1] == latest.split(".")[1] else "minor"}

## What to do
1. Update {name}: \`pip install --upgrade {name}=={latest}\`
2. Run tests to verify compatibility
3. Update requirements.txt / pyproject.toml with new version
4. Commit with \`committer "chore: upgrade {name} {current} → {latest}"\` when done

""")
  task_count += 1
PYTHON_SCRIPT

      # Get the OUTDATED as JSON
      export OUTDATED_JSON="$OUTDATED"
      export MAX_TASKS="$MAX_TASKS"

      # Re-run Python script with env
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
1. Update {name}: \`pip install --upgrade {name}=={latest}\`
2. Run tests to verify compatibility
3. Update requirements.txt or pyproject.toml
4. Commit with \`committer "chore: upgrade {name} {current} → {latest}"\` when done

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
    # Get outdated packages as JSON
    OUTDATED_JSON=$(npm outdated --json 2>/dev/null || echo "{}")

    if [[ "$OUTDATED_JSON" != "{}" ]]; then
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
1. Update {name}: \`npm install {name}@{target_version}\`
2. Run tests to verify compatibility
3. Verify package-lock.json is updated
4. Commit with \`committer "chore: upgrade {name} {current} → {target_version}"\` when done

""")
  task_count += 1
NODE_SCRIPT
    fi
  fi
fi

echo "# End of dependency update tasks"
