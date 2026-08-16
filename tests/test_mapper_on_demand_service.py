from __future__ import annotations

import pytest
from sqlalchemy import text

from lib.core.logs import get_logger
from lib.core.settings import load_settings
from lib.dal.local.database import SessionLocal
from lib.domain.services.mapper_fingerprint_service import MapperFingerprintService
from lib.domain.services.mapper_on_demand_service import MapperOnDemandService
from lib.domain.services.mapper_safety_service import MapperSafetyService
from lib.domain.services.navigation_context_service import NavigationContextService
from lib.domain.services.ui_mapper_service import UiMapperService

PACKAGE_NAME = "com.on_demand.inspect"


@pytest.fixture(autouse=True)
def _clean_on_demand_sessions() -> None:
    with SessionLocal() as session:
        session.execute(text(f"DELETE FROM mapper_runtime_snapshots WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name = '{PACKAGE_NAME}') OR package_name = '{PACKAGE_NAME}'"))
        session.execute(text(f"DELETE FROM mapper_transitions WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name = '{PACKAGE_NAME}')"))
        session.execute(text(f"DELETE FROM mapper_actions WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name = '{PACKAGE_NAME}')"))
        session.execute(text(f"DELETE FROM mapper_nodes WHERE screen_id IN (SELECT id FROM mapper_screens WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name = '{PACKAGE_NAME}'))"))
        session.execute(text(f"DELETE FROM mapper_screens WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name = '{PACKAGE_NAME}')"))
        session.execute(text(f"DELETE FROM mapper_sessions WHERE package_name = '{PACKAGE_NAME}'"))
        session.commit()
    yield


class FakeUi:
    def __init__(self, dumps: list[list[dict]]) -> None:
        self.dumps = list(dumps)

    def dump_nodes(self):
        return self.dumps.pop(0) if self.dumps else []

    def click_bounds(self, bounds: str) -> bool:
        return True


class FakeAdb:
    def shell(self, command: str) -> str:
        return f"package:{PACKAGE_NAME}"

    def press_back(self) -> None:
        return None


class FakeNav:
    def prepare_fresh_app_launch(self, package_name: str) -> None:
        return None


def _build_mapper(dumps: list[list[dict]]) -> UiMapperService:
    mapper = UiMapperService.__new__(UiMapperService)
    mapper.logger = get_logger(__name__)
    mapper.settings = load_settings()
    mapper.adb = FakeAdb()
    mapper.ui = FakeUi(dumps)
    mapper.navigation_context = FakeNav()
    mapper.fingerprint_service = MapperFingerprintService()
    mapper.safety_service = MapperSafetyService()
    mapper.REPLAY_CLICK_SETTLE_SECONDS = 0
    return mapper


def test_inspect_marks_unknown_then_known_screen() -> None:
    nodes = [[
        {"text": "Jobs", "content_desc": "", "resource_id": "jobs", "class_name": "TextView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True, "package_name": PACKAGE_NAME},
        {"text": "Profile", "content_desc": "", "resource_id": "profile", "class_name": "TextView", "bounds": "[0,10][10,20]", "clickable": True, "enabled": True, "package_name": PACKAGE_NAME},
    ]]
    service = MapperOnDemandService(load_settings())
    service.mapper = _build_mapper(nodes + nodes)

    first = service.inspect(PACKAGE_NAME)
    second = service.inspect(PACKAGE_NAME, session_id=first["session_id"])

    assert first["recognized"] is False
    assert second["recognized"] is True
    assert len(second["candidates"]) >= 1
