#!/bin/bash
# Deploy 75 Hard tracker to Proxmox host via Tailscale SSH.
#
# Uses the ``proxmox`` SSH alias (configured in ~/.ssh/config) which maps to
# tony@<proxmox-host>:<port>. Elevates with ``sudo`` for root-owned paths.
#
# Env for brain CouchDB write-through (optional; required for vault sync):
#   BRAIN_PASS       — CouchDB password for brain-admin (REQUIRED to enable sync)
#   BRAIN_URL        — defaults to https://brain.taila06bcc.ts.net
#   BRAIN_RESOLVE_IP — defaults to <brain-lxc-ip>
#   BRAIN_DB         — defaults to obsidian_brain
#   BRAIN_USER       — defaults to brain-admin
set -e

REMOTE_HOST="proxmox"
REMOTE_DIR="/opt/75hard"
STAGE_DIR="/tmp/75hard-stage"
ENV_FILE_REMOTE="/etc/75hard/env"

BRAIN_URL="${BRAIN_URL:-https://brain.taila06bcc.ts.net}"
BRAIN_RESOLVE_IP="${BRAIN_RESOLVE_IP:-}"
BRAIN_DB="${BRAIN_DB:-obsidian_brain}"
BRAIN_USER="${BRAIN_USER:-brain-admin}"

if [ -z "${BRAIN_PASS:-}" ] && [ -f "$HOME/projects/brain/state/couchdb_password.txt" ]; then
    BRAIN_PASS="$(cat "$HOME/projects/brain/state/couchdb_password.txt")"
fi

echo "==> Staging files on remote ($STAGE_DIR)..."
ssh "$REMOTE_HOST" "rm -rf $STAGE_DIR && mkdir -p $STAGE_DIR"
rsync -az --exclude=__pycache__ --exclude="*.pyc" \
    app.py tasks.py vault_sync.py requirements.txt templates static \
    "$REMOTE_HOST:$STAGE_DIR/"

echo "==> Moving staged files to $REMOTE_DIR (requires sudo)..."
ssh "$REMOTE_HOST" "sudo mkdir -p $REMOTE_DIR/templates $REMOTE_DIR/static $REMOTE_DIR/data /etc/75hard && \
    sudo cp -r $STAGE_DIR/app.py $STAGE_DIR/tasks.py $STAGE_DIR/vault_sync.py $STAGE_DIR/requirements.txt $REMOTE_DIR/ && \
    sudo cp -r $STAGE_DIR/templates/* $REMOTE_DIR/templates/ && \
    sudo cp -r $STAGE_DIR/static/* $REMOTE_DIR/static/ && \
    rm -rf $STAGE_DIR"

echo "==> Installing Python dependencies..."
ssh "$REMOTE_HOST" "sudo apt-get install -y -q python3-pip 2>/dev/null; sudo pip3 install -q --break-system-packages -r $REMOTE_DIR/requirements.txt"

if [ -n "$BRAIN_PASS" ]; then
    echo "==> Writing brain env file ($ENV_FILE_REMOTE, chmod 600)..."
    ENV_CONTENT="BRAIN_URL=$BRAIN_URL
BRAIN_RESOLVE_IP=$BRAIN_RESOLVE_IP
BRAIN_DB=$BRAIN_DB
BRAIN_USER=$BRAIN_USER
BRAIN_PASS=$BRAIN_PASS
BRAIN_VERIFY_TLS=false"
    ssh "$REMOTE_HOST" "sudo tee $ENV_FILE_REMOTE > /dev/null && sudo chmod 600 $ENV_FILE_REMOTE" <<< "$ENV_CONTENT"
else
    echo "==> BRAIN_PASS unset — vault sync will stay disabled."
fi

echo "==> Installing systemd service..."
scp 75hard.service "$REMOTE_HOST:/tmp/75hard.service"
ssh "$REMOTE_HOST" "sudo cp /tmp/75hard.service /etc/systemd/system/75hard.service && sudo systemctl daemon-reload && sudo systemctl enable 75hard && sudo systemctl restart 75hard && rm -f /tmp/75hard.service"

echo "==> Checking service status..."
ssh "$REMOTE_HOST" "sudo systemctl status 75hard --no-pager -l | head -30"

echo ""
echo "Done. Access at:"
echo "  http://<proxmox-host>:5757   (Tailscale)"
echo ""
echo "Smoke-test routes:"
echo "  /          /sprint       /running       /checkin"
echo "  POST /sprint/log  (hero free-text input)"
