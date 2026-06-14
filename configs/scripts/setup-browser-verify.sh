#!/usr/bin/env bash
# setup-browser-verify.sh — enable end-to-end browser verification for a project.
#
# Wires the Microsoft Playwright MCP (@playwright/mcp) into <project>/.claude/mcp.json
# — the config that BOTH orchestrator worker spawns (worker.py) and the /verify
# skill (start.sh) already load via --mcp-config. Once enabled, /verify's
# "UI Interaction" strategy fires: navigate the running app, snapshot pages,
# click/fill, and flag console errors / broken flows as real end-to-end evidence.
#
# Usage:
#   setup-browser-verify.sh [project_dir]            # enable (merge config + install chromium)
#   setup-browser-verify.sh [project_dir] --no-install  # config only (CI / tests)
#   setup-browser-verify.sh [project_dir] --remove      # disable (drop the playwright entry)
#
# Idempotent: re-running is safe and preserves any other MCP servers in the file.
set -euo pipefail

PROJECT_DIR="."
NO_INSTALL=0
REMOVE=0
for arg in "$@"; do
  case "$arg" in
    --no-install) NO_INSTALL=1 ;;
    --remove)     REMOVE=1 ;;
    -*)           echo "Unknown flag: $arg" >&2; exit 2 ;;
    *)            PROJECT_DIR="$arg" ;;
  esac
done

PROJECT_DIR="$(cd "$PROJECT_DIR" 2>/dev/null && pwd)" || { echo "No such dir: $PROJECT_DIR" >&2; exit 1; }
MCP_FILE="$PROJECT_DIR/.claude/mcp.json"
mkdir -p "$PROJECT_DIR/.claude"

# Merge/remove the 'playwright' server with a robust JSON edit (python3, no jq dep).
PROJECT_DIR="$PROJECT_DIR" MCP_FILE="$MCP_FILE" REMOVE="$REMOVE" python3 <<'PY'
import json, os
mcp_file = os.environ["MCP_FILE"]
remove = os.environ["REMOVE"] == "1"
try:
    with open(mcp_file) as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        data = {}
except (FileNotFoundError, json.JSONDecodeError):
    data = {}
servers = data.setdefault("mcpServers", {})
if remove:
    servers.pop("playwright", None)
    action = "removed"
else:
    servers["playwright"] = {
        "command": "npx",
        # --headless: unattended workers; --isolated: no profile state carried
        # between runs, so every verification starts from a clean browser.
        "args": ["-y", "@playwright/mcp@latest", "--headless", "--isolated"],
    }
    action = "enabled"
with open(mcp_file, "w") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
print(f"  Playwright MCP {action} in {mcp_file}")
print(f"  servers now: {', '.join(sorted(servers)) or '(none)'}")
PY

if [[ "$REMOVE" == "1" ]]; then
  echo "✓ Browser verification disabled for $PROJECT_DIR"
  exit 0
fi

if [[ "$NO_INSTALL" == "0" ]]; then
  if command -v npx >/dev/null 2>&1; then
    echo "  Installing Chromium browser binary (npx playwright install chromium)…"
    npx -y playwright install chromium || {
      echo "⚠ Chromium install failed — run 'npx playwright install chromium' manually." >&2
    }
  else
    echo "⚠ npx not found (Node required). Install Node, then run 'npx playwright install chromium'." >&2
  fi
fi

echo "✓ Browser verification enabled for $PROJECT_DIR"
echo "  /verify's UI Interaction strategy will now run against the project's frontend."
