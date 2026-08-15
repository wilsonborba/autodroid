from __future__ import annotations

import pytest

from lib.core.logs import get_logger
from lib.dal.local.database import SessionLocal
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_types import MapperMode, MapperRunConfig, MapperSessionStatus
from lib.domain.services.mapper_fingerprint_service import MapperFingerprintService
from lib.domain.services.mapper_mode_service import MapperModeService
from lib.domain.services.mapper_safety_service import MapperSafetyService
from lib.domain.services.ui_mapper_service import UiMapperService

ROOT_NODES = [{"text": "Profile", "content_desc": "", "resource_id": "profile_btn", "class_name": "TextView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True}]
LEAF_NODES = [{"text": "Details", "content_desc": "", "resource_id": "", "class_name": "TextView", "bounds": "[0,0][5,5]", "clickable": False, "enabled": True}]
DANGEROUS_ROOT_NODES = [{"text": "Delete account", "content_desc": "", "resource_id": "delete_account", "class_name": "TextView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True}]


class FakeUi:
    def __init__(self, dumps: list[list[dict]]) -> None:
        self.dumps = list(dumps)
        self.clicks: list[str] = []
        self.swipes = 0

    def dump_nodes(self):
        return self.dumps.pop(0) if self.dumps else []

    def click_bounds(self, bounds: str) -> bool:
        self.clicks.append(bounds)
        return True

    def swipe_up(self) -> None:
        self.swipes += 1


class FakeAdb:
    def __init__(self) -> None:
        self.back_calls = 0

    def press_back(self) -> None:
        self.back_calls += 1


class FakeNav:
    def __init__(self) -> None:
        self.prepared: list[str] = []

    def prepare_fresh_app_launch(self, package_name: str) -> None:
        self.prepared.append(package_name)


def build_service(dumps: list[list[dict]]) -> UiMapperService:
    service = UiMapperService.__new__(UiMapperService)
    service.logger = get_logger(__name__)
    service.settings = None
    service.adb = FakeAdb()
    service.ui = FakeUi(dumps)
    service.navigation_context = FakeNav()
    service.mode_service = MapperModeService()
    service.fingerprint_service = MapperFingerprintService()
    service.safety_service = MapperSafetyService()
    return service


def test_fresh_mapper_run_light_mode_records_root_and_leaf() -> None:
    service = build_service([ROOT_NODES, LEAF_NODES])

    result = service.run(MapperRunConfig(package_name="com.fresh.testapp", mode=MapperMode.LIGHT))

    assert result["screens_recorded"] == 2
    assert result["actions_executed"] == 1
    assert result["reused"] is False
    assert result["complemented"] is False
    assert service.navigation_context.prepared == ["com.fresh.testapp"]

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.get_session(result["session_id"])
        assert mapper_session.explored_up_to_depth == 1
        assert mapper_session.status == MapperSessionStatus.COMPLETED


def test_dangerous_action_is_blocked_by_default() -> None:
    service = build_service([DANGEROUS_ROOT_NODES])

    result = service.run(MapperRunConfig(package_name="com.dangerous.testapp", mode=MapperMode.LIGHT))

    assert result["actions_executed"] == 0
    assert service.ui.clicks == []

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        actions = repository.list_actions(result["session_id"])
        assert len(actions) == 1
        assert actions[0].skipped_reason == "dangerous_action_blocked"


def test_second_run_reuses_completed_session_by_default() -> None:
    package_name = "com.reuse.testapp"
    first = build_service([ROOT_NODES, LEAF_NODES]).run(MapperRunConfig(package_name=package_name, mode=MapperMode.LIGHT))

    second_service = build_service([ROOT_NODES, LEAF_NODES])
    second = second_service.run(MapperRunConfig(package_name=package_name, mode=MapperMode.LIGHT))

    assert second["reused"] is True
    assert second["session_id"] == first["session_id"]
    assert second_service.navigation_context.prepared == []  # never touched the device


def test_override_creates_a_new_session_ignoring_existing_one() -> None:
    package_name = "com.override.testapp"
    first = build_service([ROOT_NODES, LEAF_NODES]).run(MapperRunConfig(package_name=package_name, mode=MapperMode.LIGHT))

    second = build_service([ROOT_NODES, LEAF_NODES]).run(MapperRunConfig(package_name=package_name, mode=MapperMode.LIGHT, override=True))

    assert second["session_id"] != first["session_id"]
    assert second["reused"] is False
    assert second["complemented"] is False


def test_complement_deepens_light_session_to_medium_without_duplicating() -> None:
    package_name = "com.complement.testapp"
    light = build_service([ROOT_NODES, LEAF_NODES]).run(MapperRunConfig(package_name=package_name, mode=MapperMode.LIGHT))
    assert light["screens_recorded"] == 2

    complement_service = build_service([ROOT_NODES, LEAF_NODES])
    medium = complement_service.run(MapperRunConfig(package_name=package_name, mode=MapperMode.MEDIUM, complement=True))

    assert medium["session_id"] == light["session_id"]
    assert medium["complemented"] is True
    assert medium["screens_recorded"] == 2  # root and leaf already existed, nothing duplicated
    assert complement_service.navigation_context.prepared == [package_name]  # still needs a fresh launch to re-navigate

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.get_session(light["session_id"])
        assert mapper_session.explored_up_to_depth == 2
        assert mapper_session.mode == MapperMode.MEDIUM
        screens = repository.list_screens(light["session_id"])
        assert all(screen.expanded for screen in screens)


def test_complement_is_a_noop_when_session_already_satisfies_target_depth() -> None:
    package_name = "com.satisfied.testapp"
    medium = build_service([ROOT_NODES, LEAF_NODES]).run(MapperRunConfig(package_name=package_name, mode=MapperMode.MEDIUM))

    noop_service = build_service([ROOT_NODES, LEAF_NODES])
    result = noop_service.run(MapperRunConfig(package_name=package_name, mode=MapperMode.LIGHT, complement=True))

    assert result["session_id"] == medium["session_id"]
    assert result["complemented"] is False
    assert noop_service.navigation_context.prepared == []  # no device work needed, already satisfied


def test_resumes_interrupted_session_instead_of_creating_a_new_one() -> None:
    package_name = "com.resume.testapp"
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        crashed = repository.create_session(
            package_name=package_name,
            mode=MapperMode.LIGHT,
            skip_dangerous_actions=True,
            max_depth=1,
            max_actions=8,
            max_scrolls=0,
        )
        crashed.status = MapperSessionStatus.RUNNING
        session.commit()
        crashed_id = crashed.id

    service = build_service([LEAF_NODES])
    result = service.run(MapperRunConfig(package_name=package_name, mode=MapperMode.LIGHT))

    assert result["session_id"] == crashed_id

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.get_session(crashed_id)
        assert mapper_session.status == MapperSessionStatus.COMPLETED


def test_override_and_complement_together_raises() -> None:
    service = build_service([])
    with pytest.raises(ValueError):
        service.run(MapperRunConfig(package_name="com.invalid.testapp", mode=MapperMode.LIGHT, override=True, complement=True))
