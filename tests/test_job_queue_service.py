from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from lib.core.utils.clock import utc_now
from lib.dal.local.database import Base, SessionLocal, engine
from lib.domain.models.job_model import JobStatus
from lib.domain.services.job_queue_service import JobQueueService


def reset_db() -> None:
    # this drops and recreates every table, real production data included, if AUTODROID_DATABASE_URL
    # isn't pointed at an isolated test database (issue #29's exact category of mistake, it
    # happened again from this specific fixture: refuse instead of guessing)
    db_url = str(engine.url)
    if "lib/dal/var/autodroid.db" in db_url or "test" not in db_url.lower():
        raise RuntimeError(
            f"reset_db() refuses to run against {db_url!r}: it looks like the real database, "
            "not an isolated test one. Set AUTODROID_DATABASE_URL to a test database first."
        )
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



def test_reconcile_orphaned_running_jobs_resets_them_to_scheduled() -> None:
    # issue #49: a job left RUNNING by a dispatcher process that died mid-job (Ctrl+C, crash) is
    # otherwise invisible to claim_next_job() forever, it only ever looks at PENDING/SCHEDULED
    reset_db()
    with SessionLocal() as session:
        queue = JobQueueService(session, ZoneInfo("UTC"))
        orphan = queue.create_job(job_type="a", adapter_name="adapter", payload={})
        session.commit()
        claimed = queue.claim_next_job()  # simulates the original dispatcher claiming it
        assert claimed.id == orphan.id
        assert claimed.attempt_count == 1
        session.commit()
        # ... then that process died: nothing ever calls mark_completed/mark_failed for it

    with SessionLocal() as session:
        queue = JobQueueService(session, ZoneInfo("UTC"))
        reconciled_count = queue.reconcile_orphaned_running_jobs()
        session.commit()
        assert reconciled_count == 1

    with SessionLocal() as session:
        queue = JobQueueService(session, ZoneInfo("UTC"))
        job = queue.get_job(orphan.id)
        assert job.status == JobStatus.SCHEDULED
        assert job.attempt_count == 1  # not incremented again here, claim_next_job() does that

        claimed_again = queue.claim_next_job()
        assert claimed_again.id == orphan.id
        assert claimed_again.attempt_count == 2


def test_reconcile_orphaned_running_jobs_is_a_noop_when_nothing_is_running() -> None:
    reset_db()
    with SessionLocal() as session:
        queue = JobQueueService(session, ZoneInfo("UTC"))
        queue.create_job(job_type="a", adapter_name="adapter", payload={})  # stays PENDING
        session.commit()

        assert queue.reconcile_orphaned_running_jobs() == 0


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
