from __future__ import annotations

import subprocess


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
