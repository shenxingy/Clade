#!/usr/bin/env bash
# Assert the Claude Code plugin RESOLVES the components it ships.
#
# `claude plugin validate . --strict` checks the manifest against a schema. It
# does not load the plugin, so it is blind to a manifest that is schema-valid
# and resolves nothing. This repo shipped exactly that for an unknown length of
# time: `"agents": ["./configs/agents/a.md", ...]` is a valid field with valid
# paths, and the loader resolved Agents (0) from it while the description
# advertised 37. Only `plugin details` — which actually loads — can see that.
#
# Gate: every agent definition under configs/agents/ must appear in the loaded
# component inventory. Run it locally with the claude CLI on PATH.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if ! command -v claude >/dev/null 2>&1; then
  echo "check-cc-plugin-components: claude CLI not on PATH" >&2
  echo "  This gate must not degrade to a skip — a skipped load reports green" >&2
  echo "  on a plugin that resolves nothing, exactly as convincingly as a pass." >&2
  exit 1
fi

expected_agents=$(find configs/agents -maxdepth 1 -name '*.md' | wc -l | tr -d ' ')

details=$(claude --plugin-dir . plugin details clade 2>&1) || {
  echo "check-cc-plugin-components: the plugin failed to LOAD" >&2
  echo "$details" >&2
  exit 1
}

read_count() {
  # "  Agents (37)  name, name, ..." -> 37 ; absent section -> 0
  printf '%s\n' "$details" | sed -n "s/^[[:space:]]*$1 (\([0-9]\+\)).*/\1/p" | head -1
}

actual_agents=$(read_count Agents)
actual_skills=$(read_count Skills)
: "${actual_agents:=0}"
: "${actual_skills:=0}"

status=0

if [[ "$actual_agents" != "$expected_agents" ]]; then
  echo "check-cc-plugin-components: agents resolved=$actual_agents expected=$expected_agents" >&2
  echo "  configs/agents/ holds $expected_agents definitions the loader did not resolve." >&2
  echo "  Fix: python3 configs/scripts/regen-cc-plugin.py (then commit agents/)" >&2
  status=1
fi

if [[ "$actual_skills" -eq 0 ]]; then
  echo "check-cc-plugin-components: skills resolved=0" >&2
  status=1
fi

# The description is generated from the tree, so it must not claim components
# the load did not produce. "hooks" is the specific lie this gate was born from.
description=$(python3 -c 'import json;print(json.load(open(".claude-plugin/plugin.json"))["description"])')
actual_hooks=$(read_count Hooks)
: "${actual_hooks:=0}"
if [[ "$actual_hooks" -eq 0 ]] && printf '%s' "$description" | grep -qiE '[0-9]+ hooks'; then
  echo "check-cc-plugin-components: description advertises hooks but the loader resolved 0" >&2
  echo "  description: $description" >&2
  status=1
fi

if [[ $status -eq 0 ]]; then
  echo "check-cc-plugin-components: skills=$actual_skills agents=$actual_agents hooks=$actual_hooks ✓"
fi

exit "$status"
