from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from lib.core.utils.clock import utc_now
from lib.domain.models.worker_state_model import WorkerState, WorkerStatus


class WorkerService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def ensure_worker(self, worker_name: str) -> WorkerState:
        worker = self.session.scalar(select(WorkerState).where(WorkerState.worker_name == worker_name))
        if worker is None:
            worker = WorkerState(worker_name=worker_name, status=WorkerStatus.IDLE, metadata_json={})
            self.session.add(worker)
            self.session.flush()
        return worker

    def heartbeat(self, worker_name: str, *, status: WorkerStatus | None = None, current_job_id: int | None = None) -> WorkerState:
        worker = self.ensure_worker(worker_name)
        worker.last_heartbeat_at = utc_now()
        if status is not None:
            worker.status = status
        worker.current_job_id = current_job_id
        return worker
