from __future__ import annotations

import subprocess
import time


class AdbAdapter:
    def __init__(self, serial: str) -> None:
        self.serial = serial

    def run(self, *args: str) -> str:
        command = ["adb", "-s", self.serial, *args]
        result = subprocess.run(command, check=True, capture_output=True, text=True)
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

    def force_stop_app(self, package_name: str) -> str:
        return self.shell(f"am force-stop {package_name}")

    def start_app(self, package_name: str) -> str:
        return self.shell(f"monkey -p {package_name} -c android.intent.category.LAUNCHER 1")
