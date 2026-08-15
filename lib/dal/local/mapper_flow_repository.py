from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from lib.domain.models.mapper_flow_model import MapperFlow, MapperFlowStep, MapperFlowStepUsage
from lib.domain.models.mapper_types import MapperActionSafety


class SqlAlchemyMapperFlowRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # --- Flow --------------------------------------------------------------

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
        stmt = (
            select(MapperFlow)
            .options(selectinload(MapperFlow.step_usages).selectinload(MapperFlowStepUsage.step))
            .order_by(MapperFlow.created_at.desc())
            .execution_options(populate_existing=True)
        )
        if package_name is not None:
            stmt = stmt.where(MapperFlow.package_name == package_name)
        return list(self.session.scalars(stmt))

    def get_flow(self, flow_id: int) -> MapperFlow | None:
        # populate_existing=True: without it, a MapperFlow already in this session's identity
        # map (e.g. fetched earlier in the same request/call with an empty step_usages, before
        # any step had been attached yet) would keep returning that stale, cached collection
        # instead of the current one, since eager loading doesn't override already-loaded
        # relationship attributes on an object that's already identity-mapped.
        stmt = (
            select(MapperFlow)
            .where(MapperFlow.id == flow_id)
            .options(selectinload(MapperFlow.step_usages).selectinload(MapperFlowStepUsage.step))
            .execution_options(populate_existing=True)
        )
        return self.session.scalar(stmt)

    def get_flow_by_name(self, package_name: str, name: str) -> MapperFlow | None:
        stmt = (
            select(MapperFlow)
            .where(MapperFlow.package_name == package_name, MapperFlow.name == name)
            .options(selectinload(MapperFlow.step_usages).selectinload(MapperFlowStepUsage.step))
            .execution_options(populate_existing=True)
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
        """Deletes the Flow and its step usages. Step *definitions* are left alone: they might
        still be referenced by other Flows (that's the point of them being shared, issue #23)."""
        flow = self.session.get(MapperFlow, flow_id)
        if flow is None:
            raise ValueError(f"Mapper flow {flow_id} not found")
        self.session.delete(flow)
        self.session.flush()

    def ordered_steps(self, flow: MapperFlow) -> list[MapperFlowStep]:
        return [usage.step for usage in sorted(flow.step_usages, key=lambda usage: usage.ordinal)]

    # --- Step definitions (reusable, package-scoped) ------------------------

    def create_step(
        self,
        *,
        package_name: str,
        action_type: str,
        selector_json: dict[str, Any],
        safety: MapperActionSafety = MapperActionSafety.SAFE,
        source_screen_id: int | None = None,
        source_action_id: int | None = None,
        params_json: dict[str, Any] | None = None,
    ) -> MapperFlowStep:
        step = MapperFlowStep(
            package_name=package_name,
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

    def get_step(self, step_id: int) -> MapperFlowStep | None:
        return self.session.get(MapperFlowStep, step_id)

    def find_step_by_source_action(self, package_name: str, source_action_id: int) -> MapperFlowStep | None:
        stmt = select(MapperFlowStep).where(
            MapperFlowStep.package_name == package_name,
            MapperFlowStep.source_action_id == source_action_id,
        )
        return self.session.scalar(stmt)

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

    def delete_step_definition(self, step_id: int) -> None:
        """Deletes the step everywhere, including every Flow's usage of it. Use `detach_step`
        instead if you only want to remove it from one specific Flow."""
        step = self.session.get(MapperFlowStep, step_id)
        if step is None:
            raise ValueError(f"Mapper flow step {step_id} not found")
        self.session.delete(step)
        self.session.flush()

    # --- Flow <-> step usage -------------------------------------------------

    def is_step_in_flow(self, flow_id: int, step_id: int) -> bool:
        stmt = select(MapperFlowStepUsage).where(MapperFlowStepUsage.flow_id == flow_id, MapperFlowStepUsage.step_id == step_id)
        return self.session.scalar(stmt) is not None

    def attach_step(self, flow_id: int, step_id: int, *, ordinal: int | None = None) -> MapperFlowStepUsage:
        if self.is_step_in_flow(flow_id, step_id):
            stmt = select(MapperFlowStepUsage).where(MapperFlowStepUsage.flow_id == flow_id, MapperFlowStepUsage.step_id == step_id)
            return self.session.scalar(stmt)
        if ordinal is None:
            existing = self.session.scalars(select(MapperFlowStepUsage).where(MapperFlowStepUsage.flow_id == flow_id)).all()
            ordinal = len(existing)
        else:
            self._shift_usages_from(flow_id, ordinal)
        usage = MapperFlowStepUsage(flow_id=flow_id, step_id=step_id, ordinal=ordinal)
        self.session.add(usage)
        self.session.flush()
        return usage

    def detach_step(self, flow_id: int, step_id: int) -> None:
        """Removes the step from this Flow only. The step definition itself (and its use in
        other Flows) is untouched."""
        stmt = select(MapperFlowStepUsage).where(MapperFlowStepUsage.flow_id == flow_id, MapperFlowStepUsage.step_id == step_id)
        usage = self.session.scalar(stmt)
        if usage is None:
            raise ValueError(f"Step {step_id} is not part of flow {flow_id}")
        removed_ordinal = usage.ordinal
        self.session.delete(usage)
        self.session.flush()
        remaining = self.session.scalars(
            select(MapperFlowStepUsage).where(MapperFlowStepUsage.flow_id == flow_id, MapperFlowStepUsage.ordinal > removed_ordinal)
        ).all()
        for later_usage in remaining:
            later_usage.ordinal -= 1
        self.session.flush()

    def _shift_usages_from(self, flow_id: int, ordinal: int) -> None:
        stmt = select(MapperFlowStepUsage).where(MapperFlowStepUsage.flow_id == flow_id, MapperFlowStepUsage.ordinal >= ordinal)
        for usage in self.session.scalars(stmt):
            usage.ordinal += 1
        self.session.flush()
