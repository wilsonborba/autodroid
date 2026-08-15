from __future__ import annotations

from lib.core.settings import load_settings
from lib.dal.local.database import session_scope


_settings = load_settings()


def get_settings():
    return _settings


def get_session():
    return session_scope()


from lib.domain.services.ui_mapper_service import UiMapperService


def get_mapper_engine() -> UiMapperService:
    return UiMapperService(_settings)

from lib.domain.services.local_mapper_export_service import LocalMapperExportService


def get_mapper_export_service() -> LocalMapperExportService:
    return LocalMapperExportService()
