from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class MapperRunRequest(BaseModel):
    package_name: str
    mode: str = "light"
    skip_dangerous_actions: bool = True
    override: bool = False
    complement: bool = False


class MapperRunResponse(BaseModel):
    session_id: int
    package_name: str
    mode: str
    screens_recorded: int
    actions_executed: int
    scrolls_used: int
    revisited_screens: int
    status: str
    reused: bool = False
    complemented: bool = False


class MapperScreenRemapResponse(BaseModel):
    session_id: int
    screen_id: int
    package_name: str
    mode: str
    screens_recorded: int
    actions_executed: int
    scrolls_used: int
    revisited_screens: int
    status: str


class MapperSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    package_name: str
    mode: str
    status: str
    skip_dangerous_actions: bool
    max_depth: int
    max_actions: int
    max_scrolls: int
    created_at: datetime


class MapperActivityResponse(BaseModel):
    activity_kind: str | None = None
    current_screen_id: int | None = None
    target_screen_id: int | None = None
    strategy_type: str | None = None
    reason: str | None = None


class MapperSessionProgressResponse(BaseModel):
    session_id: int
    package_name: str
    mode: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    progress_percent: float
    screen_counts: dict[str, int]
    action_counts: dict[str, int]
    transition_count: int
    revisited_screens: int
    current_activity: dict[str, Any]
    last_meaningful_progress_at: str | None = None


class MapperScreenProgressResponse(BaseModel):
    screen_id: int
    screen_key: str
    depth: int
    visit_count: int
    completion_state: str
    is_current_screen: bool
    is_current_target: bool
    known_candidates: int
    attempted_candidates: int
    successful_candidates: int
    pending_candidates: int
    known_children: int
    progress_percent: float
    last_activity_at: str | None = None
    observation_count: int = 1


class MapperExportResponse(BaseModel):
    session_id: int
    export_path: str


# --- A) live graph query -----------------------------------------------------

class MapperNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    node_key: str
    text: str | None
    content_desc: str | None
    resource_id: str | None
    class_name: str | None
    bounds: str | None
    clickable: bool
    enabled: bool
    scrollable: bool


class MapperScreenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    screen_key: str
    fingerprint: str
    depth: int
    ordinal: int
    visit_count: int
    node_count: int = 0
    nodes: list[MapperNodeResponse] | None = None


class MapperActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    screen_id: int
    node_id: int | None
    action_key: str
    action_type: str
    label: str | None
    safety: str
    skipped_reason: str | None
    executed: bool
    success: bool | None


class MapperTransitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_screen_id: int
    action_id: int
    to_screen_id: int | None
    result_type: str


class MapperGraphResponse(BaseModel):
    session_id: int
    package_name: str
    screens: list[MapperScreenResponse]
    transitions: list[MapperTransitionResponse]


# --- B) MapperFlow -----------------------------------------------------------

class MapperFlowStepResponse(BaseModel):
    id: int
    ordinal: int | None = None  # position within a specific flow; None when the step is shown outside that context (e.g. add-step ancestors)
    action_type: str
    selector: dict[str, Any]
    safety: str
    source_screen_id: int | None
    source_action_id: int | None
    params: dict[str, Any] | None


class MapperFlowSummaryResponse(BaseModel):
    id: int
    name: str
    package_name: str
    description: str | None
    source_session_id: int | None
    created_at: datetime
    step_count: int


class MapperFlowResponse(MapperFlowSummaryResponse):
    steps: list[MapperFlowStepResponse]


class MapperFlowStepCreateRequest(BaseModel):
    step_id: int | None = None  # reuse an existing (shared) step as-is; other fields are ignored when set
    action_type: str | None = None
    selector: dict[str, Any] = {}
    params: dict[str, Any] | None = None
    source_screen_id: int | None = None
    source_action_id: int | None = None
    ordinal: int | None = None


class MapperFlowAddStepResponse(BaseModel):
    step: MapperFlowStepResponse
    ancestors: list[MapperFlowStepResponse]


class MapperFlowCreateRequest(BaseModel):
    name: str
    package_name: str
    description: str | None = None
    source_session_id: int | None = None
    transition_ids: list[int] | None = None
    steps: list[MapperFlowStepCreateRequest] | None = None


class MapperFlowUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class MapperFlowStepUpdateRequest(BaseModel):
    action_type: str | None = None
    selector: dict[str, Any] | None = None
    params: dict[str, Any] | None = None


class MapperFlowStepResultResponse(BaseModel):
    step_id: int
    action_type: str
    success: bool
    skipped_reason: str | None = None
    error: str | None = None
    node_count: int | None = None
    nodes: list[dict[str, Any]] | None = None  # set by dump_nodes, was silently dropped before #32
    screenshot_path: str | None = None
    ocr_regions: list[dict[str, str]] | None = None  # {"text": ..., "bounds": "[x1,y1][x2,y2]"} (#32)
    iterations_run: int | None = None  # set when the step had a `repeat` limit (issue #22)
    stop_reason: str | None = None  # "max_iterations" | "max_duration_seconds" | "execution_window" | "no_new_content"


class MapperFlowRunResponse(BaseModel):
    flow_id: int
    name: str
    package_name: str
    steps: list[MapperFlowStepResultResponse]


# --- Remap candidates and triggering (issue #21) ------------------------------

class MapperRemapCandidateResponse(BaseModel):
    package_name: str
    unresolved_failure_count: int


class MapperRemapRequest(BaseModel):
    package_names: list[str] | None = None
    all: bool = False
    strategy: str = "override"
    mode: str = "medium"


class MapperRemapJobResponse(BaseModel):
    package_name: str
    job_id: int


class MapperRemapResponse(BaseModel):
    queued: list[MapperRemapJobResponse]
