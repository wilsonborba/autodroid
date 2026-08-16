from __future__ import annotations

from fastapi import APIRouter, HTTPException

from lib.core.logs import get_logger
from lib.presentation.api.dependencies import get_mapper_flow_execution_service
from lib.presentation.api.schemas.device_schemas import DeviceActionRequest, DeviceActionResponse

# deliberately not under /mapper: that prefix is the mapping phase (building the structural
# map). This is about using an app that's already mapped, a distinct concern (issue #32).
router = APIRouter(prefix="/device", tags=["device-actions"])
logger = get_logger(__name__)

EXECUTE_ACTION_DESCRIPTION = """
Runs exactly one action on the device right now, no MapperFlow needs to exist beforehand. This
is the primitive for an external agent deciding what to do step by step, based on what each
previous call returned.

**Two ways to call it, pick one per request:**

1. **A mapped action** (`target_action_id`): the id of a `MapperAction` discovered while mapping
   the app (see `GET /mapper/sessions/{id}/actions`). The backend guarantees the device is on
   that action's screen before clicking it: if `current_screen_id` is given and a direct route
   exists in the map, it walks that route; otherwise it relaunches the app and replays the known
   chain of steps from the root. You never need to compute this path yourself.

2. **A raw action** (`action_type`, one of `click`, `click_first_match`, `click_bounds`,
   `type_text`, `scroll_up`, `scroll_down`, `back`, `home`, `enter`, `keyevent`, `wait`,
   `dump_nodes`, `screenshot`, `ocr_extract`): runs
   against whatever is currently on screen. Pass `target_screen_id` (a `MapperScreen` id) to also
   get navigated there first, the same way as a mapped action; without it, nothing is navigated,
   this fires immediately against the live screen, useful right after a previous call already
   confirmed the position (via its `resulting_screen_id`), or for a purely exploratory read.

`selector`/`params` shape depends on `action_type`, mirroring MapperFlowStep: `click` takes
`{"candidates": [str, ...]}` (matched by visible text or content description); `click_bounds`
takes `{"bounds": "[x1,y1][x2,y2]"}` (an exact screen region, e.g. from a prior `dump_nodes` or
`ocr_extract` result, useful too for anything the accessibility tree marks as non-clickable even
though it visually reacts to a tap, some apps do this for their own icon rows); `type_text` takes
`{"text": str, "clear": bool}` (types into whatever is currently focused, so a `click`/
`click_bounds` on the field comes first as its own step; `clear` wipes existing content before
typing); `keyevent` takes `{"keycode": str}` such as `KEYCODE_ENTER`; `enter` is a shortcut
for the most common submit action; `wait` takes `params: {"seconds": float}`; the rest need no
selector.

**Response**: `success` tells whether the action itself worked. `resulting_screen_id` is the new
known position when knowable (a mapped action's destination, or a read-only action like
`dump_nodes`/`screenshot`/`ocr_extract`/`wait` staying at its `target_screen_id`); it's `null`
after a raw click-type action, there's no mapped provenance to confirm where it landed, dump the
screen again to check. `nodes` (from `dump_nodes`) is the live accessibility tree: each item has
`text`, `content_desc`, `resource_id`, `class_name`, `bounds`, and boolean flags like `clickable`
and `scrollable`, everything needed to decide the next action. `ocr_regions` (from `ocr_extract`,
requires an earlier `screenshot` call in the same `params.filename`) is `[{"text": ..., "bounds":
...}, ...]`; OCR only reports what it read, it never judges whether a result is meaningful or
actionable, that call belongs to you.

**Errors**: a mapped action that was never actually clicked while mapping, or a `target_screen_id`
that doesn't exist in the map, returns 400 immediately, there's nothing to navigate to.
"""


@router.post("/actions", response_model=DeviceActionResponse, summary="Run one action on the device now", description=EXECUTE_ACTION_DESCRIPTION)
def execute_action(payload: DeviceActionRequest):
    logger.info(
        "POST /device/actions package=%s target_action_id=%s action_type=%s",
        payload.package_name, payload.target_action_id, payload.action_type,
    )
    try:
        result = get_mapper_flow_execution_service().execute_on_demand(
            package_name=payload.package_name,
            target_action_id=payload.target_action_id,
            target_screen_id=payload.target_screen_id,
            current_screen_id=payload.current_screen_id,
            action_type=payload.action_type,
            selector=payload.selector,
            params=payload.params,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DeviceActionResponse(**result)
