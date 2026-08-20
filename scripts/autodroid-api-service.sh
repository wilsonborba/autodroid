#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="autodroid-api.service"

info() {
  echo "==> $*"
}

usage() {
  cat <<'EOF'
Usage: scripts/autodroid-api-service.sh <command>

Commands:
  status        Show service status
  start         Start the persistent systemd service
  stop          Stop the persistent systemd service
  restart       Restart the persistent systemd service
  logs          Show recent service logs
  install       Install or update the systemd service and env file
  uninstall     Stop and remove the systemd service and env file
EOF
}

require_sudo() {
  if ! command -v sudo >/dev/null 2>&1; then
    echo "sudo is required" >&2
    exit 1
  fi
}

service_status() {
  systemctl status "$SERVICE_NAME" --no-pager -n 40 || true
}

case "${1:-}" in
  status)
    service_status
    ;;
  start)
    require_sudo
    info "starting ${SERVICE_NAME}"
    sudo systemctl start "$SERVICE_NAME"
    service_status
    ;;
  stop)
    require_sudo
    info "stopping ${SERVICE_NAME}"
    sudo systemctl stop "$SERVICE_NAME"
    service_status
    ;;
  restart)
    require_sudo
    info "restarting ${SERVICE_NAME}"
    sudo systemctl restart "$SERVICE_NAME"
    service_status
    ;;
  logs)
    require_sudo
    sudo journalctl -u "$SERVICE_NAME" -n 100 --no-pager
    ;;
  install)
    exec "$SCRIPT_DIR/install-autodroid-api-service.sh"
    ;;
  uninstall)
    exec "$SCRIPT_DIR/uninstall-autodroid-api-service.sh"
    ;;
  *)
    usage
    exit 1
    ;;
esac
