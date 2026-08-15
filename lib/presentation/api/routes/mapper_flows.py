from __future__ import annotations

from fastapi import APIRouter, HTTPException

from lib.core.logs import get_logger
from lib.domain.models.mapper_flow_model import MapperFlow
from lib.domain.services.mapper_flow_service import MapperFlowService
from lib.presentation.api.dependencies import get_mapper_flow_execution_service, get_session
from lib.presentation.api.schemas.mapper_schemas import (
    MapperFlowCreateRequest,
    MapperFlowResponse,
    MapperFlowRunResponse,
    MapperFlowStepCreateRequest,
    MapperFlowStepResponse,
    MapperFlowStepResultResponse,
    MapperFlowStepUpdateRequest,
    MapperFlowSummaryResponse,
    MapperFlowUpdateRequest,
)

router = APIRouter(prefix="/mapper/flows", tags=["mapper-flows"])
logger = get_logger(__name__)


def _step_to_response(step) -> MapperFlowStepResponse:
    return MapperFlowStepResponse(
        id=step.id,
        ordinal=step.ordinal,
        action_type=step.action_type,
        selector=step.selector_json or {},
        safety=step.safety.value,
        source_screen_id=step.source_screen_id,
        source_action_id=step.source_action_id,
        params=step.params_json,
    )


def _flow_to_response(flow: MapperFlow) -> MapperFlowResponse:
    steps = sorted(flow.steps, key=lambda step: step.ordinal)
    return MapperFlowResponse(
        id=flow.id,
        name=flow.name,
        package_name=flow.package_name,
        description=flow.description,
        source_session_id=flow.source_session_id,
        created_at=flow.created_at,
        step_count=len(steps),
        steps=[_step_to_response(step) for step in steps],
    )


def _flow_to_summary(flow: MapperFlow) -> MapperFlowSummaryResponse:
    return MapperFlowSummaryResponse(
        id=flow.id,
        name=flow.name,
        package_name=flow.package_name,
        description=flow.description,
        source_session_id=flow.source_session_id,
        created_at=flow.created_at,
        step_count=len(flow.steps),
    )


@router.get("", response_model=list[MapperFlowSummaryResponse])
def list_flows(package_name: str | None = None):
    with get_session() as session:
        flows = MapperFlowService(session).list_flows(package_name)
        return [_flow_to_summary(flow) for flow in flows]


@router.post("", response_model=MapperFlowResponse)
def create_flow(payload: MapperFlowCreateRequest):
    logger.info("POST /mapper/flows name=%s package=%s", payload.name, payload.package_name)
    steps = [step.model_dump() for step in payload.steps] if payload.steps else None
    with get_session() as session:
        try:
            flow = MapperFlowService(session).create_flow(
                name=payload.name,
                package_name=payload.package_name,
                description=payload.description,
                source_session_id=payload.source_session_id,
                transition_ids=payload.transition_ids,
                steps=steps,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _flow_to_response(flow)


@router.get("/{flow_id}", response_model=MapperFlowResponse)
def show_flow(flow_id: int):
    with get_session() as session:
        flow = MapperFlowService(session).get_flow(flow_id)
        if flow is None:
            raise HTTPException(status_code=404, detail="Mapper flow not found")
        return _flow_to_response(flow)


@router.patch("/{flow_id}", response_model=MapperFlowResponse)
def update_flow(flow_id: int, payload: MapperFlowUpdateRequest):
    logger.info("PATCH /mapper/flows/%s", flow_id)
    with get_session() as session:
        try:
            MapperFlowService(session).update_flow(flow_id, name=payload.name, description=payload.description)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _flow_to_response(MapperFlowService(session).get_flow(flow_id))


@router.delete("/{flow_id}")
def delete_flow(flow_id: int):
    logger.info("DELETE /mapper/flows/%s", flow_id)
    with get_session() as session:
        try:
            MapperFlowService(session).delete_flow(flow_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True, "flow_id": flow_id}


@router.post("/{flow_id}/steps", response_model=MapperFlowStepResponse)
def add_step(flow_id: int, payload: MapperFlowStepCreateRequest):
    logger.info("POST /mapper/flows/%s/steps action_type=%s", flow_id, payload.action_type)
    with get_session() as session:
        try:
            step = MapperFlowService(session).add_step(flow_id, payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _step_to_response(step)


@router.patch("/{flow_id}/steps/{step_id}", response_model=MapperFlowStepResponse)
def update_step(flow_id: int, step_id: int, payload: MapperFlowStepUpdateRequest):
    logger.info("PATCH /mapper/flows/%s/steps/%s", flow_id, step_id)
    with get_session() as session:
        try:
            step = MapperFlowService(session).update_step(step_id, action_type=payload.action_type, selector=payload.selector, params=payload.params)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _step_to_response(step)


@router.delete("/{flow_id}/steps/{step_id}")
def delete_step(flow_id: int, step_id: int):
    logger.info("DELETE /mapper/flows/%s/steps/%s", flow_id, step_id)
    with get_session() as session:
        try:
            MapperFlowService(session).delete_step(step_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True, "step_id": step_id}


@router.post("/{flow_id}/run", response_model=MapperFlowRunResponse)
def run_flow(flow_id: int, skip_dangerous_actions: bool = True):
    logger.info("POST /mapper/flows/%s/run", flow_id)
    with get_session() as session:
        flow = MapperFlowService(session).get_flow(flow_id)
        if flow is None:
            raise HTTPException(status_code=404, detail="Mapper flow not found")
        # flow.steps was eagerly loaded (selectinload) and the session uses expire_on_commit=False,
        # so it's safe to keep using this ORM object after the session block closes.
        result = get_mapper_flow_execution_service().run_flow(flow, skip_dangerous_actions=skip_dangerous_actions)

    return MapperFlowRunResponse(
        flow_id=result["flow_id"],
        name=result["name"],
        package_name=result["package_name"],
        steps=[MapperFlowStepResultResponse(**step_result) for step_result in result["steps"]],
    )


@router.post("/{flow_id}/steps/{ordinal}/run", response_model=MapperFlowStepResultResponse)
def run_step(flow_id: int, ordinal: int, skip_dangerous_actions: bool = True):
    logger.info("POST /mapper/flows/%s/steps/%s/run", flow_id, ordinal)
    with get_session() as session:
        flow = MapperFlowService(session).get_flow(flow_id)
        if flow is None:
            raise HTTPException(status_code=404, detail="Mapper flow not found")
        step = next((candidate for candidate in flow.steps if candidate.ordinal == ordinal), None)
        if step is None:
            raise HTTPException(status_code=404, detail=f"Step with ordinal {ordinal} not found in flow {flow_id}")
        result = get_mapper_flow_execution_service().run_step(step, skip_dangerous_actions=skip_dangerous_actions)

    return MapperFlowStepResultResponse(**result)
