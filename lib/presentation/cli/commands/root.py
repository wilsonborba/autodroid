from __future__ import annotations

import os

import json
import sys
import time as time_module
from datetime import datetime, time
from pathlib import Path

import typer
from alembic import command
from alembic.config import Config

from lib.bootstrap import create_dispatcher, create_api_app, get_mapper_export_service, get_session, get_settings
from lib.core.logs import LogTarget, configure_logging, get_logger
from lib.core.net import clear_api_state, find_available_port, is_port_available, write_api_state
from lib.dal.local.mapper_flow_repository import SqlAlchemyMapperFlowRepository
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode, MapperRunConfig, MapperSessionStatus
from lib.domain.services.job_queue_service import JobQueueService
from lib.domain.services.mapper_churn_service import MapperChurnService
from lib.domain.services.mapper_flow_execution_service import MapperFlowExecutionService
from lib.domain.services.mapper_flow_service import MapperFlowService
from lib.domain.services.mapper_on_demand_service import MapperOnDemandService
from lib.domain.services.mapper_progress_service import MapperProgressService
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
def main(ctx: typer.Context, verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable detailed CLI logs")) -> None:
    settings = get_settings()
    configure_logging(debug=settings.debug, verbose=verbose, target=LogTarget.CLI, log_file=settings.log_file)

    # every CLI invocation, not just the mapper (issue #40's system-wide follow-up to #38): a
    # nested subcommand's own arguments aren't resolved yet at this point, sys.argv is what
    # actually captures the full command regardless of how deep the subcommand nesting goes
    logger = get_logger("lib.presentation.cli")
    invocation = " ".join(sys.argv[1:])
    started_at = time_module.monotonic()
    logger.debug("CLI invoked: %s", invocation)

    def _log_completion() -> None:
        duration_ms = (time_module.monotonic() - started_at) * 1000
        logger.debug("CLI finished: %s (%.0fms)", invocation, duration_ms)

    ctx.call_on_close(_log_completion)


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


# absolute, anchored to this file's location, not the caller's cwd: a plain "lib/dal/alembic.ini"
# only resolves when invoked from the repo root, and `autodroid` is a console script meant to
# work from anywhere, same category of bug as running bare `alembic` from inside lib/dal/ (its
# env.py does `from lib.dal.local.database import ...`, which needs the repo root on sys.path,
# not just alembic.ini found).
ALEMBIC_INI_PATH = str(Path(__file__).resolve().parents[4] / "lib" / "dal" / "alembic.ini")


def _alembic_config() -> Config:
    return Config(ALEMBIC_INI_PATH)


@db_app.command("upgrade")
def db_upgrade(revision: str = "head") -> None:
    command.upgrade(_alembic_config(), revision)
    typer.echo(f"Database upgraded to {revision}")


@db_app.command("downgrade")
def db_downgrade(revision: str) -> None:
    command.downgrade(_alembic_config(), revision)
    typer.echo(f"Database downgraded to {revision}")


@db_app.command("revision")
def db_revision(message: str, autogenerate: bool = True) -> None:
    command.revision(_alembic_config(), message=message, autogenerate=autogenerate)


@db_app.command("current")
def db_current(verbose: bool = False) -> None:
    command.current(_alembic_config(), verbose=verbose)


@db_app.command("history")
def db_history(rev_range: str | None = None, verbose: bool = False) -> None:
    command.history(_alembic_config(), rev_range=rev_range, verbose=verbose, indicate_current=True)


@db_app.command("heads")
def db_heads(verbose: bool = False) -> None:
    command.heads(_alembic_config(), verbose=verbose)


@db_app.command("branches")
def db_branches(verbose: bool = False) -> None:
    command.branches(_alembic_config(), verbose=verbose)


@db_app.command("show")
def db_show(revision: str) -> None:
    command.show(_alembic_config(), revision)


@db_app.command("stamp")
def db_stamp(revision: str, purge: bool = False) -> None:
    command.stamp(_alembic_config(), revision, purge=purge)
    typer.echo(f"Database stamped at {revision}")


@db_app.command("check")
def db_check() -> None:
    # raises (alembic.util.exc.AutogenerateDiffsDetected / CommandError) when the models and the
    # latest migration are out of sync, or no revision exists yet; Typer surfaces that as a
    # non-zero exit, which is the point of this one being scriptable in CI
    command.check(_alembic_config())
    typer.echo("Database schema matches the models")


DEFAULT_API_PORT = 8000


@app.command("serve-api")
def serve_api(
    host: str = "127.0.0.1",
    port: int | None = typer.Option(None, help="Port to bind. Given explicitly: used as-is, fails loudly if it's taken. Omitted: an available port is found automatically starting from 8000, and reported."),
    allow_dangerous_actions: bool = typer.Option(False, "--allow-dangerous-actions", help="Disables the dangerous-action blocker for this API process only. Off by default; use only for explicit supervised runs."),
) -> None:
    """Starts the FastAPI/uvicorn server. A top-level command, not under `worker`: the API
    server and the worker/dispatcher (`worker run`) are two separate processes the user runs
    side by side, and this one never touches the dispatcher, so it shouldn't read as if it did.

    Writes the resolved host/port to a local state file so anything that needs to reach this API
    later can read it instead of guessing or scanning ports blind (issue #44).
    """
    import uvicorn

    if allow_dangerous_actions:
        os.environ["AUTODROID_ALLOW_DANGEROUS_ACTIONS"] = "true"
        get_settings.cache_clear()

    settings = get_settings()
    if port is not None:
        # explicit port: used as requested, never silently swapped for another one. A static
        # port is usually pinned on purpose (a fixed value other tooling already points at), so
        # failing loudly here is the correct behavior, not searching around it (issue #45).
        if not is_port_available(host, port):
            typer.echo(f"Port {port} is already in use.")
            raise typer.Exit(code=1)
        resolved_port = port
    else:
        # no port given: this is the only case where auto-discovery applies.
        resolved_port = find_available_port(host, DEFAULT_API_PORT)
        typer.echo(f"No port specified, using {resolved_port}")

    write_api_state(settings.api_state_file, host=host, port=resolved_port)
    typer.echo(f"Starting autodroid API on http://{host}:{resolved_port} (state: {settings.api_state_file})")
    if settings.allow_dangerous_actions:
        typer.echo("Dangerous action blocker disabled for this API process (--allow-dangerous-actions)")
    try:
        uvicorn.run(create_api_app(), host=host, port=resolved_port)
    finally:
        clear_api_state(settings.api_state_file)


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


@mapper_app.command("apps")
def list_mapper_apps(as_json: bool = False) -> None:
    payload = {"packages": MapperOnDemandService(get_settings()).list_packages()}
    if as_json:
        typer.echo(JsonOutput.render(payload))
        return
    for package_name in payload["packages"]:
        typer.echo(package_name)


@mapper_app.command("inspect")
def inspect_mapper_screen(package_name: str, session_id: int | None = None, as_json: bool = False) -> None:
    payload = MapperOnDemandService(get_settings()).inspect(package_name, session_id=session_id)
    if as_json:
        typer.echo(JsonOutput.render(payload))
        return
    typer.echo(f"session #{payload['session_id']} screen #{payload['screen_id']} {payload['screen_key']}")
    for candidate in payload['candidates'][:20]:
        typer.echo(f"  action #{candidate['action_id']} {candidate['label']!r} bounds={candidate['bounds']}")


@mapper_app.command("act")
def act_mapper_on_demand(package_name: str, session_id: int | None = None, action_id: int | None = None, bounds: str | None = None, action_type: str = "click", as_json: bool = False) -> None:
    payload = MapperOnDemandService(get_settings()).act(package_name, session_id=session_id, action_id=action_id, bounds=bounds, action_type=action_type)
    if as_json:
        typer.echo(JsonOutput.render(payload))
        return
    typer.echo(str(payload))


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


@mapper_app.command("progress")
def show_mapper_progress(session_id: int | None = None, package_name: str | None = typer.Option(None, "--package"), as_json: bool = False) -> None:
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        resolved_session_id = _resolve_mapper_session_id(repository, session_id, package_name)
        progress = MapperProgressService(session)
        payload = progress.get_session_progress(resolved_session_id)
        screens = progress.list_screen_progress(resolved_session_id)
        payload["screens"] = screens[:10]
        if as_json:
            typer.echo(JsonOutput.render(payload))
            return
        typer.echo(f"session #{payload['session_id']} {payload['package_name']} [{payload['mode']}] status={payload['status']} progress={payload['progress_percent']}%")
        activity = payload.get('current_activity') or {}
        if activity:
            typer.echo(f"  activity={activity.get('activity_kind')} current={activity.get('current_screen_id')} target={activity.get('target_screen_id')} strategy={activity.get('strategy_type')}")
        typer.echo(f"  screens total={payload['screen_counts']['total']} pending={payload['screen_counts']['pending']} resume_needed={payload['screen_counts']['resume_needed']} complete={payload['screen_counts']['complete']}")
        recovery = payload.get('recovery_counts') or {}
        typer.echo(f"  recoveries total={recovery.get('total', 0)} restart={recovery.get('restart', 0)} planner_restart={recovery.get('planner_restart', 0)} planner_direct={recovery.get('planner_direct', 0)} known_return={recovery.get('known_return', 0)}")
        for item in screens[:10]:
            marker = '*' if item['is_current_target'] else '-'
            typer.echo(f"  {marker} screen #{item['screen_id']} {item['screen_key']} depth={item['depth']} state={item['completion_state']} progress={item['progress_percent']}% pending={item['pending_candidates']} scrolls={item['scroll_attempts']}/{item['useful_scroll_discoveries']}")


@mapper_app.command("churn")
def show_mapper_churn(session_id: int | None = None, package_name: str | None = typer.Option(None, "--package"), as_json: bool = False) -> None:
    with get_session() as session:
        repository = SqlAlchemyMapperRepository(session)
        resolved_session_id = _resolve_mapper_session_id(repository, session_id, package_name)
        payload = MapperChurnService(session, get_settings()).get_live_churn(resolved_session_id)
        if as_json:
            typer.echo(JsonOutput.render(payload))
            return
        typer.echo(f"session #{payload['session_id']} churn={payload['severity']} score={payload['score']} confidence={payload['confidence']}")
        activity = payload.get('current_activity') or {}
        if activity:
            typer.echo(f"  activity={activity.get('activity_kind')} current={activity.get('current_screen_id')} target={activity.get('target_screen_id')} strategy={activity.get('strategy_type')}")
        metrics = payload.get('metrics') or {}
        typer.echo(f"  restarts={metrics.get('window_restarts', 0)} recoveries={metrics.get('window_recoveries', 0)} revisits={metrics.get('window_revisits', 0)} value_gain={metrics.get('window_value_gain', 0)} clicks_since_progress={metrics.get('current_clicks_since_progress', 0)}")
        for recommendation in payload.get('recommendations', [])[:3]:
            typer.echo(f"  -> {recommendation['action']} target={recommendation.get('target_screen_id')} confidence={recommendation['confidence']} reason={recommendation['rationale']}")


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


def _resolve_mapper_session_id(repository: SqlAlchemyMapperRepository, session_id: int | None, package_name: str | None) -> int:
    if session_id is not None:
        return session_id
    if not package_name:
        raise typer.BadParameter("provide a session_id or use --package")
    mapper_session = repository.get_resumable_session(package_name) or repository.get_latest_session(package_name)
    if mapper_session is None:
        raise typer.BadParameter(f"No mapper session found for package {package_name}")
    return mapper_session.id


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
