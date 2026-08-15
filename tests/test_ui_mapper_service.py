from __future__ import annotations

import pytest
from sqlalchemy import text

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

_TEST_PACKAGE_NAMES = (
    "com.fresh.testapp", "com.dangerous.testapp", "com.reuse.testapp", "com.override.testapp",
    "com.complement.testapp", "com.satisfied.testapp", "com.resume.testapp",
    "com.feedscroll.testapp", "com.noscroll.testapp", "com.realcrash.testapp",
)


@pytest.fixture(autouse=True)
def _clean_sessions():
    # this project's tests share the real dev DB (no per-test isolation), and `run()` reuses an
    # existing COMPLETED session for the same package_name, so a session left behind by a
    # previous run would make one of these tests silently take the "reuse" path instead of a
    # fresh one.
    names = ",".join(f"'{name}'" for name in _TEST_PACKAGE_NAMES)
    with SessionLocal() as session:
        session.execute(text(f"DELETE FROM mapper_transitions WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name IN ({names}))"))
        session.execute(text(f"DELETE FROM mapper_actions WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name IN ({names}))"))
        session.execute(text(f"DELETE FROM mapper_nodes WHERE screen_id IN (SELECT id FROM mapper_screens WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name IN ({names})))"))
        session.execute(text(f"DELETE FROM mapper_screens WHERE session_id IN (SELECT id FROM mapper_sessions WHERE package_name IN ({names}))"))
        session.execute(text(f"DELETE FROM mapper_sessions WHERE package_name IN ({names})"))
        session.commit()


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
        assert mapper_session.explored_up_to_depth == 3
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


def _feed_dump(item_text: str) -> list[dict]:
    return [
        {"resource_id": "feed_container", "text": "", "content_desc": "", "class_name": "RecyclerView", "bounds": "[0,0][100,800]", "clickable": False, "enabled": True, "scrollable": True},
        {"resource_id": "feed_caption", "text": item_text, "content_desc": "", "class_name": "TextView", "bounds": "[0,50][100,100]", "clickable": False, "enabled": True, "scrollable": False},
    ]


def test_scroll_stops_at_the_mode_repeat_threshold_not_at_max_scrolls() -> None:
    # each dump has different text (so a text-based fingerprint would never converge) but the
    # exact same structure, simulating a feed. light's repeat_signature_threshold is 20 and its
    # max_scrolls is 30, so if the cutoff is working, it stops well before the safety ceiling.
    dumps = [_feed_dump(f"Post {i}") for i in range(30)]
    service = build_service(dumps)

    result = service.run(MapperRunConfig(package_name="com.feedscroll.testapp", mode=MapperMode.LIGHT))

    limits = MapperModeService().get_limits(MapperMode.LIGHT)
    assert service.ui.swipes == limits.repeat_signature_threshold
    assert service.ui.swipes < limits.max_scrolls
    assert result["status"] == "completed"


def test_scroll_does_not_happen_on_a_screen_without_scrollable_content() -> None:
    service = build_service([ROOT_NODES, LEAF_NODES])

    service.run(MapperRunConfig(package_name="com.noscroll.testapp", mode=MapperMode.LIGHT))

    assert service.ui.swipes == 0


MULTI_BUTTON_ROOT = [
    {"text": "Button A", "content_desc": "", "resource_id": "btn_a", "class_name": "TextView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True},
    {"text": "Button B", "content_desc": "", "resource_id": "btn_b", "class_name": "TextView", "bounds": "[10,0][20,10]", "clickable": True, "enabled": True},
    {"text": "Button C", "content_desc": "", "resource_id": "btn_c", "class_name": "TextView", "bounds": "[20,0][30,10]", "clickable": True, "enabled": True},
]


class CrashingUi(FakeUi):
    """Fails on the Nth click_bounds call, simulating a real adb failure mid-mapping (issue
    #25), instead of just faking a stuck `status=RUNNING` row like the other resume test does."""

    def __init__(self, dumps: list[list[dict]], fail_on_click_number: int) -> None:
        super().__init__(dumps)
        self.fail_on_click_number = fail_on_click_number
        self.click_count = 0

    def click_bounds(self, bounds: str) -> bool:
        self.click_count += 1
        if self.click_count == self.fail_on_click_number:
            raise RuntimeError("simulated adb failure")
        return super().click_bounds(bounds)


def test_commit_per_action_survives_a_real_crash_mid_mapping() -> None:
    package_name = "com.realcrash.testapp"
    service = build_service([])
    service.ui = CrashingUi([MULTI_BUTTON_ROOT, LEAF_NODES, LEAF_NODES], fail_on_click_number=3)

    with pytest.raises(RuntimeError):
        service.run(MapperRunConfig(package_name=package_name, mode=MapperMode.LIGHT))

    # a fresh session, not the one the crashed run used, proves the data is actually committed
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.get_latest_session(package_name)
        assert mapper_session is not None
        assert mapper_session.status == MapperSessionStatus.RUNNING  # never reached COMPLETED
        crashed_id = mapper_session.id

        actions = repository.list_actions(crashed_id)
        assert len(actions) == 2  # button A and B fully committed, button C's attempt rolled back
        assert all(action.executed and action.success for action in actions)

    # resuming should replay A and B (already known) and only newly attempt C
    resume_service = build_service([MULTI_BUTTON_ROOT, LEAF_NODES, LEAF_NODES, LEAF_NODES])
    result = resume_service.run(MapperRunConfig(package_name=package_name, mode=MapperMode.LIGHT))

    assert result["session_id"] == crashed_id
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.get_session(crashed_id)
        assert mapper_session.status == MapperSessionStatus.COMPLETED
        actions = repository.list_actions(crashed_id)
        assert len(actions) == 3
        assert all(action.executed and action.success for action in actions)


def test_override_and_complement_together_raises() -> None:
    service = build_service([])
    with pytest.raises(ValueError):
        service.run(MapperRunConfig(package_name="com.invalid.testapp", mode=MapperMode.LIGHT, override=True, complement=True))
