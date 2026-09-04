from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lib.domain.services.android_sources_service import AndroidSourcesService

PACKAGE_NAME = "com.instagram.android"
STAGING_DIR = Path("/tmp/autodroid-android-sources-tests")


@pytest.fixture(autouse=True)
def _clean_staging_dir():
    shutil.rmtree(STAGING_DIR, ignore_errors=True)
    yield
    shutil.rmtree(STAGING_DIR, ignore_errors=True)


class FakeAdb:
    def __init__(self) -> None:
        self.listed: list[str] = []
        self.deleted: list[str] = []
        self.pushed: list[tuple[str, str]] = []
        self.pulled: list[tuple[str, str]] = []
        self.list_dir_result = "total 0\ndrwx------ 2 u0_a123 u0_a123 4096 file1.jpg\n"
        self.pull_content = b"downloaded-bytes"

    def list_dir(self, path: str) -> str:
        self.listed.append(path)
        return self.list_dir_result

    def delete_file(self, path: str) -> str:
        self.deleted.append(path)
        return ""

    def push_file(self, local_path: str, remote_path: str) -> str:
        self.pushed.append((local_path, remote_path))
        return ""

    def pull_file(self, remote_path: str, local_path: str) -> str:
        self.pulled.append((remote_path, local_path))
        Path(local_path).write_bytes(self.pull_content)
        return ""


def _build_service(*, allow_dangerous_actions: bool = False) -> AndroidSourcesService:
    service = AndroidSourcesService.__new__(AndroidSourcesService)
    settings = type("Settings", (), {
        "android_serial": "emulator-5554",
        "output_dir": STAGING_DIR,
        "allow_dangerous_actions": allow_dangerous_actions,
    })()
    service.settings = settings
    from lib.core.logs import get_logger
    service.logger = get_logger(__name__)
    service.adb = FakeAdb()
    return service


def test_list_files_defaults_to_the_app_private_data_dir() -> None:
    service = _build_service()

    result = service.list_files(PACKAGE_NAME)

    assert result["path"] == f"/data/data/{PACKAGE_NAME}"
    assert service.adb.listed == [f"/data/data/{PACKAGE_NAME}"]
    assert result["entries"] == ["total 0", "drwx------ 2 u0_a123 u0_a123 4096 file1.jpg"]


def test_list_files_accepts_an_explicit_path_within_scope() -> None:
    service = _build_service()

    result = service.list_files(PACKAGE_NAME, path="/sdcard/Download")

    assert result["path"] == "/sdcard/Download"
    assert service.adb.listed == ["/sdcard/Download"]


def test_list_files_rejects_a_path_outside_scope() -> None:
    service = _build_service()

    with pytest.raises(ValueError, match="outside the allowed scope"):
        service.list_files(PACKAGE_NAME, path="/data/data/com.other.app")

    assert service.adb.listed == []


def test_list_files_rejects_a_system_path() -> None:
    service = _build_service()

    with pytest.raises(ValueError, match="outside the allowed scope"):
        service.list_files(PACKAGE_NAME, path="/system")


def test_read_file_pulls_remote_file_then_cleans_up_local_copy() -> None:
    service = _build_service()
    target = f"/sdcard/Android/data/{PACKAGE_NAME}/files/chats/chat-id/messages/905"

    result = service.read_file(PACKAGE_NAME, target)

    assert result["path"] == target
    assert result["filename"] == "905"
    assert result["content"] == b"downloaded-bytes"
    assert result["size_bytes"] == len(b"downloaded-bytes")
    assert len(service.adb.pulled) == 1
    remote_path, local_path = service.adb.pulled[0]
    assert remote_path == target
    assert not Path(local_path).exists()


def test_read_file_rejects_path_outside_scope() -> None:
    service = _build_service()

    with pytest.raises(ValueError, match="outside the allowed scope"):
        service.read_file(PACKAGE_NAME, "/data/data/com.other.app/files/secret.zip")

    assert service.adb.pulled == []


def test_delete_file_requires_allow_dangerous_actions() -> None:
    service = _build_service(allow_dangerous_actions=False)

    with pytest.raises(PermissionError):
        service.delete_file(PACKAGE_NAME, f"/data/data/{PACKAGE_NAME}/cache/stale.jpg")

    assert service.adb.deleted == []


def test_delete_file_deletes_when_allowed_and_in_scope() -> None:
    service = _build_service(allow_dangerous_actions=True)
    target = f"/data/data/{PACKAGE_NAME}/cache/stale.jpg"

    result = service.delete_file(PACKAGE_NAME, target)

    assert result["deleted"] is True
    assert service.adb.deleted == [target]


def test_delete_file_still_scope_checked_even_when_allowed() -> None:
    service = _build_service(allow_dangerous_actions=True)

    with pytest.raises(ValueError, match="outside the allowed scope"):
        service.delete_file(PACKAGE_NAME, "/data/data/com.other.app/cache/stale.jpg")

    assert service.adb.deleted == []


def test_stage_file_requires_allow_dangerous_actions() -> None:
    service = _build_service(allow_dangerous_actions=False)

    with pytest.raises(PermissionError):
        service.stage_file(PACKAGE_NAME, "photo.jpg", b"fake-bytes")

    assert service.adb.pushed == []


def test_stage_file_defaults_to_download_folder_and_pushes_then_cleans_up() -> None:
    service = _build_service(allow_dangerous_actions=True)

    result = service.stage_file(PACKAGE_NAME, "photo.jpg", b"fake-bytes")

    assert result["path"] == "/sdcard/Download/photo.jpg"
    assert result["size_bytes"] == len(b"fake-bytes")
    assert len(service.adb.pushed) == 1
    local_path, remote_path = service.adb.pushed[0]
    assert remote_path == "/sdcard/Download/photo.jpg"
    # the local staging copy is removed after the push, it was only ever a hop to get adb push a
    # local file to read from, not something meant to linger on the API host
    assert not Path(local_path).exists()


def test_stage_file_accepts_a_folder_within_scope() -> None:
    service = _build_service(allow_dangerous_actions=True)

    result = service.stage_file(PACKAGE_NAME, "photo.jpg", b"fake-bytes", folder="/sdcard/Pictures")

    assert result["path"] == "/sdcard/Pictures/photo.jpg"


def test_stage_file_rejects_a_folder_outside_scope() -> None:
    service = _build_service(allow_dangerous_actions=True)

    with pytest.raises(ValueError, match="outside the allowed scope"):
        service.stage_file(PACKAGE_NAME, "photo.jpg", b"fake-bytes", folder="/system/bin")

    assert service.adb.pushed == []
