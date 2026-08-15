from __future__ import annotations

import time
from datetime import time as time_of_day
from typing import Any

from lib.core.logs import get_logger
from lib.core.settings import Settings
from lib.core.utils.clock import local_now
from lib.dal.local.database import session_scope
from lib.dal.local.mapper_flow_repository import SqlAlchemyMapperFlowRepository
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.dal.remote.adb_adapter import AdbAdapter
from lib.dal.remote.ocr_adapter import OcrAdapter
from lib.dal.remote.uiautomator_adapter import UiAutomatorAdapter
from lib.domain.models.mapper_flow_model import MapperFlow, MapperFlowStep
from lib.domain.models.mapper_types import MapperActionSafety, MapperFlowFailureType
from lib.domain.services.mapper_fingerprint_service import MapperFingerprintService
from lib.domain.services.mapper_flow_service import MapperFlowService
from lib.domain.services.mapper_route_planner_service import RESTART, MapperRoutePlannerService, RestartOption
from lib.domain.services.mapper_safety_service import MapperSafetyService
from lib.domain.services.navigation_context_service import NavigationContextService


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
        self.navigation_context = NavigationContextService(self.adb)
        self.safety_service = MapperSafetyService()
        self.fingerprint_service = MapperFingerprintService()
        self._handlers = {
            "click": self._execute_click,
            "click_first_match": self._execute_click_first_match,
            "click_bounds": self._execute_click_bounds,
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
        `SqlAlchemyMapperFlowRepository.ordered_steps`, not derived from `flow` itself).

        Before each step, if the device's last known screen isn't that step's expected starting
        screen, `navigate()` (issue #24's route planner) is used to bridge the gap first (issue
        #26). The starting screen is only known once a previous step in this same run succeeded
        and its outcome screen could be resolved, so the very first step, and any step right
        after one whose outcome is unknown, always just runs as-is, exactly like before this
        wiring existed."""
        self.logger.info("Running flow %s (%s) with %s steps", flow.id, flow.name, len(steps))
        results = []
        current_screen_id: int | None = None
        for step in steps:
            if current_screen_id is not None and step.source_screen_id is not None and step.source_screen_id != current_screen_id and flow.source_session_id is not None:
                self._bridge_gap(flow, current_screen_id, step.source_screen_id)
            result = self.run_step(step, flow_id=flow.id, skip_dangerous_actions=skip_dangerous_actions)
            results.append(result)
            current_screen_id = self._resolve_screen_after_step(step, result)
        self.logger.info("Finished flow %s (%s)", flow.id, flow.name)
        return {
            "flow_id": flow.id,
            "name": flow.name,
            "package_name": flow.package_name,
            "steps": results,
        }

    def _bridge_gap(self, flow: MapperFlow, current_screen_id: int, target_screen_id: int) -> None:
        with session_scope() as session:
            root_screen_id, ancestor_steps = MapperFlowService(session).resolve_restart_plan(flow.package_name, target_screen_id)
        restart_option = RestartOption(root_screen_id=root_screen_id, ancestor_step_ids=[step.id for step in ancestor_steps])
        self.navigate(
            package_name=flow.package_name,
            session_id=flow.source_session_id,
            current_screen_id=current_screen_id,
            target_screen_id=target_screen_id,
            restart_option=restart_option,
            restart_steps=ancestor_steps,
        )

    def _resolve_screen_after_step(self, step: MapperFlowStep, result: dict[str, Any]) -> int | None:
        # only trust a screen we're confident about: a failed step, or one with no known
        # provenance, means the next step just runs as-is, same as before this wiring existed
        if not result.get("success") or step.source_action_id is None:
            return None
        with session_scope() as session:
            transition = SqlAlchemyMapperRepository(session).find_transition_by_action(step.source_action_id)
            return transition.to_screen_id if transition is not None else None

    def execute_on_demand(
        self,
        *,
        package_name: str,
        target_action_id: int | None = None,
        current_screen_id: int | None = None,
        action_type: str | None = None,
        selector: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Runs one action right now, with no Flow saved beforehand (issue #32).

        A mapped action (`target_action_id`) always gets to the right screen first: a direct
        route when `current_screen_id` is known and one exists (#24), a relaunch and replay of
        the known ancestor chain otherwise, exactly the same gap-bridging `run_flow` already does
        between steps (#26), just for a single on-demand action instead of a whole Flow.

        A raw action (`action_type` instead) runs against whatever's on screen right now, no
        navigation attempted: for exploratory or OCR-driven interaction, where there's no mapped
        destination to aim for in the first place (a `dump_nodes`/`screenshot`/`ocr_extract` read,
        or a `click_bounds` on something just found that way)."""
        if target_action_id is None:
            if not action_type:
                raise ValueError("Provide either target_action_id or action_type")
            step = MapperFlowStep(package_name=package_name, action_type=action_type, selector_json=selector or {}, params_json=params)
            result = self.run_step(step)
            return {**result, "resulting_screen_id": None}

        with session_scope() as session:
            action = SqlAlchemyMapperRepository(session).get_action(target_action_id)
            if action is None:
                raise ValueError(f"Mapper action {target_action_id} not found")
            source_session_id = action.session_id
            step = MapperFlowService(session).get_or_create_step_for_action(package_name, target_action_id)
            step_source_screen_id = step.source_screen_id

        if step_source_screen_id is not None and step_source_screen_id != current_screen_id:
            flow = MapperFlow(package_name=package_name, source_session_id=source_session_id)
            if current_screen_id is not None:
                self._bridge_gap(flow, current_screen_id, step_source_screen_id)
            else:
                self._relaunch_to_screen(flow, step_source_screen_id)

        result = self.run_step(step)
        resulting_screen_id = self._resolve_screen_after_step(step, result)
        return {**result, "resulting_screen_id": resulting_screen_id}

    def _relaunch_to_screen(self, flow: MapperFlow, target_screen_id: int) -> None:
        # no current_screen_id to route from at all, a relaunch always lands at the root, so this
        # is always exactly the ancestor chain (#23), walked forward once, same idea as the
        # departure recovery in the mapper itself (issue #28), here for the on-demand executor
        with session_scope() as session:
            _root_screen_id, ancestor_steps = MapperFlowService(session).resolve_restart_plan(flow.package_name, target_screen_id)
        self.navigation_context.prepare_fresh_app_launch(flow.package_name)
        for step in ancestor_steps:
            self.run_step(step)

    def navigate(
        self,
        *,
        package_name: str,
        session_id: int,
        current_screen_id: int,
        target_screen_id: int,
        restart_option: RestartOption,
        restart_steps: list[MapperFlowStep],
    ) -> dict[str, Any]:
        """Bridges the gap between where the device is now and where a mapped step needs to
        start, deciding at runtime between a direct path through the mapped graph and a restart
        (issue #24): this is the concrete "RoutePlanner -> Worker executes -> measure -> learn"
        loop from the issue's architecture. Called automatically by `run_flow` whenever it knows
        the current screen and it doesn't match the next step's expected one (issue #26); also
        callable directly by anything else that already has both screen ids."""
        if current_screen_id == target_screen_id:
            return {"strategy_type": "already_there", "reason": "same_screen", "success": True, "duration_ms": 0.0}

        with session_scope() as session:
            planner = MapperRoutePlannerService(session)
            plan = planner.plan(
                session_id=session_id, current_screen_id=current_screen_id, target_screen_id=target_screen_id,
                restart_option=restart_option,
            )
            mapper_repository = SqlAlchemyMapperRepository(session)
            route_edges: list[tuple[int, str | None]] = []
            for transition in plan.route:
                action = mapper_repository.get_action(transition.action_id)
                node = mapper_repository.get_node(action.node_id) if action and action.node_id else None
                route_edges.append((transition.id, node.bounds if node else None))

        started_at = time.monotonic()
        success = True
        transition_observations: list[tuple[int, float, bool]] = []
        if plan.strategy_type == RESTART:
            self.navigation_context.prepare_fresh_app_launch(package_name)
            for step in restart_steps:
                outcome = self.run_step(step)
                if not outcome.get("success", True):
                    success = False
        else:
            # timed per edge, not just for the whole route, so `MapperTransitionPerformance`
            # actually learns from real runs instead of staying at its cold-start default forever
            for transition_id, bounds in route_edges:
                edge_started_at = time.monotonic()
                edge_success = bounds is not None and self.ui.click_bounds(bounds)
                transition_observations.append((transition_id, (time.monotonic() - edge_started_at) * 1000, edge_success))
                if not edge_success:
                    success = False
                    break
        duration_ms = (time.monotonic() - started_at) * 1000

        with session_scope() as session:
            MapperRoutePlannerService(session).record_execution(
                plan, actual_duration_ms=duration_ms, success=success,
                transition_observations=transition_observations or None,
            )

        self.logger.info(
            "Navigated screen %s -> %s via %s (%s) in %.0fms success=%s",
            current_screen_id, target_screen_id, plan.strategy_type, plan.reason, duration_ms, success,
        )
        return {
            "strategy_type": plan.strategy_type,
            "reason": plan.reason,
            "route_signature": plan.route_signature,
            "estimated_duration_ms": plan.estimated_duration_ms,
            "duration_ms": duration_ms,
            "success": success,
        }

    def run_step(self, step: MapperFlowStep, *, flow_id: int | None = None, skip_dangerous_actions: bool = True) -> dict[str, Any]:
        repeat_config = (step.params_json or {}).get("repeat")
        if repeat_config:
            return self._run_step_repeated(step, repeat_config, flow_id=flow_id, skip_dangerous_actions=skip_dangerous_actions)
        return self._run_step_once(step, flow_id=flow_id, skip_dangerous_actions=skip_dangerous_actions)

    def _run_step_repeated(self, step: MapperFlowStep, repeat_config: dict[str, Any], *, flow_id: int | None, skip_dangerous_actions: bool) -> dict[str, Any]:
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

            last_result = self._run_step_once(step, flow_id=flow_id, skip_dangerous_actions=skip_dangerous_actions)
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

    def _run_step_once(self, step: MapperFlowStep, *, flow_id: int | None = None, skip_dangerous_actions: bool = True) -> dict[str, Any]:
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
            self._record_failure(step, flow_id, MapperFlowFailureType.UNSUPPORTED_ACTION_TYPE, f"action_type={step.action_type!r}")
            return {"step_id": step.id, "action_type": step.action_type, "success": False, "skipped_reason": "unsupported_action_type"}

        try:
            outcome = handler(step)
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a failed step, not raised
            self.logger.error("Flow step %s (%s) failed: %s", step.id, step.action_type, exc)
            self._record_failure(step, flow_id, MapperFlowFailureType.EXCEPTION, str(exc))
            return {"step_id": step.id, "action_type": step.action_type, "success": False, "skipped_reason": None, "error": str(exc)}

        self.logger.info("Executed flow step %s (%s) success=%s", step.id, step.action_type, outcome.get("success"))
        if outcome.get("success") is False:
            failure_type = MapperFlowFailureType.SELECTOR_NOT_FOUND if step.action_type in ("click", "click_first_match") else MapperFlowFailureType.CLICK_FAILED
            self._record_failure(step, flow_id, failure_type, f"selector={step.selector_json!r}")
        return {"step_id": step.id, "action_type": step.action_type, "skipped_reason": None, **outcome}

    def _record_failure(self, step: MapperFlowStep, flow_id: int | None, failure_type: MapperFlowFailureType, detail: str | None) -> None:
        try:
            with session_scope() as session:
                SqlAlchemyMapperFlowRepository(session).record_failure(
                    package_name=step.package_name,
                    failure_type=failure_type,
                    flow_id=flow_id,
                    step_id=step.id or None,
                    detail=detail,
                )
            self.logger.warning("Recorded interaction failure for %s: %s (%s)", step.package_name, failure_type.value, detail)
        except Exception:  # noqa: BLE001 - recording the failure must never break execution itself
            self.logger.exception("Failed to record mapper flow failure for step %s", step.id)

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

    def _execute_click_bounds(self, step: MapperFlowStep) -> dict[str, Any]:
        # clicks an exact "[x1,y1][x2,y2]" region instead of matching by text/description: needed
        # to act on something already located another way (a prior dump_nodes, or an OCR region
        # from _execute_ocr_extract), not everything worth clicking has readable text (#32)
        bounds = (step.selector_json or {}).get("bounds")
        if not bounds:
            return {"success": False}
        return {"success": self.ui.click_bounds(bounds)}

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
        regions = self.ocr.extract_text_regions(path)
        # OCR is only a textual reference (issue #32): it always "succeeds" if it ran, even with
        # no regions found or nothing actionable in them, deciding what to do with the result
        # (or that it wasn't useful this time) is the caller's job, not something to fail here
        return {"success": True, "ocr_regions": regions}
