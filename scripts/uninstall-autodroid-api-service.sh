#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="autodroid-api.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
ENV_PATH="/etc/default/autodroid-api"

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is required" >&2
  exit 1
fi

echo "stopping ${SERVICE_NAME} if present"
sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
echo "disabling ${SERVICE_NAME} if present"
sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true

if [[ -f "$SERVICE_PATH" ]]; then
  echo "removing ${SERVICE_PATH}"
  sudo rm -f "$SERVICE_PATH"
fi

if [[ -f "$ENV_PATH" ]]; then
  echo "removing ${ENV_PATH}"
  sudo rm -f "$ENV_PATH"
fi

echo 'reloading systemd'
sudo systemctl daemon-reload
sudo systemctl reset-failed 2>/dev/null || true
echo 'uninstall complete'
