#!/usr/bin/env bash
# scan-coverage — Generate tasks from code coverage gaps
#
# Usage: bash scan-coverage.sh [project-dir] [threshold]
#
# Analyzes test coverage reports and generates tasks for under-covered modules.
# Supports pytest (Python) and Jest (Node.js).
# Output format: ===TASK=== blocks (can append to tasks.txt)
#
# Environment:
#   COVERAGE_THRESHOLD — minimum coverage % (default: 80)
#
# Why: Systematic coverage improvement — instead of guessing which modules need tests,
# auto-detect under-covered areas and generate worker-friendly micro-tasks.

set -euo pipefail

PROJECT_DIR="${1:-.}"
COVERAGE_THRESHOLD="${COVERAGE_THRESHOLD:-80}"

if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "Error: Directory not found: $PROJECT_DIR" >&2
  exit 1
fi

cd "$PROJECT_DIR"

# Detect Python project (pytest)
if [[ -f "pyproject.toml" || -f "setup.py" || -f "requirements.txt" ]]; then
  echo "# Coverage Improvement Tasks — Python (pytest)"
  echo ""

  # Check if pytest with coverage is available
  if ! python -m pytest --version &>/dev/null; then
    echo "Warning: pytest not found. Run: pip install pytest pytest-cov" >&2
  else
    # Run coverage analysis
    python -m pytest --cov --cov-report=json .coverage-report.json 2>/dev/null || true

    if [[ -f ".coverage-report.json" ]]; then
      # Parse JSON and extract under-covered modules
      python3 <<'PYTHON_SCRIPT'
import json
import sys

THRESHOLD = int(os.environ.get('COVERAGE_THRESHOLD', '80'))

try:
  with open('.coverage-report.json', 'r') as f:
    coverage_data = json.load(f)
except:
  sys.exit(0)

files = coverage_data.get('files', {})
under_covered = []

for file_path, data in files.items():
  coverage_pct = data.get('summary', {}).get('percent_covered', 0)

  # Skip test files, __pycache__, venv
  if any(x in file_path for x in ['test_', '__pycache__', 'venv', '.venv', 'site-packages']):
    continue

  if coverage_pct < THRESHOLD:
    under_covered.append((file_path, int(coverage_pct)))

# Sort by coverage ascending (worst first)
under_covered.sort(key=lambda x: x[1])

for file_path, pct in under_covered[:10]:  # Top 10 under-covered
  module_name = file_path.replace('/', '.').replace('.py', '')
  cat_cmd = f"""cat <<'EOF'
===TASK===
model: haiku
TYPE: HORIZONTAL
source_ref: coverage_{file_path.replace('/', '_')}
---
test: improve coverage for {module_name} (current: {pct}%)

## Context
File: {file_path}
Current coverage: {pct}%
Target: 80%

## What to do
1. Review {file_path} and identify untested code paths
2. Write unit tests to cover missing paths
3. Run \`pytest --cov {file_path}\` to verify coverage improved
4. Commit with \`committer "test: add tests for {module_name}"\` when done

EOF
"""
  os.system(cat_cmd)
PYTHON_SCRIPT
      rm -f .coverage-report.json
    fi
  fi
fi

# Detect Node.js project (Jest)
if [[ -f "package.json" ]]; then
  echo "# Coverage Improvement Tasks — Node.js (Jest)"
  echo ""

  # Check if jest is available
  if command -v npm &>/dev/null && npm list jest &>/dev/null 2>&1; then
    # Run Jest coverage
    npm run test:coverage --json > .jest-coverage.json 2>/dev/null || true

    if [[ -f ".jest-coverage.json" ]]; then
      # Parse Jest coverage report
      python3 <<'NODE_SCRIPT'
import json
import sys
import os

THRESHOLD = int(os.environ.get('COVERAGE_THRESHOLD', '80'))

try:
  with open('.jest-coverage.json', 'r') as f:
    coverage_data = json.load(f)
except:
  sys.exit(0)

coverage = coverage_data.get('coverageMap', {})
under_covered = []

for file_path, file_coverage in coverage.items():
  # Skip node_modules, dist, test files
  if any(x in file_path for x in ['node_modules', 'dist', '.test.', '.spec.']):
    continue

  lines_coverage = file_coverage.get('lines', {}).get('pct', 0)

  if lines_coverage < THRESHOLD:
    under_covered.append((file_path, int(lines_coverage)))

under_covered.sort(key=lambda x: x[1])

for file_path, pct in under_covered[:10]:
  module_name = file_path.replace('/', '.').replace('.js', '').replace('.ts', '')
  print(f"""===TASK===
model: haiku
TYPE: HORIZONTAL
source_ref: coverage_{file_path.replace('/', '_')}
---
test: improve coverage for {module_name} (current: {pct}%)

## Context
File: {file_path}
Current coverage: {pct}%
Target: 80%

## What to do
1. Review {file_path} and identify untested code paths
2. Write unit tests to cover missing branches
3. Run \`npm run test:coverage -- {file_path}\` to verify
4. Commit with \`committer "test: add tests for {module_name}"\` when done

""")
NODE_SCRIPT
      rm -f .jest-coverage.json
    fi
  fi
fi

echo "# End of coverage improvement tasks"
