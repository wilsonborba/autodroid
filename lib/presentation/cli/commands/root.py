from __future__ import annotations

import json
from datetime import datetime, time

import typer
from alembic import command
from alembic.config import Config

from lib.bootstrap import create_dispatcher, create_api_app, get_mapper_export_service, get_session, get_settings
from lib.core.logs import LogTarget, configure_logging
from lib.dal.local.mapper_flow_repository import SqlAlchemyMapperFlowRepository
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode, MapperRunConfig, MapperSessionStatus
from lib.domain.services.job_queue_service import JobQueueService
from lib.domain.services.mapper_flow_execution_service import MapperFlowExecutionService
from lib.domain.services.mapper_flow_service import MapperFlowService
from lib.domain.services.ui_mapper_service import UiMapperService
from lib.domain.services.worker_service import WorkerService
from lib.presentation.cli.formatters.job_formatter import JobFormatter
from lib.presentation.cli.outputs.json_output import JsonOutput

app = typer.Typer(help="Autodroid CLI")
jobs_app = typer.Typer(help="Job operations")
worker_app = typer.Typer(help="Worker operations")
db_app = typer.Typer(help="Database operations")
mapper_app = typer.Typer(help="Mapper operations")
flow_app = typer.Typer(help="Mapper flow operations")
app.add_typer(jobs_app, name="jobs")
app.add_typer(worker_app, name="worker")
app.add_typer(db_app, name="db")
app.add_typer(mapper_app, name="mapper")
mapper_app.add_typer(flow_app, name="flow")


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable detailed CLI logs")) -> None:
    settings = get_settings()
    configure_logging(debug=settings.debug, verbose=verbose, target=LogTarget.CLI, log_file=settings.log_file)


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
def run_mapper(
    package_name: str,
    mode: str = "light",
    skip_dangerous_actions: bool = True,
    override: bool = typer.Option(False, "--override", help="Force remapping even if a completed session already exists"),
    complement: bool = typer.Option(False, "--complement", help="Extend the existing session up to this mode's depth instead of skipping or remapping from scratch"),
) -> None:
    if override and complement:
        raise typer.BadParameter("--override and --complement cannot both be set")
    try:
        mapper_mode = MapperMode(mode)
    except ValueError as exc:
        raise typer.BadParameter(f"Invalid mapper mode: {mode}") from exc
    try:
        result = UiMapperService(get_settings()).run(MapperRunConfig(package_name=package_name, mode=mapper_mode, skip_dangerous_actions=skip_dangerous_actions, override=override, complement=complement))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
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


def _screen_summary_payload(screen) -> dict:
    return {
        "id": screen.id,
        "screen_key": screen.screen_key,
        "fingerprint": screen.fingerprint,
        "depth": screen.depth,
        "ordinal": screen.ordinal,
        "visit_count": screen.visit_count,
        "node_count": len(screen.nodes),
    }


@mapper_app.command("screens")
def list_mapper_screens(session_id: int, as_json: bool = False) -> None:
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        screens = repository.list_screens(session_id)
        if as_json:
            typer.echo(JsonOutput.render({"screens": [_screen_summary_payload(screen) for screen in screens]}))
            return
        for screen in screens:
            typer.echo(f"#{screen.id} {screen.screen_key} depth={screen.depth} nodes={len(screen.nodes)} visits={screen.visit_count}")


@mapper_app.command("screen")
def show_mapper_screen(session_id: int, screen_id: int) -> None:
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        screen = repository.get_screen(screen_id)
        if screen is None or screen.session_id != session_id:
            raise typer.Exit(code=1)
        payload = _screen_summary_payload(screen)
        payload["nodes"] = [
            {"id": node.id, "text": node.text, "content_desc": node.content_desc, "resource_id": node.resource_id, "bounds": node.bounds, "clickable": node.clickable}
            for node in screen.nodes
        ]
        typer.echo(JsonOutput.render(payload))


@mapper_app.command("actions")
def list_mapper_actions(session_id: int, screen_id: int | None = None, safety: str | None = None, executed: bool | None = None) -> None:
    safety_filter = None
    if safety is not None:
        try:
            safety_filter = MapperActionSafety(safety)
        except ValueError as exc:
            raise typer.BadParameter(f"Invalid safety filter: {safety}") from exc
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        actions = repository.list_actions(session_id, screen_id=screen_id, safety=safety_filter, executed=executed)
        for action in actions:
            typer.echo(f"#{action.id} screen={action.screen_id} {action.action_type} {action.label!r} safety={action.safety.value} executed={action.executed} success={action.success}")


@mapper_app.command("transitions")
def list_mapper_transitions(session_id: int) -> None:
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        transitions = repository.list_transitions(session_id)
        for transition in transitions:
            typer.echo(f"#{transition.id} {transition.from_screen_id} -> {transition.to_screen_id} via action={transition.action_id} ({transition.result_type})")


@mapper_app.command("graph")
def show_mapper_graph(session_id: int, as_json: bool = False) -> None:
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.get_session(session_id)
        if mapper_session is None:
            raise typer.Exit(code=1)
        payload = {
            "session_id": mapper_session.id,
            "package_name": mapper_session.package_name,
            "screens": [_screen_summary_payload(screen) for screen in mapper_session.screens],
            "transitions": [
                {"id": t.id, "from_screen_id": t.from_screen_id, "action_id": t.action_id, "to_screen_id": t.to_screen_id, "result_type": t.result_type}
                for t in mapper_session.transitions
            ],
        }
        if as_json:
            typer.echo(JsonOutput.render(payload))
            return
        for screen in payload["screens"]:
            typer.echo(f"screen #{screen['id']} {screen['screen_key']} (depth={screen['depth']}, nodes={screen['node_count']})")
        for transition in payload["transitions"]:
            typer.echo(f"  {transition['from_screen_id']} -> {transition['to_screen_id']} via action={transition['action_id']} ({transition['result_type']})")


@mapper_app.command("latest-session")
def latest_mapper_session(package_name: str, as_json: bool = False) -> None:
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.get_latest_session(package_name, status=MapperSessionStatus.COMPLETED)
        if mapper_session is None:
            raise typer.Exit(code=1)
        payload = {"id": mapper_session.id, "package_name": mapper_session.package_name, "mode": mapper_session.mode.value, "status": mapper_session.status.value}
        if as_json:
            typer.echo(JsonOutput.render(payload))
            return
        typer.echo(str(payload))


@mapper_app.command("remap-candidates")
def remap_candidates(threshold: int | None = None, as_json: bool = False) -> None:
    settings = get_settings()
    if not settings.mapper_auto_remap_enabled:
        typer.echo("Auto-remap is disabled (AUTODROID_MAPPER_AUTO_REMAP_ENABLED=false); failures are still being recorded, nothing is actionable until it's turned on.")
        return
    resolved_threshold = threshold if threshold is not None else settings.mapper_auto_remap_threshold
    with get_session() as session:
        candidates = SqlAlchemyMapperFlowRepository(session).list_remap_candidates(resolved_threshold)
        if as_json:
            typer.echo(JsonOutput.render({"candidates": [{"package_name": name, "unresolved_failure_count": count} for name, count in candidates]}))
            return
        for package_name, count in candidates:
            typer.echo(f"{package_name}: {count} unresolved failure(s)")


@mapper_app.command("remap")
def remap_apps(
    package_names: list[str] = typer.Argument(None, help="Package names to remap"),
    all_candidates: bool = typer.Option(False, "--all", help="Remap every current candidate"),
    strategy: str = typer.Option("override", help="override or complement"),
    mode: str = typer.Option("medium"),
) -> None:
    settings = get_settings()
    with get_session() as session:
        if all_candidates:
            candidates = SqlAlchemyMapperFlowRepository(session).list_remap_candidates(settings.mapper_auto_remap_threshold)
            resolved_names = [name for name, _ in candidates]
        else:
            resolved_names = list(package_names or [])
        if not resolved_names:
            raise typer.BadParameter("No package selected: pass package names or --all with existing candidates")

        queue = JobQueueService(session, settings.timezone)
        queued = []
        for package_name in resolved_names:
            job = queue.create_job(job_type="mapper.remap", adapter_name="mapper", payload={"package_name": package_name, "strategy": strategy, "mode": mode})
            queued.append({"package_name": package_name, "job_id": job.id})
        typer.echo(JsonOutput.render({"queued": queued}))


def _flow_summary_payload(flow) -> dict:
    return {
        "id": flow.id,
        "name": flow.name,
        "package_name": flow.package_name,
        "description": flow.description,
        "source_session_id": flow.source_session_id,
        "step_count": len(flow.step_usages),
    }


def _step_payload(step, *, ordinal: int | None = None) -> dict:
    return {
        "id": step.id,
        "ordinal": ordinal,
        "action_type": step.action_type,
        "selector": step.selector_json,
        "safety": step.safety.value,
        "source_screen_id": step.source_screen_id,
        "source_action_id": step.source_action_id,
        "params": step.params_json,
    }


def _flow_payload(flow) -> dict:
    payload = _flow_summary_payload(flow)
    usages = sorted(flow.step_usages, key=lambda usage: usage.ordinal)
    payload["steps"] = [_step_payload(usage.step, ordinal=usage.ordinal) for usage in usages]
    return payload


@flow_app.command("create")
def create_flow(
    name: str,
    package_name: str,
    description: str | None = None,
    from_session: int | None = typer.Option(None, "--from-session", help="Session id to promote transitions from"),
    transitions: str | None = typer.Option(None, "--transitions", help="Comma-separated transition ids"),
    steps: str | None = typer.Option(None, "--steps", help="JSON list of manual steps"),
) -> None:
    transition_ids = [int(value) for value in transitions.split(",")] if transitions else None
    parsed_steps = json.loads(steps) if steps else None
    with get_session() as session:
        try:
            flow = MapperFlowService(session).create_flow(
                name=name,
                package_name=package_name,
                description=description,
                source_session_id=from_session,
                transition_ids=transition_ids,
                steps=parsed_steps,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(JsonOutput.render(_flow_payload(flow)))


@flow_app.command("list")
def list_flows(package: str | None = typer.Option(None, "--package"), as_json: bool = False) -> None:
    with get_session() as session:
        flows = MapperFlowService(session).list_flows(package)
        if as_json:
            typer.echo(JsonOutput.render({"flows": [_flow_summary_payload(flow) for flow in flows]}))
            return
        for flow in flows:
            typer.echo(f"#{flow.id} {flow.name} [{flow.package_name}] steps={len(flow.step_usages)}")


@flow_app.command("show")
def show_flow(flow_id: int) -> None:
    with get_session() as session:
        flow = MapperFlowService(session).get_flow(flow_id)
        if flow is None:
            raise typer.Exit(code=1)
        typer.echo(JsonOutput.render(_flow_payload(flow)))


@flow_app.command("update")
def update_flow(flow_id: int, name: str | None = None, description: str | None = None) -> None:
    with get_session() as session:
        try:
            flow = MapperFlowService(session).update_flow(flow_id, name=name, description=description)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(JsonOutput.render(_flow_payload(flow)))


@flow_app.command("delete")
def delete_flow(flow_id: int) -> None:
    with get_session() as session:
        try:
            MapperFlowService(session).delete_flow(flow_id)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(f"Deleted flow {flow_id}")


@flow_app.command("add-step")
def add_step(
    flow_id: int,
    action_type: str | None = None,
    selector: str = "{}",
    params: str | None = None,
    source_screen_id: int | None = None,
    source_action_id: int | None = None,
    ordinal: int | None = None,
    step_id: int | None = typer.Option(None, "--step-id", help="Reuse an existing (shared) step instead of defining a new one"),
) -> None:
    with get_session() as session:
        try:
            outcome = MapperFlowService(session).add_step(
                flow_id,
                {
                    "step_id": step_id,
                    "action_type": action_type,
                    "selector": json.loads(selector),
                    "params": json.loads(params) if params else None,
                    "source_screen_id": source_screen_id,
                    "source_action_id": source_action_id,
                    "ordinal": ordinal,
                },
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(JsonOutput.render({
            "step": _step_payload(outcome["step"]),
            "ancestors": [_step_payload(step) for step in outcome["ancestors"]],
        }))


@flow_app.command("remove-step")
def remove_step(flow_id: int, step_id: int) -> None:
    """Removes the step from this flow only; the step definition (and its use by other flows) stays."""
    with get_session() as session:
        try:
            MapperFlowService(session).remove_step(flow_id, step_id)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(f"Removed step {step_id} from flow {flow_id}")


@flow_app.command("run")
def run_flow(flow_id: int, skip_dangerous_actions: bool = True) -> None:
    with get_session() as session:
        flow = MapperFlowService(session).get_flow(flow_id)
        if flow is None:
            raise typer.Exit(code=1)
        steps = SqlAlchemyMapperFlowRepository(session).ordered_steps(flow)
        result = MapperFlowExecutionService(get_settings()).run_flow(flow, steps, skip_dangerous_actions=skip_dangerous_actions)
    typer.echo(JsonOutput.render(result))


@flow_app.command("run-step")
def run_flow_step(flow_id: int, ordinal: int, skip_dangerous_actions: bool = True) -> None:
    with get_session() as session:
        flow = MapperFlowService(session).get_flow(flow_id)
        if flow is None:
            raise typer.Exit(code=1)
        usage = next((candidate for candidate in flow.step_usages if candidate.ordinal == ordinal), None)
        if usage is None:
            raise typer.Exit(code=1)
        result = MapperFlowExecutionService(get_settings()).run_step(usage.step, skip_dangerous_actions=skip_dangerous_actions)
    typer.echo(JsonOutput.render(result))
