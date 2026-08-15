from __future__ import annotations

from fastapi import APIRouter, HTTPException

from lib.core.logs import get_logger
from lib.presentation.api.dependencies import get_session, get_settings
from lib.domain.services.job_queue_service import JobQueueService
from lib.domain.services.worker_service import WorkerService
from lib.presentation.api.schemas.job_schemas import CreateJobRequest, JobResponse, ReprioritizeJobRequest, WorkerResponse

router = APIRouter(tags=["jobs"])
logger = get_logger(__name__)


@router.get("/health", tags=["health"], summary="Liveness check")
def healthcheck() -> dict[str, str]:
    """No dependencies checked, just confirms the API process is up and responding."""
    return {"status": "ok"}


@router.post(
    "/jobs", response_model=JobResponse, summary="Schedule a background job",
    description="Queues work for the single worker to pick up: a one-off run (`run_after`), a "
    "recurring one (`cron_expression`), or ASAP (neither set). `execution_window_start`/`_end` "
    "restrict which time of day it's allowed to run (e.g. \"09:00\"/\"18:00\"). `payload` is "
    "opaque, its shape depends on `job_type` (e.g. `mapper.remap` expects "
    "{\"package_name\": str, \"strategy\": \"override\"|\"complement\", \"mode\": str}).",
)
def create_job(payload: CreateJobRequest):
    logger.info("POST /jobs job_type=%s adapter=%s", payload.job_type, payload.adapter_name)
    settings = get_settings()
    with get_session() as session:
        queue = JobQueueService(session, settings.timezone)
        job = queue.create_job(
            job_type=payload.job_type,
            adapter_name=payload.adapter_name,
            payload=payload.payload,
            priority=payload.priority,
            run_after=payload.run_after,
            cron_expression=payload.cron_expression,
            execution_window_start=payload.execution_window_start,
            execution_window_end=payload.execution_window_end,
            max_attempts=payload.max_attempts,
        )
        return JobResponse.model_validate(job, from_attributes=True)


@router.get("/jobs", response_model=list[JobResponse], summary="List recent jobs, newest first")
def list_jobs(limit: int = 50):
    settings = get_settings()
    with get_session() as session:
        queue = JobQueueService(session, settings.timezone)
        jobs = queue.list_jobs(limit=limit)
        return [JobResponse.model_validate(job, from_attributes=True) for job in jobs]


@router.get("/jobs/{job_id}", response_model=JobResponse, summary="Get one job's current status")
def get_job(job_id: int):
    settings = get_settings()
    with get_session() as session:
        queue = JobQueueService(session, settings.timezone)
        job = queue.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return JobResponse.model_validate(job, from_attributes=True)


@router.post(
    "/jobs/{job_id}/cancel", response_model=JobResponse, summary="Cancel a job",
    description="Pending or scheduled: cancelled immediately. Already running: cooperative "
    "cancellation is requested, the job stops at its own next safe checkpoint, not instantly.",
)
def cancel_job(job_id: int):
    logger.info("POST /jobs/%s/cancel", job_id)
    settings = get_settings()
    with get_session() as session:
        queue = JobQueueService(session, settings.timezone)
        try:
            job = queue.cancel_job(job_id)
        except ValueError as exc:
            logger.warning("Cancel failed for job %s: %s", job_id, exc)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JobResponse.model_validate(job, from_attributes=True)


@router.post("/jobs/{job_id}/reprioritize", response_model=JobResponse, summary="Change a queued job's priority")
def reprioritize_job(job_id: int, payload: ReprioritizeJobRequest):
    logger.info("POST /jobs/%s/reprioritize priority=%s", job_id, payload.priority)
    settings = get_settings()
    with get_session() as session:
        queue = JobQueueService(session, settings.timezone)
        try:
            job = queue.reprioritize_job(job_id, payload.priority)
        except ValueError as exc:
            logger.warning("Reprioritize failed for job %s: %s", job_id, exc)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JobResponse.model_validate(job, from_attributes=True)


@router.get(
    "/workers/main", response_model=WorkerResponse, summary="Get the worker's current state",
    description="The single worker that processes the job queue and is the only thing that "
    "touches the physical device: whether it's idle or busy, and what it's currently working on.",
)
def get_worker():
    settings = get_settings()
    with get_session() as session:
        worker = WorkerService(session).ensure_worker(settings.worker_name)
        return WorkerResponse.model_validate(worker, from_attributes=True)
