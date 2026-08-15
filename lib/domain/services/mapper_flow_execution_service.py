from __future__ import annotations

import time
from datetime import time as time_of_day
from typing import Any

from lib.core.logs import get_logger
from lib.core.settings import Settings
from lib.core.utils.clock import local_now
from lib.dal.remote.adb_adapter import AdbAdapter
from lib.dal.remote.ocr_adapter import OcrAdapter
from lib.dal.remote.uiautomator_adapter import UiAutomatorAdapter
from lib.domain.models.mapper_flow_model import MapperFlow, MapperFlowStep
from lib.domain.models.mapper_types import MapperActionSafety
from lib.domain.services.mapper_fingerprint_service import MapperFingerprintService
from lib.domain.services.mapper_safety_service import MapperSafetyService


class MapperFlowExecutionService:
    """Executes MapperFlow definitions against the real device.

    Reads step definitions (already persisted), does not persist anything new.
    Runtime visibility is the job of structured logging (issue #17), not this service.

    A step whose `params_json` has a `repeat` descriptor runs in a controlled loop instead of
    once (issue #22): scroll during mapping is already capped by `MapperModeService`, but scroll
    during a Flow's real data extraction (e.g. paging through a whole feed) is a different
    problem with a different, usually much higher, bound. `repeat` supports `max_iterations`,
    `max_duration_seconds`, and `execution_window_start`/`execution_window_end` (same concept as
    `Job.execution_window_*`, #3), whichever is hit first wins. Regardless of any configured
    limit, the loop also stops the moment the screen stops changing (same fingerprint twice in a
    row), since there's no point repeating a step against content that isn't moving anymore.
    """

    def __init__(self, settings: Settings) -> None:
        self.logger = get_logger(__name__)
        self.settings = settings
        self.adb = AdbAdapter(settings.android_serial)
        self.ui = UiAutomatorAdapter(settings.android_serial)
        self.ocr = OcrAdapter(settings.ocr_language)
        self.safety_service = MapperSafetyService()
        self.fingerprint_service = MapperFingerprintService()
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

    def run_flow(self, flow: MapperFlow, steps: list[MapperFlowStep], *, skip_dangerous_actions: bool = True) -> dict[str, Any]:
        """`steps` is the ordered list of this flow's steps (a reusable step can belong to
        several flows, so ordering/membership is resolved by the caller via
        `SqlAlchemyMapperFlowRepository.ordered_steps`, not derived from `flow` itself)."""
        self.logger.info("Running flow %s (%s) with %s steps", flow.id, flow.name, len(steps))
        results = [self.run_step(step, skip_dangerous_actions=skip_dangerous_actions) for step in steps]
        self.logger.info("Finished flow %s (%s)", flow.id, flow.name)
        return {
            "flow_id": flow.id,
            "name": flow.name,
            "package_name": flow.package_name,
            "steps": results,
        }

    def run_step(self, step: MapperFlowStep, *, skip_dangerous_actions: bool = True) -> dict[str, Any]:
        repeat_config = (step.params_json or {}).get("repeat")
        if repeat_config:
            return self._run_step_repeated(step, repeat_config, skip_dangerous_actions=skip_dangerous_actions)
        return self._run_step_once(step, skip_dangerous_actions=skip_dangerous_actions)

    def _run_step_repeated(self, step: MapperFlowStep, repeat_config: dict[str, Any], *, skip_dangerous_actions: bool) -> dict[str, Any]:
        max_iterations = repeat_config.get("max_iterations")
        max_duration_seconds = repeat_config.get("max_duration_seconds")
        window_start = repeat_config.get("execution_window_start")
        window_end = repeat_config.get("execution_window_end")

        started_at = time.monotonic()
        iteration = 0
        last_fingerprint: str | None = None
        stop_reason: str | None = None
        # covers the edge case where the very first limit check already stops the loop (e.g. an
        # execution window that isn't open yet): the step never actually ran, but the result
        # still needs the fields callers/the API schema expect
        last_result: dict[str, Any] = {"step_id": step.id, "action_type": step.action_type, "success": False, "skipped_reason": None}

        while True:
            if max_iterations is not None and iteration >= max_iterations:
                stop_reason = "max_iterations"
                break
            if max_duration_seconds is not None and (time.monotonic() - started_at) >= max_duration_seconds:
                stop_reason = "max_duration_seconds"
                break
            if window_start and window_end and not self._within_execution_window(window_start, window_end):
                stop_reason = "execution_window"
                break

            last_result = self._run_step_once(step, skip_dangerous_actions=skip_dangerous_actions)
            iteration += 1

            fingerprint = self._current_fingerprint()
            if last_fingerprint is not None and fingerprint == last_fingerprint:
                stop_reason = "no_new_content"
                break
            last_fingerprint = fingerprint

        self.logger.info(
            "Repeated flow step %s (%s) %s time(s), stopped: %s",
            step.id, step.action_type, iteration, stop_reason,
        )
        return {**last_result, "iterations_run": iteration, "stop_reason": stop_reason}

    def _current_fingerprint(self) -> str:
        return self.fingerprint_service.fingerprint(self.ui.dump_nodes())

    def _within_execution_window(self, window_start: str, window_end: str) -> bool:
        start = time_of_day.fromisoformat(window_start)
        end = time_of_day.fromisoformat(window_end)
        current = local_now(self.settings.timezone).time().replace(microsecond=0)
        if start <= end:
            return start <= current <= end
        return current >= start or current <= end

    def _run_step_once(self, step: MapperFlowStep, *, skip_dangerous_actions: bool = True) -> dict[str, Any]:
        # steps are shared/reusable (issue #23), they no longer carry a flow-specific position,
        # so results are identified by step_id (globally stable) instead of a per-flow ordinal
        label = self._describe_step(step)
        safety = self.safety_service.classify({"text": label, "content_desc": label, "resource_id": ""}, label)

        if safety == MapperActionSafety.DANGEROUS and skip_dangerous_actions:
            self.logger.warning("Blocked dangerous flow step %s (%s: %r)", step.id, step.action_type, label)
            return {"step_id": step.id, "action_type": step.action_type, "success": False, "skipped_reason": "dangerous_action_blocked"}

        handler = self._handlers.get(step.action_type)
        if handler is None:
            self.logger.error("Unsupported flow step action_type: %s", step.action_type)
            return {"step_id": step.id, "action_type": step.action_type, "success": False, "skipped_reason": "unsupported_action_type"}

        try:
            outcome = handler(step)
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a failed step, not raised
            self.logger.error("Flow step %s (%s) failed: %s", step.id, step.action_type, exc)
            return {"step_id": step.id, "action_type": step.action_type, "success": False, "skipped_reason": None, "error": str(exc)}

        self.logger.info("Executed flow step %s (%s) success=%s", step.id, step.action_type, outcome.get("success"))
        return {"step_id": step.id, "action_type": step.action_type, "skipped_reason": None, **outcome}

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
        filename = (step.params_json or {}).get("filename") or f"flow_step_{step.id}.png"
        path = self.ui.screenshot(self.settings.output_dir / "screenshots" / filename)
        return {"success": True, "screenshot_path": str(path)}

    def _execute_ocr_extract(self, step: MapperFlowStep) -> dict[str, Any]:
        filename = (step.params_json or {}).get("filename") or f"flow_step_{step.id}.png"
        path = self.settings.output_dir / "screenshots" / filename
        lines = self.ocr.extract_lines(path)
        return {"success": True, "ocr_lines": lines}
