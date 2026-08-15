from __future__ import annotations

from types import SimpleNamespace

from lib.core.logs import get_logger
from lib.domain.adapters.linkedin import linkedin_adapter as linkedin_adapter_module
from lib.domain.adapters.linkedin.linkedin_adapter import LinkedInAdapter


class FakeAdb:
    def get_state(self) -> str:
        return "device"

    def shell(self, command: str) -> str:
        return "1"


class FakeNav:
    def __init__(self) -> None:
        self.prepared: list[str] = []

    def prepare_fresh_app_launch(self, package_name: str) -> None:
        self.prepared.append(package_name)


class FakeFlowExecutionService:
    def __init__(self, dump_nodes_results: list[list[dict]] | None = None) -> None:
        self.calls: list[str] = []
        self._dump_results = list(dump_nodes_results or [[{"text": "Profile"}]])

    def run_step(self, step, **kwargs) -> dict:
        self.calls.append(step.action_type)
        if step.action_type == "click_first_match":
            return {"success": True}
        if step.action_type == "dump_nodes":
            nodes = self._dump_results.pop(0) if self._dump_results else []
            return {"success": True, "node_count": len(nodes), "nodes": nodes}
        if step.action_type == "scroll_up":
            return {"success": True}
        if step.action_type == "screenshot":
            return {"success": True, "screenshot_path": "linkedin_profile_basic.png"}
        if step.action_type == "ocr_extract":
            return {"success": True, "ocr_lines": ["Jane Doe", "Software Engineer at Acme"]}
        raise AssertionError(f"unexpected action_type {step.action_type}")


class FakeSessionScope:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeFlowRepository:
    def __init__(self, existing_flow=None) -> None:
        self.existing_flow = existing_flow

    def get_flow_by_name(self, package_name: str, name: str):
        return self.existing_flow


class FakeFlowService:
    def __init__(self, session) -> None:
        self.flow_repository = FakeFlowRepository()

    def create_flow(self, **kwargs):
        step_definition = kwargs["steps"][0]
        step = SimpleNamespace(id=1, ordinal=0, action_type=step_definition["action_type"], selector_json=step_definition["selector"], params_json=None)
        return SimpleNamespace(id=1, name=kwargs["name"], package_name=kwargs["package_name"], steps=[step])


def build_adapter(flow_execution_service: FakeFlowExecutionService) -> LinkedInAdapter:
    adapter = LinkedInAdapter.__new__(LinkedInAdapter)
    adapter.logger = get_logger(__name__)
    adapter.settings = SimpleNamespace(linkedin_package_name="com.linkedin.android", output_dir=None)
    adapter.adb = FakeAdb()
    adapter.navigation_context = FakeNav()
    adapter.flow_execution_service = flow_execution_service
    return adapter


def test_extract_profile_basic_resets_app_and_runs_entrypoint_flow(monkeypatch) -> None:
    monkeypatch.setattr(linkedin_adapter_module, "session_scope", lambda: FakeSessionScope())
    monkeypatch.setattr(linkedin_adapter_module, "MapperFlowService", FakeFlowService)

    flow_execution_service = FakeFlowExecutionService(dump_nodes_results=[[{"text": "Jane Doe"}], [{"text": "Jane Doe"}], [{"text": "Jane Doe"}]])
    adapter = build_adapter(flow_execution_service)

    result = adapter.extract_profile_basic({})

    assert result["profile_opened"] is True
    assert adapter.navigation_context.prepared == ["com.linkedin.android"]
    # entrypoint click, then 3 dump_nodes interleaved with 2 scroll_up (default scrolls=2)
    assert flow_execution_service.calls == ["click_first_match", "dump_nodes", "scroll_up", "dump_nodes", "scroll_up", "dump_nodes"]
    assert result["ocr_lines"] == []
    assert result["visible_texts"] == ["Jane Doe"]


def test_extract_profile_basic_falls_back_to_ocr_when_no_visible_text(monkeypatch) -> None:
    monkeypatch.setattr(linkedin_adapter_module, "session_scope", lambda: FakeSessionScope())
    monkeypatch.setattr(linkedin_adapter_module, "MapperFlowService", FakeFlowService)

    flow_execution_service = FakeFlowExecutionService(dump_nodes_results=[[], [], []])
    adapter = build_adapter(flow_execution_service)

    result = adapter.extract_profile_basic({"scrolls": 2})

    assert "screenshot" in flow_execution_service.calls
    assert "ocr_extract" in flow_execution_service.calls
    assert result["ocr_lines"] == ["Jane Doe", "Software Engineer at Acme"]
    assert result["name"] == "Jane Doe"
