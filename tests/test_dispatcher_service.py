from __future__ import annotations

from zoneinfo import ZoneInfo

from sqlalchemy import select

from lib.dal.local.database import Base, SessionLocal, engine, session_scope
from lib.domain.models.job_model import Job, JobStatus
from lib.domain.models.worker_state_model import WorkerState, WorkerStatus
from lib.domain.services.automation_service import AutomationRegistryService
from lib.domain.services.dispatcher_service import DispatcherService
from lib.domain.services.job_queue_service import JobQueueService

WORKER_NAME = "test-worker"


def reset_db() -> None:
    # same guard as tests/test_job_queue_service.py: refuse to run against anything that looks
    # like the real database (issue #29's category of mistake)
    db_url = str(engine.url)
    if "lib/dal/var/autodroid.db" in db_url or "test" not in db_url.lower():
        raise RuntimeError(
            f"reset_db() refuses to run against {db_url!r}: it looks like the real database, "
            "not an isolated test one. Set AUTODROID_DATABASE_URL to a test database first."
        )
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _create_job(job_type: str) -> int:
    with SessionLocal() as session:
        queue = JobQueueService(session, ZoneInfo("UTC"))
        job = queue.create_job(job_type=job_type, adapter_name="test", payload={})
        session.commit()
        return job.id


def _build_dispatcher(registry: AutomationRegistryService) -> DispatcherService:
    return DispatcherService(
        session_factory=session_scope, registry=registry, timezone=ZoneInfo("UTC"),
        worker_name=WORKER_NAME, poll_interval_seconds=0,
    )


def test_run_once_commits_the_claim_before_the_job_runner_returns() -> None:
    # issue #46: the claim + "running" heartbeat used to sit inside the same open transaction as
    # the entire job execution, invisible to any other connection until the job finished. A
    # runner that peeks at the job's state, from a totally separate session, mid-run proves
    # whether that commit actually already happened or not.
    reset_db()
    job_id = _create_job("test.slow")
    seen: dict = {}

    def slow_runner(job: Job) -> dict:
        with SessionLocal() as probe_session:
            probe_job = probe_session.get(Job, job_id)
            probe_worker = probe_session.scalar(select(WorkerState).where(WorkerState.worker_name == WORKER_NAME))
            seen["job_status"] = probe_job.status
            seen["worker_status"] = probe_worker.status
            seen["current_job_id"] = probe_worker.current_job_id
        return {"ok": True}

    registry = AutomationRegistryService()
    registry.register("test.slow", slow_runner)
    dispatcher = _build_dispatcher(registry)

    outcome = dispatcher.run_once()

    assert outcome["status"] == "completed"
    assert seen["job_status"] == JobStatus.RUNNING
    assert seen["worker_status"] == WorkerStatus.RUNNING
    assert seen["current_job_id"] == job_id


def test_run_once_leaves_the_claim_committed_even_if_the_runner_raises() -> None:
    # a runner that blows up mid-flight (or a process killed mid-run) must not make the claim
    # look like it never happened: attempt_count and the claimed status stay, only the final
    # completed/failed bookkeeping is what's still pending
    reset_db()
    job_id = _create_job("test.boom")

    def boom_runner(job: Job) -> dict:
        raise RuntimeError("simulated failure mid-run")

    registry = AutomationRegistryService()
    registry.register("test.boom", boom_runner)
    dispatcher = _build_dispatcher(registry)

    outcome = dispatcher.run_once()

    assert outcome["status"] == "failed"
    with SessionLocal() as session:
        job = session.get(Job, job_id)
        assert job.attempt_count == 1
        assert job.status in (JobStatus.SCHEDULED, JobStatus.FAILED)


def test_run_once_marks_job_completed_and_worker_idle_after_success() -> None:
    reset_db()
    job_id = _create_job("test.ok")

    def ok_runner(job: Job) -> dict:
        return {"screens_recorded": 42}

    registry = AutomationRegistryService()
    registry.register("test.ok", ok_runner)
    dispatcher = _build_dispatcher(registry)

    outcome = dispatcher.run_once()

    assert outcome == {"worker": WORKER_NAME, "status": "completed", "job_id": job_id}
    with SessionLocal() as session:
        job = session.get(Job, job_id)
        assert job.status == JobStatus.COMPLETED
        assert job.result_json == {"screens_recorded": 42}
        worker = session.scalar(select(WorkerState).where(WorkerState.worker_name == WORKER_NAME))
        assert worker.status == WorkerStatus.IDLE
        assert worker.current_job_id is None


def test_run_once_is_idle_when_there_is_nothing_to_claim() -> None:
    reset_db()
    dispatcher = _build_dispatcher(AutomationRegistryService())

    outcome = dispatcher.run_once()

    assert outcome == {"worker": WORKER_NAME, "status": "idle"}


def _orphan_a_job(job_id: int) -> None:
    with SessionLocal() as session:
        queue = JobQueueService(session, ZoneInfo("UTC"))
        claimed = queue.claim_next_job()  # simulates a previous dispatcher claiming it
        assert claimed.id == job_id
        session.commit()
    # ... then that process died: nothing ever marks it completed/failed, it's stuck RUNNING


def test_reconcile_orphaned_jobs_resets_running_jobs_to_scheduled() -> None:
    # issue #49: a job left RUNNING by a dispatcher process that died mid-job must become
    # claimable again once a fresh dispatcher starts, not stay stuck forever
    reset_db()
    job_id = _create_job("test.a")
    _orphan_a_job(job_id)

    dispatcher = _build_dispatcher(AutomationRegistryService())
    dispatcher.reconcile_orphaned_jobs()

    with SessionLocal() as session:
        job = session.get(Job, job_id)
        assert job.status == JobStatus.SCHEDULED


def test_run_loop_reconciles_orphaned_jobs_before_the_first_poll() -> None:
    # the reconciliation has to happen in time for the very first iteration to pick the job back
    # up, not just eventually
    reset_db()
    job_id = _create_job("test.ok")
    _orphan_a_job(job_id)

    registry = AutomationRegistryService()
    registry.register("test.ok", lambda job: {"ok": True})
    dispatcher = _build_dispatcher(registry)

    dispatcher.run_loop(iterations=1)

    with SessionLocal() as session:
        job = session.get(Job, job_id)
        assert job.status == JobStatus.COMPLETED
