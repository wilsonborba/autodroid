from __future__ import annotations

from lib.domain.models.mapper_flow_model import MapperFlow, MapperFlowStep
from lib.domain.services.mapper_flow_execution_service import MapperFlowExecutionService


class FakeUi:
    def __init__(self) -> None:
        self.clicked_exact: list[tuple[str, ...]] = []
        self.clicked_contains: list[tuple[str, ...]] = []
        self.exact_result = True
        self.contains_result = True
        self.swipes = 0
        self.screenshots: list[str] = []

    def click_first_by_text_or_description(self, *candidates: str) -> bool:
        self.clicked_exact.append(candidates)
        return self.exact_result

    def click_first_by_text_or_description_contains(self, *candidates: str) -> bool:
        self.clicked_contains.append(candidates)
        return self.contains_result

    def swipe_up(self) -> None:
        self.swipes += 1

    def dump_nodes(self):
        return [{"text": "hello"}]

    def screenshot(self, path):
        self.screenshots.append(str(path))
        return path


class FakeAdb:
    def __init__(self) -> None:
        self.back_calls = 0

    def press_back(self) -> None:
        self.back_calls += 1


class FakeOcr:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def extract_lines(self, path):
        self.calls.append(str(path))
        return ["line one"]


def build_service() -> MapperFlowExecutionService:
    service = MapperFlowExecutionService.__new__(MapperFlowExecutionService)
    from lib.core.logs import get_logger
    from lib.domain.services.mapper_safety_service import MapperSafetyService

    service.logger = get_logger(__name__)
    service.settings = type("Settings", (), {"output_dir": __import__("pathlib").Path("/tmp/autodroid-flow-tests")})()
    service.ui = FakeUi()
    service.adb = FakeAdb()
    service.ocr = FakeOcr()
    service.safety_service = MapperSafetyService()
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
    step = MapperFlowStep(flow_id=1, ordinal=kwargs.pop("ordinal", 0), action_type=kwargs.pop("action_type"), selector_json=kwargs.pop("selector_json", {}), params_json=kwargs.pop("params_json", None))
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
    flow.steps = [
        make_step(ordinal=0, action_type="click", selector_json={"candidates": ["Profile"]}),
        make_step(ordinal=1, action_type="scroll_up"),
        make_step(ordinal=2, action_type="dump_nodes"),
    ]

    result = service.run_flow(flow)

    assert result["flow_id"] == 1
    assert [step["ordinal"] for step in result["steps"]] == [0, 1, 2]
    assert all(step["success"] for step in result["steps"])
    assert service.ui.swipes == 1
