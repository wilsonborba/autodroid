from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from lib.core.logs import LogTarget, configure_logging
from lib.core.settings import Settings, load_settings
from lib.dal.local.database import session_scope
from lib.domain.adapters.linkedin.tasks.extract_profile_task import ExtractLinkedInProfileTask
from lib.domain.services.automation_service import AutomationRegistryService
from lib.domain.services.dispatcher_service import DispatcherService
from lib.domain.services.local_mapper_export_service import LocalMapperExportService
from lib.domain.services.mapper_remap_task import MapperRemapTask
from lib.presentation.api.routes.device_actions import router as device_actions_router
from lib.presentation.api.routes.jobs import router as jobs_router
from lib.presentation.api.routes.mapper import router as mapper_router
from lib.presentation.api.routes.mapper_flows import router as mapper_flows_router


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def get_session():
    return session_scope()


@lru_cache(maxsize=1)
def get_registry() -> AutomationRegistryService:
    settings = get_settings()
    registry = AutomationRegistryService()
    linkedin_task = ExtractLinkedInProfileTask(settings)
    registry.register("linkedin.extract_profile_basic", linkedin_task.run)
    remap_task = MapperRemapTask(settings)
    registry.register("mapper.remap", remap_task.run)
    return registry


def create_dispatcher() -> DispatcherService:
    settings = get_settings()
    return DispatcherService(
        session_factory=session_scope,
        registry=get_registry(),
        timezone=settings.timezone,
        worker_name=settings.worker_name,
        poll_interval_seconds=settings.queue_poll_interval_seconds,
    )


API_DESCRIPTION = """
Automation backend for driving Android apps without an app-specific integration.

Three phases, in order, each with its own route group:

1. **`/mapper`**: exploration. Given a package name, walks the app's UI and records the
   structure discovered: screens, clickable elements, and the transitions between them (issue
   #1 onward). This is generic mapping (what a screen looks like, what's on it), never per-user
   content: a "profile page" is recorded once as a type, not once per person visited (#30).
2. **`/mapper/flows`**: pre-composed automation. Once an app is mapped, a fixed, named sequence
   of steps can be saved and re-run on demand (#18 onward). Good for a repeatable, always-the-same
   job (e.g. a scheduled data extraction).
3. **`/device`**: on-demand execution, one action at a time, no Flow saved beforehand (#32). This
   is the primitive an external agent (deciding what to do next based on what the previous call
   returned) should use: read `/device/actions`'s description, an already-mapped action can be
   fired by id and the backend takes care of getting to the right screen first (direct route or
   app relaunch, whichever the map supports); a raw action (`dump_nodes`, `screenshot`,
   `ocr_extract`, `click_bounds`, ...) reads or acts on whatever's on screen right now, optionally
   against a specific known screen too.

A single physical device is shared by everything above and by the job queue (`/jobs`): only one
interaction happens at a time, nothing here needs to worry about a concurrent conflicting action.
"""


API_TAGS = [
    {
        "name": "mapper",
        "description": "Exploration: map an app's UI structure (screens, clickable elements, "
        "transitions), then query what was recorded. Generic per screen type, never per-user content.",
    },
    {
        "name": "mapper-flows",
        "description": "Pre-composed automation: a named, fixed sequence of steps against an "
        "already-mapped app, saved once and re-run on demand. Use this for a repeatable job that "
        "always does the same thing.",
    },
    {
        "name": "device-actions",
        "description": "On-demand execution: run one action right now, no Flow saved beforehand. "
        "Use this when the next action depends on what a previous call returned.",
    },
    {
        "name": "jobs",
        "description": "The background job queue and its single worker: schedule, list, cancel, "
        "and reprioritize queued work; check what the worker is currently doing.",
    },
    {"name": "health", "description": "Process liveness, no dependencies checked."},
]


def create_api_app() -> FastAPI:
    settings = get_settings()
    configure_logging(debug=settings.debug, verbose=False, target=LogTarget.API)
    app = FastAPI(title="autodroid", version="0.1.0", description=API_DESCRIPTION, openapi_tags=API_TAGS, docs_url=None)
    app.include_router(jobs_router)
    app.include_router(mapper_router)
    app.include_router(mapper_flows_router)
    app.include_router(device_actions_router)

    @app.get("/docs", include_in_schema=False, response_class=HTMLResponse)
    def scalar_docs() -> str:
        return """<!doctype html>
<html>
<head>
    <title>autodroid API</title>
    <meta charset="utf-8" />
</head>
<body>
    <script id="api-reference" data-url="/openapi.json"></script>
    <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
</body>
</html>"""

    return app


@lru_cache(maxsize=1)
def get_mapper_export_service() -> LocalMapperExportService:
    return LocalMapperExportService()
