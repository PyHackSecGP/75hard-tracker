#!/bin/bash
# Deploy 75 Hard tracker to Proxmox host via Tailscale SSH
# Usage: ./deploy.sh
set -e

REMOTE="root@100.69.90.117"
SSH_OPTS="-p 2222"
REMOTE_DIR="/opt/75hard"

echo "==> Syncing files to Proxmox..."
ssh $SSH_OPTS "$REMOTE" "mkdir -p $REMOTE_DIR/templates $REMOTE_DIR/static $REMOTE_DIR/data"
rsync -az -e "ssh $SSH_OPTS" --exclude=__pycache__ --exclude="*.pyc" \
    app.py requirements.txt templates static \
    "$REMOTE:$REMOTE_DIR/"

echo "==> Installing Python dependencies..."
ssh $SSH_OPTS "$REMOTE" "apt-get install -y -q python3-pip 2>/dev/null; pip3 install -q --break-system-packages -r $REMOTE_DIR/requirements.txt"

echo "==> Installing systemd service..."
scp -P 2222 75hard.service "$REMOTE:/etc/systemd/system/75hard.service"
ssh $SSH_OPTS "$REMOTE" "systemctl daemon-reload && systemctl enable 75hard && systemctl restart 75hard"

echo "==> Checking service status..."
ssh $SSH_OPTS "$REMOTE" "systemctl status 75hard --no-pager -l"

echo ""
echo "Done. Access at:"
echo "  http://100.69.90.117:5757   (Tailscale)"
echo ""
echo "For public access later, run on Proxmox:"
echo "  cloudflared tunnel --url http://localhost:5757"
