#!/usr/bin/env bash
# PA — Raspberry Pi 5 deployment script
# Run on the Pi after cloning the repo: bash deploy/setup-pi.sh
set -euo pipefail

APP_DIR="${PA_DIR:-$HOME/pa}"
VENV_DIR="$APP_DIR/.venv"
DATA_DIR="$APP_DIR/data"
SERVICE_NAME="pa"

echo "=== PA Deployment Setup ==="
echo "App dir:  $APP_DIR"
echo "Venv dir: $VENV_DIR"
echo ""

# --- System dependencies ---
echo "[1/6] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 python3-pip python3-venv \
    sqlcipher libsqlcipher-dev \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libnspr4 libnss3 \
    git

# --- Python venv ---
echo "[2/6] Creating Python virtual environment..."
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "[3/6] Installing Python dependencies..."
pip install --upgrade pip -q
pip install -e "$APP_DIR[dev]" -q

# --- Playwright ---
echo "[4/6] Installing Playwright Chromium..."
python -m playwright install chromium
python -m playwright install-deps chromium

# --- Data directory ---
echo "[5/6] Creating data directory..."
mkdir -p "$DATA_DIR"
chmod 700 "$DATA_DIR"

# --- Config files ---
if [ ! -f "$APP_DIR/config.json" ]; then
    echo "    Creating config.json from template..."
    cp "$APP_DIR/config.example.json" "$APP_DIR/config.json"
    echo "    >> Edit config.json with your telegram_user_id and preferences"
fi

if [ ! -f "$APP_DIR/.env" ]; then
    echo "    Creating .env from template..."
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo "    >> Edit .env with your API keys"
fi

# --- Systemd service ---
echo "[6/6] Installing systemd service..."
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<UNIT
[Unit]
Description=PA Personal Financial Assistant
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$VENV_DIR/bin/python -m pa
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$DATA_DIR
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}

echo ""
echo "=== Setup complete ==="
echo ""
echo "Before starting PA:"
echo "  1. Edit $APP_DIR/config.json  — set telegram_user_id, goals, income"
echo "  2. Edit $APP_DIR/.env         — set PA_TELEGRAM_TOKEN and PA_CLAUDE_API_KEY"
echo ""
echo "Then start:"
echo "  sudo systemctl start pa"
echo ""
echo "Check logs:"
echo "  journalctl -u pa -f"
echo ""
echo "Run tests:"
echo "  source $VENV_DIR/bin/activate && python -m pytest"
