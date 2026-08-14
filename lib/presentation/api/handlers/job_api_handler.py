from __future__ import annotations

from sqlalchemy.orm import Session

from lib.domain.services.job_queue_service import JobQueueService
from lib.domain.services.worker_service import WorkerService


class JobApiHandler:
    def __init__(self, session: Session, timezone) -> None:
        self.session = session
        self.queue = JobQueueService(session, timezone)
        self.worker_service = WorkerService(session)
