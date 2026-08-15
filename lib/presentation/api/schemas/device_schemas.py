from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DeviceActionRequest(BaseModel):
    package_name: str = Field(description="The app's package name, e.g. \"com.linkedin.android\".")
    target_action_id: int | None = Field(
        default=None,
        description="A MapperAction id from the map. Navigates there automatically before clicking it. "
        "Mutually exclusive with action_type.",
    )
    current_screen_id: int | None = Field(
        default=None,
        description="The MapperScreen you believe the device is on right now (e.g. a previous "
        "call's resulting_screen_id). Omit if unknown, the backend relaunches the app and replays "
        "the known path instead of guessing.",
    )
    action_type: str | None = Field(
        default=None,
        description="One of click, click_first_match, click_bounds, scroll_up, back, wait, "
        "dump_nodes, screenshot, ocr_extract. Runs against whatever's on screen. "
        "Mutually exclusive with target_action_id.",
    )
    target_screen_id: int | None = Field(
        default=None,
        description="A MapperScreen id to navigate to before running action_type. Only used with "
        "action_type; omit to run against the current screen with no navigation.",
    )
    selector: dict[str, Any] | None = Field(
        default=None,
        description="Shape depends on action_type: click wants {\"candidates\": [str, ...]}, "
        "click_bounds wants {\"bounds\": \"[x1,y1][x2,y2]\"}, the rest ignore this field.",
    )
    params: dict[str, Any] | None = Field(
        default=None,
        description="Extra options for action_type: wait wants {\"seconds\": float}, screenshot "
        "and ocr_extract accept {\"filename\": str} (ocr_extract reads back the screenshot saved "
        "under that same filename).",
    )


class DeviceActionResponse(BaseModel):
    step_id: int | None = Field(default=None, description="The MapperFlowStep this action ran as, set for a mapped action, null for a raw one.")
    action_type: str
    success: bool = Field(description="Whether the action itself succeeded (a selector matched, a click landed, ...).")
    skipped_reason: str | None = Field(default=None, description="Set instead of running, e.g. \"dangerous_action_blocked\".")
    error: str | None = Field(default=None, description="Set if the action raised an exception while running.")
    resulting_screen_id: int | None = Field(
        default=None,
        description="The new known screen, when knowable: a mapped action's destination, or a "
        "read-only action (dump_nodes/screenshot/ocr_extract/wait) staying at its target_screen_id. "
        "Null after a raw click-type action, there's no mapped provenance to confirm where it landed.",
    )
    node_count: int | None = Field(default=None, description="Set by dump_nodes: how many nodes were on screen.")
    nodes: list[dict[str, Any]] | None = Field(default=None, description="Set by dump_nodes: the live accessibility tree.")
    screenshot_path: str | None = Field(default=None, description="Set by screenshot: where the image was saved.")
    ocr_regions: list[dict[str, str]] | None = Field(
        default=None,
        description="Set by ocr_extract: [{\"text\": ..., \"bounds\": \"[x1,y1][x2,y2]\"}, ...], one per detected text region.",
    )
