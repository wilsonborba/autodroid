from __future__ import annotations

from datetime import datetime, time

from sqlalchemy.orm import Session

from lib.domain.services.job_queue_service import JobQueueService


class JobHandler:
    def __init__(self, session: Session, timezone) -> None:
        self.queue = JobQueueService(session, timezone)

    def create_job(
        self,
        *,
        job_type: str,
        adapter_name: str,
        payload: dict,
        priority: int,
        run_after: datetime | None,
        cron_expression: str | None,
        execution_window_start: time | None,
        execution_window_end: time | None,
        max_attempts: int,
    ):
        return self.queue.create_job(
            job_type=job_type,
            adapter_name=adapter_name,
            payload=payload,
            priority=priority,
            run_after=run_after,
            cron_expression=cron_expression,
            execution_window_start=execution_window_start,
            execution_window_end=execution_window_end,
            max_attempts=max_attempts,
        )
