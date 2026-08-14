from __future__ import annotations

from fastapi import APIRouter, HTTPException

from lib.presentation.api.dependencies import get_session, get_settings
from lib.domain.services.job_queue_service import JobQueueService
from lib.domain.services.worker_service import WorkerService
from lib.presentation.api.schemas.job_schemas import CreateJobRequest, JobResponse, ReprioritizeJobRequest, WorkerResponse

router = APIRouter()


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/jobs", response_model=JobResponse)
def create_job(payload: CreateJobRequest):
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


@router.get("/jobs", response_model=list[JobResponse])
def list_jobs(limit: int = 50):
    settings = get_settings()
    with get_session() as session:
        queue = JobQueueService(session, settings.timezone)
        jobs = queue.list_jobs(limit=limit)
        return [JobResponse.model_validate(job, from_attributes=True) for job in jobs]


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: int):
    settings = get_settings()
    with get_session() as session:
        queue = JobQueueService(session, settings.timezone)
        job = queue.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return JobResponse.model_validate(job, from_attributes=True)


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(job_id: int):
    settings = get_settings()
    with get_session() as session:
        queue = JobQueueService(session, settings.timezone)
        try:
            job = queue.cancel_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JobResponse.model_validate(job, from_attributes=True)


@router.post("/jobs/{job_id}/reprioritize", response_model=JobResponse)
def reprioritize_job(job_id: int, payload: ReprioritizeJobRequest):
    settings = get_settings()
    with get_session() as session:
        queue = JobQueueService(session, settings.timezone)
        try:
            job = queue.reprioritize_job(job_id, payload.priority)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JobResponse.model_validate(job, from_attributes=True)


@router.get("/workers/main", response_model=WorkerResponse)
def get_worker():
    settings = get_settings()
    with get_session() as session:
        worker = WorkerService(session).ensure_worker(settings.worker_name)
        return WorkerResponse.model_validate(worker, from_attributes=True)
