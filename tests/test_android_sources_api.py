from __future__ import annotations

from fastapi.testclient import TestClient

from lib.bootstrap import create_api_app

PACKAGE_NAME = "com.instagram.android"


class FakeAndroidSourcesService:
    def __init__(self, *, dangerous_allowed: bool = True) -> None:
        self.dangerous_allowed = dangerous_allowed
        self.deleted_calls: list[tuple[str, str]] = []
        self.staged_calls: list[tuple[str, str, bytes, str | None]] = []
        self.read_calls: list[tuple[str, str]] = []

    def list_files(self, package_name: str, *, path: str | None = None):
        if path and "com.other.app" in path:
            raise ValueError(f"{path!r} is outside the allowed scope for {package_name}")
        target = path or f"/data/data/{package_name}"
        return {"package_name": package_name, "path": target, "raw": "total 0\n", "entries": []}

    def read_file(self, package_name: str, path: str):
        if "com.other.app" in path:
            raise ValueError(f"{path!r} is outside the allowed scope for {package_name}")
        self.read_calls.append((package_name, path))
        return {"package_name": package_name, "path": path, "filename": "905", "content": b"zip-bytes", "size_bytes": len(b"zip-bytes")}

    def delete_file(self, package_name: str, path: str):
        if not self.dangerous_allowed:
            raise PermissionError("android-sources delete requires the API to run with --allow-dangerous-actions")
        self.deleted_calls.append((package_name, path))
        return {"package_name": package_name, "path": path, "deleted": True}

    def stage_file(self, package_name: str, filename: str, content: bytes, *, folder: str | None = None):
        if not self.dangerous_allowed:
            raise PermissionError("android-sources staging requires the API to run with --allow-dangerous-actions")
        self.staged_calls.append((package_name, filename, content, folder))
        return {"package_name": package_name, "path": f"{folder or '/sdcard/Download'}/{filename}", "staged": True, "size_bytes": len(content)}


def test_list_files_endpoint(monkeypatch) -> None:
    monkeypatch.setattr("lib.presentation.api.routes.android_sources.get_android_sources_service", lambda: FakeAndroidSourcesService())
    client = TestClient(create_api_app())

    response = client.get(f"/android-sources/{PACKAGE_NAME}/files")

    assert response.status_code == 200
    assert response.json()["path"] == f"/data/data/{PACKAGE_NAME}"


def test_list_files_endpoint_returns_400_for_out_of_scope_path(monkeypatch) -> None:
    monkeypatch.setattr("lib.presentation.api.routes.android_sources.get_android_sources_service", lambda: FakeAndroidSourcesService())
    client = TestClient(create_api_app())

    response = client.get(f"/android-sources/{PACKAGE_NAME}/files", params={"path": "/data/data/com.other.app"})

    assert response.status_code == 400


def test_download_file_endpoint_returns_binary_content(monkeypatch) -> None:
    service = FakeAndroidSourcesService()
    monkeypatch.setattr("lib.presentation.api.routes.android_sources.get_android_sources_service", lambda: service)
    client = TestClient(create_api_app())
    path = f"/sdcard/Android/data/{PACKAGE_NAME}/files/chats/chat-id/messages/905"

    response = client.get(f"/android-sources/{PACKAGE_NAME}/files/content", params={"path": path})

    assert response.status_code == 200
    assert response.content == b"zip-bytes"
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-android-source-path"] == path
    assert "filename*=UTF-8''905" in response.headers["content-disposition"]
    assert service.read_calls == [(PACKAGE_NAME, path)]


def test_download_file_endpoint_returns_400_for_out_of_scope_path(monkeypatch) -> None:
    service = FakeAndroidSourcesService()
    monkeypatch.setattr("lib.presentation.api.routes.android_sources.get_android_sources_service", lambda: service)
    client = TestClient(create_api_app())

    response = client.get(f"/android-sources/{PACKAGE_NAME}/files/content", params={"path": "/data/data/com.other.app/files/secret.zip"})

    assert response.status_code == 400
    assert service.read_calls == []


def test_delete_file_endpoint_when_allowed(monkeypatch) -> None:
    service = FakeAndroidSourcesService(dangerous_allowed=True)
    monkeypatch.setattr("lib.presentation.api.routes.android_sources.get_android_sources_service", lambda: service)
    client = TestClient(create_api_app())

    response = client.delete(f"/android-sources/{PACKAGE_NAME}/files", params={"path": f"/data/data/{PACKAGE_NAME}/cache/stale.jpg"})

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert service.deleted_calls == [(PACKAGE_NAME, f"/data/data/{PACKAGE_NAME}/cache/stale.jpg")]


def test_delete_file_endpoint_returns_403_when_dangerous_actions_disabled(monkeypatch) -> None:
    service = FakeAndroidSourcesService(dangerous_allowed=False)
    monkeypatch.setattr("lib.presentation.api.routes.android_sources.get_android_sources_service", lambda: service)
    client = TestClient(create_api_app())

    response = client.delete(f"/android-sources/{PACKAGE_NAME}/files", params={"path": f"/data/data/{PACKAGE_NAME}/cache/stale.jpg"})

    assert response.status_code == 403
    assert service.deleted_calls == []


def test_stage_file_endpoint_when_allowed(monkeypatch) -> None:
    service = FakeAndroidSourcesService(dangerous_allowed=True)
    monkeypatch.setattr("lib.presentation.api.routes.android_sources.get_android_sources_service", lambda: service)
    client = TestClient(create_api_app())

    response = client.post(
        f"/android-sources/{PACKAGE_NAME}/files",
        files={"file": ("photo.jpg", b"fake-bytes", "image/jpeg")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "/sdcard/Download/photo.jpg"
    assert body["size_bytes"] == len(b"fake-bytes")
    assert service.staged_calls == [(PACKAGE_NAME, "photo.jpg", b"fake-bytes", None)]


def test_stage_file_endpoint_accepts_an_explicit_folder(monkeypatch) -> None:
    service = FakeAndroidSourcesService(dangerous_allowed=True)
    monkeypatch.setattr("lib.presentation.api.routes.android_sources.get_android_sources_service", lambda: service)
    client = TestClient(create_api_app())

    response = client.post(
        f"/android-sources/{PACKAGE_NAME}/files",
        files={"file": ("photo.jpg", b"fake-bytes", "image/jpeg")},
        data={"folder": "/sdcard/Pictures"},
    )

    assert response.status_code == 200
    assert response.json()["path"] == "/sdcard/Pictures/photo.jpg"


def test_stage_file_endpoint_returns_403_when_dangerous_actions_disabled(monkeypatch) -> None:
    service = FakeAndroidSourcesService(dangerous_allowed=False)
    monkeypatch.setattr("lib.presentation.api.routes.android_sources.get_android_sources_service", lambda: service)
    client = TestClient(create_api_app())

    response = client.post(
        f"/android-sources/{PACKAGE_NAME}/files",
        files={"file": ("photo.jpg", b"fake-bytes", "image/jpeg")},
    )

    assert response.status_code == 403
    assert service.staged_calls == []
