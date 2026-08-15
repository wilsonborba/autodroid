from __future__ import annotations

from sqlalchemy import select

from lib.dal.local.database import SessionLocal
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.dal.local.mapper_route_repository import SqlAlchemyMapperRoutePerformanceRepository
from lib.domain.models.mapper_flow_model import MapperFlow, MapperFlowFailure, MapperFlowStep
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode
from lib.domain.services.mapper_flow_execution_service import MapperFlowExecutionService
from lib.domain.services.mapper_route_planner_service import RestartOption


def _failures_for(package_name: str) -> list[MapperFlowFailure]:
    with SessionLocal() as session:
        return list(session.scalars(select(MapperFlowFailure).where(MapperFlowFailure.package_name == package_name)))


class FakeUi:
    def __init__(self, dump_sequence: list[list[dict]] | None = None) -> None:
        self.clicked_exact: list[tuple[str, ...]] = []
        self.clicked_contains: list[tuple[str, ...]] = []
        self.exact_result = True
        self.contains_result = True
        self.swipes = 0
        self.screenshots: list[str] = []
        self.clicked_bounds: list[str] = []
        self.click_bounds_result = True
        # dumps are consumed one per call; once exhausted, the last one repeats (simulates the
        # screen "settling" once there's no more new content to scroll into)
        self.dump_sequence = list(dump_sequence) if dump_sequence else [[{"text": "hello"}]]

    def click_first_by_text_or_description(self, *candidates: str) -> bool:
        self.clicked_exact.append(candidates)
        return self.exact_result

    def click_first_by_text_or_description_contains(self, *candidates: str) -> bool:
        self.clicked_contains.append(candidates)
        return self.contains_result

    def swipe_up(self) -> None:
        self.swipes += 1

    def dump_nodes(self):
        if len(self.dump_sequence) > 1:
            return self.dump_sequence.pop(0)
        return self.dump_sequence[0]

    def screenshot(self, path):
        self.screenshots.append(str(path))
        return path

    def click_bounds(self, bounds: str) -> bool:
        self.clicked_bounds.append(bounds)
        return self.click_bounds_result


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


class FakeOcr:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def extract_lines(self, path):
        self.calls.append(str(path))
        return ["line one"]


def build_service(dump_sequence: list[list[dict]] | None = None) -> MapperFlowExecutionService:
    service = MapperFlowExecutionService.__new__(MapperFlowExecutionService)
    from lib.core.logs import get_logger
    from lib.core.settings import load_settings
    from lib.domain.services.mapper_fingerprint_service import MapperFingerprintService
    from lib.domain.services.mapper_safety_service import MapperSafetyService

    service.logger = get_logger(__name__)
    settings = load_settings()
    service.settings = type("Settings", (), {"output_dir": __import__("pathlib").Path("/tmp/autodroid-flow-tests"), "timezone": settings.timezone})()
    service.ui = FakeUi(dump_sequence)
    service.adb = FakeAdb()
    service.navigation_context = FakeNav()
    service.ocr = FakeOcr()
    service.safety_service = MapperSafetyService()
    service.fingerprint_service = MapperFingerprintService()
    service._handlers = {
        "click": service._execute_click,
        "click_first_match": service._execute_click_first_match,
        "scroll_up": service._execute_scroll_up,
        "back": service._execute_back,
        "wait": service._execute_wait,
        "dump_nodes": service._execute_dump_nodes,
        "screenshot": service._execute_screenshot,
        "ocr_extract": service._execute_ocr_extract,
    }
    return service


def make_step(**kwargs) -> MapperFlowStep:
    step = MapperFlowStep(
        package_name=kwargs.pop("package_name", "com.test.testapp"),
        action_type=kwargs.pop("action_type"),
        selector_json=kwargs.pop("selector_json", {}),
        params_json=kwargs.pop("params_json", None),
    )
    step.id = kwargs.pop("id", 1)
    return step


def test_click_step_executes_and_reports_success() -> None:
    service = build_service()
    step = make_step(action_type="click", selector_json={"candidates": ["Profile", "Perfil"]})

    result = service.run_step(step)

    assert result["success"] is True
    assert service.ui.clicked_exact == [("Profile", "Perfil")]


def test_click_step_blocked_when_label_is_dangerous() -> None:
    service = build_service()
    step = make_step(action_type="click", selector_json={"candidates": ["Delete account"]})

    result = service.run_step(step)

    assert result["success"] is False
    assert result["skipped_reason"] == "dangerous_action_blocked"
    assert service.ui.clicked_exact == []


def test_click_step_dangerous_allowed_with_override() -> None:
    service = build_service()
    step = make_step(action_type="click", selector_json={"candidates": ["Delete account"]})

    result = service.run_step(step, skip_dangerous_actions=False)

    assert result["skipped_reason"] is None
    assert service.ui.clicked_exact == [("Delete account",)]


def test_click_first_match_stops_at_first_success() -> None:
    service = build_service()
    service.ui.exact_result = True
    step = make_step(
        action_type="click_first_match",
        selector_json={
            "attempts": [
                {"match": "exact", "candidates": ["Meu perfil"]},
                {"match": "contains_then_exact", "open_candidates": ["access my profile"], "then_candidates": ["My Profile"]},
            ]
        },
    )

    result = service.run_step(step)

    assert result["success"] is True
    assert service.ui.clicked_contains == []


def test_click_first_match_falls_back_to_menu() -> None:
    service = build_service()
    service.ui.exact_result = False
    step = make_step(
        action_type="click_first_match",
        selector_json={
            "attempts": [
                {"match": "exact", "candidates": ["Meu perfil"]},
                {"match": "contains_then_exact", "open_candidates": ["access my profile"], "then_candidates": ["My Profile"]},
            ]
        },
    )
    service.ui.exact_result = False

    def toggled_click(*candidates):
        service.ui.clicked_exact.append(candidates)
        return candidates == ("My Profile",)

    service.ui.click_first_by_text_or_description = toggled_click

    result = service.run_step(step)

    assert result["success"] is True
    assert service.ui.clicked_contains == [("access my profile",)]


def test_unsupported_action_type_reports_failure_without_raising() -> None:
    service = build_service()
    step = make_step(action_type="teleport", selector_json={})

    result = service.run_step(step)

    assert result["success"] is False
    assert result["skipped_reason"] == "unsupported_action_type"


def test_run_flow_executes_all_steps_in_order() -> None:
    service = build_service()
    flow = MapperFlow(id=1, name="extract_profile", package_name="com.linkedin.android")
    steps = [
        make_step(id=10, action_type="click", selector_json={"candidates": ["Profile"]}),
        make_step(id=11, action_type="scroll_up"),
        make_step(id=12, action_type="dump_nodes"),
    ]

    result = service.run_flow(flow, steps)

    assert result["flow_id"] == 1
    assert [step["step_id"] for step in result["steps"]] == [10, 11, 12]
    assert all(step["success"] for step in result["steps"])
    assert service.ui.swipes == 1


def _changing_dumps(count: int) -> list[list[dict]]:
    return [[{"text": f"item-{i}"}] for i in range(count)]


def test_repeated_step_stops_at_max_iterations() -> None:
    service = build_service(dump_sequence=_changing_dumps(20))
    step = make_step(action_type="scroll_up", params_json={"repeat": {"max_iterations": 5}})

    result = service.run_step(step)

    assert result["iterations_run"] == 5
    assert result["stop_reason"] == "max_iterations"
    assert service.ui.swipes == 5


def test_repeated_step_stops_at_max_duration(monkeypatch) -> None:
    service = build_service(dump_sequence=_changing_dumps(50))
    step = make_step(action_type="scroll_up", params_json={"repeat": {"max_duration_seconds": 1}})

    clock = {"value": 0.0}

    def fake_monotonic():
        clock["value"] += 0.5
        return clock["value"]

    monkeypatch.setattr("lib.domain.services.mapper_flow_execution_service.time.monotonic", fake_monotonic)

    result = service.run_step(step)

    assert result["stop_reason"] == "max_duration_seconds"
    assert result["iterations_run"] >= 1


def test_repeated_step_stops_when_content_stops_changing() -> None:
    # 3 distinct dumps, then it "settles" and keeps returning the last one forever: it takes one
    # extra iteration past the last distinct dump to actually notice the fingerprint repeated
    service = build_service(dump_sequence=_changing_dumps(3))
    step = make_step(action_type="scroll_up", params_json={"repeat": {"max_iterations": 50}})

    result = service.run_step(step)

    assert result["stop_reason"] == "no_new_content"
    assert result["iterations_run"] == 4
    assert service.ui.swipes == 4


def test_repeated_step_respects_execution_window_already_closed() -> None:
    service = build_service(dump_sequence=_changing_dumps(10))
    step = make_step(
        action_type="scroll_up",
        params_json={"repeat": {"max_iterations": 5, "execution_window_start": "00:00:00", "execution_window_end": "00:00:01"}},
    )

    result = service.run_step(step)

    assert result["stop_reason"] == "execution_window"
    assert result["iterations_run"] == 0
    assert service.ui.swipes == 0


def test_step_without_repeat_config_runs_exactly_once() -> None:
    service = build_service()
    step = make_step(action_type="scroll_up")

    result = service.run_step(step)

    assert "iterations_run" not in result
    assert service.ui.swipes == 1


def test_click_selector_not_found_records_interaction_failure() -> None:
    service = build_service()
    service.ui.exact_result = False
    step = make_step(package_name="com.failure1.testapp", action_type="click", selector_json={"candidates": ["Ghost Button"]})

    result = service.run_step(step, flow_id=7)

    assert result["success"] is False
    failures = _failures_for("com.failure1.testapp")
    assert len(failures) == 1
    assert failures[0].failure_type.value == "selector_not_found"
    assert failures[0].flow_id == 7
    assert failures[0].resolved_at is None


def test_unsupported_action_type_records_failure() -> None:
    service = build_service()
    step = make_step(package_name="com.failure2.testapp", action_type="teleport", selector_json={})

    service.run_step(step)

    failures = _failures_for("com.failure2.testapp")
    assert len(failures) == 1
    assert failures[0].failure_type.value == "unsupported_action_type"


def test_successful_step_does_not_record_a_failure() -> None:
    service = build_service()
    step = make_step(package_name="com.failure3.testapp", action_type="click", selector_json={"candidates": ["Profile"]})

    service.run_step(step)

    assert _failures_for("com.failure3.testapp") == []


def test_dangerous_action_blocked_does_not_record_a_failure() -> None:
    service = build_service()
    step = make_step(package_name="com.failure4.testapp", action_type="click", selector_json={"candidates": ["Delete account"]})

    service.run_step(step)

    assert _failures_for("com.failure4.testapp") == []


def test_navigate_returns_immediately_when_already_at_target_screen() -> None:
    service = build_service()

    result = service.navigate(
        package_name="com.samescreen.testapp", session_id=1, current_screen_id=5, target_screen_id=5,
        restart_option=RestartOption(root_screen_id=5, ancestor_step_ids=[]), restart_steps=[],
    )

    assert result["strategy_type"] == "already_there"
    assert result["success"] is True


def test_navigate_walks_direct_path_and_records_route_performance() -> None:
    with SessionLocal() as session:
        repository = SqlAlchemyMapperRepository(session)
        mapper_session = repository.create_session(package_name="com.navigate.testapp", mode=MapperMode.LIGHT, skip_dangerous_actions=True, max_depth=3, max_actions=20, max_scrolls=0)
        root = repository.create_screen(session_id=mapper_session.id, fingerprint="root", screen_key="root", depth=0, ordinal=0)
        target = repository.create_screen(session_id=mapper_session.id, fingerprint="target", screen_key="target", depth=1, ordinal=1)
        node = repository.create_node(screen_id=root.id, node_key="node", text="Go", clickable=True, bounds="[0,0][10,10]")
        action = repository.create_action(session_id=mapper_session.id, screen_id=root.id, node_id=node.id, action_key="click:go", action_type="click", label="Go", safety=MapperActionSafety.SAFE)
        repository.create_transition(session_id=mapper_session.id, from_screen_id=root.id, action_id=action.id, to_screen_id=target.id, result_type="clicked")
        session.commit()
        session_id, root_id, target_id = mapper_session.id, root.id, target.id

    service = build_service()
    result = service.navigate(
        package_name="com.navigate.testapp", session_id=session_id, current_screen_id=root_id, target_screen_id=target_id,
        restart_option=RestartOption(root_screen_id=root_id, ancestor_step_ids=[]), restart_steps=[],
    )

    assert result["strategy_type"] == "direct_path"
    assert result["success"] is True
    assert service.ui.clicked_bounds == ["[0,0][10,10]"]
    assert service.navigation_context.prepared == []  # direct path never needed a restart

    with SessionLocal() as session:
        perf_repository = SqlAlchemyMapperRoutePerformanceRepository(session)
        perf = perf_repository.get_route_performance(result["route_signature"])
        assert perf is not None
        assert perf.sample_count == 1

        transitions = SqlAlchemyMapperRepository(session).list_transitions(session_id)
        transition_perf = perf_repository.get_transition_performance(transitions[0].id)
        assert transition_perf is not None
        assert transition_perf.sample_count == 1
        assert transition_perf.success_count == 1


def test_navigate_restarts_and_replays_ancestor_steps_when_no_direct_path_exists() -> None:
    service = build_service()
    ancestor_step = make_step(id=501, action_type="click", selector_json={"candidates": ["Home"]})

    result = service.navigate(
        package_name="com.norestartpath.testapp", session_id=999999, current_screen_id=1, target_screen_id=2,
        restart_option=RestartOption(root_screen_id=1, ancestor_step_ids=[ancestor_step.id]),
        restart_steps=[ancestor_step],
    )

    assert result["strategy_type"] == "restart"
    assert result["success"] is True
    assert service.navigation_context.prepared == ["com.norestartpath.testapp"]
    assert service.ui.clicked_exact == [("Home",)]
