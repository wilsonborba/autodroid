from __future__ import annotations

import shlex
import subprocess
import time
from typing import Callable

from lib.core.logs import get_logger


def parse_adb_devices(output: str) -> list[str]:
    devices: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("List of devices attached") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def resolve_android_serial(
    configured_serial: str = "",
    devices_runner: Callable[[], str] | None = None,
) -> str:
    explicit = configured_serial.strip()
    if explicit:
        return explicit
    if devices_runner is None:
        result = subprocess.run(["adb", "devices"], check=True, capture_output=True, text=True)
        raw_output = result.stdout
    else:
        raw_output = devices_runner()
    devices = parse_adb_devices(raw_output)
    if not devices:
        raise RuntimeError(
            "No running Android devices found via 'adb devices'. "
            "Start an emulator or set ANDROID_SERIAL."
        )
    if len(devices) > 1:
        raise RuntimeError(
            f"Multiple Android devices detected ({', '.join(devices)}); "
            "refusing to pick randomly. Set ANDROID_SERIAL to choose one."
        )
    return devices[0]


class AdbAdapter:
    def __init__(self, serial: str = "") -> None:
        self.serial = serial
        self.logger = get_logger(__name__)

    def resolve_serial(self) -> str:
        return resolve_android_serial(self.serial)

    def run(self, *args: str) -> str:
        command = ["adb", "-s", self.resolve_serial(), *args]
        self.logger.debug("Running adb command: %s", " ".join(command))
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            self.logger.error("adb command failed: %s (%s)", " ".join(command), exc.stderr.strip() if exc.stderr else exc)
            raise
        return result.stdout.strip()

    def get_state(self) -> str:
        return self.run("get-state")

    def shell(self, command: str) -> str:
        return self.run("shell", command)

    def keyevent(self, keycode: str) -> str:
        return self.shell(f"input keyevent {keycode}")

    def go_home(self) -> None:
        self.keyevent("KEYCODE_HOME")
        time.sleep(1)

    def press_back(self) -> None:
        self.keyevent("KEYCODE_BACK")
        time.sleep(0.5)

    def press_enter(self) -> None:
        self.keyevent("KEYCODE_ENTER")
        time.sleep(0.5)

    def force_stop_app(self, package_name: str) -> str:
        return self.shell(f"am force-stop {package_name}")

    def start_app(self, package_name: str) -> str:
        return self.shell(f"monkey -p {package_name} -c android.intent.category.LAUNCHER 1")

    def list_dir(self, path: str) -> str:
        # `ls -la` over the device's own shell (issue #63): plain shell reaches shared storage
        # (/sdcard/...) on any device; an app's private data dir (/data/data/<pkg>/...) only
        # answers this way on a rooted/eng emulator build, the common case for an AVD, not on a
        # real device with a locked-down non-debuggable app. shlex.quote guards against the path
        # being interpreted by the device's shell if it ever contains a space or metacharacter.
        return self.shell(f"ls -la {shlex.quote(path)}")

    def stat_path(self, path: str) -> str:
        return self.shell(f"stat {shlex.quote(path)}")

    def delete_file(self, path: str) -> str:
        # -f only, deliberately not -r: this removes exactly one file, a directory arg fails
        # loudly instead of silently wiping a whole tree (issue #63's own safety boundary, app
        # data/storage only, never something broader by accident)
        return self.shell(f"rm -f {shlex.quote(path)}")

    def push_file(self, local_path: str, remote_path: str) -> str:
        return self.run("push", local_path, remote_path)

    def pull_file(self, remote_path: str, local_path: str) -> str:
        return self.run("pull", remote_path, local_path)
