from __future__ import annotations

from unittest.mock import MagicMock, patch

from lib.dal.remote.adb_adapter import AdbAdapter


def _adapter() -> AdbAdapter:
    return AdbAdapter("emulator-5554")


def _run_command(mock_run: MagicMock) -> list[str]:
    return mock_run.call_args.args[0]


@patch("subprocess.run")
def test_list_dir_runs_ls_la_over_shell(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(stdout="total 0\n", stderr="")
    adapter = _adapter()

    adapter.list_dir("/sdcard/Download")

    assert _run_command(mock_run) == ["adb", "-s", "emulator-5554", "shell", "ls -la /sdcard/Download"]


@patch("subprocess.run")
def test_list_dir_quotes_paths_with_spaces_or_metacharacters(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(stdout="", stderr="")
    adapter = _adapter()

    adapter.list_dir("/sdcard/My Folder; rm -rf /")

    command = _run_command(mock_run)
    assert command[-1] == "ls -la '/sdcard/My Folder; rm -rf /'"


@patch("subprocess.run")
def test_delete_file_uses_rm_f_not_recursive(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(stdout="", stderr="")
    adapter = _adapter()

    adapter.delete_file("/sdcard/Download/stale.jpg")

    command = _run_command(mock_run)
    assert command[-1] == "rm -f /sdcard/Download/stale.jpg"
    assert "-r" not in command[-1]


@patch("subprocess.run")
def test_push_file_runs_adb_push(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(stdout="", stderr="")
    adapter = _adapter()

    adapter.push_file("/tmp/local.jpg", "/sdcard/Download/local.jpg")

    assert _run_command(mock_run) == ["adb", "-s", "emulator-5554", "push", "/tmp/local.jpg", "/sdcard/Download/local.jpg"]


@patch("subprocess.run")
def test_pull_file_runs_adb_pull(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(stdout="", stderr="")
    adapter = _adapter()

    adapter.pull_file("/sdcard/Download/remote.jpg", "/tmp/remote.jpg")

    assert _run_command(mock_run) == ["adb", "-s", "emulator-5554", "pull", "/sdcard/Download/remote.jpg", "/tmp/remote.jpg"]
