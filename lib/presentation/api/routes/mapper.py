from __future__ import annotations

from fastapi import APIRouter, HTTPException

from lib.presentation.api.dependencies import get_mapper_engine, get_session
from lib.domain.models.mapper_types import MapperMode, MapperRunConfig
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.presentation.api.schemas.mapper_schemas import MapperRunRequest, MapperRunResponse, MapperSessionResponse

router = APIRouter(prefix="/mapper", tags=["mapper"])


@router.post("/run", response_model=MapperRunResponse)
def run_mapper(payload: MapperRunRequest):
    try:
        mode = MapperMode(payload.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid mapper mode: {payload.mode}") from exc
    result = get_mapper_engine().run(
        MapperRunConfig(
            package_name=payload.package_name,
            mode=mode,
            skip_dangerous_actions=payload.skip_dangerous_actions,
        )
    )
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
