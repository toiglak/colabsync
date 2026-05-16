#!/usr/bin/env bash
# colab-hook.sh — run this inside a Google Colab cell to start colabsync.
#
# Usage (in a Colab code cell):
#   !curl -fsSL https://raw.githubusercontent.com/toiglak/colabsync/main/scripts/colab-hook.sh | bash
#
# What it does:
#   1. Installs cloudflared (Cloudflare's tunnel client).
#   2. Installs colabsync server-side via uv/pip.
#   3. Generates a shared secret.
#   4. Starts the colabsync WebSocket server on localhost.
#   5. Opens a Cloudflare Quick Tunnel and captures the public URL.
#   6. Prints a join link for the local `colabsync` CLI.
#
# Then, on your local machine:
#   colabsync <join-link>

set -euo pipefail

COLABSYNC_PORT="${COLABSYNC_PORT:-8765}"
COLABSYNC_DEST="${COLABSYNC_DEST:-/content}"
COLABSYNC_VERSION="${COLABSYNC_VERSION:-0.1.0}"

# ---------------------------------------------------------------------------
# 1. Install cloudflared
# ---------------------------------------------------------------------------
if ! command -v cloudflared &>/dev/null; then
  echo "[colabsync] installing cloudflared..."
  sudo mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
    | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] \
https://pkg.cloudflare.com/cloudflared any main" \
    | sudo tee /etc/apt/sources.list.d/cloudflared.list
  sudo apt-get update -qq && sudo apt-get install -y -qq cloudflared
fi

# ---------------------------------------------------------------------------
# 2. Install colabsync (Python package, server side only)
# ---------------------------------------------------------------------------
if ! command -v uv &>/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

uv tool install "colabsync==${COLABSYNC_VERSION}" --quiet 2>/dev/null \
  || uv tool install "git+https://github.com/toiglak/colabsync.git" --quiet

# ---------------------------------------------------------------------------
# 3. Generate a shared secret
# ---------------------------------------------------------------------------
SECRET_HEX=$(python3 -c "import os; print(os.urandom(32).hex())")

# ---------------------------------------------------------------------------
# 4. Start the colabsync server in the background
# ---------------------------------------------------------------------------
echo "[colabsync] starting server on port ${COLABSYNC_PORT}, dest=${COLABSYNC_DEST}"
COLABSYNC_SECRET="$SECRET_HEX" \
  colabsync-server \
    --port "$COLABSYNC_PORT" \
    --dest "$COLABSYNC_DEST" \
  &>/tmp/colabsync-server.log &
SERVER_PID=$!
sleep 1

if ! kill -0 "$SERVER_PID" 2>/dev/null; then
  echo "[colabsync] server failed to start. Log:" >&2
  cat /tmp/colabsync-server.log >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 5. Open a Cloudflare Quick Tunnel
# ---------------------------------------------------------------------------
echo "[colabsync] opening tunnel..."
cloudflared tunnel --url "http://localhost:${COLABSYNC_PORT}" \
  &>/tmp/colabsync-tunnel.log &
TUNNEL_PID=$!

# Wait for the tunnel URL to appear in the log
TUNNEL_URL=""
for i in $(seq 1 30); do
  TUNNEL_URL=$(grep -oP 'https://[a-z0-9\-]+\.trycloudflare\.com' /tmp/colabsync-tunnel.log 2>/dev/null | head -1 || true)
  if [[ -n "$TUNNEL_URL" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$TUNNEL_URL" ]]; then
  echo "[colabsync] failed to get tunnel URL. Log:" >&2
  cat /tmp/colabsync-tunnel.log >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 6. Encode and print the join link
# ---------------------------------------------------------------------------
JOIN_LINK=$(python3 - <<EOF
import base64, sys
url = "${TUNNEL_URL}"
secret = "${SECRET_HEX}"
payload = f"{url}\n{secret}".encode()
b64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
print("cs1_" + b64)
EOF
)

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║              colabsync is ready                      ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Run this on your local machine:                     ║"
echo "║                                                      ║"
echo "║  colabsync ${JOIN_LINK}"
echo "║                                                      ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "[colabsync] server PID=$SERVER_PID  tunnel PID=$TUNNEL_PID"
echo "[colabsync] dest: ${COLABSYNC_DEST}"
