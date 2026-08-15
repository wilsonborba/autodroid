from __future__ import annotations

import pytest
from sqlalchemy import text

from lib.core.logs import get_logger
from lib.dal.local.database import SessionLocal
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode, MapperRunConfig, MapperSessionStatus
from lib.domain.services.mapper_fingerprint_service import MapperFingerprintService
from lib.domain.services.mapper_mode_service import MapperModeService
from lib.domain.services.mapper_safety_service import MapperSafetyService
from lib.domain.services.ui_mapper_service import UiMapperService

ROOT_NODES = [{"text": "Profile", "content_desc": "", "resource_id": "profile_btn", "class_name": "TextView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True}]
LEAF_NODES = [{"text": "", "content_desc": "", "resource_id": "", "class_name": "TextView", "bounds": "[0,0][5,5]", "clickable": False, "enabled": True}]
DANGEROUS_ROOT_NODES = [{"text": "Delete account", "content_desc": "", "resource_id": "delete_account", "class_name": "TextView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True}]

IN_APP_ROOT = [{"text": "Profile", "content_desc": "", "resource_id": "profile_btn", "class_name": "TextView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True, "package_name": "com.target.testapp"}]
IN_APP_LEAF = [{"text": "", "content_desc": "", "resource_id": "", "class_name": "TextView", "bounds": "[0,0][5,5]", "clickable": False, "enabled": True, "package_name": "com.target.testapp"}]
FOREIGN_APP_SCREEN = [{"text": "Share via", "content_desc": "", "resource_id": "chooser_item", "class_name": "TextView", "bounds": "[0,0][5,5]", "clickable": False, "enabled": True, "package_name": "com.android.systemui"}]
MIXED_PACKAGE_ROOT = [
    {"text": "Search jobs", "content_desc": "", "resource_id": "search_btn", "class_name": "TextView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True, "package_name": "com.target.testapp"},
    {"text": "Clock", "content_desc": "", "resource_id": "clock", "class_name": "TextView", "bounds": "[90,0][100,10]", "clickable": True, "enabled": True, "package_name": "com.android.systemui"},
]


def _profile_dump(name: str) -> list[dict]:
    return [
        {"resource_id": "profile_header", "text": name, "content_desc": "", "class_name": "TextView", "bounds": "[0,0][100,10]", "clickable": False, "enabled": True, "package_name": "com.target.testapp"},
        {"resource_id": "connections_link", "text": "Connections", "content_desc": "", "class_name": "TextView", "bounds": "[0,20][100,30]", "clickable": True, "enabled": True, "package_name": "com.target.testapp"},
    ]


ROOT_TWO_PROFILES = [
    {"resource_id": "open_profile_a", "text": "Profile A", "content_desc": "", "class_name": "TextView", "bounds": "[0,0][100,10]", "clickable": True, "enabled": True, "package_name": "com.target.testapp"},
    {"resource_id": "open_profile_b", "text": "Profile B", "content_desc": "", "class_name": "TextView", "bounds": "[0,10][100,20]", "clickable": True, "enabled": True, "package_name": "com.target.testapp"},
]

_TEST_PACKAGE_NAMES = (
    "com.fresh.testapp", "com.dangerous.testapp", "com.reuse.testapp", "com.override.testapp",
    "com.complement.testapp", "com.satisfied.testapp", "com.resume.testapp",
    "com.feedscroll.testapp", "com.noscroll.testapp", "com.realcrash.testapp", "com.target.testapp",
    "com.scrollbudget.testapp", "com.replay.testapp", "com.interleave.testapp",
    "com.candidatelog.testapp", "com.replaylog.testapp",
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


def test_candidate_and_click_outcome_are_logged_at_debug_level(caplog) -> None:
    caplog.set_level("DEBUG")
    service = build_service([ROOT_NODES, LEAF_NODES])

    service.run(MapperRunConfig(package_name="com.candidatelog.testapp", mode=MapperMode.LIGHT))

    messages = [record.message for record in caplog.records]
    assert any("Candidate found: 'Profile'" in message for message in messages)
    assert any(message.startswith("Clicked 'Profile'") and "success=True" in message for message in messages)


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


def test_click_that_leaves_the_target_app_is_not_recorded_as_a_screen() -> None:
    service = build_service([IN_APP_ROOT, FOREIGN_APP_SCREEN])

    result = service.run(MapperRunConfig(package_name="com.target.testapp", mode=MapperMode.LIGHT))

    assert result["screens_recorded"] == 1  # only the root; the foreign screen was never recorded
    assert result["actions_executed"] == 1  # the click still happened, it still used the budget
    # recovery relaunches the app instead of a plain back press (issue #28): a plain back from an
    # unknown foreign screen isn't reliable, relaunching guarantees a known state (the root)
    assert service.navigation_context.prepared == ["com.target.testapp", "com.target.testapp"]
    assert service.adb.back_calls == 0

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        transitions = repository.list_transitions(result["session_id"])
        assert len(transitions) == 1
        assert transitions[0].result_type == "left_app"
        assert transitions[0].to_screen_id is None


def test_candidates_from_other_packages_are_never_attempted() -> None:
    # a dump also carries status bar / nav bar / launcher-edge nodes, each with their own
    # package_name; clicking those would waste the action budget before ever trying the app's
    # own buttons, so they should never even become candidates in the first place
    service = build_service([MIXED_PACKAGE_ROOT, IN_APP_LEAF])

    result = service.run(MapperRunConfig(package_name="com.target.testapp", mode=MapperMode.LIGHT))

    assert result["actions_executed"] == 1
    assert service.ui.clicks == ["[0,0][10,10]"]  # the systemui clock was never clicked
    assert result["screens_recorded"] == 2


def test_non_clickable_labeled_node_is_still_a_candidate() -> None:
    # LinkedIn (and apparently other apps) regularly exports a genuinely tappable element as
    # clickable=false in the accessibility tree, class doesn't matter either: a plain TextView
    # ("Groups", in the real case that surfaced this) turned out just as tappable as a proper
    # Button. The app's own flag isn't trusted anymore, the safety classification is the real
    # gate against wasting a click, not this accessibility attribute (issue #37).
    root = [{
        "text": "Wilson Borba", "content_desc": "", "resource_id": "profile_card",
        "class_name": "android.widget.Button", "bounds": "[0,0][10,10]",
        "clickable": False, "enabled": True, "package_name": "com.target.testapp",
    }]
    service = build_service([root, IN_APP_LEAF])

    result = service.run(MapperRunConfig(package_name="com.target.testapp", mode=MapperMode.LIGHT))

    assert result["actions_executed"] == 1
    assert service.ui.clicks == ["[0,0][10,10]"]


def test_non_clickable_plain_textview_is_still_a_candidate() -> None:
    # same as above, but without even a Button-ish class name, exactly the "Groups" case: a
    # plain android.widget.TextView with no clickable flag at all, still worth trying
    root = [{
        "text": "Groups", "content_desc": "", "resource_id": "home_nav_panel_section_text",
        "class_name": "android.widget.TextView", "bounds": "[0,0][10,10]",
        "clickable": False, "enabled": True, "package_name": "com.target.testapp",
    }]
    service = build_service([root, IN_APP_LEAF])

    result = service.run(MapperRunConfig(package_name="com.target.testapp", mode=MapperMode.LIGHT))

    assert result["actions_executed"] == 1
    assert service.ui.clicks == ["[0,0][10,10]"]


def test_leaving_the_app_from_a_deep_screen_relaunches_and_replays_the_way_back() -> None:
    root = [{"text": "Open Section", "content_desc": "", "resource_id": "open_section", "class_name": "TextView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True, "package_name": "com.target.testapp"}]
    mid = [{"text": "Share", "content_desc": "", "resource_id": "share_btn", "class_name": "TextView", "bounds": "[0,20][10,30]", "clickable": True, "enabled": True, "package_name": "com.target.testapp"}]
    foreign = [{"text": "Share via", "content_desc": "", "resource_id": "chooser", "class_name": "TextView", "bounds": "[0,0][5,5]", "clickable": False, "enabled": True, "package_name": "com.android.systemui"}]
    service = build_service([root, mid, foreign])

    service.run(MapperRunConfig(package_name="com.target.testapp", mode=MapperMode.MEDIUM))

    # open_section, then share (which leaves the app), then open_section again to walk back to mid
    assert service.ui.clicks == ["[0,0][10,10]", "[0,20][10,30]", "[0,0][10,10]"]
    assert service.navigation_context.prepared == ["com.target.testapp", "com.target.testapp"]


def test_click_that_stays_in_the_target_app_is_recorded_normally() -> None:
    service = build_service([IN_APP_ROOT, IN_APP_LEAF])

    result = service.run(MapperRunConfig(package_name="com.target.testapp", mode=MapperMode.LIGHT))

    assert result["screens_recorded"] == 2

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        transitions = repository.list_transitions(result["session_id"])
        assert transitions[0].result_type == "clicked"
        assert transitions[0].to_screen_id is not None


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


def test_scroll_stops_after_consecutive_empty_scrolls_not_at_max_scrolls() -> None:
    # the first two scrolls reveal genuinely new posts, then it "hits bottom" and repeats
    # forever: light's max_consecutive_empty_scrolls is 3, max_scrolls is 30, so if the early
    # exit is working, it stops well before the safety ceiling (issue #34)
    dumps = [_feed_dump("Post 0"), _feed_dump("Post 1"), _feed_dump("Post 2")] + [_feed_dump("Post 2")] * 10
    service = build_service(dumps)

    result = service.run(MapperRunConfig(package_name="com.feedscroll.testapp", mode=MapperMode.LIGHT))

    limits = MapperModeService().get_limits(MapperMode.LIGHT)
    assert service.ui.swipes == 5  # 2 scrolls with new content + 3 confirming nothing more is coming
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


def test_navigate_back_prefers_an_in_app_back_button_over_system_back() -> None:
    screen_with_back_button = [{"text": "", "content_desc": "Back", "resource_id": "toolbar_back_button", "class_name": "ImageButton", "bounds": "[0,0][5,5]", "clickable": True, "enabled": True, "package_name": "com.target.testapp"}]
    service = build_service([screen_with_back_button])

    service._navigate_back("com.target.testapp")

    assert service.ui.clicks == ["[0,0][5,5]"]
    assert service.adb.back_calls == 0


def test_navigate_back_falls_back_to_system_back_without_an_in_app_button() -> None:
    screen_without_back_button = [{"text": "Some content", "content_desc": "", "resource_id": "content", "class_name": "TextView", "bounds": "[0,0][5,5]", "clickable": False, "enabled": True, "package_name": "com.target.testapp"}]
    service = build_service([screen_without_back_button])

    service._navigate_back("com.target.testapp")

    assert service.ui.clicks == []
    assert service.adb.back_calls == 1


def test_navigate_back_ignores_a_back_looking_button_from_another_package() -> None:
    foreign_back_button = [{"text": "", "content_desc": "Back", "resource_id": "back_button", "class_name": "ImageButton", "bounds": "[0,0][5,5]", "clickable": True, "enabled": True, "package_name": "com.android.systemui"}]
    service = build_service([foreign_back_button])

    service._navigate_back("com.target.testapp")

    assert service.ui.clicks == []  # not trusted, could take us further from the target app
    assert service.adb.back_calls == 1


def test_second_instance_of_a_structural_type_is_deduped_not_re_explored() -> None:
    # root -> Profile A (first of its type, fully explored, its Connections link gets tried) and
    # Profile B (same structure, different text: recognized as another instance, deduped)
    dumps = [ROOT_TWO_PROFILES, _profile_dump("Alice")] + [[]] * 8 + [_profile_dump("Bob")] + [[]] * 8
    service = build_service(dumps)

    result = service.run(MapperRunConfig(package_name="com.target.testapp", mode=MapperMode.MEDIUM))

    assert result["screens_recorded"] == 3  # root, Alice, Bob: all recorded, coverage preserved
    assert service.ui.clicks.count("[0,20][100,30]") == 1  # Connections: tried once (Alice), not for Bob

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        screens = repository.list_screens(result["session_id"])  # ordered: root, Alice, Bob
        bob_screen = screens[2]
        assert bob_screen.expanded is True  # deduped screens still end up expanded=True
        assert repository.list_actions(result["session_id"], screen_id=bob_screen.id) == []  # never got its own candidates tried


def _fixed_content_dump(section_text: str) -> list[dict]:
    return [
        {"resource_id": "scroll_container", "text": "", "content_desc": "", "class_name": "ScrollView", "bounds": "[0,0][100,800]", "clickable": False, "enabled": True, "scrollable": True, "package_name": "com.target.testapp"},
        {"resource_id": "section_text", "text": section_text, "content_desc": "", "class_name": "TextView", "bounds": "[0,50][100,100]", "clickable": False, "enabled": True, "package_name": "com.target.testapp"},
    ]


def test_scrolling_a_fixed_content_page_accumulates_into_the_same_screen() -> None:
    # each "scroll" reveals a different section (About, Experience, Education), reaching a fixed
    # end (repeats "Education" once we're at the bottom): a profile-like page, not a feed
    sections = ["About", "Experience", "Education", "Education", "Education", "Education", "Education"]
    dumps = [_fixed_content_dump(s) for s in sections]
    service = build_service(dumps)
    # each section header is real, labeled content (needed below), so it's now also a candidate
    # in its own right (issue #37); this fixture is only about scroll accumulation, so a click
    # attempt on one is made to fail harmlessly instead of recursing into the next queued dump,
    # which is reserved for the next scroll, not "whatever clicking a section header reveals"
    service.ui.click_bounds = lambda bounds: False

    result = service.run(MapperRunConfig(package_name="com.target.testapp", mode=MapperMode.MEDIUM))

    assert result["screens_recorded"] == 1  # not one screen per scroll position
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        screen = repository.list_screens(result["session_id"])[0]
        node_texts = {node.text for node in repository.get_screen(screen.id).nodes}
        assert {"About", "Experience", "Education"} <= node_texts  # all sections accumulated here


MESSAGE_TARGET_ROOT = [{"resource_id": "message_btn", "text": "Message", "content_desc": "", "class_name": "TextView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True, "package_name": "com.target.testapp"}]
COMPOSE_SCREEN = [{"resource_id": "send_btn", "text": "Send", "content_desc": "", "class_name": "TextView", "bounds": "[0,50][10,60]", "clickable": True, "enabled": True, "package_name": "com.target.testapp"}]


def test_peek_candidate_catalogs_revealed_screen_without_exploring_it() -> None:
    service = build_service([MESSAGE_TARGET_ROOT, COMPOSE_SCREEN])

    result = service.run(MapperRunConfig(package_name="com.target.testapp", mode=MapperMode.LIGHT))

    assert result["screens_recorded"] == 2  # root + the revealed compose screen, catalogued
    assert "[0,50][10,60]" not in service.ui.clicks  # Send was never clicked

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        screens = repository.list_screens(result["session_id"])
        compose_screen = screens[1]
        assert repository.list_actions(result["session_id"], screen_id=compose_screen.id) == []


def _scrollable_dump(section_text: str) -> list[dict]:
    # the varying marker lives in resource_id, not text (issue #37 review): a labeled node is
    # now a candidate on its own regardless of clickable, this fixture only cares about scroll
    # behaviour, not click behaviour, so it stays label-less on purpose (node_key still differs
    # per scroll via resource_id, which is all "new content this scroll" detection needs)
    return [
        {"resource_id": "scroll_container", "text": "", "content_desc": "", "class_name": "ScrollView", "bounds": "[0,0][100,800]", "clickable": False, "enabled": True, "scrollable": True, "package_name": "com.scrollbudget.testapp"},
        {"resource_id": f"section_text_{section_text}", "text": "", "content_desc": "", "class_name": "TextView", "bounds": "[0,50][100,100]", "clickable": False, "enabled": True, "package_name": "com.scrollbudget.testapp"},
    ]


def test_scroll_budget_is_per_screen_not_shared_across_the_session() -> None:
    # issue #33: a screen that already used up the whole session's scroll counter must not leave
    # every screen mapped afterward with zero scrolls of its own. Content differs every scroll
    # (new node_key each time), so max_consecutive_empty_scrolls never triggers, only max_scrolls
    # (the per-screen ceiling) decides when this particular screen stops.
    service = build_service([_scrollable_dump(f"content-{i}") for i in range(5)])
    state = {"screens_recorded": 0, "actions_executed": 0, "scrolls_used": 3, "revisited_screens": 0}  # 3 already "spent" elsewhere this session

    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.create_session(package_name="com.scrollbudget.testapp", mode=MapperMode.LIGHT, skip_dangerous_actions=True, max_depth=1, max_actions=8, max_scrolls=3)
        session.commit()
        session_id = mapper_session.id

        service._explore(
            repository, session_id, depth=0, state=state, visited_this_pass=set(),
            max_depth=1, max_actions=8, max_scrolls=3, max_consecutive_empty_scrolls=100,
            config_skip_dangerous_actions=True, package_name="com.scrollbudget.testapp",
        )
        session.commit()

    assert service.ui.swipes == 3  # got its own full 3 scrolls despite the session counter starting at 3
    assert state["scrolls_used"] == 6  # 3 pre-existing + 3 from this screen, still tracked for reporting


def test_replay_target_skips_dead_ends_and_already_expanded_destinations() -> None:
    # issue #33: replaying every recorded action unconditionally every time a screen is revisited
    # (including ones that left the app or lead to an already fully-explored screen) is what a
    # user reported as an endless loop; only a destination still worth reaching should be replayed
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.create_session(package_name="com.replay.testapp", mode=MapperMode.LIGHT, skip_dangerous_actions=True, max_depth=1, max_actions=8, max_scrolls=0)
        screen_a = repository.create_screen(session_id=mapper_session.id, fingerprint="a", screen_key="a", depth=0, ordinal=0)
        screen_b_expanded = repository.create_screen(session_id=mapper_session.id, fingerprint="b", screen_key="b", depth=1, ordinal=1)
        repository.mark_screen_expanded(screen_b_expanded.id)
        screen_c_open = repository.create_screen(session_id=mapper_session.id, fingerprint="c", screen_key="c", depth=1, ordinal=2)

        def make_click_action(label: str, bounds: str):
            node = repository.create_node(screen_id=screen_a.id, node_key=f"node-{label}", text=label, clickable=True, bounds=bounds)
            return repository.create_action(session_id=mapper_session.id, screen_id=screen_a.id, node_id=node.id, action_key=f"click:{label}", action_type="click", label=label, safety=MapperActionSafety.SAFE, executed=True, success=True)

        action_to_expanded = make_click_action("ToExpanded", "[0,0][10,10]")
        repository.create_transition(session_id=mapper_session.id, from_screen_id=screen_a.id, action_id=action_to_expanded.id, to_screen_id=screen_b_expanded.id, result_type="clicked")

        action_to_open = make_click_action("ToOpen", "[0,20][10,30]")
        repository.create_transition(session_id=mapper_session.id, from_screen_id=screen_a.id, action_id=action_to_open.id, to_screen_id=screen_c_open.id, result_type="clicked")

        action_left_app = make_click_action("LeftApp", "[0,40][10,50]")
        repository.create_transition(session_id=mapper_session.id, from_screen_id=screen_a.id, action_id=action_left_app.id, to_screen_id=None, result_type="left_app")

        session.commit()
        action_to_expanded_id, action_to_open_id, action_left_app_id = action_to_expanded.id, action_to_open.id, action_left_app.id

    service = build_service([])
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        assert service._replay_target(repository, repository.get_action(action_to_expanded_id)) is None
        assert service._replay_target(repository, repository.get_action(action_left_app_id)) is None
        target = service._replay_target(repository, repository.get_action(action_to_open_id))
        assert target is not None
        assert target.bounds == "[0,20][10,30]"


def test_replay_target_logs_why_an_action_is_not_replayable(caplog) -> None:
    # issue #38: this is exactly the kind of "it clicked here but didn't recognize X" tracking
    # detail asked for, the reason has to be readable from the log, not just inferred
    caplog.set_level("DEBUG")
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.create_session(package_name="com.replaylog.testapp", mode=MapperMode.LIGHT, skip_dangerous_actions=True, max_depth=1, max_actions=8, max_scrolls=0)
        screen_a = repository.create_screen(session_id=mapper_session.id, fingerprint="a", screen_key="a", depth=0, ordinal=0)
        screen_b_expanded = repository.create_screen(session_id=mapper_session.id, fingerprint="b", screen_key="b", depth=1, ordinal=1)
        repository.mark_screen_expanded(screen_b_expanded.id)

        node = repository.create_node(screen_id=screen_a.id, node_key="node-ToExpanded", text="ToExpanded", clickable=True, bounds="[0,0][10,10]")
        action = repository.create_action(session_id=mapper_session.id, screen_id=screen_a.id, node_id=node.id, action_key="click:ToExpanded", action_type="click", label="ToExpanded", safety=MapperActionSafety.SAFE, executed=True, success=True)
        repository.create_transition(session_id=mapper_session.id, from_screen_id=screen_a.id, action_id=action.id, to_screen_id=screen_b_expanded.id, result_type="clicked")
        session.commit()
        action_id = action.id

    service = build_service([])
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        service._replay_target(repository, repository.get_action(action_id))

    assert any("already fully expanded" in record.message for record in caplog.records)


class _EventLoggingUi(FakeUi):
    def __init__(self, dumps: list[list[dict]]) -> None:
        super().__init__(dumps)
        self.events: list[str] = []

    def swipe_up(self) -> None:
        super().swipe_up()
        self.events.append("swipe")

    def click_bounds(self, bounds: str) -> bool:
        self.events.append(f"click:{bounds}")
        return super().click_bounds(bounds)


def test_scroll_and_interact_are_interleaved_not_scroll_then_click_at_the_end() -> None:
    # issue #34: a candidate revealed by a scroll is tried right away, not deferred until every
    # last scroll has finished; proven by checking the swipe/click order, not just the counts
    scroll_container = {"resource_id": "scroll", "text": "", "content_desc": "", "class_name": "ScrollView", "bounds": "[0,0][100,800]", "clickable": False, "enabled": True, "scrollable": True, "package_name": "com.interleave.testapp"}
    item_a = {"resource_id": "item_a", "text": "Item A", "content_desc": "", "class_name": "TextView", "bounds": "[0,50][100,60]", "clickable": True, "enabled": True, "package_name": "com.interleave.testapp"}
    item_b = {"resource_id": "item_b", "text": "Item B", "content_desc": "", "class_name": "TextView", "bounds": "[0,70][100,80]", "clickable": True, "enabled": True, "package_name": "com.interleave.testapp"}
    root = [scroll_container]
    after_scroll_1 = [scroll_container, item_a]
    after_scroll_2 = [scroll_container, item_a, item_b]
    dead_end: list[dict] = []

    service = build_service([])
    service.ui = _EventLoggingUi([
        root, after_scroll_1, dead_end, dead_end, after_scroll_2, dead_end, dead_end,
        after_scroll_2, after_scroll_2, after_scroll_2,
    ])

    service.run(MapperRunConfig(package_name="com.interleave.testapp", mode=MapperMode.LIGHT))

    assert service.ui.events == [
        "swipe", "click:[0,50][100,60]",
        "swipe", "click:[0,70][100,80]",
        "swipe", "swipe", "swipe",
    ]
