#!/bin/bash
set -e

LOGFILE="/tmp/75hard.log"
PORT=5757

echo "==> Stopping existing process on port $PORT..."
pkill -f "python.*app.py" 2>/dev/null || true
sleep 1

echo "==> Starting 75hard-tracker..."
cd "$(dirname "$0")"
nohup python3 app.py >> "$LOGFILE" 2>&1 &
echo "PID: $!"

sleep 1
if curl -so /dev/null -w "%{http_code}" "http://localhost:$PORT/" | grep -q 200; then
    echo "==> OK — http://localhost:$PORT/"
else
    echo "==> FAILED — check $LOGFILE"
    exit 1
fi
