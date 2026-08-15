from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from lib.dal.remote.adb_adapter import AdbAdapter


@dataclass(frozen=True)
class ResumeContext:
    enabled: bool = False
    screen_map: dict[str, Any] | None = None
    last_known_screen: str | None = None


class NavigationContextService:
    def __init__(self, adb: AdbAdapter) -> None:
        self.adb = adb

    def prepare_fresh_app_launch(self, package_name: str) -> None:
        self.adb.go_home()
        self.adb.force_stop_app(package_name)
        time.sleep(1)
        self.adb.go_home()
        self.adb.start_app(package_name)
        time.sleep(3)

    def load_resume_context(self, payload: dict[str, Any]) -> ResumeContext:
        if not payload.get("resume_enabled"):
            return ResumeContext(enabled=False)
        return ResumeContext(
            enabled=True,
            screen_map=payload.get("screen_map"),
            last_known_screen=payload.get("last_known_screen"),
        )

    def can_resume(self, resume_context: ResumeContext) -> bool:
        return resume_context.enabled and bool(resume_context.screen_map)
