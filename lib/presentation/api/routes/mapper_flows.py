from __future__ import annotations

from fastapi import APIRouter, HTTPException

from lib.core.logs import get_logger
from lib.dal.local.mapper_flow_repository import SqlAlchemyMapperFlowRepository
from lib.domain.models.mapper_flow_model import MapperFlow, MapperFlowStep
from lib.domain.services.mapper_flow_service import MapperFlowService
from lib.presentation.api.dependencies import get_mapper_flow_execution_service, get_session
from lib.presentation.api.schemas.mapper_schemas import (
    MapperFlowAddStepResponse,
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

router = APIRouter(
    prefix="/mapper/flows",
    tags=["mapper-flows"],
    # a Flow is a named, pre-composed sequence of steps against an already-mapped app: use this
    # group for a fixed job that always does the same thing. For one-off, decided-as-you-go
    # actions, use /device/actions instead, no Flow needs to be saved beforehand.
)
logger = get_logger(__name__)


def _step_to_response(step: MapperFlowStep, *, ordinal: int | None = None) -> MapperFlowStepResponse:
    return MapperFlowStepResponse(
        id=step.id,
        ordinal=ordinal,
        action_type=step.action_type,
        selector=step.selector_json or {},
        safety=step.safety.value,
        source_screen_id=step.source_screen_id,
        source_action_id=step.source_action_id,
        params=step.params_json,
    )


def _flow_to_response(flow: MapperFlow) -> MapperFlowResponse:
    usages = sorted(flow.step_usages, key=lambda usage: usage.ordinal)
    return MapperFlowResponse(
        id=flow.id,
        name=flow.name,
        package_name=flow.package_name,
        description=flow.description,
        source_session_id=flow.source_session_id,
        created_at=flow.created_at,
        step_count=len(usages),
        steps=[_step_to_response(usage.step, ordinal=usage.ordinal) for usage in usages],
    )


def _flow_to_summary(flow: MapperFlow) -> MapperFlowSummaryResponse:
    return MapperFlowSummaryResponse(
        id=flow.id,
        name=flow.name,
        package_name=flow.package_name,
        description=flow.description,
        source_session_id=flow.source_session_id,
        created_at=flow.created_at,
        step_count=len(flow.step_usages),
    )


@router.get("", response_model=list[MapperFlowSummaryResponse], summary="List saved flows, optionally by package")
def list_flows(package_name: str | None = None):
    with get_session() as session:
        flows = MapperFlowService(session).list_flows(package_name)
        return [_flow_to_summary(flow) for flow in flows]


@router.post(
    "", response_model=MapperFlowResponse, summary="Create a named, saved flow",
    description="Requires either `steps` (inline definitions, each `{action_type, selector, "
    "params}`, `source_screen_id`/`source_action_id` optional provenance) or `transition_ids` "
    "(build the flow directly from mapped transitions instead). Adding a step whose "
    "`source_screen_id` isn't reachable from an already-included step auto-pulls the ancestor "
    "chain needed to get there (issue #23), so the flow is always runnable end to end. Steps are "
    "shared, package-scoped objects (`POST /mapper/flows/{id}/steps` with an existing `step_id` "
    "reuses one instead of duplicating it, editing a shared step affects every flow using it).",
)
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


@router.get("/{flow_id}", response_model=MapperFlowResponse, summary="Get one flow with its ordered steps")
def show_flow(flow_id: int):
    with get_session() as session:
        flow = MapperFlowService(session).get_flow(flow_id)
        if flow is None:
            raise HTTPException(status_code=404, detail="Mapper flow not found")
        return _flow_to_response(flow)


@router.patch("/{flow_id}", response_model=MapperFlowResponse, summary="Rename or redescribe a flow")
def update_flow(flow_id: int, payload: MapperFlowUpdateRequest):
    logger.info("PATCH /mapper/flows/%s", flow_id)
    with get_session() as session:
        try:
            MapperFlowService(session).update_flow(flow_id, name=payload.name, description=payload.description)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _flow_to_response(MapperFlowService(session).get_flow(flow_id))


@router.delete("/{flow_id}", summary="Delete a flow", description="Removes the flow and its step usages. Shared steps themselves survive, other flows using them are unaffected.")
def delete_flow(flow_id: int):
    logger.info("DELETE /mapper/flows/%s", flow_id)
    with get_session() as session:
        try:
            MapperFlowService(session).delete_flow(flow_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True, "flow_id": flow_id}


@router.post(
    "/{flow_id}/steps", response_model=MapperFlowAddStepResponse, summary="Append a step to a flow",
    description="Pass `step_id` to reuse an existing shared step as-is, or the fields to define a "
    "new one. If the step's `source_screen_id` isn't reachable from what's already in the flow, "
    "the ancestor chain needed to get there is resolved and attached automatically (issue #23); "
    "`ancestors` in the response is exactly what got auto-added, in order, before the step itself.",
)
def add_step(flow_id: int, payload: MapperFlowStepCreateRequest):
    logger.info("POST /mapper/flows/%s/steps step_id=%s action_type=%s", flow_id, payload.step_id, payload.action_type)
    with get_session() as session:
        try:
            outcome = MapperFlowService(session).add_step(flow_id, payload.model_dump())
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return MapperFlowAddStepResponse(
            step=_step_to_response(outcome["step"]),
            ancestors=[_step_to_response(step) for step in outcome["ancestors"]],
        )


@router.patch(
    "/{flow_id}/steps/{step_id}", response_model=MapperFlowStepResponse, summary="Edit a shared step",
    description="Steps are shared across flows by design (issue #23): this changes the step "
    "itself, affecting every flow that uses it, not just this one.",
)
def update_step(flow_id: int, step_id: int, payload: MapperFlowStepUpdateRequest):
    logger.info("PATCH /mapper/flows/%s/steps/%s (shared step, affects every flow using it)", flow_id, step_id)
    with get_session() as session:
        try:
            step = MapperFlowService(session).update_step(step_id, action_type=payload.action_type, selector=payload.selector, params=payload.params)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _step_to_response(step)


@router.delete(
    "/{flow_id}/steps/{step_id}", summary="Remove a step from one flow",
    description="Detaches the step from this flow only; the step definition (and any other flow's use of it) is untouched.",
)
def remove_step(flow_id: int, step_id: int):
    logger.info("DELETE /mapper/flows/%s/steps/%s (removes from this flow only)", flow_id, step_id)
    with get_session() as session:
        try:
            MapperFlowService(session).remove_step(flow_id, step_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"removed": True, "flow_id": flow_id, "step_id": step_id}


@router.post(
    "/{flow_id}/run", response_model=MapperFlowRunResponse, summary="Run every step of a flow, in order",
    description="Between steps, if the device's last known screen doesn't match the next step's "
    "expected one, navigates there first automatically (direct route via #24, or app relaunch "
    "and ancestor replay), the same gap-bridging `/device/actions` uses for a single action "
    "(issue #26). Blocks until the whole flow finishes; each step's own result is in `steps`.",
)
def run_flow(flow_id: int, skip_dangerous_actions: bool = True):
    logger.info("POST /mapper/flows/%s/run", flow_id)
    with get_session() as session:
        flow = MapperFlowService(session).get_flow(flow_id)
        if flow is None:
            raise HTTPException(status_code=404, detail="Mapper flow not found")
        # flow.step_usages was eagerly loaded (selectinload) and the session uses
        # expire_on_commit=False, so it's safe to keep using this ORM object after the block closes
        steps = SqlAlchemyMapperFlowRepository(session).ordered_steps(flow)
        result = get_mapper_flow_execution_service().run_flow(flow, steps, skip_dangerous_actions=skip_dangerous_actions)

    return MapperFlowRunResponse(
        flow_id=result["flow_id"],
        name=result["name"],
        package_name=result["package_name"],
        steps=[MapperFlowStepResultResponse(**step_result) for step_result in result["steps"]],
    )


@router.post(
    "/{flow_id}/steps/{ordinal}/run", response_model=MapperFlowStepResultResponse, summary="Run a single step from a saved flow",
    description="Runs against wherever the device currently is, no navigation attempted (unlike "
    "`.../run`, which bridges gaps between steps). `ordinal` is the step's 0-based position in this flow.",
)
def run_step(flow_id: int, ordinal: int, skip_dangerous_actions: bool = True):
    logger.info("POST /mapper/flows/%s/steps/%s/run", flow_id, ordinal)
    with get_session() as session:
        flow = MapperFlowService(session).get_flow(flow_id)
        if flow is None:
            raise HTTPException(status_code=404, detail="Mapper flow not found")
        usage = next((candidate for candidate in flow.step_usages if candidate.ordinal == ordinal), None)
        if usage is None:
            raise HTTPException(status_code=404, detail=f"Step with ordinal {ordinal} not found in flow {flow_id}")
        result = get_mapper_flow_execution_service().run_step(usage.step, skip_dangerous_actions=skip_dangerous_actions)

    return MapperFlowStepResultResponse(**result)
