from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from lib.core.utils.clock import utc_now
from lib.dal.local.database import Base, SessionLocal, engine
from lib.domain.models.job_model import JobStatus
from lib.domain.services.job_queue_service import JobQueueService


def reset_db() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)



def test_claim_next_job_respects_highest_priority() -> None:
    reset_db()
    with SessionLocal() as session:
        queue = JobQueueService(session, ZoneInfo("UTC"))
        queue.create_job(job_type="a", adapter_name="adapter", payload={}, priority=1)
        high = queue.create_job(job_type="b", adapter_name="adapter", payload={}, priority=10)
        session.commit()

    with SessionLocal() as session:
        queue = JobQueueService(session, ZoneInfo("UTC"))
        claimed = queue.claim_next_job()
        assert claimed is not None
        assert claimed.id == high.id
        assert claimed.status == JobStatus.RUNNING



def test_claim_next_job_respects_execution_window() -> None:
    reset_db()
    now = utc_now().astimezone(ZoneInfo("UTC"))
    future = (now + timedelta(hours=2)).time().replace(second=0, microsecond=0, tzinfo=None)
    future_end = (now + timedelta(hours=2, minutes=30)).time().replace(second=0, microsecond=0, tzinfo=None)

    with SessionLocal() as session:
        queue = JobQueueService(session, ZoneInfo("UTC"))
        queue.create_job(
            job_type="windowed",
            adapter_name="adapter",
            payload={},
            priority=5,
            execution_window_start=future,
            execution_window_end=future_end,
        )
        session.commit()

    with SessionLocal() as session:
        queue = JobQueueService(session, ZoneInfo("UTC"))
        claimed = queue.claim_next_job()
        assert claimed is None
