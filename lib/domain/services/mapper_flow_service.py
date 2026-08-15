from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from lib.core.logs import get_logger
from lib.dal.local.mapper_flow_repository import SqlAlchemyMapperFlowRepository
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_flow_model import MapperFlow, MapperFlowStep
from lib.domain.models.mapper_model import MapperTransition
from lib.domain.models.mapper_types import MapperActionSafety
from lib.domain.services.mapper_safety_service import MapperSafetyService


class MapperFlowService:
    """CRUD for MapperFlow definitions. Does not talk to the device, see MapperFlowExecutionService for that.

    Steps are reusable, package-scoped components (issue #23), not owned by a single Flow.
    Adding a mapped step to a Flow automatically resolves and attaches its ancestor chain (the
    path from the app's root to that step's screen), so a manually-composed Flow is always
    reachable without needing separate validation.
    """

    def __init__(self, session: Session) -> None:
        self.logger = get_logger(__name__)
        self.mapper_repository = SqlAlchemyMapperRepository(session)
        self.flow_repository = SqlAlchemyMapperFlowRepository(session)
        self.safety_service = MapperSafetyService()

    # --- Flow ----------------------------------------------------------------

    def create_flow(
        self,
        *,
        name: str,
        package_name: str,
        description: str | None = None,
        source_session_id: int | None = None,
        transition_ids: list[int] | None = None,
        steps: list[dict[str, Any]] | None = None,
    ) -> MapperFlow:
        if not steps and not transition_ids:
            raise ValueError("Provide either 'steps' or 'source_session_id' with 'transition_ids'")

        flow = self.flow_repository.create_flow(
            name=name,
            package_name=package_name,
            description=description,
            source_session_id=source_session_id,
        )

        if steps:
            for step in steps:
                self.add_step(flow.id, step)
        else:
            for transition_id in transition_ids or []:
                self._add_step_from_transition_id(flow.id, transition_id)

        self.logger.info("Created mapper flow %s (%s) for %s", flow.id, name, package_name)
        return self.flow_repository.get_flow(flow.id)

    def list_flows(self, package_name: str | None = None) -> list[MapperFlow]:
        return self.flow_repository.list_flows(package_name)

    def get_flow(self, flow_id: int) -> MapperFlow | None:
        return self.flow_repository.get_flow(flow_id)

    def update_flow(self, flow_id: int, *, name: str | None = None, description: str | None = None) -> MapperFlow:
        flow = self.flow_repository.update_flow(flow_id, name=name, description=description)
        self.logger.info("Updated mapper flow %s", flow_id)
        return flow

    def delete_flow(self, flow_id: int) -> None:
        self.flow_repository.delete_flow(flow_id)
        self.logger.info("Deleted mapper flow %s", flow_id)

    # --- Steps (reusable, auto-ancestor-pull) --------------------------------

    def add_step(self, flow_id: int, step: dict[str, Any]) -> dict[str, Any]:
        """Adds a step to a Flow. `step` either has a `step_id` (reuse an existing, already
        mapped step as-is) or the fields to define a new one (`action_type`, `selector`, ...).

        Returns `{"step": MapperFlowStep, "ancestors": list[MapperFlowStep]}`: `ancestors` is
        the chain that was automatically resolved and attached before `step`, in order, so the
        caller can see exactly what got added, not just guess.
        """
        flow = self.flow_repository.get_flow(flow_id)
        if flow is None:
            raise ValueError(f"Mapper flow {flow_id} not found")

        existing_step_id = step.get("step_id")
        if existing_step_id is not None:
            target_step = self.flow_repository.get_step(existing_step_id)
            if target_step is None:
                raise ValueError(f"Mapper flow step {existing_step_id} not found")
        else:
            target_step = self._get_or_create_step(flow.package_name, step)

        ancestors: list[MapperFlowStep] = []
        if target_step.source_screen_id is not None:
            ancestors = self._resolve_ancestor_steps(flow.package_name, target_step.source_screen_id)
            for ancestor in ancestors:
                self.flow_repository.attach_step(flow_id, ancestor.id)

        self.flow_repository.attach_step(flow_id, target_step.id, ordinal=step.get("ordinal"))
        self.logger.info(
            "Added step %s to mapper flow %s (%s ancestor step(s) auto-included)",
            target_step.id, flow_id, len(ancestors),
        )
        return {"step": target_step, "ancestors": ancestors}

    def update_step(self, step_id: int, *, action_type: str | None = None, selector: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> MapperFlowStep:
        step = self.flow_repository.update_step(step_id, action_type=action_type, selector_json=selector, params_json=params)
        self.logger.info("Updated mapper flow step %s (shared by every flow that uses it)", step_id)
        return step

    def remove_step(self, flow_id: int, step_id: int) -> None:
        """Removes the step from this Flow only. The step definition (and any other Flow's use
        of it) is left untouched, since it can be shared (issue #23)."""
        self.flow_repository.detach_step(flow_id, step_id)
        self.logger.info("Removed step %s from mapper flow %s", step_id, flow_id)

    def _get_or_create_step(self, package_name: str, step: dict[str, Any]) -> MapperFlowStep:
        source_action_id = step.get("source_action_id")
        if source_action_id is not None:
            existing = self.flow_repository.find_step_by_source_action(package_name, source_action_id)
            if existing is not None:
                return existing
        if not step.get("action_type"):
            raise ValueError("Provide either 'step_id' (reuse an existing step) or 'action_type' (define a new one)")
        selector = step.get("selector") or {}
        return self.flow_repository.create_step(
            package_name=package_name,
            action_type=step["action_type"],
            selector_json=selector,
            safety=self._classify_selector(selector),
            source_screen_id=step.get("source_screen_id"),
            source_action_id=source_action_id,
            params_json=step.get("params"),
        )

    def resolve_restart_plan(self, package_name: str, source_screen_id: int) -> tuple[int, list[MapperFlowStep]]:
        """Public wrapper around `_resolve_ancestor_steps` (issue #26): what a restart-from-root
        would need to replay to reach `source_screen_id`, root screen id first, steps root-first.
        Used by `MapperFlowExecutionService.run_flow` to bridge a gap between two steps, the same
        ancestor-walk already used when composing a Flow manually (#23)."""
        ancestor_steps = self._resolve_ancestor_steps(package_name, source_screen_id)
        root_screen_id = ancestor_steps[0].source_screen_id if ancestor_steps else source_screen_id
        return root_screen_id, ancestor_steps

    def _resolve_ancestor_steps(self, package_name: str, source_screen_id: int) -> list[MapperFlowStep]:
        """Walks MapperTransition backwards from `source_screen_id` up to the session root,
        ensuring a reusable step exists for each ancestor action (reused by source_action_id
        when one already does), returned root-first (the order they need to run in)."""
        chain: list[MapperTransition] = []
        current_screen_id = source_screen_id
        seen_screens: set[int] = set()
        while current_screen_id not in seen_screens:
            seen_screens.add(current_screen_id)
            transition = self.mapper_repository.find_transition_to_screen(current_screen_id)
            if transition is None:
                break
            chain.append(transition)
            current_screen_id = transition.from_screen_id
        chain.reverse()

        ancestor_steps: list[MapperFlowStep] = []
        for transition in chain:
            existing = self.flow_repository.find_step_by_source_action(package_name, transition.action_id)
            ancestor_steps.append(existing if existing is not None else self._create_step_from_transition(package_name, transition))
        return ancestor_steps

    def _create_step_from_transition(self, package_name: str, transition: MapperTransition) -> MapperFlowStep:
        action = self.mapper_repository.get_action(transition.action_id)
        if action is None:
            raise ValueError(f"Mapper action {transition.action_id} not found")
        node = self.mapper_repository.get_node(action.node_id) if action.node_id else None

        label = action.label or (node.text if node else None) or (node.content_desc if node else None)
        if label:
            selector = {"candidates": [label]}
        elif node is not None and node.resource_id:
            selector = {"resource_id": node.resource_id}
        else:
            selector = {}

        return self.flow_repository.create_step(
            package_name=package_name,
            action_type="click",
            selector_json=selector,
            safety=action.safety,
            source_screen_id=transition.from_screen_id,
            source_action_id=action.id,
        )

    def _add_step_from_transition_id(self, flow_id: int, transition_id: int) -> None:
        transition = self.mapper_repository.get_transition(transition_id)
        if transition is None:
            raise ValueError(f"Mapper transition {transition_id} not found")
        flow = self.flow_repository.get_flow(flow_id)
        step = self._create_step_from_transition(flow.package_name, transition)
        self.add_step(flow_id, {"step_id": step.id})

    def _classify_selector(self, selector: dict[str, Any]) -> MapperActionSafety:
        candidates = selector.get("candidates") or []
        label = candidates[0] if candidates else ""
        return self.safety_service.classify({"text": label, "content_desc": label, "resource_id": selector.get("resource_id", "")}, label)
