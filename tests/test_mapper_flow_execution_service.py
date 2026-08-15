from __future__ import annotations

import pytest
from sqlalchemy import select, text

from lib.dal.local.database import SessionLocal
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.dal.local.mapper_route_repository import SqlAlchemyMapperRoutePerformanceRepository
from lib.domain.models.mapper_flow_model import MapperFlow, MapperFlowFailure, MapperFlowStep
from lib.domain.models.mapper_types import MapperActionSafety, MapperMode
from lib.domain.services.mapper_flow_execution_service import MapperFlowExecutionService
from lib.domain.services.mapper_route_planner_service import RestartOption


@pytest.fixture(autouse=True)
def _clean_failures():
    # this project's tests share the real dev DB (no per-test isolation); the failure-recording
    # tests count rows for a fixed package_name, so a row left behind by a previous run would
    # make a fresh run see more failures than it actually caused itself.
    with SessionLocal() as session:
        session.execute(text("DELETE FROM mapper_flow_failures"))
        session.commit()


def _seed_gap_graph(session, *, package_name: str, with_direct_edge: bool):
    """root has two children: `screen_c` (what "step 1" leads to) and `screen_a` (what "step 2"
    expects to start from); `screen_a` also leads to `screen_b`. With `with_direct_edge`, a
    direct `screen_c -> screen_a` transition exists (a real gap the route planner can bridge
    without restarting); without it, reaching `screen_a` requires a restart."""
    repository = SqlAlchemyMapperRepository(session)
    mapper_session = repository.create_session(package_name=package_name, mode=MapperMode.LIGHT, skip_dangerous_actions=True, max_depth=3, max_actions=20, max_scrolls=0)
    root = repository.create_screen(session_id=mapper_session.id, fingerprint="root", screen_key="root", depth=0, ordinal=0)
    screen_a = repository.create_screen(session_id=mapper_session.id, fingerprint="a", screen_key="a", depth=1, ordinal=1)
    screen_b = repository.create_screen(session_id=mapper_session.id, fingerprint="b", screen_key="b", depth=2, ordinal=2)
    screen_c = repository.create_screen(session_id=mapper_session.id, fingerprint="c", screen_key="c", depth=1, ordinal=3)

    def add_edge(from_screen, to_screen, label, bounds):
        node = repository.create_node(screen_id=from_screen.id, node_key=f"node-{label}", text=label, clickable=True, bounds=bounds)
        action = repository.create_action(session_id=mapper_session.id, screen_id=from_screen.id, node_id=node.id, action_key=f"click:{label}", action_type="click", label=label, safety=MapperActionSafety.SAFE)
        repository.create_transition(session_id=mapper_session.id, from_screen_id=from_screen.id, action_id=action.id, to_screen_id=to_screen.id, result_type="clicked")
        return action

    action_root_to_c = add_edge(root, screen_c, "GoC", "[0,0][10,10]")
    add_edge(root, screen_a, "GoA", "[0,20][10,30]")  # the restart-fallback ancestor path
    action_a_to_b = add_edge(screen_a, screen_b, "GoB", "[0,40][10,50]")
    if with_direct_edge:
        add_edge(screen_c, screen_a, "Bridge", "[0,60][10,70]")

    return mapper_session, root, screen_a, screen_c, action_root_to_c, action_a_to_b


def _gap_flow_and_steps(mapper_session, root, screen_a, action_root_to_c, action_a_to_b, package_name: str):
    flow = MapperFlow(name="Gap flow", package_name=package_name)
    flow.id = 1
    flow.source_session_id = mapper_session.id

    step_one = make_step(id=901, package_name=package_name, action_type="click", selector_json={"candidates": ["GoC"]})
    step_one.source_screen_id = root.id
    step_one.source_action_id = action_root_to_c.id

    step_two = make_step(id=902, package_name=package_name, action_type="click", selector_json={"candidates": ["GoB"]})
    step_two.source_screen_id = screen_a.id
    step_two.source_action_id = action_a_to_b.id

    return flow, [step_one, step_two]


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
        self.typed_text: list[tuple[str, bool]] = []
        self.type_text_result = True
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

    def type_text(self, text: str, *, clear: bool = False) -> bool:
        self.typed_text.append((text, clear))
        return self.type_text_result


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

    def extract_text_regions(self, path):
        self.calls.append(str(path))
        return [{"text": "line one", "bounds": "[0,0][50,20]"}]


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
        "click_bounds": service._execute_click_bounds,
        "type_text": service._execute_type_text,
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


def test_click_bounds_step_clicks_the_exact_region() -> None:
    service = build_service()
    step = make_step(action_type="click_bounds", selector_json={"bounds": "[0,0][50,20]"})

    result = service.run_step(step)

    assert result["success"] is True
    assert service.ui.clicked_bounds == ["[0,0][50,20]"]


def test_click_bounds_step_fails_without_bounds() -> None:
    service = build_service()
    step = make_step(action_type="click_bounds", selector_json={})

    result = service.run_step(step)

    assert result["success"] is False
    assert service.ui.clicked_bounds == []


def test_type_text_step_types_into_the_focused_field() -> None:
    service = build_service()
    step = make_step(action_type="type_text", selector_json={"text": "Congrats on the launch!"})

    result = service.run_step(step)

    assert result["success"] is True
    assert service.ui.typed_text == [("Congrats on the launch!", False)]


def test_type_text_step_passes_clear_flag_through() -> None:
    service = build_service()
    step = make_step(action_type="type_text", selector_json={"text": "replacement", "clear": True})

    result = service.run_step(step)

    assert result["success"] is True
    assert service.ui.typed_text == [("replacement", True)]


def test_type_text_step_fails_without_text() -> None:
    service = build_service()
    step = make_step(action_type="type_text", selector_json={})

    result = service.run_step(step)

    assert result["success"] is False
    assert service.ui.typed_text == []


def test_ocr_extract_step_returns_text_regions() -> None:
    service = build_service()
    step = make_step(action_type="ocr_extract", selector_json={})

    result = service.run_step(step)

    assert result["success"] is True
    assert result["ocr_regions"] == [{"text": "line one", "bounds": "[0,0][50,20]"}]


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


def test_run_flow_does_not_bridge_when_steps_are_already_adjacent() -> None:
    package_name = "com.adjacentflow.testapp"
    with SessionLocal() as session:
        mapper_session, root, screen_a, screen_c, action_root_to_c, action_a_to_b = _seed_gap_graph(session, package_name=package_name, with_direct_edge=False)
        session.commit()
        flow, steps = _gap_flow_and_steps(mapper_session, root, screen_a, action_root_to_c, action_a_to_b, package_name)
        # step 1 now leads straight into step 2's expected screen: no gap to bridge
        steps[1].source_screen_id = screen_c.id

    service = build_service()
    result = service.run_flow(flow, steps)

    assert [step_result["success"] for step_result in result["steps"]] == [True, True]
    assert service.ui.clicked_bounds == []  # navigate() never ran, nothing to bridge
    assert service.navigation_context.prepared == []
    assert service.ui.clicked_exact == [("GoC",), ("GoB",)]


def test_run_flow_bridges_a_real_gap_using_the_route_planner() -> None:
    package_name = "com.bridgedflow.testapp"
    with SessionLocal() as session:
        mapper_session, root, screen_a, screen_c, action_root_to_c, action_a_to_b = _seed_gap_graph(session, package_name=package_name, with_direct_edge=True)
        session.commit()
        flow, steps = _gap_flow_and_steps(mapper_session, root, screen_a, action_root_to_c, action_a_to_b, package_name)

    service = build_service()
    result = service.run_flow(flow, steps)

    assert [step_result["success"] for step_result in result["steps"]] == [True, True]
    assert service.ui.clicked_bounds == ["[0,60][10,70]"]  # the bridging edge, walked once
    assert service.navigation_context.prepared == []  # a direct path never needs a restart
    assert service.ui.clicked_exact == [("GoC",), ("GoB",)]  # both steps still ran normally

    with SessionLocal() as session:
        transitions = SqlAlchemyMapperRepository(session).list_transitions(mapper_session.id)
        bridge_transition = next(t for t in transitions if t.from_screen_id == screen_c.id and t.to_screen_id == screen_a.id)
        perf = SqlAlchemyMapperRoutePerformanceRepository(session).get_transition_performance(bridge_transition.id)
        assert perf is not None and perf.sample_count == 1  # the bridging run was learned from


def test_run_flow_falls_back_to_restart_when_gap_has_no_direct_path() -> None:
    package_name = "com.restartflow.testapp"
    with SessionLocal() as session:
        mapper_session, root, screen_a, screen_c, action_root_to_c, action_a_to_b = _seed_gap_graph(session, package_name=package_name, with_direct_edge=False)
        session.commit()
        flow, steps = _gap_flow_and_steps(mapper_session, root, screen_a, action_root_to_c, action_a_to_b, package_name)

    service = build_service()
    result = service.run_flow(flow, steps)

    assert [step_result["success"] for step_result in result["steps"]] == [True, True]
    assert service.navigation_context.prepared == [package_name]  # had to restart the app
    # "GoA" is the auto-resolved ancestor replayed to reach step 2's screen, then step 2 itself
    assert ("GoA",) in service.ui.clicked_exact
    assert ("GoB",) in service.ui.clicked_exact


def test_execute_on_demand_runs_directly_when_already_at_the_target_screen() -> None:
    package_name = "com.ondemand1.testapp"
    with SessionLocal() as session:
        mapper_session, root, screen_a, screen_c, action_root_to_c, action_a_to_b = _seed_gap_graph(session, package_name=package_name, with_direct_edge=False)
        session.commit()
        screen_a_id, action_a_to_b_id = screen_a.id, action_a_to_b.id

    service = build_service()
    result = service.execute_on_demand(package_name=package_name, target_action_id=action_a_to_b_id, current_screen_id=screen_a_id)

    assert result["success"] is True
    assert service.navigation_context.prepared == []  # already there, no relaunch
    assert service.ui.clicked_bounds == []  # no bridging happened
    assert service.ui.clicked_exact == [("GoB",)]


def test_execute_on_demand_bridges_a_gap_using_the_route_planner() -> None:
    package_name = "com.ondemand2.testapp"
    with SessionLocal() as session:
        mapper_session, root, screen_a, screen_c, action_root_to_c, action_a_to_b = _seed_gap_graph(session, package_name=package_name, with_direct_edge=True)
        session.commit()
        screen_c_id, action_a_to_b_id = screen_c.id, action_a_to_b.id

    service = build_service()
    result = service.execute_on_demand(package_name=package_name, target_action_id=action_a_to_b_id, current_screen_id=screen_c_id)

    assert result["success"] is True
    assert service.ui.clicked_bounds == ["[0,60][10,70]"]  # the bridging edge, walked once
    assert service.navigation_context.prepared == []
    assert service.ui.clicked_exact == [("GoB",)]


def test_execute_on_demand_relaunches_and_replays_ancestors_when_position_unknown() -> None:
    package_name = "com.ondemand3.testapp"
    with SessionLocal() as session:
        mapper_session, root, screen_a, screen_c, action_root_to_c, action_a_to_b = _seed_gap_graph(session, package_name=package_name, with_direct_edge=False)
        session.commit()
        action_a_to_b_id = action_a_to_b.id

    service = build_service()
    result = service.execute_on_demand(package_name=package_name, target_action_id=action_a_to_b_id, current_screen_id=None)

    assert result["success"] is True
    assert service.navigation_context.prepared == [package_name]
    assert ("GoA",) in service.ui.clicked_exact  # ancestor chain replayed to reach screen_a
    assert ("GoB",) in service.ui.clicked_exact  # then the actual target action


def test_execute_on_demand_raw_action_never_navigates() -> None:
    service = build_service()

    result = service.execute_on_demand(package_name="com.ondemand4.testapp", action_type="dump_nodes")

    assert result["success"] is True
    assert result["resulting_screen_id"] is None
    assert service.navigation_context.prepared == []


def test_execute_on_demand_requires_either_target_action_id_or_action_type() -> None:
    service = build_service()

    with pytest.raises(ValueError):
        service.execute_on_demand(package_name="com.ondemand5.testapp")


def test_execute_on_demand_raw_action_navigates_to_target_screen_first() -> None:
    package_name = "com.ondemand6.testapp"
    with SessionLocal() as session:
        mapper_session, root, screen_a, screen_c, action_root_to_c, action_a_to_b = _seed_gap_graph(session, package_name=package_name, with_direct_edge=True)
        session.commit()
        screen_a_id, screen_c_id = screen_a.id, screen_c.id

    service = build_service()
    result = service.execute_on_demand(package_name=package_name, action_type="dump_nodes", target_screen_id=screen_a_id, current_screen_id=screen_c_id)

    assert result["success"] is True
    assert service.ui.clicked_bounds == ["[0,60][10,70]"]  # bridged to screen_a via the direct edge
    assert result["resulting_screen_id"] == screen_a_id  # dump_nodes is read-only, still there


def test_execute_on_demand_raw_action_skips_navigation_when_already_there() -> None:
    package_name = "com.ondemand7.testapp"
    with SessionLocal() as session:
        mapper_session, root, screen_a, screen_c, action_root_to_c, action_a_to_b = _seed_gap_graph(session, package_name=package_name, with_direct_edge=False)
        session.commit()
        screen_a_id = screen_a.id

    service = build_service()
    result = service.execute_on_demand(package_name=package_name, action_type="dump_nodes", target_screen_id=screen_a_id, current_screen_id=screen_a_id)

    assert result["success"] is True
    assert service.ui.clicked_bounds == []
    assert service.navigation_context.prepared == []


def test_execute_on_demand_raw_action_fails_fast_for_unmapped_target_screen() -> None:
    service = build_service()

    with pytest.raises(ValueError):
        service.execute_on_demand(package_name="com.ondemand8.testapp", action_type="dump_nodes", target_screen_id=999999)


def test_execute_on_demand_click_type_raw_action_has_no_resulting_screen_id() -> None:
    package_name = "com.ondemand9.testapp"
    with SessionLocal() as session:
        mapper_session, root, screen_a, screen_c, action_root_to_c, action_a_to_b = _seed_gap_graph(session, package_name=package_name, with_direct_edge=False)
        session.commit()
        screen_a_id = screen_a.id

    service = build_service()
    result = service.execute_on_demand(
        package_name=package_name, action_type="click_bounds", selector={"bounds": "[1,1][2,2]"},
        target_screen_id=screen_a_id, current_screen_id=screen_a_id,
    )

    assert result["success"] is True
    assert result["resulting_screen_id"] is None  # a click could have led anywhere, never assumed
