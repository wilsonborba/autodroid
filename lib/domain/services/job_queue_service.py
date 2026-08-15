from __future__ import annotations

from datetime import datetime, time
from typing import Any

from croniter import croniter
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from lib.core.logs import get_logger
from lib.core.utils.clock import local_now, utc_now
from lib.domain.models.job_model import Job, JobEvent, JobStatus


class JobQueueService:
    def __init__(self, session: Session, timezone) -> None:
        self.session = session
        self.timezone = timezone
        self.logger = get_logger(__name__)

    def create_job(
        self,
        *,
        job_type: str,
        adapter_name: str,
        payload: dict[str, Any],
        priority: int = 100,
        run_after: datetime | None = None,
        cron_expression: str | None = None,
        execution_window_start: time | None = None,
        execution_window_end: time | None = None,
        max_attempts: int = 3,
    ) -> Job:
        resolved_run_after = run_after
        status = JobStatus.PENDING
        if cron_expression and resolved_run_after is None:
            resolved_run_after = croniter(cron_expression, utc_now()).get_next(datetime)
            status = JobStatus.SCHEDULED
        elif resolved_run_after and resolved_run_after > utc_now():
            status = JobStatus.SCHEDULED

        job = Job(
            job_type=job_type,
            adapter_name=adapter_name,
            payload_json=payload,
            status=status,
            priority=priority,
            run_after=resolved_run_after,
            cron_expression=cron_expression,
            execution_window_start=execution_window_start,
            execution_window_end=execution_window_end,
            max_attempts=max_attempts,
        )
        self.session.add(job)
        self.session.flush()
        self.record_event(job.id, "job_created", f"Job {job.job_type} created", payload)
        self.logger.info("Created job %s (%s) priority=%s", job.id, job.job_type, job.priority)
        return job

    def list_jobs(self, limit: int = 50) -> list[Job]:
        stmt: Select[tuple[Job]] = (
            select(Job)
            .options(selectinload(Job.events))
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def get_job(self, job_id: int) -> Job | None:
        stmt = select(Job).options(selectinload(Job.events)).where(Job.id == job_id)
        return self.session.scalar(stmt)

    def reprioritize_job(self, job_id: int, priority: int) -> Job:
        job = self._require_job(job_id)
        job.priority = priority
        self.record_event(job.id, "job_reprioritized", f"Priority changed to {priority}", {"priority": priority})
        return job

    def cancel_job(self, job_id: int) -> Job:
        job = self._require_job(job_id)
        if job.status in {JobStatus.PENDING, JobStatus.SCHEDULED, JobStatus.PAUSED}:
            job.status = JobStatus.CANCELLED
            job.finished_at = utc_now()
            self.record_event(job.id, "job_cancelled", "Job cancelled before execution", None)
        elif job.status == JobStatus.RUNNING:
            job.cancel_requested = True
            self.record_event(job.id, "cancel_requested", "Cooperative cancellation requested", None)
        return job

    def claim_next_job(self) -> Job | None:
        now = utc_now()
        stmt = (
            select(Job)
            .where(Job.status.in_([JobStatus.PENDING, JobStatus.SCHEDULED]))
            .order_by(Job.priority.desc(), Job.run_after.asc().nullsfirst(), Job.created_at.asc())
        )
        jobs = list(self.session.scalars(stmt))
        for job in jobs:
            if not self._is_due(job, now):
                continue
            if not self._is_within_execution_window(job):
                continue
            job.status = JobStatus.RUNNING
            job.started_at = job.started_at or now
            job.attempt_count += 1
            self.record_event(job.id, "job_claimed", "Job claimed by dispatcher", None)
            self.logger.info("Claimed job %s (%s)", job.id, job.job_type)
            return job
        return None

    def mark_completed(self, job_id: int, result: dict[str, Any]) -> Job:
        job = self._require_job(job_id)
        job.status = JobStatus.COMPLETED
        job.result_json = result
        job.finished_at = utc_now()
        self.record_event(job.id, "job_completed", "Job completed successfully", result)
        self.logger.info("Completed job %s (%s)", job.id, job.job_type)
        self._enqueue_next_recurring_run(job)
        return job

    def mark_failed(self, job_id: int, error_message: str) -> Job:
        job = self._require_job(job_id)
        if job.cancel_requested:
            job.status = JobStatus.CANCELLED
            self.record_event(job.id, "job_cancelled", "Job cancelled during execution", None)
        elif job.attempt_count < job.max_attempts:
            job.status = JobStatus.SCHEDULED
            job.run_after = utc_now()
            self.record_event(job.id, "job_retry_scheduled", error_message, {"attempt_count": job.attempt_count})
        else:
            job.status = JobStatus.FAILED
            job.finished_at = utc_now()
            job.error_message = error_message
            self.record_event(job.id, "job_failed", error_message, None)
            self.logger.error("Job %s failed: %s", job.id, error_message)
        return job

    def record_event(self, job_id: int, event_type: str, message: str, data: dict[str, Any] | None) -> JobEvent:
        event = JobEvent(job_id=job_id, event_type=event_type, message=message, data_json=data)
        self.session.add(event)
        return event

    def _enqueue_next_recurring_run(self, job: Job) -> None:
        if not job.cron_expression:
            return
        next_run = croniter(job.cron_expression, job.run_after or utc_now()).get_next(datetime)
        self.create_job(
            job_type=job.job_type,
            adapter_name=job.adapter_name,
            payload=job.payload_json,
            priority=job.priority,
            run_after=next_run,
            cron_expression=job.cron_expression,
            execution_window_start=job.execution_window_start,
            execution_window_end=job.execution_window_end,
            max_attempts=job.max_attempts,
        )

    def _is_due(self, job: Job, now: datetime) -> bool:
        return job.run_after is None or job.run_after <= now

    def _is_within_execution_window(self, job: Job) -> bool:
        if job.execution_window_start is None or job.execution_window_end is None:
            return True
        current_time = local_now(self.timezone).time().replace(tzinfo=None)
        start = job.execution_window_start
        end = job.execution_window_end
        if start <= end:
            return start <= current_time <= end
        return current_time >= start or current_time <= end

    def _require_job(self, job_id: int) -> Job:
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        return job
