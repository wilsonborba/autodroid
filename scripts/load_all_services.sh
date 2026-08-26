#!/usr/bin/env bash
set -euo pipefail

# Services must start in dependency order: the API receives requests, the job
# worker consumes them, and only then does the resource-heavy Android emulator
# start.
readonly SERVICES=(
  "autodroid-api.service"
  "autodroid-worker.service"
  "android-worker.service"
)
readonly START_TIMEOUT_SECONDS=45

wait_until_active() {
  local service="$1"
  local started_at=$SECONDS

  while ! systemctl is-active --quiet "$service"; do
    if systemctl is-failed --quiet "$service"; then
      echo "${service} failed to start." >&2
      sudo systemctl status "$service" --no-pager -n 30 >&2 || true
      return 1
    fi
    if (( SECONDS - started_at >= START_TIMEOUT_SECONDS )); then
      echo "Timed out waiting for ${service} to become active." >&2
      sudo systemctl status "$service" --no-pager -n 30 >&2 || true
      return 1
    fi
    sleep 1
  done
}

main() {
  sudo -v

  for service in "${SERVICES[@]}"; do
    echo "Starting ${service}…"
    sudo systemctl start "$service"
    wait_until_active "$service"
    echo "${service} is active."
  done

  echo "All Autodroid services are running."
}

main "$@"
