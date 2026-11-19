from __future__ import annotations

import subprocess
import pytest

from lib.core.settings import load_settings
from lib.dal.remote.adb_adapter import AdbAdapter, parse_adb_devices, resolve_android_serial


def test_parse_adb_devices_ignores_headers_and_non_ready_states() -> None:
    raw = (
        "* daemon not running; starting now at tcp:5037\n"
        "* daemon started successfully\n"
        "List of devices attached\n"
        "emulator-5554\tdevice\n"
        "emulator-5556\toffline\n"
        "R58M12345\tunauthorized\n"
        "\n"
    )
    assert parse_adb_devices(raw) == ["emulator-5554"]


def test_resolve_android_serial_picks_single_running_emulator() -> None:
    raw = "List of devices attached\nemulator-5554\tdevice\n"
    assert resolve_android_serial("", devices_runner=lambda: raw) == "emulator-5554"


def test_resolve_android_serial_uses_explicit_override_without_calling_adb() -> None:
    called = False

    def runner() -> str:
        nonlocal called
        called = True
        return "List of devices attached\nemulator-5554\tdevice\n"

    assert resolve_android_serial("127.0.0.1:5555", devices_runner=runner) == "127.0.0.1:5555"
    assert not called


def test_resolve_android_serial_rejects_multiple_devices_with_clear_error() -> None:
    raw = "List of devices attached\nemulator-5554\tdevice\nemulator-5556\tdevice\n"
    with pytest.raises(RuntimeError) as exc_info:
        resolve_android_serial("", devices_runner=lambda: raw)
    msg = str(exc_info.value)
    assert "emulator-5554" in msg
    assert "emulator-5556" in msg
    assert "ANDROID_SERIAL" in msg


def test_resolve_android_serial_rejects_no_devices() -> None:
    raw = "List of devices attached\n\n"
    with pytest.raises(RuntimeError, match="No running Android devices"):
        resolve_android_serial("", devices_runner=lambda: raw)


def test_adb_adapter_uses_discovered_serial_when_settings_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANDROID_SERIAL", raising=False)
    settings = load_settings()
    assert settings.android_serial == ""

    seen_commands: list[list[str]] = []

    def fake_run(cmd, check=True, capture_output=True, text=True):
        seen_commands.append(list(cmd))
        if cmd == ["adb", "devices"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="List of devices attached\nemulator-5554\tdevice\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="package:com.example.app\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    adb = AdbAdapter(settings.android_serial)
    out = adb.shell("pm list packages")
    assert "com.example.app" in out
    assert seen_commands == [
        ["adb", "devices"],
        ["adb", "-s", "emulator-5554", "shell", "pm list packages"],
    ]
