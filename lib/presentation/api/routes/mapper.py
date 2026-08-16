from __future__ import annotations

from fastapi import APIRouter, HTTPException

from lib.core.logs import get_logger
from lib.presentation.api.dependencies import get_mapper_engine, get_mapper_export_service, get_mapper_on_demand_service, get_session, get_settings
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode, MapperRunConfig, MapperSessionStatus
from lib.dal.local.mapper_flow_repository import SqlAlchemyMapperFlowRepository
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.services.job_queue_service import JobQueueService
from lib.domain.services.mapper_churn_service import MapperChurnService
from lib.domain.services.mapper_progress_service import MapperProgressService
from lib.presentation.api.schemas.mapper_schemas import (
    MapperActivityResponse,
    MapperActionResponse,
    MapperChurnStatusResponse,
    MapperExportResponse,
    MapperGraphResponse,
    MapperNodeResponse,
    MapperOnDemandActionRequest,
    MapperOnDemandActionResponse,
    MapperOnDemandInspectResponse,
    MapperOnDemandStartResponse,
    MapperRemapCandidateResponse,
    MapperRemapJobResponse,
    MapperRemapRequest,
    MapperRemapResponse,
    MapperRunRequest,
    MapperRunResponse,
    MapperRuntimeSnapshotResponse,
    MapperScreenProgressResponse,
    MapperScreenRemapResponse,
    MapperSessionProgressResponse,
    MapperScreenResponse,
    MapperSessionResponse,
    MapperTransitionResponse,
)

router = APIRouter(prefix="/mapper", tags=["mapper"])
logger = get_logger(__name__)


@router.post(
    "/run", response_model=MapperRunResponse, summary="Map an app's UI structure",
    description="Explores the app (screens, clickable elements, transitions between them), "
    "structural only, never per-user content: two people's profile pages are recorded as one "
    "type, not one entry each (issue #30). `mode` is `light` (broad, shallow overview), `medium` "
    "(a few levels deep), or `deep` (maps everything, stops once nothing new turns up). Calling "
    "this again for an already-mapped package reuses the existing session unless `override` "
    "(remap from scratch) or `complement` (go deeper without redoing what's known) is set; "
    "those two are mutually exclusive. This call blocks until mapping finishes.",
)
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


@router.get("/apps", response_model=list[str], summary="List installed app packages visible to the device")
def list_installed_packages():
    return get_mapper_on_demand_service().list_packages()


@router.post("/apps/{package_name}/start", response_model=MapperOnDemandStartResponse, summary="Start an app with a fresh launch for on-demand mapper use")
def start_mapper_app(package_name: str):
    try:
        return MapperOnDemandStartResponse(**get_mapper_on_demand_service().start_app(package_name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Unable to start {package_name}: {exc}") from exc


@router.get("/on-demand/inspect", response_model=MapperOnDemandInspectResponse, summary="Inspect the current screen with mapper-aware persistence")
def inspect_on_demand_screen(package_name: str, session_id: int | None = None):
    try:
        return MapperOnDemandInspectResponse(**get_mapper_on_demand_service().inspect(package_name, session_id=session_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/on-demand/actions", response_model=MapperOnDemandActionResponse, summary="Execute one guided on-demand mapper action and persist what was learned")
def execute_on_demand_mapper_action(payload: MapperOnDemandActionRequest):
    try:
        return MapperOnDemandActionResponse(**get_mapper_on_demand_service().act(
            payload.package_name,
            session_id=payload.session_id,
            action_id=payload.action_id,
            bounds=payload.bounds,
            action_type=payload.action_type,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions", response_model=list[MapperSessionResponse], summary="List mapper sessions, newest first")
def list_mapper_sessions(limit: int = 50):
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        sessions = repository.list_sessions(limit=limit)
        return [MapperSessionResponse.model_validate(item, from_attributes=True) for item in sessions]


@router.get("/sessions/{session_id}", response_model=MapperSessionResponse, summary="Get one mapper session")
def show_mapper_session(session_id: int):
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.get_session(session_id)
        if mapper_session is None:
            raise HTTPException(status_code=404, detail="Mapper session not found")
        return MapperSessionResponse.model_validate(mapper_session, from_attributes=True)


@router.get("/sessions/{session_id}/progress", response_model=MapperSessionProgressResponse, summary="Get structured live progress for a mapper session")
def show_mapper_session_progress(session_id: int):
    with get_session() as session:
        progress = MapperProgressService(session)
        try:
            payload = progress.get_session_progress(session_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return MapperSessionProgressResponse(**payload)


@router.get("/sessions/{session_id}/progress/activity", response_model=MapperActivityResponse, summary="Get the mapper's current live activity for a session")
def show_mapper_session_activity(session_id: int):
    with get_session() as session:
        progress = MapperProgressService(session)
        try:
            payload = progress.get_current_activity(session_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return MapperActivityResponse(**payload)


@router.get("/sessions/{session_id}/progress/screens", response_model=list[MapperScreenProgressResponse], summary="List per-screen progress for a mapper session")
def list_mapper_screen_progress(session_id: int):
    with get_session() as session:
        progress = MapperProgressService(session)
        try:
            payload = progress.list_screen_progress(session_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return [MapperScreenProgressResponse(**item) for item in payload]


@router.get("/sessions/{session_id}/progress/screens/{screen_id}", response_model=MapperScreenProgressResponse, summary="Get one screen's structured mapper progress")
def show_mapper_screen_progress(session_id: int, screen_id: int):
    with get_session() as session:
        progress = MapperProgressService(session)
        try:
            payload = progress.get_screen_progress(session_id, screen_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return MapperScreenProgressResponse(**payload)


@router.get("/sessions/{session_id}/churn", response_model=MapperChurnStatusResponse, summary="Get live operational churn scoring and recommendations for a mapper session")
def show_mapper_session_churn(session_id: int):
    with get_session() as session:
        churn = MapperChurnService(session, get_settings())
        try:
            payload = churn.get_live_churn(session_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return MapperChurnStatusResponse(**payload)


@router.get("/sessions/{session_id}/churn/telemetry", response_model=list[MapperRuntimeSnapshotResponse], summary="List persisted runtime telemetry snapshots for a mapper session")
def list_mapper_session_runtime_telemetry(session_id: int, limit: int = 50):
    with get_session() as session:
        churn = MapperChurnService(session, get_settings())
        try:
            payload = churn.list_runtime_snapshots(session_id, limit=limit)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return [MapperRuntimeSnapshotResponse(**item) for item in payload]


@router.post(
    "/sessions/{session_id}/screens/{screen_id}/remap", response_model=MapperScreenRemapResponse, summary="Remap one specific screen inline",
    description="Replays the path from the app root to a previously mapped screen, forces that screen's `expanded` flag back to false, and re-explores it inline so new candidates below it are captured immediately (issue #41).",
)
def remap_mapper_screen(session_id: int, screen_id: int):
    logger.info("POST /mapper/sessions/%s/screens/%s/remap", session_id, screen_id)
    try:
        result = get_mapper_engine().remap_screen(session_id, screen_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MapperScreenRemapResponse(**result)


@router.post(
    "/sessions/{session_id}/export", response_model=MapperExportResponse, summary="Export a session's map as local JSON files",
    description="Writes the session's screens/actions/transitions to disk as a structured, "
    "human-readable JSON export (issue #15), for inspection or archival outside the database.",
)
def export_mapper_session(session_id: int):
    logger.info("POST /mapper/sessions/%s/export", session_id)
    export_path = get_mapper_export_service().export_session(session_id, get_settings().output_dir / "mappers")
    return MapperExportResponse(session_id=session_id, export_path=str(export_path))


@router.get(
    "/sessions/{session_id}/screens", response_model=list[MapperScreenResponse], summary="List screens discovered in a session",
    description="One entry per structurally distinct screen type found (not per visit, and not "
    "per person/data instance for pages like a profile, see issue #30). Use "
    "`GET .../screens/{screen_id}` for a single screen's full node list.",
)
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


@router.get(
    "/sessions/{session_id}/screens/{screen_id}", response_model=MapperScreenResponse, summary="Get one screen with its full node list",
    description="Includes every node captured on that screen (text, content_desc, resource_id, "
    "class_name, bounds, clickable/scrollable/... flags), the same shape `dump_nodes` returns "
    "live via `/device/actions`, but from what was recorded while mapping.",
)
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


@router.get(
    "/sessions/{session_id}/actions", response_model=list[MapperActionResponse], summary="List actions discovered in a session",
    description="Every clickable candidate the mapper found, filterable by `screen_id`, `safety` "
    "(`safe`|`dangerous`, dangerous ones are blocked by default while mapping), and `executed`. "
    "An action's `id` is what `/device/actions` takes as `target_action_id` to fire it on demand.",
)
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


@router.get(
    "/sessions/{session_id}/transitions", response_model=list[MapperTransitionResponse], summary="List transitions (edges) discovered in a session",
    description="One entry per action tried: `to_screen_id` is set only when it actually led "
    "somewhere new (`result_type=\"clicked\"`); a null `to_screen_id` means it failed, was "
    "blocked as dangerous, or left the app entirely (`result_type` says which).",
)
def list_mapper_transitions(session_id: int):
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        transitions = repository.list_transitions(session_id)
        return [MapperTransitionResponse.model_validate(transition, from_attributes=True) for transition in transitions]


@router.get(
    "/sessions/{session_id}/graph", response_model=MapperGraphResponse, summary="Get the whole session as one graph",
    description="Every screen and every transition in a single response, for a caller that "
    "wants the full picture at once instead of paging through the separate endpoints.",
)
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


@router.get(
    "/apps/{package_name}/latest-session", response_model=MapperSessionResponse, summary="Get an app's most recent completed map",
    description="404 if the package was never fully mapped. Its `id` is what `source_session_id` "
    "takes when creating a MapperFlow, and what `/device/actions`' `current_screen_id`/"
    "`target_screen_id` values belong to.",
)
def get_latest_mapper_session(package_name: str):
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.get_latest_session(package_name, status=MapperSessionStatus.COMPLETED)
        if mapper_session is None:
            raise HTTPException(status_code=404, detail=f"No completed mapper session found for {package_name}")
        return MapperSessionResponse.model_validate(mapper_session, from_attributes=True)


@router.get(
    "/apps/remap-candidates", response_model=list[MapperRemapCandidateResponse], summary="List apps whose map looks stale",
    description="Packages with enough recorded interaction failures (a selector that stopped "
    "matching, a click that stopped working) to suggest the app's real UI drifted from what was "
    "mapped (issue #21). Opt-in: returns empty unless auto-remap is enabled in settings, failures "
    "still accumulate in the background either way. `threshold` overrides the configured minimum "
    "failure count for this call only.",
)
def list_remap_candidates(threshold: int | None = None):
    settings = get_settings()
    if not settings.mapper_auto_remap_enabled:
        # opt-in (issue #21): with auto-remap disabled, failures still accumulate in the
        # background, but nothing surfaces as "actionable" until it's turned on
        return []
    resolved_threshold = threshold if threshold is not None else settings.mapper_auto_remap_threshold
    with get_session() as session:
        repository = SqlAlchemyMapperFlowRepository(session)
        candidates = repository.list_remap_candidates(resolved_threshold)
        return [MapperRemapCandidateResponse(package_name=package_name, unresolved_failure_count=count) for package_name, count in candidates]


@router.post(
    "/apps/remap", response_model=MapperRemapResponse, summary="Queue a remap job for one or more apps",
    description="Queues background jobs (doesn't run inline, doesn't block): `package_names` "
    "picks specific apps, or `all=true` remaps every current remap candidate. `strategy` is "
    "`override` (remap from scratch) or `complement` (extend the existing map deeper without "
    "redoing what's known); `mode` is the same `light`/`medium`/`deep` as `POST /mapper/run`. "
    "Queuing this also resolves the failures that made those packages candidates in the first place.",
)
def remap_apps(payload: MapperRemapRequest):
    logger.info("POST /mapper/apps/remap package_names=%s all=%s strategy=%s", payload.package_names, payload.all, payload.strategy)
    settings = get_settings()
    with get_session() as session:
        if payload.all:
            candidates = SqlAlchemyMapperFlowRepository(session).list_remap_candidates(settings.mapper_auto_remap_threshold)
            package_names = [package_name for package_name, _ in candidates]
        else:
            package_names = payload.package_names or []
        if not package_names:
            raise HTTPException(status_code=400, detail="No package selected: provide 'package_names' or 'all=true' with existing candidates")

        queue = JobQueueService(session, settings.timezone)
        queued = []
        for package_name in package_names:
            job = queue.create_job(
                job_type="mapper.remap",
                adapter_name="mapper",
                payload={"package_name": package_name, "strategy": payload.strategy, "mode": payload.mode},
            )
            queued.append(MapperRemapJobResponse(package_name=package_name, job_id=job.id))
        return MapperRemapResponse(queued=queued)
