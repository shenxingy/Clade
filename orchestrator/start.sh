#!/usr/bin/env bash
# start.sh — Launch the Claude Code Orchestrator Web UI
#
# Usage: ./orchestrator/start.sh [--port PORT]
# Default port: 8765

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
PORT="${ORCHESTRATOR_PORT:-8765}"
# Project dir: must be set explicitly via --project or ORCHESTRATOR_PROJECT_DIR.
# No default — users pick a project from the UI when none is specified.
PROJECT_DIR="${ORCHESTRATOR_PROJECT_DIR:-}"

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)    PORT="$2"; shift 2 ;;
    --project) PROJECT_DIR="$(cd "$2" && pwd)"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

# ─── Check python ─────────────────────────────────────────────────────────────

if ! command -v python3 &>/dev/null; then
  echo "Error: python3 not found. Please install Python 3.9+."
  exit 1
fi

if ! command -v claude &>/dev/null && ! command -v cc &>/dev/null; then
  echo "Warning: claude CLI not found in PATH."
  echo "Make sure 'claude' or 'cc' is available before using the orchestrator."
fi

# ─── Set up venv (uv preferred, python3 fallback) ────────────────────────────

echo "Checking Python dependencies..."

if [[ ! -d "$VENV_DIR" ]]; then
  if command -v uv &>/dev/null; then
    uv venv "$VENV_DIR" --quiet
  else
    python3 -m venv "$VENV_DIR"
  fi
fi

if ! "$VENV_DIR/bin/python" -c "import fastapi, uvicorn, ptyprocess, watchfiles" 2>/dev/null; then
  echo "Installing dependencies..."
  if command -v uv &>/dev/null; then
    uv pip install -r "$SCRIPT_DIR/requirements.txt" --python "$VENV_DIR" --quiet
  else
    "$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" --quiet
  fi
  echo "  Done."
else
  echo "  All dependencies present."
fi

# ─── Start server ─────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Claude Code Orchestrator"
if [[ -n "$PROJECT_DIR" ]]; then
  echo "Project: $PROJECT_DIR"
else
  echo "Project: (none — pick one via the + button)"
fi
echo "URL: http://localhost:$PORT"
echo "Press Ctrl+C to stop."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Open browser after a short delay
(sleep 1.5 && python3 -m webbrowser "http://localhost:$PORT") &
BROWSER_PID=$!

cleanup() {
  echo ""
  echo "Shutting down orchestrator..."
  kill "$BROWSER_PID" 2>/dev/null || true
  exit 0
}
trap cleanup SIGINT SIGTERM

cd "$SCRIPT_DIR"

# Detect Tailscale IP for direct access from other devices
TAILSCALE_IP=""
if command -v tailscale &>/dev/null; then
  TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || true)
fi

if [[ -n "$TAILSCALE_IP" ]]; then
  BIND_HOST="0.0.0.0"
  echo "Tailscale detected: http://${TAILSCALE_IP}:${PORT}"
  echo "(accessible from any device on your Tailscale network)"
else
  BIND_HOST="127.0.0.1"
fi
echo ""

if [[ -n "$PROJECT_DIR" ]]; then
  export ORCHESTRATOR_PROJECT_DIR="$PROJECT_DIR"
fi
"$VENV_DIR/bin/uvicorn" server:app --port "$PORT" --host "$BIND_HOST"
