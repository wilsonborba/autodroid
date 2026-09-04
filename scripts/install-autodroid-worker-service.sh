#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="autodroid-worker.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
PROJECT_DIR="/home/wilsonborba/Documents/Others/Asodya/autodroid"
VENV_BIN="${PROJECT_DIR}/.venv/bin/autodroid"

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is required" >&2
  exit 1
fi

if [[ ! -x "$VENV_BIN" ]]; then
  echo "expected venv binary not found or not executable: ${VENV_BIN}" >&2
  exit 1
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

cat > "$tmpdir/autodroid-worker.service" <<EOF
[Unit]
Description=Autodroid Job Dispatcher Worker
After=network.target

[Service]
Type=simple
User=wilsonborba
Group=wilsonborba
WorkingDirectory=${PROJECT_DIR}
Environment=HOME=/home/wilsonborba
ExecStart=${VENV_BIN} worker run
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
EOF

echo "installing ${SERVICE_PATH}"
sudo install -m 644 "$tmpdir/autodroid-worker.service" "$SERVICE_PATH"
echo 'reloading systemd'
sudo systemctl daemon-reload
echo "enabling ${SERVICE_NAME}"
sudo systemctl enable "$SERVICE_NAME"
echo "starting ${SERVICE_NAME}"
sudo systemctl restart "$SERVICE_NAME"
echo
sudo systemctl status "$SERVICE_NAME" --no-pager -n 20 || true
echo
echo "autodroid worker installed, enabled and running"
