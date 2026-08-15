from __future__ import annotations

import json
from datetime import datetime, time

import typer
from alembic import command
from alembic.config import Config

from lib.bootstrap import create_dispatcher, create_api_app, get_mapper_export_service, get_session, get_settings
from lib.core.logs import LogTarget, configure_logging
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_types import MapperMode, MapperRunConfig
from lib.domain.services.job_queue_service import JobQueueService
from lib.domain.services.ui_mapper_service import UiMapperService
from lib.domain.services.worker_service import WorkerService
from lib.presentation.cli.formatters.job_formatter import JobFormatter
from lib.presentation.cli.outputs.json_output import JsonOutput

app = typer.Typer(help="Autodroid CLI")
jobs_app = typer.Typer(help="Job operations")
worker_app = typer.Typer(help="Worker operations")
db_app = typer.Typer(help="Database operations")
mapper_app = typer.Typer(help="Mapper operations")
app.add_typer(jobs_app, name="jobs")
app.add_typer(worker_app, name="worker")
app.add_typer(db_app, name="db")
app.add_typer(mapper_app, name="mapper")


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable detailed CLI logs")) -> None:
    settings = get_settings()
    configure_logging(debug=settings.debug, verbose=verbose, target=LogTarget.CLI)


def _parse_json_payload(raw: str | None) -> dict:
    if not raw:
        return {}
    return json.loads(raw)


@jobs_app.command("create")
def create_job(
    job_type: str,
    adapter_name: str,
    payload: str = typer.Option("{}", help="JSON payload string"),
    priority: int = 100,
    run_after: str | None = None,
    cron_expression: str | None = None,
    execution_window_start: str | None = None,
    execution_window_end: str | None = None,
    max_attempts: int = 3,
) -> None:
    settings = get_settings()
    parsed_run_after = datetime.fromisoformat(run_after) if run_after else None
    parsed_window_start = time.fromisoformat(execution_window_start) if execution_window_start else None
    parsed_window_end = time.fromisoformat(execution_window_end) if execution_window_end else None
    with get_session() as session:
        queue = JobQueueService(session, settings.timezone)
        job = queue.create_job(
            job_type=job_type,
            adapter_name=adapter_name,
            payload=_parse_json_payload(payload),
            priority=priority,
            run_after=parsed_run_after,
            cron_expression=cron_expression,
            execution_window_start=parsed_window_start,
            execution_window_end=parsed_window_end,
            max_attempts=max_attempts,
        )
        typer.echo(JobFormatter.format(job))


@jobs_app.command("list")
def list_jobs(limit: int = 50, as_json: bool = False) -> None:
    settings = get_settings()
    with get_session() as session:
        queue = JobQueueService(session, settings.timezone)
        jobs = queue.list_jobs(limit=limit)
        if as_json:
            typer.echo(JsonOutput.render({"jobs": [{"id": job.id, "job_type": job.job_type, "status": job.status.value, "priority": job.priority} for job in jobs]}))
            return
        for job in jobs:
            typer.echo(JobFormatter.format(job))


@jobs_app.command("show")
def show_job(job_id: int, as_json: bool = False) -> None:
    settings = get_settings()
    with get_session() as session:
        queue = JobQueueService(session, settings.timezone)
        job = queue.get_job(job_id)
        if job is None:
            raise typer.Exit(code=1)
        if as_json:
            typer.echo(JsonOutput.render({
                "id": job.id,
                "job_type": job.job_type,
                "status": job.status.value,
                "priority": job.priority,
                "result_json": job.result_json,
                "error_message": job.error_message,
            }))
            return
        typer.echo(JobFormatter.format(job))


@jobs_app.command("cancel")
def cancel_job(job_id: int) -> None:
    settings = get_settings()
    with get_session() as session:
        queue = JobQueueService(session, settings.timezone)
        job = queue.cancel_job(job_id)
        typer.echo(JobFormatter.format(job))


@jobs_app.command("reprioritize")
def reprioritize_job(job_id: int, priority: int) -> None:
    settings = get_settings()
    with get_session() as session:
        queue = JobQueueService(session, settings.timezone)
        job = queue.reprioritize_job(job_id, priority)
        typer.echo(JobFormatter.format(job))


@worker_app.command("run")
def run_worker(iterations: int | None = typer.Option(None, help="Run dispatcher loop N times")) -> None:
    dispatcher = create_dispatcher()
    if iterations == 1:
        typer.echo(JsonOutput.render(dispatcher.run_once()))
        return
    dispatcher.run_loop(iterations=iterations)


@worker_app.command("status")
def worker_status(as_json: bool = False) -> None:
    settings = get_settings()
    with get_session() as session:
        worker = WorkerService(session).ensure_worker(settings.worker_name)
        payload = {
            "worker_name": worker.worker_name,
            "status": worker.status.value,
            "current_job_id": worker.current_job_id,
            "execution_enabled": worker.execution_enabled,
        }
        if as_json:
            typer.echo(JsonOutput.render(payload))
            return
        typer.echo(str(payload))


@db_app.command("upgrade")
def db_upgrade(revision: str = "head") -> None:
    command.upgrade(Config("alembic.ini"), revision)
    typer.echo(f"Database upgraded to {revision}")


@db_app.command("revision")
def db_revision(message: str) -> None:
    command.revision(Config("alembic.ini"), message=message, autogenerate=True)


@worker_app.command("serve-api")
def serve_api(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(create_api_app(), host=host, port=port)


@mapper_app.command("run")
def run_mapper(package_name: str, mode: str = "light", skip_dangerous_actions: bool = True) -> None:
    try:
        mapper_mode = MapperMode(mode)
    except ValueError as exc:
        raise typer.BadParameter(f"Invalid mapper mode: {mode}") from exc
    result = UiMapperService(get_settings()).run(MapperRunConfig(package_name=package_name, mode=mapper_mode, skip_dangerous_actions=skip_dangerous_actions))
    typer.echo(JsonOutput.render(result))


@mapper_app.command("sessions")
def list_mapper_sessions(limit: int = 50, as_json: bool = False) -> None:
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        sessions = repository.list_sessions(limit=limit)
        if as_json:
            typer.echo(JsonOutput.render({"sessions": [{"id": item.id, "package_name": item.package_name, "mode": item.mode.value, "status": item.status.value} for item in sessions]}))
            return
        for item in sessions:
            typer.echo(f"#{item.id} {item.package_name} [{item.mode.value}] {item.status.value}")


@mapper_app.command("show")
def show_mapper_session(session_id: int, as_json: bool = False) -> None:
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.get_session(session_id)
        if mapper_session is None:
            raise typer.Exit(code=1)
        payload = {
            "id": mapper_session.id,
            "package_name": mapper_session.package_name,
            "mode": mapper_session.mode.value,
            "status": mapper_session.status.value,
            "max_depth": mapper_session.max_depth,
            "max_actions": mapper_session.max_actions,
            "max_scrolls": mapper_session.max_scrolls,
        }
        if as_json:
            typer.echo(JsonOutput.render(payload))
            return
        typer.echo(str(payload))


@mapper_app.command("export")
def export_mapper_session(session_id: int) -> None:
    output_dir = get_settings().output_dir / "mappers"
    export_path = get_mapper_export_service().export_session(session_id, output_dir)
    typer.echo(str(export_path))
