#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="autodroid-api.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
ENV_PATH="/etc/default/autodroid-api"
PROJECT_DIR="/home/wilsonborba/Documents/Others/Asodya/autodroid"
VENV_BIN="${PROJECT_DIR}/.venv/bin/autodroid"
API_PORT="7777"

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

cat > "$tmpdir/autodroid-api.env" <<EOF
AUTODROID_ALLOW_DANGEROUS_ACTIONS=true
EOF

cat > "$tmpdir/autodroid-api.service" <<EOF
[Unit]
Description=Autodroid API Server
After=network.target

[Service]
Type=simple
User=wilsonborba
Group=wilsonborba
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${ENV_PATH}
Environment=HOME=/home/wilsonborba
ExecStart=${VENV_BIN} serve-api --port ${API_PORT} --allow-dangerous-actions
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
EOF

echo "installing ${ENV_PATH}"
sudo install -m 644 "$tmpdir/autodroid-api.env" "$ENV_PATH"
echo "installing ${SERVICE_PATH}"
sudo install -m 644 "$tmpdir/autodroid-api.service" "$SERVICE_PATH"
echo 'reloading systemd'
sudo systemctl daemon-reload
echo "enabling ${SERVICE_NAME}"
sudo systemctl enable "$SERVICE_NAME"
echo 'installation complete'
echo
echo 'next commands:'
echo '  scripts/autodroid-api-service.sh start'
echo '  scripts/autodroid-api-service.sh status'
