from __future__ import annotations

import time
from typing import Any

from lib.core.logs import get_logger
from lib.core.settings import Settings
from lib.dal.remote.adb_adapter import AdbAdapter
from lib.dal.remote.ocr_adapter import OcrAdapter
from lib.dal.remote.uiautomator_adapter import UiAutomatorAdapter
from lib.domain.models.mapper_flow_model import MapperFlow, MapperFlowStep
from lib.domain.models.mapper_types import MapperActionSafety
from lib.domain.services.mapper_safety_service import MapperSafetyService


class MapperFlowExecutionService:
    """Executes MapperFlow definitions against the real device.

    Reads step definitions (already persisted), does not persist anything new.
    Runtime visibility is the job of structured logging (issue #17), not this service.
    """

    def __init__(self, settings: Settings) -> None:
        self.logger = get_logger(__name__)
        self.settings = settings
        self.adb = AdbAdapter(settings.android_serial)
        self.ui = UiAutomatorAdapter(settings.android_serial)
        self.ocr = OcrAdapter(settings.ocr_language)
        self.safety_service = MapperSafetyService()
        self._handlers = {
            "click": self._execute_click,
            "click_first_match": self._execute_click_first_match,
            "scroll_up": self._execute_scroll_up,
            "back": self._execute_back,
            "wait": self._execute_wait,
            "dump_nodes": self._execute_dump_nodes,
            "screenshot": self._execute_screenshot,
            "ocr_extract": self._execute_ocr_extract,
        }

    def run_flow(self, flow: MapperFlow, *, skip_dangerous_actions: bool = True) -> dict[str, Any]:
        self.logger.info("Running flow %s (%s) with %s steps", flow.id, flow.name, len(flow.steps))
        results = [self.run_step(step, skip_dangerous_actions=skip_dangerous_actions) for step in flow.steps]
        self.logger.info("Finished flow %s (%s)", flow.id, flow.name)
        return {
            "flow_id": flow.id,
            "name": flow.name,
            "package_name": flow.package_name,
            "steps": results,
        }

    def run_step(self, step: MapperFlowStep, *, skip_dangerous_actions: bool = True) -> dict[str, Any]:
        label = self._describe_step(step)
        safety = self.safety_service.classify({"text": label, "content_desc": label, "resource_id": ""}, label)

        if safety == MapperActionSafety.DANGEROUS and skip_dangerous_actions:
            self.logger.warning("Blocked dangerous flow step %s (%s: %r)", step.ordinal, step.action_type, label)
            return {"ordinal": step.ordinal, "action_type": step.action_type, "success": False, "skipped_reason": "dangerous_action_blocked"}

        handler = self._handlers.get(step.action_type)
        if handler is None:
            self.logger.error("Unsupported flow step action_type: %s", step.action_type)
            return {"ordinal": step.ordinal, "action_type": step.action_type, "success": False, "skipped_reason": "unsupported_action_type"}

        try:
            outcome = handler(step)
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a failed step, not raised
            self.logger.error("Flow step %s (%s) failed: %s", step.ordinal, step.action_type, exc)
            return {"ordinal": step.ordinal, "action_type": step.action_type, "success": False, "skipped_reason": None, "error": str(exc)}

        self.logger.info("Executed flow step %s (%s) success=%s", step.ordinal, step.action_type, outcome.get("success"))
        return {"ordinal": step.ordinal, "action_type": step.action_type, "skipped_reason": None, **outcome}

    def _describe_step(self, step: MapperFlowStep) -> str:
        selector = step.selector_json or {}
        if step.action_type == "click":
            candidates = selector.get("candidates") or []
            return candidates[0] if candidates else ""
        if step.action_type == "click_first_match":
            for attempt in selector.get("attempts", []):
                candidates = attempt.get("candidates") or attempt.get("then_candidates") or attempt.get("open_candidates") or []
                if candidates:
                    return candidates[0]
        return ""

    def _execute_click(self, step: MapperFlowStep) -> dict[str, Any]:
        candidates = (step.selector_json or {}).get("candidates") or []
        return {"success": self.ui.click_first_by_text_or_description(*candidates)}

    def _execute_click_first_match(self, step: MapperFlowStep) -> dict[str, Any]:
        for attempt in (step.selector_json or {}).get("attempts", []):
            match_type = attempt.get("match")
            if match_type == "exact":
                if self.ui.click_first_by_text_or_description(*attempt.get("candidates", [])):
                    return {"success": True}
            elif match_type == "contains_then_exact":
                opened = self.ui.click_first_by_text_or_description_contains(*attempt.get("open_candidates", []))
                if opened and self.ui.click_first_by_text_or_description(*attempt.get("then_candidates", [])):
                    return {"success": True}
        return {"success": False}

    def _execute_scroll_up(self, step: MapperFlowStep) -> dict[str, Any]:
        self.ui.swipe_up()
        return {"success": True}

    def _execute_back(self, step: MapperFlowStep) -> dict[str, Any]:
        self.adb.press_back()
        return {"success": True}

    def _execute_wait(self, step: MapperFlowStep) -> dict[str, Any]:
        seconds = (step.params_json or {}).get("seconds", 1)
        time.sleep(seconds)
        return {"success": True}

    def _execute_dump_nodes(self, step: MapperFlowStep) -> dict[str, Any]:
        nodes = self.ui.dump_nodes()
        return {"success": True, "node_count": len(nodes), "nodes": nodes}

    def _execute_screenshot(self, step: MapperFlowStep) -> dict[str, Any]:
        filename = (step.params_json or {}).get("filename") or f"flow_{step.flow_id}.png"
        path = self.ui.screenshot(self.settings.output_dir / "screenshots" / filename)
        return {"success": True, "screenshot_path": str(path)}

    def _execute_ocr_extract(self, step: MapperFlowStep) -> dict[str, Any]:
        filename = (step.params_json or {}).get("filename") or f"flow_{step.flow_id}.png"
        path = self.settings.output_dir / "screenshots" / filename
        lines = self.ocr.extract_lines(path)
        return {"success": True, "ocr_lines": lines}
