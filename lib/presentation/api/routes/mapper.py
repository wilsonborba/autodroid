from __future__ import annotations

from fastapi import APIRouter, HTTPException

from lib.core.logs import get_logger
from lib.presentation.api.dependencies import get_mapper_engine, get_mapper_export_service, get_session, get_settings
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode, MapperRunConfig, MapperSessionStatus
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.presentation.api.schemas.mapper_schemas import (
    MapperActionResponse,
    MapperExportResponse,
    MapperGraphResponse,
    MapperNodeResponse,
    MapperRunRequest,
    MapperRunResponse,
    MapperScreenResponse,
    MapperSessionResponse,
    MapperTransitionResponse,
)

router = APIRouter(prefix="/mapper", tags=["mapper"])
logger = get_logger(__name__)


@router.post("/run", response_model=MapperRunResponse)
def run_mapper(payload: MapperRunRequest):
    logger.info("POST /mapper/run package=%s mode=%s", payload.package_name, payload.mode)
    if payload.override and payload.complement:
        raise HTTPException(status_code=400, detail="override and complement cannot both be set")
    try:
        mode = MapperMode(payload.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid mapper mode: {payload.mode}") from exc
    try:
        result = get_mapper_engine().run(
            MapperRunConfig(
                package_name=payload.package_name,
                mode=mode,
                skip_dangerous_actions=payload.skip_dangerous_actions,
                override=payload.override,
                complement=payload.complement,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MapperRunResponse(**result)


@router.get("/sessions", response_model=list[MapperSessionResponse])
def list_mapper_sessions(limit: int = 50):
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        sessions = repository.list_sessions(limit=limit)
        return [MapperSessionResponse.model_validate(item, from_attributes=True) for item in sessions]


@router.get("/sessions/{session_id}", response_model=MapperSessionResponse)
def show_mapper_session(session_id: int):
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.get_session(session_id)
        if mapper_session is None:
            raise HTTPException(status_code=404, detail="Mapper session not found")
        return MapperSessionResponse.model_validate(mapper_session, from_attributes=True)


@router.post("/sessions/{session_id}/export", response_model=MapperExportResponse)
def export_mapper_session(session_id: int):
    logger.info("POST /mapper/sessions/%s/export", session_id)
    export_path = get_mapper_export_service().export_session(session_id, get_settings().output_dir / "mappers")
    return MapperExportResponse(session_id=session_id, export_path=str(export_path))


@router.get("/sessions/{session_id}/screens", response_model=list[MapperScreenResponse])
def list_mapper_screens(session_id: int):
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        screens = repository.list_screens(session_id)
        return [
            MapperScreenResponse(
                id=screen.id,
                screen_key=screen.screen_key,
                fingerprint=screen.fingerprint,
                depth=screen.depth,
                ordinal=screen.ordinal,
                visit_count=screen.visit_count,
                node_count=len(screen.nodes),
            )
            for screen in screens
        ]


@router.get("/sessions/{session_id}/screens/{screen_id}", response_model=MapperScreenResponse)
def show_mapper_screen(session_id: int, screen_id: int):
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        screen = repository.get_screen(screen_id)
        if screen is None or screen.session_id != session_id:
            raise HTTPException(status_code=404, detail="Mapper screen not found")
        return MapperScreenResponse(
            id=screen.id,
            screen_key=screen.screen_key,
            fingerprint=screen.fingerprint,
            depth=screen.depth,
            ordinal=screen.ordinal,
            visit_count=screen.visit_count,
            node_count=len(screen.nodes),
            nodes=[MapperNodeResponse.model_validate(node, from_attributes=True) for node in screen.nodes],
        )


@router.get("/sessions/{session_id}/actions", response_model=list[MapperActionResponse])
def list_mapper_actions(session_id: int, screen_id: int | None = None, safety: str | None = None, executed: bool | None = None):
    safety_filter = None
    if safety is not None:
        try:
            safety_filter = MapperActionSafety(safety)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid safety filter: {safety}") from exc
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        actions = repository.list_actions(session_id, screen_id=screen_id, safety=safety_filter, executed=executed)
        return [
            MapperActionResponse(
                id=action.id,
                screen_id=action.screen_id,
                node_id=action.node_id,
                action_key=action.action_key,
                action_type=action.action_type,
                label=action.label,
                safety=action.safety.value,
                skipped_reason=action.skipped_reason,
                executed=action.executed,
                success=action.success,
            )
            for action in actions
        ]


@router.get("/sessions/{session_id}/transitions", response_model=list[MapperTransitionResponse])
def list_mapper_transitions(session_id: int):
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        transitions = repository.list_transitions(session_id)
        return [MapperTransitionResponse.model_validate(transition, from_attributes=True) for transition in transitions]


@router.get("/sessions/{session_id}/graph", response_model=MapperGraphResponse)
def show_mapper_graph(session_id: int):
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.get_session(session_id)
        if mapper_session is None:
            raise HTTPException(status_code=404, detail="Mapper session not found")
        return MapperGraphResponse(
            session_id=mapper_session.id,
            package_name=mapper_session.package_name,
            screens=[
                MapperScreenResponse(
                    id=screen.id,
                    screen_key=screen.screen_key,
                    fingerprint=screen.fingerprint,
                    depth=screen.depth,
                    ordinal=screen.ordinal,
                    visit_count=screen.visit_count,
                    node_count=len(screen.nodes),
                )
                for screen in mapper_session.screens
            ],
            transitions=[MapperTransitionResponse.model_validate(t, from_attributes=True) for t in mapper_session.transitions],
        )


@router.get("/apps/{package_name}/latest-session", response_model=MapperSessionResponse)
def get_latest_mapper_session(package_name: str):
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.get_latest_session(package_name, status=MapperSessionStatus.COMPLETED)
        if mapper_session is None:
            raise HTTPException(status_code=404, detail=f"No completed mapper session found for {package_name}")
        return MapperSessionResponse.model_validate(mapper_session, from_attributes=True)
