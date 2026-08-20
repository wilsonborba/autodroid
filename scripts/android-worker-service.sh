#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="android-worker.service"
EMULATOR_MATCH='qemu-system-.* @android-worker-01'

info() {
  echo "==> $*"
}

warn() {
  echo "WARN: $*" >&2
}

usage() {
  cat <<'EOF'
Usage: scripts/android-worker-service.sh <command>

Commands:
  status        Show service status and adb readiness
  start         Start the persistent systemd service
  stop          Stop the persistent systemd service
  restart       Restart the persistent systemd service
  logs          Show recent service logs
  adopt         Stop manual emulator process and start systemd service
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
  echo
  echo 'ADB devices:'
  adb devices -l || true
  echo
  echo 'Boot property:'
  adb -s emulator-5554 shell getprop sys.boot_completed 2>/dev/null || true
}

service_state() {
  systemctl is-active "$SERVICE_NAME" 2>/dev/null || true
}

show_failure_context() {
  warn "service state: $(service_state)"
  warn 'recent service logs:'
  journalctl -u "$SERVICE_NAME" -n 30 --no-pager || true
  echo
  echo 'ADB devices:'
  adb devices -l || true
}

wait_for_device() {
  local serial=''
  info 'waiting for adb device emulator-5554'
  for attempt in $(seq 1 120); do
    local state
    state="$(service_state)"
    if [[ "$state" == "failed" || "$state" == "inactive" || "$state" == "deactivating" ]]; then
      warn "service stopped before adb device appeared"
      show_failure_context
      return 1
    fi
    if [[ "$attempt" -eq 1 || $((attempt % 10)) -eq 0 ]]; then
      info "adb wait progress: attempt ${attempt}/120, service=${state}"
    fi
    serial="$(adb devices | awk '$2=="device" && $1=="emulator-5554" {print $1; exit}')"
    if [[ -n "$serial" ]]; then
      info "adb device detected: $serial"
      break
    fi
    sleep 2
  done

  if [[ -z "$serial" ]]; then
    warn 'emulator-5554 did not become ready in time'
    show_failure_context
    return 1
  fi

  info 'waiting for Android boot completion'
  for attempt in $(seq 1 120); do
    local state
    state="$(service_state)"
    if [[ "$state" == "failed" || "$state" == "inactive" || "$state" == "deactivating" ]]; then
      warn "service stopped before Android finished booting"
      show_failure_context
      return 1
    fi
    if [[ "$attempt" -eq 1 || $((attempt % 10)) -eq 0 ]]; then
      local boot_prop
      boot_prop="$(adb -s "$serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)"
      info "boot wait progress: attempt ${attempt}/120, service=${state}, sys.boot_completed=${boot_prop:-<empty>}"
    fi
    if [[ "$(adb -s "$serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; then
      info "device ready: $serial"
      return 0
    fi
    sleep 2
  done

  warn 'emulator boot did not complete in time'
  show_failure_context
  return 1
}

manual_pid() {
  pgrep -f "$EMULATOR_MATCH" || true
}

adopt_manual_process() {
  local pids
  pids="$(manual_pid | xargs 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "stopping manual emulator pid(s): $pids"
    kill $pids 2>/dev/null || true
    sleep 3
    pids="$(manual_pid | xargs 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      kill -9 $pids 2>/dev/null || true
    fi
  fi
}

case "${1:-}" in
  status)
    service_status
    ;;
  start)
    require_sudo
    info "starting ${SERVICE_NAME}"
    sudo systemctl start "$SERVICE_NAME"
    wait_for_device
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
    wait_for_device
    service_status
    ;;
  logs)
    require_sudo
    sudo journalctl -u "$SERVICE_NAME" -n 100 --no-pager
    ;;
  adopt)
    require_sudo
    adopt_manual_process
    info "restarting ${SERVICE_NAME} after adopt"
    sudo systemctl restart "$SERVICE_NAME"
    wait_for_device
    service_status
    ;;
  install)
    exec "$SCRIPT_DIR/install-android-worker-service.sh"
    ;;
  uninstall)
    exec "$SCRIPT_DIR/uninstall-android-worker-service.sh"
    ;;
  *)
    usage
    exit 1
    ;;
esac
