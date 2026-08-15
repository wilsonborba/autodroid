from __future__ import annotations

from fastapi import APIRouter, HTTPException

from lib.core.logs import get_logger
from lib.presentation.api.dependencies import get_mapper_flow_execution_service
from lib.presentation.api.schemas.device_schemas import DeviceActionRequest, DeviceActionResponse

# deliberately not under /mapper: that prefix is the mapping phase (building the structural
# map). This is about using an app that's already mapped, a distinct concern (issue #32).
router = APIRouter(prefix="/device", tags=["device-actions"])
logger = get_logger(__name__)


@router.post("/actions", response_model=DeviceActionResponse)
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
