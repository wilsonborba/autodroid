from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from lib.core.logs import get_logger
from lib.dal.local.mapper_flow_repository import SqlAlchemyMapperFlowRepository
from lib.dal.local.mapper_repository import SqlAlchemyMapperRepository
from lib.domain.models.mapper_flow_model import MapperFlow, MapperFlowStep
from lib.domain.models.mapper_types import MapperActionSafety
from lib.domain.services.mapper_safety_service import MapperSafetyService


class MapperFlowService:
    """CRUD for MapperFlow definitions. Does not talk to the device, see MapperFlowExecutionService for that."""

    def __init__(self, session: Session) -> None:
        self.logger = get_logger(__name__)
        self.mapper_repository = SqlAlchemyMapperRepository(session)
        self.flow_repository = SqlAlchemyMapperFlowRepository(session)
        self.safety_service = MapperSafetyService()

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
                self._add_manual_step(flow.id, step)
        else:
            for transition_id in transition_ids or []:
                self._add_step_from_transition(flow.id, transition_id)

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

    def add_step(self, flow_id: int, step: dict[str, Any]) -> MapperFlowStep:
        created = self._add_manual_step(flow_id, step)
        self.logger.info("Added step %s to mapper flow %s", created.ordinal, flow_id)
        return created

    def update_step(self, step_id: int, *, action_type: str | None = None, selector: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> MapperFlowStep:
        step = self.flow_repository.update_step(step_id, action_type=action_type, selector_json=selector, params_json=params)
        self.logger.info("Updated mapper flow step %s", step_id)
        return step

    def delete_step(self, step_id: int) -> None:
        self.flow_repository.delete_step(step_id)
        self.logger.info("Deleted mapper flow step %s", step_id)

    def _add_manual_step(self, flow_id: int, step: dict[str, Any]) -> MapperFlowStep:
        selector = step.get("selector") or {}
        return self.flow_repository.add_step(
            flow_id,
            action_type=step["action_type"],
            selector_json=selector,
            safety=self._classify_selector(selector),
            source_screen_id=step.get("source_screen_id"),
            source_action_id=step.get("source_action_id"),
            params_json=step.get("params"),
            ordinal=step.get("ordinal"),
        )

    def _add_step_from_transition(self, flow_id: int, transition_id: int) -> MapperFlowStep:
        transition = self.mapper_repository.get_transition(transition_id)
        if transition is None:
            raise ValueError(f"Mapper transition {transition_id} not found")
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

        return self.flow_repository.add_step(
            flow_id,
            action_type="click",
            selector_json=selector,
            safety=action.safety,
            source_screen_id=transition.from_screen_id,
            source_action_id=action.id,
        )

    def _classify_selector(self, selector: dict[str, Any]) -> MapperActionSafety:
        candidates = selector.get("candidates") or []
        label = candidates[0] if candidates else ""
        return self.safety_service.classify({"text": label, "content_desc": label, "resource_id": selector.get("resource_id", "")}, label)
