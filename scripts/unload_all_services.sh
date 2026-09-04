#!/usr/bin/env bash
set -euo pipefail

# Stop in reverse dependency order: first release the Android emulator, then
# stop the worker, and finally the API.
readonly SERVICES=(
  "android-worker.service"
  "autodroid-worker.service"
  "autodroid-api.service"
)
readonly STOP_TIMEOUT_SECONDS=45

wait_until_inactive() {
  local service="$1"
  local started_at=$SECONDS
  local state

  while true; do
    state=$(systemctl show "$service" --property=ActiveState --value)
    case "$state" in
      inactive)
        return 0
        ;;
      failed)
        echo "${service} entered a failed state while stopping." >&2
        sudo systemctl status "$service" --no-pager -n 30 >&2 || true
        return 1
        ;;
    esac
    if (( SECONDS - started_at >= STOP_TIMEOUT_SECONDS )); then
      echo "Timed out waiting for ${service} to stop." >&2
      sudo systemctl status "$service" --no-pager -n 30 >&2 || true
      return 1
    fi
    sleep 1
  done
}

main() {
  sudo -v

  for service in "${SERVICES[@]}"; do
    echo "Stopping ${service}…"
    sudo systemctl stop "$service"
    wait_until_inactive "$service"
    echo "${service} is inactive."
  done

  echo "All Autodroid services are stopped."
}

main "$@"
