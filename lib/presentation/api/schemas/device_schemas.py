from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DeviceActionRequest(BaseModel):
    package_name: str
    # a mapped action: gets navigated to automatically before running (issue #32)
    target_action_id: int | None = None
    current_screen_id: int | None = None
    # a raw action against whatever's on screen right now, no navigation attempted
    action_type: str | None = None
    selector: dict[str, Any] | None = None
    params: dict[str, Any] | None = None


class DeviceActionResponse(BaseModel):
    step_id: int | None = None
    action_type: str
    success: bool
    skipped_reason: str | None = None
    error: str | None = None
    resulting_screen_id: int | None = None
    node_count: int | None = None
    nodes: list[dict[str, Any]] | None = None
    screenshot_path: str | None = None
    ocr_regions: list[dict[str, str]] | None = None
