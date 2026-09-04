from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from lib.core.logs import get_logger
from lib.core.settings import Settings
from lib.dal.remote.adb_adapter import AdbAdapter

# folders an app's own file/media picker commonly reads from when a user "chooses" a file inside
# the app (issue #63): not package-scoped, shared across every app on the device, the same way a
# real user's Downloads/Pictures already are. Package-private paths (below) cover the other half:
# what an app already saved for itself, not what a human deliberately staged for it to pick up.
SHARED_STAGING_ROOTS = ("/sdcard/Download", "/sdcard/Pictures", "/sdcard/DCIM/Camera")


class AndroidSourcesService:
    """CRUD over the files an app can see on the emulator: what it already saved for itself
    (app-private data, its own external storage folder), and shared staging folders a human would
    normally drop a file into before picking it inside the app's own upload flow (issue #63).

    Read is always available (issue #63's own safety boundary: listing isn't destructive).
    Write/delete require `settings.allow_dangerous_actions`, the same flag every other
    irreversible action in this project already gates on.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = get_logger(__name__)
        self.adb = AdbAdapter(settings.android_serial)

    def _allowed_roots(self, package_name: str) -> tuple[str, ...]:
        return (
            f"/data/data/{package_name}",
            f"/sdcard/Android/data/{package_name}",
            *SHARED_STAGING_ROOTS,
        )

    def _validate_scope(self, package_name: str, path: str) -> None:
        # never trust the caller-supplied path alone (issue #63's whole point): every operation
        # here must stay inside this app's own data or a known shared staging folder, nothing
        # that could reach the Android OS itself, another app, or a system partition
        normalized = path.rstrip("/") or "/"
        allowed = self._allowed_roots(package_name)
        if not any(normalized == root or normalized.startswith(root + "/") for root in allowed):
            raise ValueError(f"{path!r} is outside the allowed scope for {package_name}: must be under one of {allowed}")

    def list_files(self, package_name: str, path: str | None = None) -> dict[str, Any]:
        target = path or f"/data/data/{package_name}"
        self._validate_scope(package_name, target)
        output = self.adb.list_dir(target)
        self.logger.debug("Listed %s for %s: %d line(s)", target, package_name, output.count("\n") + 1 if output else 0)
        return {"package_name": package_name, "path": target, "raw": output, "entries": [line for line in output.splitlines() if line.strip()]}

    def read_file(self, package_name: str, path: str) -> dict[str, Any]:
        self._validate_scope(package_name, path)
        filename = Path(path).name or "download"
        local_tmp = self.settings.output_dir / "android_sources_pulls" / package_name / f"{uuid4().hex}-{filename}"
        local_tmp.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.adb.pull_file(path, str(local_tmp))
            content = local_tmp.read_bytes()
        finally:
            local_tmp.unlink(missing_ok=True)
        self.logger.info("Read %s (%d bytes) for %s", path, len(content), package_name)
        return {"package_name": package_name, "path": path, "filename": filename, "content": content, "size_bytes": len(content)}

    def delete_file(self, package_name: str, path: str) -> dict[str, Any]:
        if not self.settings.allow_dangerous_actions:
            raise PermissionError("android-sources delete requires the API to run with --allow-dangerous-actions")
        self._validate_scope(package_name, path)
        self.adb.delete_file(path)
        self.logger.info("Deleted %s for %s", path, package_name)
        return {"package_name": package_name, "path": path, "deleted": True}

    def stage_file(self, package_name: str, filename: str, content: bytes, folder: str | None = None) -> dict[str, Any]:
        # writes the file into an Android storage location an in-app "choose file" flow can read
        # from next, as if a user had put it there themselves (issue #63): no bridge into the
        # app's own process, the file just needs to already exist in Android storage first
        if not self.settings.allow_dangerous_actions:
            raise PermissionError("android-sources staging requires the API to run with --allow-dangerous-actions")
        target_folder = (folder or "/sdcard/Download").rstrip("/")
        self._validate_scope(package_name, target_folder)
        remote_path = f"{target_folder}/{filename}"
        local_tmp = self.settings.output_dir / "android_sources_staging" / filename
        local_tmp.parent.mkdir(parents=True, exist_ok=True)
        local_tmp.write_bytes(content)
        try:
            self.adb.push_file(str(local_tmp), remote_path)
        finally:
            local_tmp.unlink(missing_ok=True)
        self.logger.info("Staged %s (%d bytes) at %s for %s", filename, len(content), remote_path, package_name)
        return {"package_name": package_name, "path": remote_path, "staged": True, "size_bytes": len(content)}
