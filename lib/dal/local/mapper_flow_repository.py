from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from lib.domain.models.mapper_flow_model import MapperFlow, MapperFlowStep
from lib.domain.models.mapper_types import MapperActionSafety


class SqlAlchemyMapperFlowRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_flow(
        self,
        *,
        name: str,
        package_name: str,
        description: str | None = None,
        source_session_id: int | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> MapperFlow:
        flow = MapperFlow(
            name=name,
            package_name=package_name,
            description=description,
            source_session_id=source_session_id,
            metadata_json=metadata_json,
        )
        self.session.add(flow)
        self.session.flush()
        return flow

    def list_flows(self, package_name: str | None = None) -> list[MapperFlow]:
        stmt = select(MapperFlow).options(selectinload(MapperFlow.steps)).order_by(MapperFlow.created_at.desc())
        if package_name is not None:
            stmt = stmt.where(MapperFlow.package_name == package_name)
        return list(self.session.scalars(stmt))

    def get_flow(self, flow_id: int) -> MapperFlow | None:
        stmt = select(MapperFlow).where(MapperFlow.id == flow_id).options(selectinload(MapperFlow.steps))
        return self.session.scalar(stmt)

    def get_flow_by_name(self, package_name: str, name: str) -> MapperFlow | None:
        stmt = (
            select(MapperFlow)
            .where(MapperFlow.package_name == package_name, MapperFlow.name == name)
            .options(selectinload(MapperFlow.steps))
        )
        return self.session.scalar(stmt)

    def update_flow(self, flow_id: int, *, name: str | None = None, description: str | None = None) -> MapperFlow:
        flow = self.session.get(MapperFlow, flow_id)
        if flow is None:
            raise ValueError(f"Mapper flow {flow_id} not found")
        if name is not None:
            flow.name = name
        if description is not None:
            flow.description = description
        self.session.flush()
        return flow

    def delete_flow(self, flow_id: int) -> None:
        flow = self.session.get(MapperFlow, flow_id)
        if flow is None:
            raise ValueError(f"Mapper flow {flow_id} not found")
        self.session.delete(flow)
        self.session.flush()

    def add_step(
        self,
        flow_id: int,
        *,
        action_type: str,
        selector_json: dict[str, Any],
        safety: MapperActionSafety = MapperActionSafety.SAFE,
        source_screen_id: int | None = None,
        source_action_id: int | None = None,
        params_json: dict[str, Any] | None = None,
        ordinal: int | None = None,
    ) -> MapperFlowStep:
        flow = self.session.get(MapperFlow, flow_id)
        if flow is None:
            raise ValueError(f"Mapper flow {flow_id} not found")
        if ordinal is None:
            existing = self.session.scalars(select(MapperFlowStep).where(MapperFlowStep.flow_id == flow_id)).all()
            ordinal = len(existing)
        else:
            self._shift_steps_from(flow_id, ordinal)
        step = MapperFlowStep(
            flow_id=flow_id,
            ordinal=ordinal,
            action_type=action_type,
            selector_json=selector_json,
            safety=safety,
            source_screen_id=source_screen_id,
            source_action_id=source_action_id,
            params_json=params_json,
        )
        self.session.add(step)
        self.session.flush()
        return step

    def update_step(
        self,
        step_id: int,
        *,
        action_type: str | None = None,
        selector_json: dict[str, Any] | None = None,
        params_json: dict[str, Any] | None = None,
    ) -> MapperFlowStep:
        step = self.session.get(MapperFlowStep, step_id)
        if step is None:
            raise ValueError(f"Mapper flow step {step_id} not found")
        if action_type is not None:
            step.action_type = action_type
        if selector_json is not None:
            step.selector_json = selector_json
        if params_json is not None:
            step.params_json = params_json
        self.session.flush()
        return step

    def delete_step(self, step_id: int) -> None:
        step = self.session.get(MapperFlowStep, step_id)
        if step is None:
            raise ValueError(f"Mapper flow step {step_id} not found")
        flow_id = step.flow_id
        removed_ordinal = step.ordinal
        self.session.delete(step)
        self.session.flush()
        remaining = self.session.scalars(
            select(MapperFlowStep).where(MapperFlowStep.flow_id == flow_id, MapperFlowStep.ordinal > removed_ordinal)
        ).all()
        for later_step in remaining:
            later_step.ordinal -= 1
        self.session.flush()

    def _shift_steps_from(self, flow_id: int, ordinal: int) -> None:
        stmt = select(MapperFlowStep).where(MapperFlowStep.flow_id == flow_id, MapperFlowStep.ordinal >= ordinal)
        for step in self.session.scalars(stmt):
            step.ordinal += 1
        self.session.flush()
