from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI

from lib.core.logs import LogTarget, configure_logging
from lib.core.settings import Settings, load_settings
from lib.dal.local.database import session_scope
from lib.domain.adapters.linkedin.tasks.extract_profile_task import ExtractLinkedInProfileTask
from lib.domain.services.automation_service import AutomationRegistryService
from lib.domain.services.dispatcher_service import DispatcherService
from lib.domain.services.local_mapper_export_service import LocalMapperExportService
from lib.presentation.api.routes.jobs import router as jobs_router
from lib.presentation.api.routes.mapper import router as mapper_router


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


def create_api_app() -> FastAPI:
    settings = get_settings()
    configure_logging(debug=settings.debug, verbose=False, target=LogTarget.API)
    app = FastAPI(title="autodroid", version="0.1.0")
    app.include_router(jobs_router)
    app.include_router(mapper_router)
    return app


@lru_cache(maxsize=1)
def get_mapper_export_service() -> LocalMapperExportService:
    return LocalMapperExportService()
