from __future__ import annotations

import time
from typing import Any

from lib.core.logs import get_logger
from lib.domain.models.worker_state_model import WorkerStatus
from lib.domain.services.automation_service import AutomationRegistryService
from lib.domain.services.job_queue_service import JobQueueService
from lib.domain.services.worker_service import WorkerService


class DispatcherService:
    def __init__(
        self,
        session_factory,
        registry: AutomationRegistryService,
        timezone,
        worker_name: str,
        poll_interval_seconds: float,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.timezone = timezone
        self.worker_name = worker_name
        self.poll_interval_seconds = poll_interval_seconds
        self.logger = get_logger(__name__)

    def run_once(self) -> dict[str, Any]:
        with self.session_factory() as session:
            queue_service = JobQueueService(session, self.timezone)
            worker_service = WorkerService(session)
            worker = worker_service.ensure_worker(self.worker_name)
            if not worker.execution_enabled:
                worker_service.heartbeat(self.worker_name, status=WorkerStatus.DISABLED)
                return {"worker": self.worker_name, "status": "disabled"}

            job = queue_service.claim_next_job()
            if job is None:
                worker_service.heartbeat(self.worker_name, status=WorkerStatus.IDLE, current_job_id=None)
                return {"worker": self.worker_name, "status": "idle"}

            worker_service.heartbeat(self.worker_name, status=WorkerStatus.RUNNING, current_job_id=job.id)
            # commit the claim right away, before running the job (issue #46): a job runner can
            # take minutes (a deep mapper remap, for instance), and without this the claim +
            # "running" heartbeat sit inside one open transaction the whole time, invisible to
            # every other connection (GET /jobs/{id}, GET /workers/main just show stale
            # pre-claim data until the job finishes) and a Ctrl+C mid-run rolls the claim back
            # too, making it look like the job never even started even though the runner's own
            # separate session may already have persisted real work
            session.commit()

            try:
                runner = self.registry.get_runner(job.job_type)
                result = runner(job)
                queue_service.mark_completed(job.id, result)
                worker_service.heartbeat(self.worker_name, status=WorkerStatus.IDLE, current_job_id=None)
                session.commit()
                return {"worker": self.worker_name, "status": "completed", "job_id": job.id}
            except Exception as exc:
                self.logger.exception("Job %s failed", job.id)
                queue_service.mark_failed(job.id, str(exc))
                worker_service.heartbeat(self.worker_name, status=WorkerStatus.IDLE, current_job_id=None)
                session.commit()
                return {"worker": self.worker_name, "status": "failed", "job_id": job.id, "error": str(exc)}

    def run_loop(self, iterations: int | None = None) -> None:
        count = 0
        while iterations is None or count < iterations:
            self.run_once()
            count += 1
            time.sleep(self.poll_interval_seconds)
