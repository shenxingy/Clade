#!/usr/bin/env bash
# caddy-setup.sh — One-time setup: Caddy reverse proxy + HTTPS + Basic Auth
#
# Usage: ./orchestrator/caddy-setup.sh
#
# What it does:
#   1. Installs Caddy if not present
#   2. Prompts for Basic Auth credentials
#   3. Writes orchestrator/Caddyfile
#   4. Starts Caddy (or reloads if already running)
#   5. Prints DNS instructions

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CADDYFILE="$SCRIPT_DIR/Caddyfile"

# ─── Config (override via env or prompt) ──────────────────────────────────────

DOMAIN="${ORCHESTRATOR_DOMAIN:-orchestrator.alexshen.dev}"
AUTH_USER="${ORCHESTRATOR_USER:-}"
AUTH_PASS="${ORCHESTRATOR_PASS:-}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Orchestrator — Caddy Setup"
echo "Domain: $DOMAIN"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ─── 1. Install Caddy ─────────────────────────────────────────────────────────

if ! command -v caddy &>/dev/null; then
  echo "Caddy not found. Installing..."
  if command -v apt-get &>/dev/null; then
    sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl 2>/dev/null || true
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
      | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
      | sudo tee /etc/apt/sources.list.d/caddy-stable.list
    sudo apt-get update -q && sudo apt-get install -y caddy
  elif command -v brew &>/dev/null; then
    brew install caddy
  else
    echo "ERROR: Cannot auto-install Caddy. Please install manually:"
    echo "  https://caddyserver.com/docs/install"
    exit 1
  fi
  echo "  Caddy installed."
else
  echo "  Caddy $(caddy version | head -1) already installed."
fi

# ─── 2. Prompt for credentials ────────────────────────────────────────────────

echo ""
if [[ -z "$AUTH_USER" ]]; then
  read -rp "Basic Auth username [alex]: " AUTH_USER
  AUTH_USER="${AUTH_USER:-alex}"
fi

if [[ -z "$AUTH_PASS" ]]; then
  while true; do
    read -rsp "Basic Auth password: " AUTH_PASS; echo
    read -rsp "Confirm password:    " AUTH_PASS2; echo
    [[ "$AUTH_PASS" == "$AUTH_PASS2" ]] && break
    echo "Passwords don't match, try again."
  done
fi

# Hash the password using caddy's built-in hasher
echo ""
echo "Hashing password..."
HASHED=$(caddy hash-password --plaintext "$AUTH_PASS")
echo "  Done."

# ─── 3. Write Caddyfile ───────────────────────────────────────────────────────

cat > "$CADDYFILE" << EOF
$DOMAIN {
    basic_auth {
        $AUTH_USER $HASHED
    }
    reverse_proxy localhost:8765
}
EOF

echo ""
echo "Caddyfile written to: $CADDYFILE"

# ─── 4. Deploy to /etc/caddy/Caddyfile and reload via systemd ─────────────────

echo ""
echo "Deploying to /etc/caddy/Caddyfile..."
sudo cp "$CADDYFILE" /etc/caddy/Caddyfile
sudo systemctl reload caddy
echo "  Caddy reloaded."

# ─── 5. DNS instructions ──────────────────────────────────────────────────────

SERVER_IP=$(curl -sf https://api.ipify.org 2>/dev/null || echo "<your-server-ip>")

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "One step left: add a DNS record"
echo ""
echo "  Type:  A"
echo "  Name:  orchestrator"
echo "  Value: $SERVER_IP"
echo "  TTL:   300 (or Auto)"
echo ""
echo "Then run ./orchestrator/start.sh as usual."
echo "Caddy will auto-obtain a TLS cert from Let's Encrypt."
echo ""
echo "Access: https://$DOMAIN"
echo "Login:  $AUTH_USER / (your password)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
