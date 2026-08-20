#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="android-worker.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
ENV_PATH="/etc/default/android-worker"
ANDROID_HOME="/home/wilsonborba/Android/Sdk"
ANDROID_AVD_HOME="/opt/android-worker/avd"
EMULATOR_BIN="${ANDROID_HOME}/emulator/emulator"
AVD_NAME="android-worker-01"
XVFB_BIN="$(command -v Xvfb)"

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is required" >&2
  exit 1
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

cat > "$tmpdir/android-worker.env" <<EOF
ANDROID_HOME=${ANDROID_HOME}
ANDROID_SDK_ROOT=${ANDROID_HOME}
ANDROID_AVD_HOME=${ANDROID_AVD_HOME}
DISPLAY=:99
EOF

cat > "$tmpdir/android-worker.service" <<EOF
[Unit]
Description=Android Automation Worker
After=network.target

[Service]
Type=simple
User=wilsonborba
Group=wilsonborba
EnvironmentFile=${ENV_PATH}
Environment=HOME=/home/wilsonborba
ExecStart=/bin/bash -lc 'pkill -f "^${XVFB_BIN} :99 " >/dev/null 2>&1 || true; ${XVFB_BIN} :99 -screen 0 1080x2400x24 -nolisten tcp -ac >/tmp/android-worker-xvfb.log 2>&1 & XVFB_PID=\$!; trap "kill \$XVFB_PID >/dev/null 2>&1 || true" EXIT; sleep 1; exec ${EMULATOR_BIN} @${AVD_NAME} -no-audio -accel on -gpu swangle_indirect'
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
EOF

echo "installing ${ENV_PATH}"
sudo install -m 644 "$tmpdir/android-worker.env" "$ENV_PATH"
echo "installing ${SERVICE_PATH}"
sudo install -m 644 "$tmpdir/android-worker.service" "$SERVICE_PATH"
echo 'reloading systemd'
sudo systemctl daemon-reload
echo "enabling ${SERVICE_NAME}"
sudo systemctl enable "$SERVICE_NAME"
echo "starting ${SERVICE_NAME}"
exec "$SCRIPT_DIR/android-worker-service.sh" adopt
