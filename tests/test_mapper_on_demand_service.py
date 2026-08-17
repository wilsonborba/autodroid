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
        self.clicked_bounds: list[str] = []
        self.long_clicked_bounds: list[tuple[str, float | None]] = []
        self.typed_text: list[tuple[str, bool]] = []
        self.double_clicked_bounds: list[tuple[str, float | None]] = []
        self.dragged_bounds: list[tuple[str, str, float | None]] = []
        self.pinched: list[tuple[str, str, int, int]] = []
        self.clipboard_set_calls: list[str] = []
        self.clipboard_text = ""
        self.press_hold_started: list[str] = []
        self.press_hold_released: list[str] = []
        self.clicked_resource_ids: list[str] = []
        self.clicked_exact: list[tuple[str, ...]] = []

    def dump_nodes(self):
        return self.dumps.pop(0) if self.dumps else []

    def click_bounds(self, bounds: str) -> bool:
        self.clicked_bounds.append(bounds)
        return True

    def long_click_bounds(self, bounds: str, duration: float | None = None) -> bool:
        self.long_clicked_bounds.append((bounds, duration))
        return True

    def type_text(self, text: str, *, clear: bool = False) -> bool:
        self.typed_text.append((text, clear))
        return True

    def double_click_bounds(self, bounds: str, duration: float | None = None) -> bool:
        self.double_clicked_bounds.append((bounds, duration))
        return True

    def drag_bounds(self, from_bounds: str, to_bounds: str, duration: float | None = None) -> bool:
        self.dragged_bounds.append((from_bounds, to_bounds, duration))
        return True

    def pinch_by_resource_id(self, resource_id: str, *, direction: str, percent: int = 100, steps: int = 50) -> bool:
        self.pinched.append((resource_id, direction, percent, steps))
        return True

    def set_clipboard(self, text: str) -> bool:
        self.clipboard_set_calls.append(text)
        return True

    def get_clipboard(self) -> str:
        return self.clipboard_text

    def press_hold_start(self, bounds: str) -> bool:
        self.press_hold_started.append(bounds)
        return True

    def press_hold_release(self, bounds: str) -> bool:
        self.press_hold_released.append(bounds)
        return True

    def click_by_resource_id(self, resource_id: str) -> bool:
        self.clicked_resource_ids.append(resource_id)
        return True

    def click_first_by_text_or_description(self, *candidates: str) -> bool:
        self.clicked_exact.append(candidates)
        return True

    def swipe_up(self) -> None:
        return None

    def swipe_down(self) -> None:
        return None

    def swipe_bounds(self, bounds: str, direction: str, distance: int | None = None) -> bool:
        return True

    def screenshot(self, path):
        return path


class FakeAdb:
    def shell(self, command: str) -> str:
        return f"package:{PACKAGE_NAME}"

    def press_back(self) -> None:
        return None


class FakeNav:
    def prepare_fresh_app_launch(self, package_name: str) -> None:
        return None


def _build_mapper(ui: "FakeUi") -> UiMapperService:
    mapper = UiMapperService.__new__(UiMapperService)
    mapper.logger = get_logger(__name__)
    mapper.settings = load_settings()
    mapper.adb = FakeAdb()
    mapper.ui = ui
    mapper.navigation_context = FakeNav()
    mapper.fingerprint_service = MapperFingerprintService()
    mapper.safety_service = MapperSafetyService()
    mapper.REPLAY_CLICK_SETTLE_SECONDS = 0
    return mapper


def _build_flow_execution(ui: "FakeUi"):
    from lib.domain.services.mapper_flow_execution_service import MapperFlowExecutionService

    flow = MapperFlowExecutionService.__new__(MapperFlowExecutionService)
    flow.logger = get_logger(__name__)
    flow.settings = load_settings()
    flow.adb = FakeAdb()
    flow.ui = ui
    flow.ocr = None
    flow.navigation_context = FakeNav()
    flow.safety_service = MapperSafetyService()
    flow.fingerprint_service = MapperFingerprintService()
    flow._handlers = {
        "click": flow._execute_click,
        "click_first_match": flow._execute_click_first_match,
        "click_bounds": flow._execute_click_bounds,
        "type_text": flow._execute_type_text,
        "long_click_bounds": flow._execute_long_click_bounds,
        "double_click_bounds": flow._execute_double_click_bounds,
        "drag_bounds": flow._execute_drag_bounds,
        "pinch": flow._execute_pinch,
        "clipboard_set": flow._execute_clipboard_set,
        "clipboard_get": flow._execute_clipboard_get,
        "press_hold_start": flow._execute_press_hold_start,
        "press_hold_release": flow._execute_press_hold_release,
        "scroll_up": flow._execute_scroll_up,
        "scroll_down": flow._execute_scroll_down,
        "back": flow._execute_back,
        "home": flow._execute_home,
        "enter": flow._execute_enter,
        "keyevent": flow._execute_keyevent,
        "wait": flow._execute_wait,
        "dump_nodes": flow._execute_dump_nodes,
        "screenshot": flow._execute_screenshot,
        "ocr_extract": flow._execute_ocr_extract,
    }
    return flow


def _build_service(dumps: list[list[dict]]) -> MapperOnDemandService:
    ui = FakeUi(dumps)
    service = MapperOnDemandService.__new__(MapperOnDemandService)
    service.settings = load_settings()
    service.mapper = _build_mapper(ui)
    service.flow_execution = _build_flow_execution(ui)
    return service


def test_inspect_marks_unknown_then_known_screen() -> None:
    nodes = [
        {"text": "Jobs", "content_desc": "", "resource_id": "jobs", "class_name": "TextView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True, "package_name": PACKAGE_NAME},
        {"text": "Profile", "content_desc": "", "resource_id": "profile", "class_name": "TextView", "bounds": "[0,10][10,20]", "clickable": True, "enabled": True, "package_name": PACKAGE_NAME},
    ]
    service = _build_service([nodes, nodes])

    first = service.inspect(PACKAGE_NAME)
    second = service.inspect(PACKAGE_NAME, session_id=first["session_id"])

    assert first["recognized"] is False
    assert second["recognized"] is True
    assert len(second["candidates"]) >= 1


def test_act_type_text_types_into_focused_field() -> None:
    # issue #61: type_text has no bounds to act on, it types into whatever's already focused
    # (same contract as everywhere else this action type exists), the mapper on-demand act()
    # used to only know how to click/back
    nodes = [{"text": "Message", "content_desc": "", "resource_id": "composer", "class_name": "EditText", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True, "package_name": PACKAGE_NAME}]
    service = _build_service([nodes, nodes, nodes])

    inspected = service.inspect(PACKAGE_NAME)
    result = service.act(PACKAGE_NAME, session_id=inspected["session_id"], action_type="type_text", selector={"text": "hello"})

    assert result["success"] is True
    assert service.mapper.ui.typed_text == [("hello", False)]


def test_act_long_click_bounds_long_presses() -> None:
    # issue #61: a touchscreen's equivalent of a right-click (context menus, e.g. the "Reply"
    # option on a shared reel inside a DM), needed on-demand the same way it already exists for
    # a saved Flow's steps
    nodes = [{"text": "Card", "content_desc": "", "resource_id": "card", "class_name": "View", "bounds": "[0,0][10,10]", "clickable": False, "enabled": True, "package_name": PACKAGE_NAME}]
    service = _build_service([nodes, nodes, nodes])

    inspected = service.inspect(PACKAGE_NAME)
    result = service.act(PACKAGE_NAME, session_id=inspected["session_id"], action_type="long_click_bounds", selector={"bounds": "[0,0][10,10]", "duration": 1.2})

    assert result["success"] is True
    assert service.mapper.ui.long_clicked_bounds == [("[0,0][10,10]", 1.2)]


def test_act_double_click_bounds_double_taps() -> None:
    # issue #62: full gesture-taxonomy parity, on-demand delegates to the same dispatch a saved
    # Flow step already uses instead of hand-rolling its own subset
    nodes = [{"text": "Photo", "content_desc": "", "resource_id": "photo", "class_name": "ImageView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True, "package_name": PACKAGE_NAME}]
    service = _build_service([nodes, nodes, nodes])

    inspected = service.inspect(PACKAGE_NAME)
    result = service.act(PACKAGE_NAME, session_id=inspected["session_id"], action_type="double_click_bounds", selector={"bounds": "[0,0][10,10]"})

    assert result["success"] is True
    assert service.mapper.ui.double_clicked_bounds == [("[0,0][10,10]", None)]


def test_act_drag_bounds_drags_between_two_regions() -> None:
    nodes = [{"text": "Item", "content_desc": "", "resource_id": "item", "class_name": "View", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True, "package_name": PACKAGE_NAME}]
    service = _build_service([nodes, nodes, nodes])

    inspected = service.inspect(PACKAGE_NAME)
    result = service.act(PACKAGE_NAME, session_id=inspected["session_id"], action_type="drag_bounds", selector={"from_bounds": "[0,0][10,10]", "to_bounds": "[0,50][10,60]"})

    assert result["success"] is True
    assert service.mapper.ui.dragged_bounds == [("[0,0][10,10]", "[0,50][10,60]", None)]


def test_act_pinch_zooms_the_selected_widget() -> None:
    nodes = [{"text": "Map", "content_desc": "", "resource_id": "map", "class_name": "MapView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True, "package_name": PACKAGE_NAME}]
    service = _build_service([nodes, nodes, nodes])

    inspected = service.inspect(PACKAGE_NAME)
    result = service.act(PACKAGE_NAME, session_id=inspected["session_id"], action_type="pinch", selector={"resource_id": PACKAGE_NAME + ":id/map", "direction": "out"})

    assert result["success"] is True
    assert service.mapper.ui.pinched == [(PACKAGE_NAME + ":id/map", "out", 100, 50)]


def test_act_clipboard_set_writes_and_clipboard_get_reads() -> None:
    nodes = [{"text": "Field", "content_desc": "", "resource_id": "field", "class_name": "EditText", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True, "package_name": PACKAGE_NAME}]
    service = _build_service([nodes, nodes, nodes, nodes, nodes])

    inspected = service.inspect(PACKAGE_NAME)
    written = service.act(PACKAGE_NAME, session_id=inspected["session_id"], action_type="clipboard_set", selector={"text": "copied"})
    service.mapper.ui.clipboard_text = "copied"
    read = service.act(PACKAGE_NAME, session_id=inspected["session_id"], action_type="clipboard_get")

    assert written["success"] is True
    assert service.mapper.ui.clipboard_set_calls == ["copied"]
    assert read["success"] is True
    assert read["clipboard_text"] == "copied"


def test_act_press_hold_start_and_release_are_two_separate_calls() -> None:
    nodes = [{"text": "Mic", "content_desc": "", "resource_id": "mic", "class_name": "ImageView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True, "package_name": PACKAGE_NAME}]
    service = _build_service([nodes, nodes, nodes, nodes, nodes])

    inspected = service.inspect(PACKAGE_NAME)
    started = service.act(PACKAGE_NAME, session_id=inspected["session_id"], action_type="press_hold_start", selector={"bounds": "[0,0][10,10]"})
    released = service.act(PACKAGE_NAME, session_id=inspected["session_id"], action_type="press_hold_release", selector={"bounds": "[0,0][10,10]"})

    assert started["success"] is True
    assert released["success"] is True
    assert service.mapper.ui.press_hold_started == ["[0,0][10,10]"]
    assert service.mapper.ui.press_hold_released == ["[0,0][10,10]"]


def test_act_by_action_id_dispatches_click_bounds_not_bare_click() -> None:
    # regression guard: a cataloged candidate is persisted as plain "click" with only bounds
    # known (no candidates/resource_id), but the Flow handler for "click" only ever reads
    # candidates/resource_id; without mapping this to click_bounds the click would silently no-op
    nodes = [{"text": "Jobs", "content_desc": "", "resource_id": "jobs", "class_name": "TextView", "bounds": "[0,0][10,10]", "clickable": True, "enabled": True, "package_name": PACKAGE_NAME}]
    service = _build_service([nodes, nodes, nodes])

    inspected = service.inspect(PACKAGE_NAME)
    action_id = inspected["candidates"][0]["action_id"]
    result = service.act(PACKAGE_NAME, session_id=inspected["session_id"], action_id=action_id)

    assert result["success"] is True
    assert service.mapper.ui.clicked_bounds == ["[0,0][10,10]"]
    assert service.mapper.ui.clicked_exact == []
