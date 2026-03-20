#!/usr/bin/env bash
# Push PA code to Raspberry Pi via SSH
# Usage: bash deploy/push-to-pi.sh [user@host] [remote_dir]
set -euo pipefail

PI_HOST="${1:-pi@raspberrypi.local}"
REMOTE_DIR="${2:-~/pa}"

echo "Pushing to $PI_HOST:$REMOTE_DIR ..."

# Sync code (excludes secrets, venv, caches)
rsync -avz --delete \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude 'data/' \
    --exclude '.env' \
    --exclude 'config.json' \
    --exclude 'vault.enc' \
    --exclude '*.db' \
    --exclude '*.key' \
    --exclude '.git/' \
    --exclude '.claude/' \
    --exclude 'logs/' \
    ./ "$PI_HOST:$REMOTE_DIR/"

echo "Restarting PA service..."
ssh "$PI_HOST" "sudo systemctl restart pa"

echo "Done. Check logs: ssh $PI_HOST journalctl -u pa -f"
